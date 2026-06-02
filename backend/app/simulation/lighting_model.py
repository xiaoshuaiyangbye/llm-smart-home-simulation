from app.schemas.state_schema import DeviceState, RoomState, SmartHomeState

WINDOW_TRANSMITTANCE = 0.12
CLOSED_WINDOW_DAYLIGHT_FACTOR = 0.75
OPEN_WINDOW_DAYLIGHT_GAIN = 0.25
WEATHER_VISIBLE_FACTORS = {
    "sunny": 1.0,
    "cloudy": 0.75,
    "overcast": 0.5,
    "rainy": 0.35,
}
ROOM_DAYLIGHT_FACTORS = {
    "living_room": 0.08,
    "bedroom": 0.05,
    "study_room": 0.06,
    "dining_room": 0.06,
    "kitchen": 0.05,
    "bathroom": 0.035,
    "laundry": 0.045,
    "balcony": 0.12,
    "corridor": 0.03,
}


def update_room_illuminance(state: SmartHomeState, room_id: str) -> RoomState:
    room = _get_room(state, room_id)
    curtain_opening_factor = _get_curtain_opening_factor(state.devices, room_id)
    window_daylight_factor = _get_window_daylight_factor(state.devices, room_id)
    weather_visible_factor = WEATHER_VISIBLE_FACTORS[state.outdoor_environment.weather]
    room_daylight_factor = ROOM_DAYLIGHT_FACTORS.get(room_id, 0.05)

    # Natural daylight:
    # E_daylight = E_out * tau_window * f_window * f_curtain * f_weather * f_room.
    # Closed glass still admits part of the daylight; opening the window
    # increases the effective daylight factor by reducing frame/glass loss.
    daylight_lux = (
        state.outdoor_environment.outdoor_illuminance_lux
        * WINDOW_TRANSMITTANCE
        * window_daylight_factor
        * curtain_opening_factor
        * weather_visible_factor
        * room_daylight_factor
    )

    # Artificial lighting:
    # E_lamp = sum(brightness_pct / 100 * max_lux_contribution).
    lamp_lux = sum(
        device.brightness_pct / 100 * device.max_lux_contribution
        for device in state.devices
        if device.device_type == "light" and device.room == room_id and device.is_on
    )

    indoor_illuminance_lux = max(0.0, min(1200.0, daylight_lux + lamp_lux))
    return room.model_copy(
        update={"indoor_illuminance_lux": round(indoor_illuminance_lux, 2)}
    )


def update_all_room_illuminance(state: SmartHomeState) -> SmartHomeState:
    rooms = [update_room_illuminance(state, room.room_id) for room in state.rooms]
    return state.model_copy(update={"rooms": rooms})


def _get_room(state: SmartHomeState, room_id: str) -> RoomState:
    for room in state.rooms:
        if room.room_id == room_id:
            return room
    raise ValueError(f"Room not found: {room_id}")


def _get_curtain_opening_factor(devices: list[DeviceState], room_id: str) -> float:
    for device in devices:
        if device.device_type == "curtain" and device.room == room_id:
            return device.opening_pct / 100
    return 0.6


def _get_window_daylight_factor(devices: list[DeviceState], room_id: str) -> float:
    for device in devices:
        if device.device_type == "window" and device.room == room_id:
            opening_factor = device.opening_pct / 100
            return CLOSED_WINDOW_DAYLIGHT_FACTOR + OPEN_WINDOW_DAYLIGHT_GAIN * opening_factor
    return CLOSED_WINDOW_DAYLIGHT_FACTOR + OPEN_WINDOW_DAYLIGHT_GAIN * 0.2
