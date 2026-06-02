from app.schemas.state_schema import DeviceState, RoomState, SmartHomeState

K_HUMIDITY_AIR_EXCHANGE = 0.018
K_HUMIDITY_AIR_LEAKAGE = 0.004
K_OCCUPANCY_HUMIDITY_GAIN = 0.035
K_AC_COOL_DEHUMIDIFICATION = 0.045
K_AC_DRY_DEHUMIDIFICATION = 0.12


def update_room_humidity(
    state: SmartHomeState,
    room_id: str,
    dt_minutes: int = 1,
) -> RoomState:
    room = _get_room(state, room_id)
    outdoor_humidity = state.outdoor_environment.outdoor_humidity_percent
    window_opening_factor = _get_opening_factor(state.devices, room_id, "window", 20)
    ac_dehumidification = _calculate_ac_dehumidification(room, state.devices)

    # Simplified moisture balance:
    # H_next = H_in
    #        + k_air_exchange * window_opening * (H_out - H_in)
    #        + k_air_leakage * (H_out - H_in)
    #        + k_occupancy_gain
    #        - k_ac_dehumidification.
    # The model is intentionally lightweight for repeated experiments; it
    # captures ventilation, outdoor humidity drift, human moisture gain and
    # air-conditioner dehumidification trends.
    humidity_delta = (
        K_HUMIDITY_AIR_EXCHANGE
        * window_opening_factor
        * (outdoor_humidity - room.indoor_humidity_percent)
        + K_HUMIDITY_AIR_LEAKAGE * (outdoor_humidity - room.indoor_humidity_percent)
        + (K_OCCUPANCY_HUMIDITY_GAIN if room.occupancy else 0.0)
        - ac_dehumidification
    )
    indoor_humidity_percent = room.indoor_humidity_percent + humidity_delta * (dt_minutes / 10)
    indoor_humidity_percent = max(25.0, min(90.0, indoor_humidity_percent))
    return room.model_copy(
        update={"indoor_humidity_percent": round(indoor_humidity_percent, 2)}
    )


def update_all_room_humidity(
    state: SmartHomeState,
    dt_minutes: int = 1,
) -> SmartHomeState:
    rooms = [
        update_room_humidity(state, room.room_id, dt_minutes=dt_minutes)
        for room in state.rooms
    ]
    return state.model_copy(update={"rooms": rooms})


def _calculate_ac_dehumidification(room: RoomState, devices: list[DeviceState]) -> float:
    for device in devices:
        if device.device_type != "ac" or device.room != room.room_id or not device.is_on:
            continue
        if device.mode == "dry":
            return K_AC_DRY_DEHUMIDIFICATION * max(0.0, room.indoor_humidity_percent - 45.0)
        if device.mode == "cool":
            return K_AC_COOL_DEHUMIDIFICATION * max(0.0, room.indoor_humidity_percent - 50.0)
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
