from app.schemas.state_schema import (
    ComfortState,
    DeviceState,
    RoomComfortSnapshot,
    RoomState,
    SmartHomeState,
)
from app.simulation.standards import (
    determine_evaluation_season,
    get_humidity_range,
    get_lighting_range,
    get_thermal_ranges,
    standard_basis,
)
from app.simulation.thermal_model import calculate_apparent_temperature


def update_comfort_metrics(state: SmartHomeState) -> SmartHomeState:
    season = determine_evaluation_season(state)
    room_snapshots = [
        calculate_room_comfort(state, room, season)
        for room in state.rooms
    ]
    if not room_snapshots:
        return state.model_copy(update={"comfort_metrics": ComfortState()})

    comfort_state = ComfortState(
        average_overall_score=round(_average(snapshot.overall_comfort_score for snapshot in room_snapshots), 2),
        average_thermal_score=round(_average(snapshot.thermal_comfort_score for snapshot in room_snapshots), 2),
        average_lighting_score=round(_average(snapshot.lighting_comfort_score for snapshot in room_snapshots), 2),
        average_humidity_score=round(_average(snapshot.humidity_comfort_score for snapshot in room_snapshots), 2),
        comfortable_room_count=sum(1 for snapshot in room_snapshots if snapshot.comfort_level == "comfortable"),
        evaluation_season=season,
        standard_basis=standard_basis(),
        rooms=room_snapshots,
    )
    return state.model_copy(update={"comfort_metrics": comfort_state})


def calculate_room_comfort(state: SmartHomeState, room: RoomState, season: str) -> RoomComfortSnapshot:
    fan = _find_room_device(state.devices, room.room_id, "fan")
    apparent_temperature = calculate_apparent_temperature(room, fan)
    comfortable_temperature_range, acceptable_temperature_range = get_thermal_ranges(season)
    illuminance_range = get_lighting_range(room)
    humidity_range = get_humidity_range(season)

    thermal_score = _comfort_band_score(
        apparent_temperature,
        comfortable_range=comfortable_temperature_range,
        acceptable_range=acceptable_temperature_range,
        penalty_per_unit=12.0,
    )
    lighting_score = _range_score(room.indoor_illuminance_lux, illuminance_range, penalty_per_unit=0.18)
    humidity_score = _range_score(room.indoor_humidity_percent, humidity_range, penalty_per_unit=4.0)

    # Overall comfort uses weighted aggregation. Thermal comfort receives the
    # largest weight; lighting and humidity are retained as explicit sub-metrics
    # so experiments can separately compare light and thermal control.
    overall_score = thermal_score * 0.42 + lighting_score * 0.34 + humidity_score * 0.24
    comfort_level = "comfortable" if overall_score >= 80 else "acceptable" if overall_score >= 60 else "uncomfortable"

    return RoomComfortSnapshot(
        room_id=room.room_id,
        apparent_temperature_c=apparent_temperature,
        thermal_comfort_score=round(thermal_score, 2),
        lighting_comfort_score=round(lighting_score, 2),
        humidity_comfort_score=round(humidity_score, 2),
        overall_comfort_score=round(overall_score, 2),
        comfort_level=comfort_level,
        thermal_standard_range_c=list(comfortable_temperature_range),
        lighting_standard_range_lux=list(illuminance_range),
        humidity_standard_range_percent=list(humidity_range),
    )


def _range_score(value: float, target_range: tuple[float, float], penalty_per_unit: float) -> float:
    lower, upper = target_range
    if lower <= value <= upper:
        return 100.0
    deviation = lower - value if value < lower else value - upper
    return max(0.0, 100.0 - deviation * penalty_per_unit)


def _comfort_band_score(
    value: float,
    comfortable_range: tuple[float, float],
    acceptable_range: tuple[float, float],
    penalty_per_unit: float,
) -> float:
    comfortable_lower, comfortable_upper = comfortable_range
    acceptable_lower, acceptable_upper = acceptable_range
    if comfortable_lower <= value <= comfortable_upper:
        return 100.0
    if acceptable_lower <= value <= acceptable_upper:
        deviation = comfortable_lower - value if value < comfortable_lower else value - comfortable_upper
        edge_width = max(0.1, comfortable_lower - acceptable_lower if value < comfortable_lower else acceptable_upper - comfortable_upper)
        return max(80.0, 100.0 - 20.0 * deviation / edge_width)
    deviation = acceptable_lower - value if value < acceptable_lower else value - acceptable_upper
    return max(0.0, 80.0 - deviation * penalty_per_unit)


def _find_room_device(
    devices: list[DeviceState],
    room_id: str,
    device_type: str,
) -> DeviceState | None:
    for device in devices:
        if device.room == room_id and device.device_type == device_type:
            return device
    return None


def _average(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0
