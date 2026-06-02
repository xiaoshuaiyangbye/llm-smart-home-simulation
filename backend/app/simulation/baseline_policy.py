from __future__ import annotations

from typing import Any

from app.schemas.action_schema import PlannedDeviceAction
from app.schemas.state_schema import DeviceState, RoomState, SmartHomeState

COMMON_HOME_ROOMS = {"living_room", "dining_room", "corridor"}


def plan_conventional_baseline_actions(state: SmartHomeState) -> list[dict[str, Any]]:
    """Careless fixed household policy used as the experiment baseline."""
    occupied_room = next((room for room in state.rooms if room.occupancy and room.activity != "away"), None)
    if occupied_room is None:
        return [action.model_dump() for action in _plan_away_actions(state)]

    actions: list[PlannedDeviceAction] = []
    for device in state.devices:
        if device.device_type == "sensor":
            continue
        room = next((item for item in state.rooms if item.room_id == device.room), None)
        if room is None:
            continue

        if room.room_id != occupied_room.room_id:
            actions.extend(_unoccupied_room_actions(device, room, occupied_room, state))
            continue

        actions.extend(_occupied_room_actions(device, room, state))

    return [action.model_dump() for action in _dedupe_actions(actions)]


def _plan_away_actions(state: SmartHomeState) -> list[PlannedDeviceAction]:
    actions: list[PlannedDeviceAction] = []
    hot_sunny = state.outdoor_environment.weather == "sunny" and state.outdoor_environment.outdoor_temperature_c >= 28
    curtain_opening = 30 if hot_sunny else 45
    window_opening = 10 if state.outdoor_environment.weather == "rainy" else 15

    for device in state.devices:
        if device.device_type == "light" and _light_active(device):
            actions.append(_action(device.entity_id, "turn_off", {}, "baseline away: turn off lights"))
        elif device.device_type == "ac" and _ac_active(device):
            actions.append(_action(device.entity_id, "turn_off", {}, "baseline away: turn off AC"))
        elif device.device_type == "fan" and _fan_active(device):
            actions.append(_action(device.entity_id, "turn_off", {}, "baseline away: turn off fan"))
        elif device.device_type == "curtain" and abs(device.opening_pct - curtain_opening) > 1:
            actions.append(
                _action(
                    device.entity_id,
                    "set_opening",
                    {"opening_pct": curtain_opening},
                    "baseline away: reduce solar gain",
                )
            )
        elif device.device_type == "window" and abs(device.opening_pct - window_opening) > 1:
            actions.append(
                _action(
                    device.entity_id,
                    "set_opening",
                    {"opening_pct": window_opening},
                    "baseline away: keep windows mostly closed",
                )
            )
    return actions


def _unoccupied_room_actions(
    device: DeviceState,
    room: RoomState,
    occupied_room: RoomState,
    state: SmartHomeState,
) -> list[PlannedDeviceAction]:
    if _is_home_evening(occupied_room, state) and room.room_id in COMMON_HOME_ROOMS:
        if device.device_type == "light" and not _light_active(device):
            return [
                _action(
                    device.entity_id,
                    "turn_on",
                    {"brightness_pct": 55, "color_temperature_k": 4000},
                    "baseline careless home routine: common-area light left on",
                )
            ]
        if device.device_type == "fan" and not _fan_active(device) and room.indoor_temperature_c > 27.5:
            return [
                _action(
                    device.entity_id,
                    "set_speed",
                    {"speed_pct": 25},
                    "baseline careless home routine: common-area fan left on",
                )
            ]
    if device.device_type == "window" and state.outdoor_environment.weather == "rainy" and device.opening_pct > 10:
        return [
            _action(
                device.entity_id,
                "set_opening",
                {"opening_pct": 10},
                "baseline rainy weather: limit unoccupied-room ventilation",
            )
        ]
    return []


def _occupied_room_actions(device: DeviceState, room: RoomState, state: SmartHomeState) -> list[PlannedDeviceAction]:
    if device.device_type == "light":
        brightness = _baseline_brightness(room, state)
        if brightness <= 0:
            return [_action(device.entity_id, "turn_off", {}, "baseline occupied room: sufficient or sleep lighting")]
        return [
            _action(
                device.entity_id,
                "turn_on",
                {"brightness_pct": brightness, "color_temperature_k": _baseline_color_temperature(room)},
                "baseline occupied room: fixed lighting level",
            )
        ]

    if device.device_type == "curtain":
        opening = _baseline_curtain_opening(room, state)
        return [
            _action(
                device.entity_id,
                "set_opening",
                {"opening_pct": opening},
                "baseline occupied room: fixed curtain schedule",
            )
        ]

    if device.device_type == "window":
        opening = _baseline_window_opening(room, state)
        return [
            _action(
                device.entity_id,
                "set_opening",
                {"opening_pct": opening},
                "baseline occupied room: fixed ventilation level",
            )
        ]

    if device.device_type == "ac":
        ac_target = _baseline_ac_target(room, state)
        if ac_target is None:
            return [_action(device.entity_id, "turn_off", {}, "baseline occupied room: thermostat off")]
        mode, setpoint = ac_target
        return [
            _action(
                device.entity_id,
                "turn_on",
                {"mode": mode, "setpoint_c": setpoint},
                "baseline occupied room: fixed thermostat",
            )
        ]

    if device.device_type == "fan":
        speed = _baseline_fan_speed(room, state)
        if speed <= 0:
            return [_action(device.entity_id, "turn_off", {}, "baseline occupied room: fan off")]
        return [
            _action(
                device.entity_id,
                "set_speed",
                {"speed_pct": speed},
                "baseline occupied room: fixed fan speed",
            )
        ]

    return []


def _baseline_brightness(room: RoomState, state: SmartHomeState) -> float:
    if room.activity == "sleep":
        return 0
    hour = state.outdoor_environment.time_hour
    evening_or_night = hour < 7 or hour >= 18
    needs_light = room.indoor_illuminance_lux < 350 or evening_or_night or room.activity in {"study", "movie"}
    if not needs_light:
        return 0
    if room.activity == "movie":
        return 25
    if room.activity == "study":
        return 80
    if room.room_id in {"kitchen", "bathroom"}:
        return 75
    if room.room_id == "dining_room":
        return 65
    return 60


def _baseline_color_temperature(room: RoomState) -> int:
    if room.activity == "study":
        return 4500
    if room.activity == "movie":
        return 3000
    return 4000


def _baseline_curtain_opening(room: RoomState, state: SmartHomeState) -> float:
    if room.activity == "sleep":
        return 10
    if room.activity == "movie":
        return 15
    if state.outdoor_environment.weather == "sunny" and state.outdoor_environment.outdoor_temperature_c >= 30:
        return 45
    if state.outdoor_environment.time_hour < 7 or state.outdoor_environment.time_hour >= 22:
        return 35
    return 70


def _baseline_window_opening(room: RoomState, state: SmartHomeState) -> float:
    if room.activity == "sleep":
        return 10
    if state.outdoor_environment.weather == "rainy":
        return 5
    if _baseline_ac_target(room, state) is not None:
        return 10
    outdoor = state.outdoor_environment
    if outdoor.outdoor_humidity_percent > 75:
        return 10
    if 18 <= outdoor.outdoor_temperature_c <= 27 and abs(outdoor.outdoor_temperature_c - room.indoor_temperature_c) <= 4:
        return 35
    return 20


def _baseline_ac_target(room: RoomState, state: SmartHomeState) -> tuple[str, float] | None:
    if room.activity == "sleep":
        if room.indoor_temperature_c > 29.2 or (state.outdoor_environment.outdoor_temperature_c >= 31 and room.indoor_temperature_c > 28.5):
            return ("cool", 27.5)
        if room.indoor_temperature_c < 19:
            return ("heat", 20)
        return None

    if room.indoor_temperature_c > 29.2 or (state.outdoor_environment.outdoor_temperature_c >= 32 and room.indoor_temperature_c > 28.5):
        return ("cool", 27)
    if room.indoor_temperature_c < 19:
        return ("heat", 21)
    return None


def _baseline_fan_speed(room: RoomState, state: SmartHomeState) -> float:
    if room.activity == "sleep":
        return 0
    if _baseline_ac_target(room, state) is not None:
        return 30 if room.indoor_temperature_c >= 30 else 0
    if room.indoor_temperature_c > 28:
        return 50
    if room.indoor_temperature_c > 26.5:
        return 35
    return 0


def _is_home_evening(occupied_room: RoomState, state: SmartHomeState) -> bool:
    hour = state.outdoor_environment.time_hour
    return occupied_room.activity != "sleep" and 18 <= hour <= 22


def _action(entity_id: str, action: str, parameters: dict[str, Any], reason: str) -> PlannedDeviceAction:
    return PlannedDeviceAction(entity_id=entity_id, action=action, parameters=parameters, reason=reason)


def _dedupe_actions(actions: list[PlannedDeviceAction]) -> list[PlannedDeviceAction]:
    by_entity: dict[str, PlannedDeviceAction] = {}
    for action in actions:
        by_entity[action.entity_id] = action
    return list(by_entity.values())


def _light_active(device: DeviceState) -> bool:
    return bool(getattr(device, "is_on", False) and getattr(device, "brightness_pct", 0) > 0)


def _ac_active(device: DeviceState) -> bool:
    return bool(getattr(device, "is_on", False) and getattr(device, "mode", "off") != "off")


def _fan_active(device: DeviceState) -> bool:
    return bool(getattr(device, "is_on", False) and getattr(device, "speed_pct", 0) > 0)
