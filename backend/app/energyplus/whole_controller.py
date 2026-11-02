"""A single auditable Harness receives the complete nine-room physical state."""
import json
import time
import urllib.request

from app.energyplus.contracts import Controls
from app.energyplus.controllers import map_actions, rule_controls


def constrain(controls, binding):
    caps = binding["capabilities"]
    return controls.model_copy(update={
        "hvac_enabled": controls.hvac_enabled and "ac" in caps,
        "ventilation_fraction": controls.ventilation_fraction if "fan" in caps else 0,
        "window_fraction": controls.window_fraction if binding["exterior_windows"] else 0})


class WholeController:
    def __init__(self, request, output, bindings, calibration=None):
        self.request, self.output, self.bindings, self.calibration = request, output, bindings, calibration
        self.previous = {rid: constrain(request.manual_room_controls.get(rid, request.manual_controls) if request.controller == "manual" else Controls(
            cooling_setpoint_c=request.temperature_target_c, heating_setpoint_c=min(22, request.temperature_target_c-2),
            hvac_enabled=False, ventilation_fraction=0, window_fraction=0), b) for rid, b in bindings.items()}

    def propose(self, observation):
        start = time.perf_counter()
        trace = {"controller": self.request.controller, "spatial_scope": "whole_home",
                 "observation_minute": observation["minute"], "semantic_mode_effective": "not_used", "stages": []}
        if self.request.controller == "manual":
            controls = {rid: constrain(self.request.manual_room_controls.get(rid, self.request.manual_controls), b) for rid, b in self.bindings.items()}
        elif self.request.controller == "rule":
            controls = {rid: constrain(rule_controls(observation["rooms"][rid], self.request,
                self.calibration["illuminance"]["slope"] if self.calibration and rid == self.request.current_room_id else b["full_lamp_lux"]), b)
                for rid, b in self.bindings.items()}
        else:
            controls, detail = self.harness(observation)
            trace.update(detail)
        guards = []
        for rid, control in controls.items():
            updates = {}
            if self.request.controller.startswith("harness") and observation["rooms"][rid]["co2_ppm"] > self.request.co2_limit_ppm:
                if "fan" in self.bindings[rid]["capabilities"]:
                    updates["ventilation_fraction"] = 1
                    guards.append({"room_id": rid, "guard": "co2_ventilation"})
            if control.hvac_enabled and control.window_fraction:
                updates["window_fraction"] = 0
                guards.append({"room_id": rid, "guard": "window_hvac"})
            controls[rid] = control.model_copy(update=updates)
        self.previous = controls
        trace.update(applied_controls={rid: c.model_dump() for rid, c in controls.items()}, guard_interventions=guards,
                     wall_clock_latency_ms=(time.perf_counter()-start)*1000)
        return controls, trace

    def harness(self, observation):
        from app.agents.llm_client import MockLLMClient, RealLLMClient
        from app.experiments.logger import ExperimentLogger
        from app.experiments.task_runner import TaskRunner
        from app.schemas.task_schema import AgentCommandRequest
        from app.simulation.environment import SmartHomeEnvironment, get_initial_state
        initial = get_initial_state()
        for room in initial.rooms:
            obs = observation["rooms"][room.room_id]
            room.indoor_temperature_c = obs["temperature_c"]
            room.indoor_humidity_percent = obs["relative_humidity_pct"]
            room.indoor_illuminance_lux = obs["total_illuminance_lux"]
            room.occupancy = obs["occupants"] > 0
        initial.current_time_step = observation["minute"] // 5
        initial.outdoor_environment.outdoor_temperature_c = observation["outdoor_temperature_c"]
        initial.outdoor_environment.time_hour = int(observation["minute"] / 60) % 24
        for device in initial.devices:
            control = self.previous[device.room]
            if device.device_type == "light":
                device.brightness_pct = control.light_fraction*100
                device.is_on = control.light_fraction > 0
            elif device.device_type == "ac":
                device.is_on, device.setpoint_c = control.hvac_enabled, control.cooling_setpoint_c
                device.mode = "cool" if control.hvac_enabled else "off"
            elif device.device_type == "fan":
                device.speed_pct, device.is_on = control.ventilation_fraction*100, control.ventilation_fraction > 0
            elif device.device_type == "window":
                device.opening_pct = control.window_fraction*100
        runner = TaskRunner(SmartHomeEnvironment(initial), ExperimentLogger(self.output / "harness"),
            refresh_realtime=False, execute_actions=False, log_task_results=False,
            enable_feedback_correction=False, enable_context_memory=False)
        runner.semantic_agent.llm_client = RealLLMClient() if self.request.controller == "harness_real" else MockLLMClient()
        model_result = None
        if self.request.controller == "harness_real":
            body = json.dumps({"user_command": self.request.user_command, "state": {
                "devices": [d.model_dump() for d in initial.devices],
                "rooms": [{"room_id": rid, **obs} for rid, obs in observation["rooms"].items()],
                "outdoor": {"temperature_c": observation["outdoor_temperature_c"]}}}, ensure_ascii=False).encode()
            req = urllib.request.Request("http://127.0.0.1:8011/plan", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as response:
                model_result = json.load(response)
            actions = [{**c["arguments"], "reason": model_result["output"]["explanation"]} for c in model_result["output"]["tool_calls"]]

            class ModelPlanner:
                def plan(self, semantic, current_state):
                    return {"plan_id": "deepseek-energyplus-home", "agent": "planning_agent", "intent": semantic["intent"],
                            "room": semantic["room"], "scope": semantic["scope"], "actions": actions}
            runner.planning_agent = ModelPlanner()
        result = runner.run_agent_command(AgentCommandRequest(user_command=self.request.user_command,
            current_room_id=self.request.current_room_id))
        if not result.success:
            raise RuntimeError(result.error or "Whole-home Harness planning failed")
        actions = result.plan_result.get("actions", [])
        controls = dict(self.previous)
        mapped, rejected = [], []
        by_entity = {d["entity_id"]: rid for rid, b in self.bindings.items() for d in b["devices"]}
        for action in actions:
            rid = by_entity.get(action.get("entity_id"))
            if rid is None:
                rejected.append({"action": action, "reason": "Entity absent from whole-home inventory"})
                continue
            binding = self.bindings[rid]
            if action["entity_id"].startswith("window.") and not binding["exterior_windows"]:
                rejected.append({"action": action, "reason": "No exterior window in designed geometry; no invented actuator"})
                continue
            controls[rid], accepted, denied = map_actions([action], controls[rid], rid,
                {d["entity_id"] for d in binding["devices"]})
            mapped.extend(accepted)
            rejected.extend(denied)
        return controls, {"semantic_mode_effective": "real_semantics_real_deepseek_plan" if model_result else "mock",
            "real_model_result": model_result, "proposed_actions": actions, "mapped_actions": mapped, "rejected_actions": rejected,
            "decision_trace": result.plan_result.get("decision_trace"), "stages": result.multi_agent_blackboard.get("stages", []),
            "feedback_scope": "dry-run Harness feedback is not physical outcome; EnergyPlus observations are authoritative"}
