from app.schemas.action_schema import AgentAction
from app.schemas.state_schema import DeviceState

LEGACY_ENTITY_ALIASES = {
    "living_room_light": "light.living_room_main",
    "living_room_ac": "ac.living_room_main",
    "living_room_curtain": "curtain.living_room_main",
    "bedroom_light": "light.bedroom_main",
    "bedroom_ac": "ac.bedroom_main",
    "study_room_light": "light.study_room_main",
    "study_room_ac": "ac.study_room_main",
}

SUPPORTED_ACTIONS = {
    "light": {"turn_on", "turn_off", "set_brightness", "set_color_temperature"},
    "curtain": {"open", "close", "set_opening"},
    "ac": {"turn_on", "turn_off", "set_temperature", "set_mode"},
    "fan": {"turn_on", "turn_off", "set_speed"},
    "window": {"open", "close", "set_opening"},
}


def clamp_percentage(value: float) -> float:
    return max(0.0, min(100.0, value))


def resolve_entity_id(entity_id: str) -> str:
    return LEGACY_ENTITY_ALIASES.get(entity_id, entity_id)


def apply_action_to_devices(
    devices: list[DeviceState],
    action: AgentAction,
) -> list[DeviceState]:
    updated_devices: list[DeviceState] = []
    for device in devices:
        if device.entity_id != resolve_entity_id(action.device_id):
            updated_devices.append(device)
            continue

        updated_devices.append(_apply_action_to_device(device, action))
    return updated_devices


def _apply_action_to_device(device: DeviceState, action: AgentAction) -> DeviceState:
    if device.device_type == "light":
        return _apply_light_action(device, action)
    if device.device_type == "curtain":
        return _apply_opening_action(device, action)
    if device.device_type == "ac":
        return _apply_ac_action(device, action)
    if device.device_type == "fan":
        return _apply_fan_action(device, action)
    if device.device_type == "window":
        return _apply_opening_action(device, action)
    return device


def _apply_light_action(device: DeviceState, action: AgentAction) -> DeviceState:
    if action.action_type == "turn_on":
        brightness_pct = device.brightness_pct if device.brightness_pct > 0 else 80
        return device.model_copy(update={"is_on": True, "brightness_pct": brightness_pct})
    if action.action_type == "turn_off":
        return device.model_copy(update={"is_on": False, "brightness_pct": 0})
    if action.action_type == "set_level" and isinstance(action.value, (int, float)):
        brightness_pct = _normalize_action_level(float(action.value))
        return device.model_copy(
            update={"is_on": brightness_pct > 0, "brightness_pct": brightness_pct}
        )
    return device


def _apply_opening_action(device: DeviceState, action: AgentAction) -> DeviceState:
    if action.action_type == "set_level" and isinstance(action.value, (int, float)):
        return device.model_copy(
            update={"opening_pct": _normalize_action_level(float(action.value))}
        )
    return device


def _apply_ac_action(device: DeviceState, action: AgentAction) -> DeviceState:
    if action.action_type == "turn_on":
        return device.model_copy(update={"is_on": True, "mode": "cool"})
    if action.action_type == "turn_off":
        return device.model_copy(update={"is_on": False, "mode": "off"})
    if action.action_type == "set_level" and isinstance(action.value, (int, float)):
        level = _normalize_action_level(float(action.value))
        setpoint_c = 28 - (level / 100) * 8
        return device.model_copy(
            update={"is_on": level > 0, "mode": "cool" if level > 0 else "off", "setpoint_c": round(setpoint_c, 1)}
        )
    return device


def _apply_fan_action(device: DeviceState, action: AgentAction) -> DeviceState:
    if action.action_type == "turn_on":
        speed_pct = device.speed_pct if device.speed_pct > 0 else 60
        return device.model_copy(update={"is_on": True, "speed_pct": speed_pct})
    if action.action_type == "turn_off":
        return device.model_copy(update={"is_on": False, "speed_pct": 0})
    if action.action_type == "set_level" and isinstance(action.value, (int, float)):
        speed_pct = _normalize_action_level(float(action.value))
        return device.model_copy(update={"is_on": speed_pct > 0, "speed_pct": speed_pct})
    return device


def _normalize_action_level(value: float) -> float:
    if 0 <= value <= 1:
        value *= 100
    return clamp_percentage(value)


def apply_device_control_action(
    devices: list[DeviceState],
    entity_id: str,
    action: str,
    parameters: dict,
) -> tuple[bool, list[DeviceState], str]:
    resolved_entity_id = resolve_entity_id(entity_id)
    target_device = next(
        (device for device in devices if device.entity_id == resolved_entity_id),
        None,
    )
    if target_device is None:
        return False, devices, f"Device entity_id '{entity_id}' does not exist."

    if target_device.device_type == "sensor":
        return False, devices, "Sensor devices do not support control actions."

    supported_actions = SUPPORTED_ACTIONS[target_device.device_type]
    if action not in supported_actions:
        return (
            False,
            devices,
            f"Action '{action}' is not supported for device type '{target_device.device_type}'.",
        )

    updated_device, notes = _apply_control_action_to_device(
        target_device,
        action,
        parameters,
    )
    updated_devices = [
        updated_device if device.entity_id == resolved_entity_id else device
        for device in devices
    ]
    message = f"Action '{action}' applied to '{resolved_entity_id}'."
    if notes:
        message += " " + " ".join(notes)
    return True, updated_devices, message


def _apply_control_action_to_device(
    device: DeviceState,
    action: str,
    parameters: dict,
) -> tuple[DeviceState, list[str]]:
    notes: list[str] = []
    if device.device_type == "light":
        return _apply_light_control(device, action, parameters, notes), notes
    if device.device_type == "curtain":
        return _apply_opening_control(device, action, parameters, notes), notes
    if device.device_type == "ac":
        return _apply_ac_control(device, action, parameters, notes), notes
    if device.device_type == "fan":
        return _apply_fan_control(device, action, parameters, notes), notes
    if device.device_type == "window":
        return _apply_opening_control(device, action, parameters, notes), notes
    return device, notes


def _apply_light_control(
    device: DeviceState,
    action: str,
    parameters: dict,
    notes: list[str],
) -> DeviceState:
    if action == "turn_on":
        brightness_pct = _clamped_parameter(
            parameters,
            "brightness_pct",
            device.brightness_pct if device.brightness_pct > 0 else 80,
            0,
            100,
            notes,
        )
        color_temperature_k = int(
            _clamped_parameter(
                parameters,
                "color_temperature_k",
                device.color_temperature_k,
                2700,
                6500,
                notes,
            )
        )
        return device.model_copy(
            update={
                "is_on": True,
                "brightness_pct": brightness_pct,
                "color_temperature_k": color_temperature_k,
            }
        )
    if action == "turn_off":
        return device.model_copy(update={"is_on": False, "brightness_pct": 0})
    if action == "set_brightness":
        brightness_pct = _clamped_parameter(
            parameters,
            "brightness_pct",
            device.brightness_pct,
            0,
            100,
            notes,
        )
        return device.model_copy(
            update={"is_on": brightness_pct > 0, "brightness_pct": brightness_pct}
        )
    color_temperature_k = int(
        _clamped_parameter(
            parameters,
            "color_temperature_k",
            device.color_temperature_k,
            2700,
            6500,
            notes,
        )
    )
    return device.model_copy(update={"color_temperature_k": color_temperature_k})


def _apply_opening_control(
    device: DeviceState,
    action: str,
    parameters: dict,
    notes: list[str],
) -> DeviceState:
    if action == "open":
        return device.model_copy(update={"opening_pct": 100})
    if action == "close":
        return device.model_copy(update={"opening_pct": 0})
    opening_pct = _clamped_parameter(
        parameters,
        "opening_pct",
        device.opening_pct,
        0,
        100,
        notes,
    )
    return device.model_copy(update={"opening_pct": opening_pct})


def _apply_ac_control(
    device: DeviceState,
    action: str,
    parameters: dict,
    notes: list[str],
) -> DeviceState:
    if action == "turn_on":
        mode = parameters.get("mode", device.mode if device.mode != "off" else "cool")
        if mode not in {"cool", "heat", "fan", "dry"}:
            notes.append(f"mode '{mode}' is invalid and was set to 'cool'.")
            mode = "cool"
        setpoint_c = _clamped_parameter(
            parameters,
            "setpoint_c",
            device.setpoint_c,
            16,
            30,
            notes,
        )
        return device.model_copy(update={"is_on": True, "mode": mode, "setpoint_c": setpoint_c})
    if action == "turn_off":
        return device.model_copy(update={"is_on": False, "mode": "off"})
    if action == "set_temperature":
        setpoint_c = _clamped_parameter(
            parameters,
            "setpoint_c",
            device.setpoint_c,
            16,
            30,
            notes,
        )
        return device.model_copy(update={"is_on": True, "setpoint_c": setpoint_c})
    mode = parameters.get("mode", device.mode)
    if mode not in {"cool", "heat", "fan", "dry", "off"}:
        notes.append(f"mode '{mode}' is invalid and was kept as '{device.mode}'.")
        mode = device.mode
    return device.model_copy(update={"is_on": mode != "off", "mode": mode})


def _apply_fan_control(
    device: DeviceState,
    action: str,
    parameters: dict,
    notes: list[str],
) -> DeviceState:
    if action == "turn_on":
        speed_pct = _clamped_parameter(
            parameters,
            "speed_pct",
            device.speed_pct if device.speed_pct > 0 else 60,
            0,
            100,
            notes,
        )
        return device.model_copy(update={"is_on": True, "speed_pct": speed_pct})
    if action == "turn_off":
        return device.model_copy(update={"is_on": False, "speed_pct": 0})
    speed_pct = _clamped_parameter(
        parameters,
        "speed_pct",
        device.speed_pct,
        0,
        100,
        notes,
    )
    return device.model_copy(update={"is_on": speed_pct > 0, "speed_pct": speed_pct})


def _clamped_parameter(
    parameters: dict,
    key: str,
    default_value: float,
    minimum: float,
    maximum: float,
    notes: list[str],
) -> float:
    raw_value = parameters.get(key, default_value)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        notes.append(f"{key}='{raw_value}' is invalid and was replaced with {default_value}.")
        value = float(default_value)

    clipped_value = max(minimum, min(maximum, value))
    if clipped_value != value:
        notes.append(f"{key} was clipped from {value:g} to {clipped_value:g}.")
    return clipped_value
