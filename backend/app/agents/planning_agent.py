from datetime import datetime
from typing import Any

from app.schemas.action_schema import PlannedDeviceAction
from app.schemas.state_schema import SmartHomeState


class PlanningAgent:
    def plan(self, semantic_result: dict[str, Any], current_state: SmartHomeState) -> dict[str, Any]:
        room_id = semantic_result.get("room", "living_room")
        intent = semantic_result.get("intent", "basic_light_control")
        control_goal = semantic_result.get("control_goal")
        if intent in {"context_update", "occupancy_update"}:
            return {
                "plan_id": f"plan-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "agent": "planning_agent",
                "intent": intent,
                "room": room_id,
                "scope": semantic_result.get("scope", "single_room"),
                "control_goal": control_goal,
                "actions": [],
            }
        if intent == "away_mode":
            actions = self._plan_all_room_away_actions(current_state)
            return {
                "plan_id": f"plan-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "agent": "planning_agent",
                "intent": intent,
                "room": "all_rooms",
                "scope": "all_rooms",
                "control_goal": control_goal,
                "actions": [action.model_dump() for action in actions],
            }

        if room_id == "all_rooms":
            if intent == "basic_light_control":
                actions = self._plan_all_room_light_actions(current_state, control_goal)
            elif intent == "basic_curtain_control":
                actions = self._plan_all_room_opening_actions(
                    current_state,
                    semantic_result.get("devices", ["curtain"]),
                    control_goal,
                )
            elif intent == "basic_ac_control":
                targets = semantic_result.get("targets", {})
                actions = self._plan_all_room_ac_actions(
                    current_state,
                    control_goal,
                    targets.get("temperature_c_range", [24, 26.7]),
                )
            elif intent == "thermal_comfort_control":
                targets = semantic_result.get("targets", {})
                actions = self._plan_all_room_thermal_actions(
                    current_state,
                    control_goal,
                    targets.get("temperature_c_range", [24, 26.7]),
                    semantic_result.get("devices", []),
                )
            elif intent == "away_mode":
                actions = self._plan_all_room_away_actions(current_state)
            elif intent == "energy_saving_mode":
                actions = self._plan_all_room_energy_saving_actions(current_state)
            else:
                actions = []
            current_room_context = semantic_result.get("current_room_context")
            if isinstance(current_room_context, str):
                actions.extend(self._plan_vacated_room_shutdown_actions(semantic_result, current_state, current_room_context))
            return {
                "plan_id": f"plan-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "agent": "planning_agent",
                "intent": intent,
                "room": room_id,
                "scope": "all_rooms",
                "control_goal": control_goal,
                "actions": [action.model_dump() for action in actions],
            }

        room = next((room for room in current_state.rooms if room.room_id == room_id), current_state.rooms[0])
        targets = semantic_result.get("targets", {})
        illuminance_range = targets.get("illuminance_lux_range", [0, 1200])
        temperature_range = targets.get("temperature_c_range", [18, 30])
        actions = self._plan_actions(intent, room_id, room.indoor_illuminance_lux, room.indoor_temperature_c, illuminance_range, temperature_range, current_state, control_goal, semantic_result.get("devices"))
        actions.extend(self._plan_vacated_room_shutdown_actions(semantic_result, current_state, room_id))
        if intent == "sleep_mode":
            actions.extend(self._plan_sleep_cleanup_actions(current_state, room_id))
        actions = self._apply_contextual_safety_constraints(actions, semantic_result, current_state, room_id)
        return {
            "plan_id": f"plan-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "agent": "planning_agent",
            "intent": intent,
            "room": room_id,
            "scope": semantic_result.get("scope", "single_room"),
            "control_goal": control_goal,
            "actions": [action.model_dump() for action in actions],
        }

    def _plan_actions(
        self,
        intent: str,
        room_id: str,
        illuminance_lux: float,
        temperature_c: float,
        illuminance_range: list[float],
        temperature_range: list[float],
        state: SmartHomeState,
        control_goal: str | None = None,
        devices: list[str] | None = None,
    ) -> list[PlannedDeviceAction]:
        if intent == "away_mode":
            return [
                self._action(room_id, "light", "turn_off", {}, "turn off lighting when away"),
                self._action(room_id, "ac", "turn_off", {}, "turn off air conditioning when away"),
                self._action(room_id, "fan", "turn_off", {}, "turn off fan when away"),
                self._action(room_id, "curtain", "set_opening", {"opening_pct": 30}, "reduce solar gain while away"),
            ]
        if intent == "basic_light_control":
            if control_goal == "turn_off":
                return [self._action(room_id, "light", "turn_off", {}, "turn off requested room lighting")]
            return [self._action(room_id, "light", "turn_on", {"brightness_pct": 70, "color_temperature_k": 4000}, "turn on requested room lighting")]
        if intent == "basic_curtain_control":
            return self._plan_room_opening_actions(state, room_id, devices or ["curtain"], control_goal)
        if intent == "basic_ac_control":
            if control_goal == "turn_off":
                return [self._action(room_id, "ac", "turn_off", {}, "turn off requested room air conditioner")]
            target_temperature = self._target_temperature(temperature_range, default=25.0)
            mode = "heat" if temperature_c < target_temperature - 0.5 else "cool"
            return [
                self._action(
                    room_id,
                    "ac",
                    "turn_on",
                    {"mode": mode, "setpoint_c": target_temperature},
                    "apply requested room air conditioner control",
                )
            ]
        if intent == "sleep_mode":
            actions = [
                self._action(room_id, "curtain", "close", {}, "darken room for sleep"),
                self._action(room_id, "light", "turn_off", {}, "keep illuminance low for sleep"),
            ]
            if temperature_c > 29 or state.outdoor_environment.outdoor_temperature_c > 30:
                actions.append(self._action(room_id, "ac", "turn_on", {"mode": "cool", "setpoint_c": 27}, "use relaxed cooling only when sleep heat load is high"))
                actions.append(self._action(room_id, "fan", "turn_off", {}, "avoid continuous airflow during sleep"))
                actions.append(self._action(room_id, "window", "set_opening", {"opening_pct": 10}, "keep minimal ventilation while cooling"))
            else:
                if self._has_device(state, room_id, "ac"):
                    actions.append(self._action(room_id, "ac", "turn_off", {}, "avoid unnecessary air conditioning in mild sleep conditions"))
                fan_speed = 20 if temperature_c > 28 else 0
                actions.append(
                    self._action(
                        room_id,
                        "fan",
                        "set_speed" if fan_speed else "turn_off",
                        {"speed_pct": fan_speed} if fan_speed else {},
                        "use quiet airflow only if the bedroom is warm",
                    )
                )
                window_opening = 20 if state.outdoor_environment.weather != "rainy" and state.outdoor_environment.outdoor_humidity_percent <= 75 else 10
                actions.append(self._action(room_id, "window", "set_opening", {"opening_pct": window_opening}, "use mild night ventilation for sleep"))
            return actions
        if intent == "movie_mode":
            actions = [
                self._action(room_id, "curtain", "set_opening", {"opening_pct": 15}, "reduce glare for movie mode"),
                self._action(room_id, "light", "turn_on", {"brightness_pct": 20, "color_temperature_k": 3000}, "provide low ambient light"),
            ]
            if temperature_c > 28.5 and not self._prefer_passive_cooling(state, temperature_c, 28.5):
                actions.append(self._action(room_id, "ac", "turn_on", {"mode": "cool", "setpoint_c": 27}, "cool only when passive movie comfort is insufficient"))
            elif temperature_c > 27.5 and self._has_device(state, room_id, "fan"):
                actions.append(self._action(room_id, "fan", "set_speed", {"speed_pct": 30}, "use low fan speed for movie comfort"))
            return actions
        if intent == "energy_saving_mode":
            return self._plan_energy_saving(room_id, illuminance_lux, temperature_c, illuminance_range, temperature_range, state)

        actions: list[PlannedDeviceAction] = []
        min_lux, max_lux = illuminance_range
        min_temp, max_temp = temperature_range
        if illuminance_lux < min_lux:
            if state.outdoor_environment.weather in {"sunny", "cloudy"}:
                opening = 45 if self._is_hot_sunny_afternoon(state) else 70
                actions.append(self._action(room_id, "curtain", "set_opening", {"opening_pct": opening}, "increase daylight while controlling solar gain"))
            actions.append(self._action(room_id, "light", "turn_on", {"brightness_pct": 75, "color_temperature_k": 4500}, "raise illuminance for target activity"))
        elif illuminance_lux > max_lux:
            actions.append(self._action(room_id, "light", "set_brightness", {"brightness_pct": 30}, "reduce artificial lighting because illuminance is high"))
            actions.append(self._action(room_id, "curtain", "set_opening", {"opening_pct": 30}, "reduce daylight and glare"))

        if temperature_c > max_temp:
            actions.append(self._action(room_id, "curtain", "set_opening", {"opening_pct": 35}, "reduce solar radiation before cooling"))
            passive_first = self._prefer_passive_cooling(state, temperature_c, max_temp)
            if passive_first and self._has_device(state, room_id, "window"):
                actions.append(self._action(room_id, "window", "set_opening", {"opening_pct": 45}, "use mild outdoor air before air conditioning"))
            if self._has_device(state, room_id, "ac") and not passive_first:
                setpoint = max(25.5, min(max_temp, 26.5))
                actions.append(self._action(room_id, "ac", "turn_on", {"mode": "cool", "setpoint_c": setpoint}, "maintain thermal comfort with a moderate cooling setpoint"))
            if self._has_device(state, room_id, "fan"):
                fan_speed = 35 if passive_first else (45 if temperature_c < max_temp + 1.5 else 60)
                actions.append(self._action(room_id, "fan", "set_speed", {"speed_pct": fan_speed}, "improve apparent thermal comfort without excessive airflow"))
        elif temperature_c < min_temp:
            if self._has_device(state, room_id, "ac"):
                actions.append(self._action(room_id, "ac", "turn_on", {"mode": "heat", "setpoint_c": (min_temp + max_temp) / 2}, "raise room temperature to comfort range"))

        if not actions and intent in {"basic_light_control", "lighting_comfort_control", "study_mode"}:
            actions.append(self._action(room_id, "light", "turn_on", {"brightness_pct": 65, "color_temperature_k": 4300}, "keep lighting within comfort range"))
        return actions

    def _plan_energy_saving(self, room_id: str, illuminance_lux: float, temperature_c: float, illuminance_range: list[float], temperature_range: list[float], state: SmartHomeState) -> list[PlannedDeviceAction]:
        actions: list[PlannedDeviceAction] = []
        if illuminance_lux < illuminance_range[0] and state.outdoor_environment.weather in {"sunny", "cloudy"}:
            actions.append(self._action(room_id, "curtain", "set_opening", {"opening_pct": 55 if self._is_hot_sunny_afternoon(state) else 80}, "use daylight before increasing lamp brightness"))
            actions.append(self._action(room_id, "light", "set_brightness", {"brightness_pct": 35}, "use low lamp brightness for energy saving"))
        else:
            actions.append(self._action(room_id, "light", "set_brightness", {"brightness_pct": 20}, "reduce lamp energy use"))
        if temperature_c > temperature_range[1]:
            actions.append(self._action(room_id, "curtain", "set_opening", {"opening_pct": 30}, "reduce solar heat gain"))
            if self._has_device(state, room_id, "ac"):
                actions.append(self._action(room_id, "ac", "turn_on", {"mode": "cool", "setpoint_c": 27}, "use relaxed cooling setpoint for energy saving"))
            if self._has_device(state, room_id, "fan"):
                actions.append(self._action(room_id, "fan", "set_speed", {"speed_pct": 60}, "improve comfort with lower cooling energy"))
        return actions

    def _is_hot_sunny_afternoon(self, state: SmartHomeState) -> bool:
        return state.outdoor_environment.weather == "sunny" and 12 <= state.outdoor_environment.time_hour <= 16 and state.outdoor_environment.outdoor_temperature_c >= 30

    def _target_temperature(self, temperature_range: list[float], default: float) -> float:
        if len(temperature_range) != 2:
            return default
        target = (float(temperature_range[0]) + float(temperature_range[1])) / 2
        return round(max(16.0, min(30.0, target)), 1)

    def _prefer_passive_cooling(self, state: SmartHomeState, temperature_c: float, max_temp: float) -> bool:
        outdoor = state.outdoor_environment
        if outdoor.weather == "rainy" or outdoor.outdoor_humidity_percent > 78:
            return False
        if outdoor.outdoor_temperature_c > 30:
            return False
        return temperature_c <= max_temp + 1.5 or outdoor.outdoor_temperature_c + 1.0 < temperature_c

    def _action(self, room_id: str, device_type: str, action: str, parameters: dict[str, Any], reason: str) -> PlannedDeviceAction:
        return PlannedDeviceAction(entity_id=f"{device_type}.{room_id}_main", action=action, parameters=parameters, reason=reason)

    def _plan_all_room_light_actions(self, state: SmartHomeState, control_goal: str | None) -> list[PlannedDeviceAction]:
        action = "turn_off" if control_goal == "turn_off" else "turn_on"
        parameters = {} if action == "turn_off" else {"brightness_pct": 70, "color_temperature_k": 4000}
        reason = "turn off all room lights" if action == "turn_off" else "turn on all room lights"
        room_order = {room.room_id: index for index, room in enumerate(state.rooms)}
        lights = sorted(
            (device for device in state.devices if device.device_type == "light"),
            key=lambda device: room_order.get(device.room, 999),
        )
        return [
            PlannedDeviceAction(
                entity_id=light.entity_id,
                action=action,
                parameters=parameters,
                reason=reason,
            )
            for light in lights
        ]

    def _plan_all_room_opening_actions(
        self,
        state: SmartHomeState,
        devices: list[str],
        control_goal: str | None,
    ) -> list[PlannedDeviceAction]:
        device_types = self._opening_device_types(devices)
        opening_pct = self._opening_target_pct(control_goal)
        room_order = {room.room_id: index for index, room in enumerate(state.rooms)}
        opening_devices = sorted(
            (
                device
                for device in state.devices
                if device.device_type in device_types
            ),
            key=lambda device: (room_order.get(device.room, 999), device.device_type),
        )
        return [
            PlannedDeviceAction(
                entity_id=device.entity_id,
                action="set_opening",
                parameters={"opening_pct": opening_pct},
                reason=f"apply all-room {device.device_type} opening control",
            )
            for device in opening_devices
        ]

    def _plan_all_room_ac_actions(
        self,
        state: SmartHomeState,
        control_goal: str | None,
        temperature_range: list[float],
    ) -> list[PlannedDeviceAction]:
        room_by_id = {room.room_id: room for room in state.rooms}
        room_order = {room.room_id: index for index, room in enumerate(state.rooms)}
        air_conditioners = sorted(
            (device for device in state.devices if device.device_type == "ac"),
            key=lambda device: room_order.get(device.room, 999),
        )
        if control_goal == "turn_off":
            return [
                PlannedDeviceAction(
                    entity_id=device.entity_id,
                    action="turn_off",
                    parameters={},
                    reason="turn off all air conditioners",
                )
                for device in air_conditioners
            ]

        target_temperature = self._target_temperature(temperature_range, default=25.0)
        actions: list[PlannedDeviceAction] = []
        for device in air_conditioners:
            room = room_by_id.get(device.room)
            room_temperature = room.indoor_temperature_c if room else target_temperature
            mode = "heat" if room_temperature < target_temperature - 0.5 else "cool"
            actions.append(
                PlannedDeviceAction(
                    entity_id=device.entity_id,
                    action="turn_on",
                    parameters={"mode": mode, "setpoint_c": target_temperature},
                    reason="apply all-room air conditioner control",
                )
            )
        return actions

    def _plan_all_room_thermal_actions(
        self,
        state: SmartHomeState,
        control_goal: str | None,
        temperature_range: list[float],
        devices: list[str],
    ) -> list[PlannedDeviceAction]:
        target_device_types = set(devices or [])
        if control_goal == "turn_off":
            shutdown_types = target_device_types & {"ac", "fan"} or {"ac", "fan"}
            return [
                PlannedDeviceAction(
                    entity_id=device.entity_id,
                    action="turn_off",
                    parameters={},
                    reason="turn off all requested thermal devices",
                )
                for device in state.devices
                if device.device_type in shutdown_types
            ]

        actions: list[PlannedDeviceAction] = []
        min_temp, max_temp = temperature_range
        for room in state.rooms:
            if room.activity == "away" and not room.occupancy:
                continue
            if room.indoor_temperature_c > max_temp:
                curtain = self._room_device(state, room.room_id, "curtain")
                if curtain:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=curtain.entity_id,
                            action="set_opening",
                            parameters={"opening_pct": 35},
                            reason="reduce solar gain for whole-home thermal comfort",
                        )
                    )
                passive_first = self._prefer_passive_cooling(state, room.indoor_temperature_c, max_temp)
                window = self._room_device(state, room.room_id, "window")
                if passive_first and window:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=window.entity_id,
                            action="set_opening",
                            parameters={"opening_pct": 35},
                            reason="use passive ventilation for whole-home thermal comfort",
                        )
                    )
                ac = self._room_device(state, room.room_id, "ac")
                if ac and not passive_first:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=ac.entity_id,
                            action="turn_on",
                            parameters={"mode": "cool", "setpoint_c": max(25.5, min(max_temp, 27.0))},
                            reason="cool occupied room for whole-home thermal comfort",
                        )
                    )
                fan = self._room_device(state, room.room_id, "fan")
                if fan:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=fan.entity_id,
                            action="set_speed",
                            parameters={"speed_pct": 45},
                            reason="improve apparent temperature for whole-home thermal comfort",
                        )
                    )
            elif room.indoor_temperature_c < min_temp:
                ac = self._room_device(state, room.room_id, "ac")
                if ac:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=ac.entity_id,
                            action="turn_on",
                            parameters={"mode": "heat", "setpoint_c": (min_temp + max_temp) / 2},
                            reason="heat occupied room for whole-home thermal comfort",
                        )
                    )
        return actions

    def _plan_all_room_away_actions(self, state: SmartHomeState) -> list[PlannedDeviceAction]:
        actions: list[PlannedDeviceAction] = []
        for device in state.devices:
            if device.device_type == "light" and device.is_on:
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="turn_off",
                        parameters={},
                        reason="turn off all lighting for away mode",
                    )
                )
            elif device.device_type == "ac" and device.is_on:
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="turn_off",
                        parameters={},
                        reason="turn off all air conditioners for away mode",
                    )
                )
            elif device.device_type == "fan" and device.is_on:
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="turn_off",
                        parameters={},
                        reason="turn off all fans for away mode",
                    )
                )
            elif device.device_type == "curtain":
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="set_opening",
                        parameters={"opening_pct": 30},
                        reason="reduce solar gain while away",
                    )
                )
            elif device.device_type == "window":
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="set_opening",
                        parameters={"opening_pct": 10},
                        reason="keep windows mostly closed while away",
                    )
                )
        return actions

    def _plan_all_room_energy_saving_actions(self, state: SmartHomeState) -> list[PlannedDeviceAction]:
        occupied_rooms = {room.room_id for room in state.rooms if room.occupancy and room.activity != "away"}
        actions: list[PlannedDeviceAction] = []
        for device in state.devices:
            room_is_occupied = device.room in occupied_rooms
            if device.device_type == "light":
                if not room_is_occupied and device.is_on and device.brightness_pct > 0:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=device.entity_id,
                            action="turn_off",
                            parameters={},
                            reason="turn off lighting in unoccupied room for whole-home energy saving",
                        )
                    )
                elif room_is_occupied and device.is_on and device.brightness_pct > 35:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=device.entity_id,
                            action="set_brightness",
                            parameters={"brightness_pct": 35},
                            reason="lower occupied-room lighting for whole-home energy saving",
                        )
                    )
            elif device.device_type == "ac":
                if not room_is_occupied and device.is_on:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=device.entity_id,
                            action="turn_off",
                            parameters={},
                            reason="turn off air conditioner in unoccupied room for whole-home energy saving",
                        )
                    )
                elif room_is_occupied and device.is_on and device.mode == "cool" and device.setpoint_c < 27:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=device.entity_id,
                            action="set_temperature",
                            parameters={"setpoint_c": 27},
                            reason="relax cooling setpoint for whole-home energy saving",
                        )
                    )
            elif device.device_type == "fan" and not room_is_occupied and device.is_on:
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="turn_off",
                        parameters={},
                        reason="turn off fan in unoccupied room for whole-home energy saving",
                    )
                )
            elif device.device_type == "window":
                target_opening = 10 if state.outdoor_environment.weather == "rainy" else 20
                if device.opening_pct > target_opening:
                    actions.append(
                        PlannedDeviceAction(
                            entity_id=device.entity_id,
                            action="set_opening",
                            parameters={"opening_pct": target_opening},
                            reason="limit ventilation load during whole-home energy saving",
                        )
                    )
        return actions

    def _plan_room_opening_actions(
        self,
        state: SmartHomeState,
        room_id: str,
        devices: list[str],
        control_goal: str | None,
    ) -> list[PlannedDeviceAction]:
        device_types = self._opening_device_types(devices)
        opening_pct = self._opening_target_pct(control_goal)
        return [
            PlannedDeviceAction(
                entity_id=device.entity_id,
                action="set_opening",
                parameters={"opening_pct": opening_pct},
                reason=f"apply {device.device_type} opening control for requested room",
            )
            for device in state.devices
            if device.room == room_id and device.device_type in device_types
        ]

    def _opening_device_types(self, devices: list[str]) -> set[str]:
        device_types = {device for device in devices if device in {"curtain", "window"}}
        return device_types or {"curtain"}

    def _opening_target_pct(self, control_goal: str | None) -> float:
        if control_goal == "turn_off":
            return 0.0
        if control_goal == "turn_on":
            return 100.0
        return 60.0

    def _has_device(self, state: SmartHomeState, room_id: str, device_type: str) -> bool:
        return any(device.room == room_id and device.device_type == device_type for device in state.devices)

    def _room_device(self, state: SmartHomeState, room_id: str, device_type: str):
        return next((device for device in state.devices if device.room == room_id and device.device_type == device_type), None)

    def _apply_contextual_safety_constraints(
        self,
        actions: list[PlannedDeviceAction],
        semantic_result: dict[str, Any],
        state: SmartHomeState,
        room_id: str,
    ) -> list[PlannedDeviceAction]:
        constraints = semantic_result.get("constraints", {})
        if not constraints.get("health_context_active"):
            return actions

        adjusted_actions = [
            self._adjust_action_for_context(action, constraints, state)
            for action in actions
        ]
        planned_entities = {action.entity_id for action in adjusted_actions}
        adjusted_actions.extend(
            self._plan_active_device_guard_actions(
                state=state,
                room_id=room_id,
                constraints=constraints,
                planned_entities=planned_entities,
            )
        )
        return adjusted_actions

    def _adjust_action_for_context(
        self,
        action: PlannedDeviceAction,
        constraints: dict[str, Any],
        state: SmartHomeState,
    ) -> PlannedDeviceAction:
        device_type = action.entity_id.split(".", 1)[0]
        if device_type == "window" and constraints.get("avoid_window_opening"):
            opening = self._requested_opening_pct(action)
            if action.action == "open" or opening > 10:
                return action.model_copy(
                    update={
                        "action": "set_opening",
                        "parameters": {"opening_pct": 0},
                        "reason": f"{action.reason}; blocked by health context to avoid draft",
                    }
                )

        if device_type == "fan" and constraints.get("avoid_strong_fan"):
            limit = float(constraints.get("fan_speed_limit_pct", 30))
            if action.action == "set_speed":
                speed = min(float(action.parameters.get("speed_pct", limit)), limit)
                return action.model_copy(
                    update={
                        "parameters": {"speed_pct": speed},
                        "reason": f"{action.reason}; limited by health context to avoid strong airflow",
                    }
                )
            if action.action == "turn_on":
                parameters = {**action.parameters, "speed_pct": min(float(action.parameters.get("speed_pct", limit)), limit)}
                return action.model_copy(
                    update={
                        "parameters": parameters,
                        "reason": f"{action.reason}; limited by health context to avoid strong airflow",
                    }
                )

        if device_type == "ac" and constraints.get("avoid_overcooling"):
            floor = float(constraints.get("cooling_setpoint_floor_c", 26))
            if action.action in {"turn_on", "set_temperature"}:
                mode = action.parameters.get("mode", "cool")
                if mode == "cool":
                    setpoint = max(float(action.parameters.get("setpoint_c", floor)), floor)
                    parameters = {**action.parameters, "mode": "cool", "setpoint_c": setpoint}
                    return action.model_copy(
                        update={
                            "parameters": parameters,
                            "reason": f"{action.reason}; raised setpoint by health context to avoid overcooling",
                        }
                    )
        return action

    def _requested_opening_pct(self, action: PlannedDeviceAction) -> float:
        if action.action == "close":
            return 0.0
        if action.action == "open":
            return 100.0
        return float(action.parameters.get("opening_pct", 0))

    def _plan_active_device_guard_actions(
        self,
        state: SmartHomeState,
        room_id: str,
        constraints: dict[str, Any],
        planned_entities: set[str],
    ) -> list[PlannedDeviceAction]:
        guard_actions: list[PlannedDeviceAction] = []
        fan_limit = float(constraints.get("fan_speed_limit_pct", 30))
        for device in state.devices:
            if device.room != room_id or device.entity_id in planned_entities:
                continue
            if device.device_type == "window" and constraints.get("avoid_window_opening") and device.opening_pct > 10:
                guard_actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="set_opening",
                        parameters={"opening_pct": 0},
                        reason="close window due to active health context and draft avoidance",
                    )
                )
            if device.device_type == "fan" and constraints.get("avoid_strong_fan") and device.is_on and device.speed_pct > fan_limit:
                guard_actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="set_speed",
                        parameters={"speed_pct": fan_limit},
                        reason="reduce fan speed due to active health context",
                    )
                )
        return guard_actions

    def _plan_vacated_room_shutdown_actions(
        self,
        semantic_result: dict[str, Any],
        state: SmartHomeState,
        target_room_id: str,
    ) -> list[PlannedDeviceAction]:
        if semantic_result.get("current_room_context") != target_room_id:
            return []

        previous_rooms = [
            room_id
            for room_id in semantic_result.get("previous_occupied_rooms", [])
            if room_id != target_room_id
        ]
        if not previous_rooms:
            return []

        actions: list[PlannedDeviceAction] = []
        for device in state.devices:
            if device.room not in previous_rooms or device.device_type not in {"light", "ac", "fan"}:
                continue
            if not self._is_device_active(device):
                continue
            actions.append(
                PlannedDeviceAction(
                    entity_id=device.entity_id,
                    action="turn_off",
                    parameters={},
                    reason="turn off energy-consuming device in vacated room",
                )
            )
        return actions

    def _is_device_active(self, device) -> bool:
        if device.device_type == "light":
            return bool(device.is_on and device.brightness_pct > 0)
        if device.device_type == "ac":
            return bool(device.is_on and device.mode != "off")
        if device.device_type == "fan":
            return bool(device.is_on and device.speed_pct > 0)
        return False

    def _plan_sleep_cleanup_actions(self, state: SmartHomeState, sleep_room_id: str) -> list[PlannedDeviceAction]:
        actions: list[PlannedDeviceAction] = []
        for device in state.devices:
            if device.room == sleep_room_id:
                continue
            if device.device_type == "light" and device.is_on and device.brightness_pct > 0:
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="turn_off",
                        parameters={},
                        reason="turn off non-bedroom lighting for sleep",
                    )
                )
            elif device.device_type == "ac" and device.is_on:
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="turn_off",
                        parameters={},
                        reason="turn off non-bedroom air conditioner for sleep",
                    )
                )
            elif device.device_type == "fan" and device.is_on and device.speed_pct > 0:
                actions.append(
                    PlannedDeviceAction(
                        entity_id=device.entity_id,
                        action="turn_off",
                        parameters={},
                        reason="turn off non-bedroom fan for sleep",
                    )
                )
        return actions
