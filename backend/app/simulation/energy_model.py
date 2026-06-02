from collections import defaultdict

from app.schemas.state_schema import (
    AcDeviceState,
    DeviceEnergySnapshot,
    DeviceState,
    EnergyState,
    FanDeviceState,
    LightDeviceState,
    RoomEnergySnapshot,
    RoomState,
    SmartHomeState,
)

ELECTRICITY_PRICE_CNY_PER_KWH = 0.62
CARBON_FACTOR_KG_PER_KWH = 0.5703
LIGHT_STANDBY_W = 0.2
AC_STANDBY_W = 1.5
FAN_STANDBY_W = 0.3


def update_energy_metrics(state: SmartHomeState, dt_minutes: int = 0) -> SmartHomeState:
    device_snapshots: list[DeviceEnergySnapshot] = []
    by_device_type: dict[str, float] = defaultdict(float)
    by_room: dict[str, float] = defaultdict(float)
    room_by_id = {room.room_id: room for room in state.rooms}

    for device in state.devices:
        operating_power_w, standby_power_w, power_state = calculate_device_power_breakdown(
            device,
            room_by_id.get(device.room),
            state,
        )
        power_w = operating_power_w + standby_power_w
        device_snapshots.append(
            DeviceEnergySnapshot(
                entity_id=device.entity_id,
                room=device.room,
                device_type=device.device_type,
                current_power_w=round(power_w, 2),
                operating_power_w=round(operating_power_w, 2),
                standby_power_w=round(standby_power_w, 2),
                power_state=power_state,
            )
        )
        by_device_type[device.device_type] += power_w
        by_room[device.room] += power_w

    current_power_w = sum(snapshot.current_power_w for snapshot in device_snapshots)
    operating_power_w = sum(snapshot.operating_power_w for snapshot in device_snapshots)
    standby_power_w = sum(snapshot.standby_power_w for snapshot in device_snapshots)
    baseline_power_w = calculate_baseline_power_w(state)
    previous_kwh = state.energy_metrics.cumulative_energy_kwh
    added_kwh = current_power_w * max(0, dt_minutes) / 60 / 1000
    cumulative_kwh = previous_kwh + added_kwh
    saving_rate = 0.0
    if baseline_power_w > 0:
        saving_rate = (baseline_power_w - current_power_w) / baseline_power_w * 100
    average_comfort = state.comfort_metrics.average_overall_score
    comfort_adjusted_efficiency = 0.0
    if current_power_w > 0:
        comfort_adjusted_efficiency = average_comfort / (current_power_w / 1000)

    energy_state = EnergyState(
        current_power_w=round(current_power_w, 2),
        operating_power_w=round(operating_power_w, 2),
        standby_power_w=round(standby_power_w, 2),
        cumulative_energy_kwh=round(cumulative_kwh, 5),
        baseline_power_w=round(baseline_power_w, 2),
        energy_saving_rate_percent=round(saving_rate, 2),
        baseline_definition="即时固定策略估算：有人时按常规亮度、过渡季约 29C 以上才启用空调和基础风扇策略；生活快速仿真报告使用独立并行粗放人工基线环境计算正式节能率。",
        estimated_cost_cny=round(cumulative_kwh * ELECTRICITY_PRICE_CNY_PER_KWH, 4),
        estimated_carbon_kg=round(cumulative_kwh * CARBON_FACTOR_KG_PER_KWH, 4),
        projected_hourly_energy_kwh=round(current_power_w / 1000, 4),
        baseline_projected_hourly_energy_kwh=round(baseline_power_w / 1000, 4),
        comfort_adjusted_efficiency_score=round(comfort_adjusted_efficiency, 2),
        by_device_type_w={key: round(value, 2) for key, value in sorted(by_device_type.items())},
        by_room_w=[
            RoomEnergySnapshot(room_id=room.room_id, current_power_w=round(by_room.get(room.room_id, 0), 2))
            for room in state.rooms
        ],
        devices=device_snapshots,
    )
    return state.model_copy(update={"energy_metrics": energy_state})


def calculate_device_power_w(device: DeviceState, room: RoomState | None = None) -> float:
    operating_power_w, standby_power_w, _power_state = calculate_device_power_breakdown(device, room)
    return operating_power_w + standby_power_w


def calculate_device_power_breakdown(
    device: DeviceState,
    room: RoomState | None = None,
    state: SmartHomeState | None = None,
) -> tuple[float, float, str]:
    if device.device_type == "light":
        if device.is_on:
            return _light_power_w(device), 0.0, "operating"
        return 0.0, LIGHT_STANDBY_W, "standby"
    if device.device_type == "ac":
        if not device.is_on or device.mode == "off":
            return 0.0, AC_STANDBY_W, "standby"
        return _ac_power_w(device, room, state), 0.0, "operating"
    if device.device_type == "fan":
        if device.is_on:
            return _fan_power_w(device), 0.0, "operating"
        return 0.0, FAN_STANDBY_W, "standby"
    if device.device_type == "sensor":
        return 1.0, 0.0, "operating"
    return 0.0, 0.0, "off"


def calculate_baseline_power_w(state: SmartHomeState) -> float:
    total = 0.0
    room_by_id = {room.room_id: room for room in state.rooms}
    for device in state.devices:
        room = room_by_id.get(device.room)
        if device.device_type == "light":
            total += _baseline_light_power_w(device, room, state)
        elif device.device_type == "ac" and room is not None:
            total += _baseline_ac_power_w(room, state)
        elif device.device_type == "fan" and room is not None:
            total += _baseline_fan_power_w(room)
        elif device.device_type == "sensor":
            total += 1.0
    return total


def _baseline_light_power_w(device: LightDeviceState, room: RoomState | None, state: SmartHomeState) -> float:
    if room is None or not room.occupancy or room.activity in {"away", "sleep"}:
        return LIGHT_STANDBY_W
    is_evening_or_night = state.outdoor_environment.time_hour < 7 or state.outdoor_environment.time_hour >= 18
    needs_light = room.indoor_illuminance_lux < 350 or room.activity in {"study", "movie"} or is_evening_or_night
    if not needs_light:
        return LIGHT_STANDBY_W
    if room.activity == "movie":
        brightness = 0.25
    elif room.activity == "study":
        brightness = 0.8
    elif room.room_id in {"kitchen", "bathroom"}:
        brightness = 0.75
    elif room.room_id == "dining_room":
        brightness = 0.65
    else:
        brightness = 0.6
    return _light_max_power_w(device) * brightness


def _baseline_ac_power_w(room: RoomState, state: SmartHomeState) -> float:
    if not room.occupancy or room.activity == "away":
        return AC_STANDBY_W
    warm_limit = 29.2 if room.activity == "sleep" else 29.2
    cold_limit = 19.0 if room.activity == "sleep" else 19.0
    target = 27.5 if room.activity == "sleep" else 27.0
    if room.indoor_temperature_c > warm_limit:
        return min(1500.0, 650.0 + (room.indoor_temperature_c - target) * 120.0)
    if room.indoor_temperature_c < cold_limit:
        return min(1600.0, 750.0 + (21.0 - room.indoor_temperature_c) * 120.0)
    return AC_STANDBY_W


def _baseline_fan_power_w(room: RoomState) -> float:
    if not room.occupancy or room.activity in {"away", "sleep"}:
        return FAN_STANDBY_W
    if room.indoor_temperature_c > 29.0:
        return 45.0 * 0.5
    if room.indoor_temperature_c > 27.5:
        return 45.0 * 0.35
    return FAN_STANDBY_W


def _light_power_w(device: LightDeviceState) -> float:
    if not device.is_on:
        return 0.0
    return _light_max_power_w(device) * device.brightness_pct / 100


def _light_max_power_w(device: LightDeviceState) -> float:
    if device.max_lux_contribution >= 650:
        return 30.0
    if device.max_lux_contribution >= 520:
        return 24.0
    return 18.0


def _ac_power_w(device: AcDeviceState, room: RoomState | None, state: SmartHomeState | None = None) -> float:
    if device.mode == "fan":
        return 80.0
    if device.mode == "dry":
        return 450.0 + _ventilation_humidity_load_w(device, room, state)
    if room is None:
        return 800.0
    if device.mode == "cool":
        load = max(0.0, room.indoor_temperature_c - device.setpoint_c)
        return min(1500.0, 650.0 + load * 120.0 + _ventilation_thermal_load_w(device, room, state) + _ventilation_humidity_load_w(device, room, state))
    if device.mode == "heat":
        load = max(0.0, device.setpoint_c - room.indoor_temperature_c)
        return min(1600.0, 750.0 + load * 120.0 + _ventilation_thermal_load_w(device, room, state))
    return 0.0


def _fan_power_w(device: FanDeviceState) -> float:
    if not device.is_on:
        return 0.0
    return 45.0 * device.speed_pct / 100


def _ventilation_thermal_load_w(
    device: AcDeviceState,
    room: RoomState | None,
    state: SmartHomeState | None,
) -> float:
    if room is None or state is None:
        return 0.0
    window_opening_factor = _get_opening_factor(state.devices, device.room, "window", 20)
    if window_opening_factor <= 0:
        return 0.0
    outdoor_temperature = state.outdoor_environment.outdoor_temperature_c
    if device.mode == "cool":
        temperature_gap = max(0.0, outdoor_temperature - room.indoor_temperature_c)
    elif device.mode == "heat":
        temperature_gap = max(0.0, room.indoor_temperature_c - outdoor_temperature)
    else:
        temperature_gap = abs(outdoor_temperature - room.indoor_temperature_c)
    return window_opening_factor * temperature_gap * 35.0


def _ventilation_humidity_load_w(
    device: AcDeviceState,
    room: RoomState | None,
    state: SmartHomeState | None,
) -> float:
    if room is None or state is None or device.mode not in {"cool", "dry"}:
        return 0.0
    window_opening_factor = _get_opening_factor(state.devices, device.room, "window", 20)
    outdoor_humidity = state.outdoor_environment.outdoor_humidity_percent
    humidity_gap = max(0.0, outdoor_humidity - room.indoor_humidity_percent)
    return window_opening_factor * humidity_gap * 4.0


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
