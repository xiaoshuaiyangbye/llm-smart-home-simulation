from app.schemas.state_schema import DeviceState, RoomState, SmartHomeState

K_ENV = 0.02
K_SOLAR = 0.00022
K_AC = 0.18
K_INTERNAL = 0.01
K_WINDOW = 0.06
MAX_TEMPERATURE_STEP_C = 3.0


def update_room_temperature(
    state: SmartHomeState,
    room_id: str,
    dt_minutes: int = 1,
) -> RoomState:
    room = _get_room(state, room_id)
    outdoor_environment = state.outdoor_environment
    curtain_opening_factor = _get_opening_factor(state.devices, room_id, "curtain", 60)
    window_opening_factor = _get_opening_factor(state.devices, room_id, "window", 20)
    ac_effect = _calculate_ac_effect(room, state.devices)

    # Simplified thermal balance on a normalized 10-minute step:
    # T_next = T_in
    #        + k_env * (T_out - T_in)
    #        + k_solar * solar_radiation * curtain_opening_factor
    #        - k_ac * ac_effect
    #        + k_internal
    #        + k_window * window_opening_factor * (T_out - T_in).
    # dt_minutes is scaled by 10 so long steps keep a reasonable trend.
    # The per-step clamp avoids unrealistic indoor spikes during hour-sized
    # life-simulation steps, especially in mild transitional weather.
    temperature_delta = (
        K_ENV * (outdoor_environment.outdoor_temperature_c - room.indoor_temperature_c)
        + K_SOLAR
        * outdoor_environment.solar_radiation_w_m2
        * curtain_opening_factor
        - K_AC * ac_effect
        + (K_INTERNAL if room.occupancy else 0.0)
        + K_WINDOW
        * window_opening_factor
        * (outdoor_environment.outdoor_temperature_c - room.indoor_temperature_c)
    )
    scaled_delta = temperature_delta * (dt_minutes / 10)
    scaled_delta = max(-MAX_TEMPERATURE_STEP_C, min(MAX_TEMPERATURE_STEP_C, scaled_delta))
    indoor_temperature_c = room.indoor_temperature_c + scaled_delta
    return room.model_copy(
        update={"indoor_temperature_c": round(indoor_temperature_c, 2)}
    )


def update_all_room_temperature(
    state: SmartHomeState,
    dt_minutes: int = 1,
) -> SmartHomeState:
    rooms = [
        update_room_temperature(state, room.room_id, dt_minutes=dt_minutes)
        for room in state.rooms
    ]
    return state.model_copy(update={"rooms": rooms})


def calculate_apparent_temperature(
    room_state: RoomState,
    fan_state: DeviceState | None,
) -> float:
    if fan_state and fan_state.device_type == "fan" and fan_state.is_on:
        return round(
            room_state.indoor_temperature_c - 0.5 - fan_state.speed_pct / 100 * 1.5,
            2,
        )
    return round(room_state.indoor_temperature_c, 2)


def _calculate_ac_effect(room: RoomState, devices: list[DeviceState]) -> float:
    for device in devices:
        if device.device_type != "ac" or device.room != room.room_id or not device.is_on:
            continue
        if device.mode == "cool":
            return max(0.0, room.indoor_temperature_c - device.setpoint_c)
        if device.mode == "heat":
            return -max(0.0, device.setpoint_c - room.indoor_temperature_c)
    return 0.0


def _get_room(state: SmartHomeState, room_id: str) -> RoomState:
    for room in state.rooms:
        if room.room_id == room_id:
            return room
    raise ValueError(f"Room not found: {room_id}")


def _get_opening_factor(
    devices: list[DeviceState],
    room_id: str,
    device_type: str,
    default_opening_pct: float,
) -> float:
    for device in devices:
        if device.device_type == device_type and device.room == room_id:
            return device.opening_pct / 100
    return default_opening_pct / 100
