"""Controller proposals and a small auditable actuator capability boundary."""
import time
import json
import urllib.request

from app.energyplus.contracts import Controls, RunRequest


def rule_controls(observation, request: RunRequest, full_lamp_lux=600):
    occupied = observation["occupants"] > 0
    light = max(0, min(1, (request.illuminance_target_lux - observation["daylight_lux"]) / full_lamp_lux)) if occupied else 0
    return Controls(light_fraction=light, cooling_setpoint_c=request.temperature_target_c,
        heating_setpoint_c=min(22, request.temperature_target_c - 2), hvac_enabled=occupied,
        ventilation_fraction=(1 if observation["co2_ppm"] > request.co2_limit_ppm - 100 else 0.25) if occupied else 0,
        window_fraction=0)


def map_actions(actions, previous: Controls, room_id="living_room", allowed_entities=None):
    proposed = previous.model_dump()
    mapped, rejected = [], []
    for action in actions:
        before = dict(proposed)
        entity = action.get("entity_id", "")
        verb, parameters = action.get("action"), action.get("parameters", {})
        device = entity.split(".")[0]
        if entity != f"{device}.{room_id}_main" or (allowed_entities is not None and entity not in allowed_entities):
            rejected.append({"action": action, "reason": "Entity is not mapped in this simulated room"})
            continue
        try:
            if device == "light" and verb in {"turn_on", "turn_off", "set_brightness"}:
                value = float(parameters.get("brightness_pct", 100 if verb == "turn_on" else 0))
                if verb == "turn_off":
                    value = 0
                if not 0 <= value <= 100:
                    raise ValueError("Brightness range")
                proposed["light_fraction"] = value / 100
            elif device == "ac" and verb in {"turn_on", "turn_off", "set_temperature", "set_mode"}:
                proposed["hvac_enabled"] = verb != "turn_off" and parameters.get("mode") != "off"
                if verb == "set_temperature":
                    value = float(parameters["setpoint_c"])
                    if not 18 <= value <= 30:
                        raise ValueError("Temperature range")
                    proposed["cooling_setpoint_c"] = value
                    proposed["heating_setpoint_c"] = min(proposed["heating_setpoint_c"], value - 1)
                if verb == "set_mode" and parameters.get("mode") not in {"cool", "off"}:
                    raise ValueError("This first-zone adapter supports cooling/off mode only; explicit heating target is a separate actuator")
            elif device in {"fan", "window"}:
                field, parameter = ("ventilation_fraction", "speed_pct") if device == "fan" else ("window_fraction", "opening_pct")
                allowed = {"turn_on", "turn_off", "set_speed"} if device == "fan" else {"open", "close", "set_opening"}
                if verb not in allowed:
                    raise ValueError("Unsupported action")
                value = float(parameters.get(parameter, 100 if verb in {"turn_on", "open"} else 0))
                if verb in {"turn_off", "close"}:
                    value = 0
                if not 0 <= value <= 100:
                    raise ValueError("Opening/flow range")
                proposed[field] = value / 100
            else:
                raise ValueError("No validated EnergyPlus actuator mapping")
            Controls.model_validate(proposed)
            mapped.append(action)
        except (ValueError, KeyError, TypeError) as exc:
            proposed = before
            rejected.append({"action": action, "reason": str(exc)})
    return Controls.model_validate(proposed), mapped, rejected


class Controller:
    def __init__(self, request: RunRequest, output, calibration=None):
        self.request, self.output, self.calibration = request, output, calibration
        self.previous = request.manual_controls if request.controller == "manual" else Controls(
            cooling_setpoint_c=request.temperature_target_c,
            heating_setpoint_c=min(22, request.temperature_target_c - 2),
            hvac_enabled=False, ventilation_fraction=0, window_fraction=0, light_fraction=0)
        self.runner = None

    def propose(self, observation):
        started = time.perf_counter()
        full_lux = 600 if not self.calibration else max(1, self.calibration["illuminance"]["slope"])
        rule = rule_controls(observation, self.request, full_lux)
        trace = {"controller": self.request.controller, "semantic_mode_effective": "not_used",
                 "observation_minute": observation["minute"], "stages": []}
        if self.request.controller == "manual":
            controls = self.request.manual_controls
        elif self.request.controller == "rule":
            controls = rule
        else:
            controls, detail = self.harness(observation, rule)
            trace.update(detail)
            # CO2 is not in the original semantic schema. Keep this explicit deterministic guard separate.
            if observation["co2_ppm"] > self.request.co2_limit_ppm and controls.ventilation_fraction < 1:
                controls = controls.model_copy(update={"ventilation_fraction": 1})
                trace["co2_guard_intervention"] = True
        if controls.hvac_enabled and controls.window_fraction > 0:
            trace["window_hvac_guard_intervention"] = True
            controls = controls.model_copy(update={"window_fraction": 0})
        self.previous = controls
        trace.update(applied_controls=controls.model_dump(), wall_clock_latency_ms=(time.perf_counter() - started) * 1000)
        return controls, trace

    def harness(self, observation, rule):
        from app.agents.llm_client import MockLLMClient, RealLLMClient
        from app.experiments.logger import ExperimentLogger
        from app.experiments.task_runner import TaskRunner
        from app.schemas.task_schema import AgentCommandRequest
        from app.simulation.environment import SmartHomeEnvironment, get_initial_state
        initial = get_initial_state()
        initial.rooms = [r for r in initial.rooms if r.room_id == "living_room"]
        initial.devices = [d for d in initial.devices if d.room == "living_room"]
        room = initial.rooms[0]
        room.indoor_temperature_c = observation["temperature_c"]
        room.indoor_humidity_percent = observation["relative_humidity_pct"]
        room.indoor_illuminance_lux = observation["total_illuminance_lux"]
        room.occupancy = observation["occupants"] > 0
        initial.current_time_step = observation["minute"] // 5
        initial.outdoor_environment.outdoor_temperature_c = observation["outdoor_temperature_c"]
        initial.outdoor_environment.time_hour = int(observation["minute"] / 60) % 24
        for device in initial.devices:
            if device.device_type == "light":
                device.brightness_pct = self.previous.light_fraction * 100
                device.is_on = device.brightness_pct > 0
            elif device.device_type == "ac":
                device.is_on = self.previous.hvac_enabled
                device.setpoint_c = self.previous.cooling_setpoint_c
            elif device.device_type == "fan":
                device.speed_pct = self.previous.ventilation_fraction * 100
                device.is_on = device.speed_pct > 0
            elif device.device_type == "window":
                device.opening_pct = self.previous.window_fraction * 100
        runner = TaskRunner(SmartHomeEnvironment(initial), ExperimentLogger(self.output / "harness"),
                            refresh_realtime=False, execute_actions=False, log_task_results=False,
                            enable_feedback_correction=False, enable_context_memory=False)
        runner.semantic_agent.llm_client = RealLLMClient() if self.request.controller == "harness_real" else MockLLMClient()
        model_result = None
        if self.request.controller == "harness_real":
            model_state = {"devices": [d.model_dump() for d in initial.devices if d.device_type in {"light", "ac", "fan", "window"}],
                           "rooms": [{"room_id": "living_room", "temperature_c": observation["temperature_c"],
                                      "co2_ppm": observation["co2_ppm"], "illuminance_lux": observation["total_illuminance_lux"]}],
                           "outdoor": {"temperature_c": observation["outdoor_temperature_c"]}}
            body = json.dumps({"user_command": self.request.user_command, "state": model_state}, ensure_ascii=False).encode()
            http_request = urllib.request.Request("http://127.0.0.1:8011/plan", data=body,
                                                   headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(http_request, timeout=120) as response:
                model_result = json.load(response)
            actions = [{**call["arguments"], "reason": model_result["output"]["explanation"]}
                       for call in model_result["output"]["tool_calls"]]

            class ModelProposedPlanner:
                def plan(self, semantic, current_state):
                    return {"plan_id": "deepseek-energyplus", "agent": "planning_agent", "intent": semantic["intent"],
                            "room": "living_room", "scope": "single_room", "actions": actions}
            runner.planning_agent = ModelProposedPlanner()
        result = runner.run_agent_command(AgentCommandRequest(user_command=self.request.user_command, current_room_id="living_room"))
        if not result.success:
            raise RuntimeError(result.error or "Harness planning failed")
        actions = result.plan_result.get("actions", [])
        controls, mapped, rejected = map_actions(actions, self.previous)
        return controls, {"semantic_mode_effective": "real_semantics_real_deepseek_plan" if model_result else "mock",
            "real_model_result": model_result,
            "model_revision": result.semantic_result.get("llm_metrics", {}).get("model_revision"),
            "proposed_actions": actions, "mapped_actions": mapped, "rejected_actions": rejected,
            "decision_trace": result.plan_result.get("decision_trace"),
            "stages": result.multi_agent_blackboard.get("stages", []),
            "feedback_scope": "original dry-run feedback is not physical outcome; EnergyPlus observations are authoritative"}
