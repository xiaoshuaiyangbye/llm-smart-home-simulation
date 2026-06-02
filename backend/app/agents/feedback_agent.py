from typing import Any

from app.schemas.action_schema import PlannedDeviceAction
from app.schemas.state_schema import SmartHomeState
from app.simulation.thermal_model import calculate_apparent_temperature


class FeedbackAgent:
    def evaluate(self, semantic_result: dict[str, Any], state: SmartHomeState, revision_round: int = 0) -> dict[str, Any]:
        room_id = semantic_result.get("room", "living_room")
        if semantic_result.get("intent") in {"context_update", "occupancy_update"}:
            return {
                "completed": True,
                "feedback": "Context memory or occupancy state has been updated.",
                "metrics": {
                    "context_memory_active": bool(semantic_result.get("memory_context")),
                },
                "correction_round": revision_round,
                "correction_actions": [],
            }
        if room_id == "all_rooms" and semantic_result.get("intent") == "basic_light_control":
            return self._evaluate_all_room_lights(semantic_result, state, revision_round)
        if room_id == "all_rooms" and semantic_result.get("intent") == "basic_curtain_control":
            return self._evaluate_all_room_opening_devices(semantic_result, state, revision_round)
        if room_id == "all_rooms" and semantic_result.get("intent") == "basic_ac_control":
            return self._evaluate_all_room_ac(semantic_result, state, revision_round)
        if room_id == "all_rooms" and semantic_result.get("intent") == "thermal_comfort_control":
            return self._evaluate_all_room_thermal(semantic_result, state, revision_round)
        if room_id == "all_rooms" and semantic_result.get("intent") == "away_mode":
            return self._evaluate_all_room_away_mode(state, revision_round)
        if room_id == "all_rooms" and semantic_result.get("intent") == "energy_saving_mode":
            return self._evaluate_all_room_energy_saving_mode(state, revision_round)

        room = next((room for room in state.rooms if room.room_id == room_id), None)
        if room is None:
            return {
                "completed": False,
                "feedback": f"Room '{room_id}' is not available for feedback evaluation.",
                "metrics": {"room_found": False},
                "correction_round": revision_round,
                "correction_actions": [],
            }
        targets = semantic_result.get("targets", {})
        illuminance_range = targets.get("illuminance_lux_range", [0, 1200])
        temperature_range = targets.get("temperature_c_range", [18, 30])
        humidity_range = targets.get("humidity_percent_range")
        fan = next((device for device in state.devices if device.room == room_id and device.device_type == "fan"), None)
        apparent_temperature = calculate_apparent_temperature(room, fan)

        illuminance_error = self._range_error(room.indoor_illuminance_lux, illuminance_range)
        temperature_error = self._range_error(apparent_temperature, temperature_range)
        humidity_error = self._range_error(room.indoor_humidity_percent, humidity_range) if self._valid_range(humidity_range) else 0.0
        waste_actions = self._vacated_room_corrections(state, semantic_result)
        lighting_control_in_progress = self._lighting_control_in_progress(state, room_id, room.indoor_illuminance_lux, illuminance_range)
        thermal_control_in_progress = self._thermal_control_in_progress(state, room_id, apparent_temperature, temperature_range)
        humidity_control_in_progress = self._humidity_control_in_progress(state, room_id, room.indoor_humidity_percent, humidity_range)
        physical_targets_met = illuminance_error == 0 and temperature_error == 0 and humidity_error == 0
        staged_targets_met = (
            (illuminance_error == 0 or lighting_control_in_progress)
            and (temperature_error == 0 or thermal_control_in_progress)
            and (humidity_error == 0 or humidity_control_in_progress)
        )
        completed = staged_targets_met and not waste_actions
        correction_actions = [] if completed or revision_round >= 3 else self._corrections(
            state,
            room_id,
            room.indoor_illuminance_lux,
            apparent_temperature,
            illuminance_range,
            temperature_range,
            semantic_result.get("intent"),
        )
        if not completed and revision_round < 3 and humidity_error > 0:
            correction_actions.extend(self._humidity_corrections(state, room_id, room.indoor_humidity_percent, humidity_range))
        if not completed and revision_round < 3:
            correction_actions.extend(waste_actions)
        correction_actions = self._apply_contextual_safety_constraints(correction_actions, semantic_result)
        return {
            "completed": completed,
            "feedback": self._feedback_text(room_id, completed, revision_round),
            "metrics": {
                "illuminance_error": round(illuminance_error, 2),
                "temperature_error": round(temperature_error, 2),
                "humidity_error": round(humidity_error, 2),
                "apparent_temperature_c": apparent_temperature,
                "vacated_room_waste_device_count": len(waste_actions),
                "physical_targets_met": physical_targets_met,
                "staged_targets_met": staged_targets_met,
                "lighting_control_in_progress": lighting_control_in_progress,
                "thermal_control_in_progress": thermal_control_in_progress,
                "humidity_control_in_progress": humidity_control_in_progress,
                "room_overall_comfort_score": self._room_overall_comfort_score(state, room_id),
            },
            "correction_round": revision_round,
            "correction_actions": [action.model_dump() for action in correction_actions],
        }

    def _range_error(self, value: float, target_range: list[float]) -> float:
        if value < target_range[0]:
            return target_range[0] - value
        if value > target_range[1]:
            return value - target_range[1]
        return 0.0

    def _valid_range(self, target_range: Any) -> bool:
        return isinstance(target_range, list) and len(target_range) == 2

    def _lighting_control_in_progress(
        self,
        state: SmartHomeState,
        room_id: str,
        illuminance: float,
        illuminance_range: list[float],
    ) -> bool:
        if illuminance_range[0] <= illuminance <= illuminance_range[1]:
            return True
        light = self._device(state, room_id, "light")
        curtain = self._device(state, room_id, "curtain")
        if illuminance < illuminance_range[0]:
            return bool(
                (light and getattr(light, "is_on", False) and getattr(light, "brightness_pct", 0) > 0)
                or (curtain and getattr(curtain, "opening_pct", 0) >= 50)
            )
        return bool(
            (light and (not getattr(light, "is_on", False) or getattr(light, "brightness_pct", 0) <= 40))
            or (curtain and getattr(curtain, "opening_pct", 100) <= 35)
        )

    def _thermal_control_in_progress(
        self,
        state: SmartHomeState,
        room_id: str,
        apparent_temperature: float,
        temperature_range: list[float],
    ) -> bool:
        if temperature_range[0] <= apparent_temperature <= temperature_range[1]:
            return True
        ac = self._device(state, room_id, "ac")
        fan = self._device(state, room_id, "fan")
        curtain = self._device(state, room_id, "curtain")
        if apparent_temperature > temperature_range[1]:
            return bool(
                (ac and getattr(ac, "is_on", False) and getattr(ac, "mode", "") == "cool" and getattr(ac, "setpoint_c", 30) <= max(27.0, temperature_range[1] + 0.5))
                or (fan and getattr(fan, "is_on", False) and getattr(fan, "speed_pct", 0) > 0)
                or (curtain and getattr(curtain, "opening_pct", 100) <= 35)
            )
        return bool(
            ac and getattr(ac, "is_on", False) and getattr(ac, "mode", "") == "heat" and getattr(ac, "setpoint_c", 0) >= temperature_range[0]
        )

    def _humidity_control_in_progress(
        self,
        state: SmartHomeState,
        room_id: str,
        humidity: float,
        humidity_range: Any,
    ) -> bool:
        if not self._valid_range(humidity_range):
            return True
        if humidity_range[0] <= humidity <= humidity_range[1]:
            return True
        window = self._device(state, room_id, "window")
        ac = self._device(state, room_id, "ac")
        if humidity > humidity_range[1]:
            return bool(
                (window and getattr(window, "opening_pct", 0) >= 30)
                or (ac and getattr(ac, "is_on", False) and getattr(ac, "mode", "") in {"cool", "dry"})
            )
        return bool(window and getattr(window, "opening_pct", 100) <= 10)

    def _humidity_corrections(
        self,
        state: SmartHomeState,
        room_id: str,
        humidity: float,
        humidity_range: Any,
    ) -> list[PlannedDeviceAction]:
        if not self._valid_range(humidity_range):
            return []
        actions: list[PlannedDeviceAction] = []
        if humidity > humidity_range[1]:
            if self._has_device(state, room_id, "window"):
                actions.append(PlannedDeviceAction(entity_id=f"window.{room_id}_main", action="set_opening", parameters={"opening_pct": 45}, reason="feedback correction for high humidity"))
            if self._has_device(state, room_id, "ac"):
                actions.append(PlannedDeviceAction(entity_id=f"ac.{room_id}_main", action="turn_on", parameters={"mode": "dry", "setpoint_c": 26}, reason="feedback correction for high humidity"))
        elif humidity < humidity_range[0] and self._has_device(state, room_id, "window"):
            actions.append(PlannedDeviceAction(entity_id=f"window.{room_id}_main", action="set_opening", parameters={"opening_pct": 5}, reason="feedback correction for low humidity"))
        return actions

    def _device(self, state: SmartHomeState, room_id: str, device_type: str):
        return next((device for device in state.devices if device.room == room_id and device.device_type == device_type), None)

    def _room_overall_comfort_score(self, state: SmartHomeState, room_id: str) -> float | None:
        snapshot = next((room for room in state.comfort_metrics.rooms if room.room_id == room_id), None)
        return round(snapshot.overall_comfort_score, 2) if snapshot else None

    def _corrections(
        self,
        state: SmartHomeState,
        room_id: str,
        illuminance: float,
        temperature: float,
        illuminance_range: list[float],
        temperature_range: list[float],
        intent: str | None = None,
    ) -> list[PlannedDeviceAction]:
        actions: list[PlannedDeviceAction] = []
        if illuminance < illuminance_range[0]:
            actions.append(PlannedDeviceAction(entity_id=f"light.{room_id}_main", action="set_brightness", parameters={"brightness_pct": 90}, reason="feedback correction for low illuminance"))
        elif illuminance > illuminance_range[1]:
            actions.append(PlannedDeviceAction(entity_id=f"curtain.{room_id}_main", action="set_opening", parameters={"opening_pct": 20}, reason="feedback correction for excessive illuminance"))
        if temperature > temperature_range[1]:
            actions.append(PlannedDeviceAction(entity_id=f"curtain.{room_id}_main", action="set_opening", parameters={"opening_pct": 0}, reason="feedback correction to reduce solar heat gain"))
            if self._has_device(state, room_id, "ac"):
                setpoint = 26 if intent == "sleep_mode" else max(25.5, min(temperature_range[1], 26.5))
                actions.append(PlannedDeviceAction(entity_id=f"ac.{room_id}_main", action="turn_on", parameters={"mode": "cool", "setpoint_c": setpoint}, reason="feedback correction for high temperature"))
            if self._has_device(state, room_id, "fan"):
                speed = 20 if intent == "sleep_mode" else 60
                actions.append(PlannedDeviceAction(entity_id=f"fan.{room_id}_main", action="set_speed", parameters={"speed_pct": speed}, reason="feedback correction to reduce apparent temperature"))
        elif temperature < temperature_range[0]:
            if self._has_device(state, room_id, "ac"):
                actions.append(PlannedDeviceAction(entity_id=f"ac.{room_id}_main", action="turn_on", parameters={"mode": "heat", "setpoint_c": temperature_range[1]}, reason="feedback correction for low temperature"))
        return actions

    def _vacated_room_corrections(
        self,
        state: SmartHomeState,
        semantic_result: dict[str, Any],
    ) -> list[PlannedDeviceAction]:
        previous_rooms = {
            str(room_id)
            for room_id in semantic_result.get("previous_occupied_rooms", [])
            if isinstance(room_id, str)
        }
        if not previous_rooms:
            return []

        actions: list[PlannedDeviceAction] = []
        for device in state.devices:
            if device.room not in previous_rooms:
                continue
            if device.device_type == "light" and device.is_on and device.brightness_pct > 0:
                actions.append(PlannedDeviceAction(entity_id=device.entity_id, action="turn_off", parameters={}, reason="feedback correction for vacated-room light"))
            elif device.device_type == "ac" and device.is_on:
                actions.append(PlannedDeviceAction(entity_id=device.entity_id, action="turn_off", parameters={}, reason="feedback correction for vacated-room AC"))
            elif device.device_type == "fan" and device.is_on and device.speed_pct > 0:
                actions.append(PlannedDeviceAction(entity_id=device.entity_id, action="turn_off", parameters={}, reason="feedback correction for vacated-room fan"))
        return actions

    def _has_device(self, state: SmartHomeState, room_id: str, device_type: str) -> bool:
        return any(device.room == room_id and device.device_type == device_type for device in state.devices)

    def _apply_contextual_safety_constraints(
        self,
        actions: list[PlannedDeviceAction],
        semantic_result: dict[str, Any],
    ) -> list[PlannedDeviceAction]:
        constraints = semantic_result.get("constraints", {})
        if not constraints.get("health_context_active"):
            return actions

        adjusted_actions: list[PlannedDeviceAction] = []
        fan_limit = float(constraints.get("fan_speed_limit_pct", 30))
        cooling_floor = float(constraints.get("cooling_setpoint_floor_c", 26))
        for action in actions:
            device_type = action.entity_id.split(".", 1)[0]
            if device_type == "fan" and action.action == "set_speed" and constraints.get("avoid_strong_fan"):
                adjusted_actions.append(
                    action.model_copy(
                        update={
                            "parameters": {"speed_pct": min(float(action.parameters.get("speed_pct", fan_limit)), fan_limit)},
                            "reason": f"{action.reason}; limited by health context",
                        }
                    )
                )
                continue
            if device_type == "ac" and action.action in {"turn_on", "set_temperature"} and constraints.get("avoid_overcooling"):
                parameters = {**action.parameters, "setpoint_c": max(float(action.parameters.get("setpoint_c", cooling_floor)), cooling_floor)}
                if action.action == "turn_on":
                    parameters.setdefault("mode", "cool")
                adjusted_actions.append(
                    action.model_copy(
                        update={
                            "parameters": parameters,
                            "reason": f"{action.reason}; adjusted by health context",
                        }
                    )
                )
                continue
            adjusted_actions.append(action)
        return adjusted_actions

    def _evaluate_all_room_lights(self, semantic_result: dict[str, Any], state: SmartHomeState, revision_round: int) -> dict[str, Any]:
        control_goal = semantic_result.get("control_goal")
        should_be_on = control_goal != "turn_off"
        lights = [device for device in state.devices if device.device_type == "light"]
        mismatched_lights = [
            light
            for light in lights
            if (light.is_on and light.brightness_pct > 0) != should_be_on
        ]
        completed = not mismatched_lights
        correction_actions = []
        if not completed and revision_round < 3:
            action = "turn_on" if should_be_on else "turn_off"
            parameters = {"brightness_pct": 70, "color_temperature_k": 4000} if should_be_on else {}
            correction_actions = [
                PlannedDeviceAction(
                    entity_id=light.entity_id,
                    action=action,
                    parameters=parameters,
                    reason="feedback correction for all room light control",
                )
                for light in mismatched_lights
            ]
        target_text = "on" if should_be_on else "off"
        return {
            "completed": completed,
            "feedback": (
                f"All room lights are {target_text}."
                if completed
                else f"{len(mismatched_lights)} room lights have not reached the requested {target_text} state."
            ),
            "metrics": {
                "target_light_count": len(lights),
                "mismatched_light_count": len(mismatched_lights),
            },
            "correction_round": revision_round,
            "correction_actions": [action.model_dump() for action in correction_actions],
        }

    def _evaluate_all_room_opening_devices(
        self,
        semantic_result: dict[str, Any],
        state: SmartHomeState,
        revision_round: int,
    ) -> dict[str, Any]:
        control_goal = semantic_result.get("control_goal")
        should_open = control_goal != "turn_off"
        target_opening = 100 if should_open else 0
        device_types = {
            device_type
            for device_type in semantic_result.get("devices", [])
            if device_type in {"curtain", "window"}
        } or {"curtain"}
        devices = [
            device
            for device in state.devices
            if device.device_type in device_types
        ]
        mismatched_devices = [
            device
            for device in devices
            if abs(device.opening_pct - target_opening) > 1
        ]
        completed = not mismatched_devices
        correction_actions = []
        if not completed and revision_round < 3:
            correction_actions = [
                PlannedDeviceAction(
                    entity_id=device.entity_id,
                    action="set_opening",
                    parameters={"opening_pct": target_opening},
                    reason="feedback correction for all-room opening control",
                )
                for device in mismatched_devices
            ]

        target_text = "open" if should_open else "closed"
        return {
            "completed": completed,
            "feedback": (
                f"All requested opening devices are {target_text}."
                if completed
                else f"{len(mismatched_devices)} requested opening devices have not reached {target_text} state."
            ),
            "metrics": {
                "target_device_types": sorted(device_types),
                "target_device_count": len(devices),
                "mismatched_device_count": len(mismatched_devices),
            },
            "correction_round": revision_round,
            "correction_actions": [action.model_dump() for action in correction_actions],
        }

    def _evaluate_all_room_ac(
        self,
        semantic_result: dict[str, Any],
        state: SmartHomeState,
        revision_round: int,
    ) -> dict[str, Any]:
        control_goal = semantic_result.get("control_goal")
        should_be_on = control_goal != "turn_off"
        air_conditioners = [device for device in state.devices if device.device_type == "ac"]
        mismatched_devices = [
            device
            for device in air_conditioners
            if bool(device.is_on and device.mode != "off") != should_be_on
        ]
        completed = not mismatched_devices
        correction_actions: list[PlannedDeviceAction] = []
        if not completed and revision_round < 3:
            action = "turn_on" if should_be_on else "turn_off"
            parameters = (
                {"mode": "cool", "setpoint_c": self._target_temperature(semantic_result)}
                if should_be_on
                else {}
            )
            correction_actions = [
                PlannedDeviceAction(
                    entity_id=device.entity_id,
                    action=action,
                    parameters=parameters,
                    reason="feedback correction for all-room air conditioner control",
                )
                for device in mismatched_devices
            ]

        target_text = "on" if should_be_on else "off"
        return {
            "completed": completed,
            "feedback": (
                f"All air conditioners are {target_text}."
                if completed
                else f"{len(mismatched_devices)} air conditioners have not reached the requested {target_text} state."
            ),
            "metrics": {
                "target_ac_count": len(air_conditioners),
                "mismatched_ac_count": len(mismatched_devices),
            },
            "correction_round": revision_round,
            "correction_actions": [action.model_dump() for action in correction_actions],
        }

    def _target_temperature(self, semantic_result: dict[str, Any]) -> float:
        targets = semantic_result.get("targets", {})
        temperature_range = targets.get("temperature_c_range", [24, 26.7]) if isinstance(targets, dict) else [24, 26.7]
        if not isinstance(temperature_range, list) or len(temperature_range) != 2:
            return 25.0
        target = (float(temperature_range[0]) + float(temperature_range[1])) / 2
        return round(max(16.0, min(30.0, target)), 1)

    def _evaluate_all_room_thermal(
        self,
        semantic_result: dict[str, Any],
        state: SmartHomeState,
        revision_round: int,
    ) -> dict[str, Any]:
        control_goal = semantic_result.get("control_goal")
        target_device_types = {
            device_type
            for device_type in semantic_result.get("devices", [])
            if device_type in {"ac", "fan"}
        } or {"ac", "fan"}
        if control_goal == "turn_off":
            active_devices = [
                device
                for device in state.devices
                if device.device_type in target_device_types
                and (
                    (device.device_type == "ac" and device.is_on and device.mode != "off")
                    or (device.device_type == "fan" and device.is_on and device.speed_pct > 0)
                )
            ]
            completed = not active_devices
            correction_actions = []
            if not completed and revision_round < 3:
                correction_actions = [
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="turn_off",
                        parameters={},
                        reason="feedback correction for all-room thermal shutdown",
                    )
                    for device in active_devices
                ]
            return {
                "completed": completed,
                "feedback": (
                    "All requested thermal devices are off."
                    if completed
                    else f"{len(active_devices)} thermal devices should be turned off."
                ),
                "metrics": {"active_thermal_device_count": len(active_devices)},
                "correction_round": revision_round,
                "correction_actions": [action.model_dump() for action in correction_actions],
            }

        targets = semantic_result.get("targets", {})
        temperature_range = targets.get("temperature_c_range", [18, 30]) if isinstance(targets, dict) else [18, 30]
        target_rooms = [room for room in state.rooms if room.occupancy and room.activity != "away"] or state.rooms
        pending_rooms = []
        for room in target_rooms:
            fan = self._device(state, room.room_id, "fan")
            apparent_temperature = calculate_apparent_temperature(room, fan)
            if self._range_error(apparent_temperature, temperature_range) == 0:
                continue
            if not self._thermal_control_in_progress(state, room.room_id, apparent_temperature, temperature_range):
                pending_rooms.append(room)

        completed = not pending_rooms
        correction_actions: list[PlannedDeviceAction] = []
        if not completed and revision_round < 3:
            for room in pending_rooms:
                apparent_temperature = calculate_apparent_temperature(room, self._device(state, room.room_id, "fan"))
                correction_actions.extend(
                    self._corrections(
                        state,
                        room.room_id,
                        room.indoor_illuminance_lux,
                        apparent_temperature,
                        [0, 1200],
                        temperature_range,
                        semantic_result.get("intent"),
                    )
                )
        return {
            "completed": completed,
            "feedback": (
                "All target rooms have thermal comfort control in progress."
                if completed
                else f"{len(pending_rooms)} rooms still need thermal correction actions."
            ),
            "metrics": {
                "target_room_count": len(target_rooms),
                "pending_thermal_room_count": len(pending_rooms),
            },
            "correction_round": revision_round,
            "correction_actions": [action.model_dump() for action in correction_actions],
        }

    def _evaluate_all_room_away_mode(self, state: SmartHomeState, revision_round: int) -> dict[str, Any]:
        active_devices = [
            device
            for device in state.devices
            if (
                (device.device_type == "light" and device.is_on and device.brightness_pct > 0)
                or (device.device_type == "ac" and device.is_on)
                or (device.device_type == "fan" and device.is_on and device.speed_pct > 0)
            )
        ]
        completed = not active_devices
        correction_actions = []
        if not completed and revision_round < 3:
            correction_actions = [
                PlannedDeviceAction(
                    entity_id=device.entity_id,
                    action="turn_off",
                    parameters={},
                    reason="feedback correction for all-room away mode",
                )
                for device in active_devices
            ]
        return {
            "completed": completed,
            "feedback": (
                "All unnecessary active devices are off for away mode."
                if completed
                else f"{len(active_devices)} active devices should be turned off for away mode."
            ),
            "metrics": {
                "active_device_count": len(active_devices),
            },
            "correction_round": revision_round,
            "correction_actions": [action.model_dump() for action in correction_actions],
        }

    def _evaluate_all_room_energy_saving_mode(self, state: SmartHomeState, revision_round: int) -> dict[str, Any]:
        occupied_rooms = {room.room_id for room in state.rooms if room.occupancy and room.activity != "away"}
        waste_devices = [
            device
            for device in state.devices
            if device.room not in occupied_rooms
            and (
                (device.device_type == "light" and device.is_on and device.brightness_pct > 0)
                or (device.device_type == "ac" and device.is_on)
                or (device.device_type == "fan" and device.is_on and device.speed_pct > 0)
            )
        ]
        completed = not waste_devices
        correction_actions = []
        if not completed and revision_round < 3:
            correction_actions = [
                PlannedDeviceAction(
                    entity_id=device.entity_id,
                    action="turn_off",
                    parameters={},
                    reason="feedback correction for whole-home energy saving in unoccupied room",
                )
                for device in waste_devices
            ]
        return {
            "completed": completed,
            "feedback": (
                "No unnecessary active devices remain in unoccupied rooms."
                if completed
                else f"{len(waste_devices)} unoccupied-room devices should be turned off for energy saving."
            ),
            "metrics": {
                "occupied_room_count": len(occupied_rooms),
                "waste_device_count": len(waste_devices),
            },
            "correction_round": revision_round,
            "correction_actions": [action.model_dump() for action in correction_actions],
        }

    def _feedback_text(self, room_id: str, completed: bool, revision_round: int) -> str:
        if completed:
            return f"The {room_id} illuminance and temperature are within target ranges."
        if revision_round >= 3:
            return f"The {room_id} has not fully reached the target ranges after 3 correction rounds."
        return f"The {room_id} has not reached target ranges; correction actions are required."
