from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from app.schemas.state_schema import RoomState, SmartHomeState

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
Season = Literal["summer", "winter", "transition"]


def load_standard_config() -> dict[str, Any]:
    with (CONFIG_DIR / "standards.yaml").open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError("Invalid standards.yaml")
    return data["standards"]


STANDARD_CONFIG = load_standard_config()


def standard_basis() -> list[str]:
    return [
        f"{item['code']}《{item['name']}》"
        for item in STANDARD_CONFIG.values()
        if isinstance(item, dict) and "code" in item and "name" in item
    ]


def determine_evaluation_season(state: SmartHomeState) -> Season:
    month = _month_from_timestamp(state.outdoor_environment.data_updated_at)
    if month is not None:
        if 6 <= month <= 9:
            return "summer"
        if month in {11, 12, 1, 2, 3}:
            return "winter"
        return "transition"

    outdoor_temperature = state.outdoor_environment.outdoor_temperature_c
    if outdoor_temperature >= 26:
        return "summer"
    if outdoor_temperature <= 12:
        return "winter"
    return "transition"


def get_thermal_ranges(season: Season) -> tuple[tuple[float, float], tuple[float, float]]:
    thermal_config = STANDARD_CONFIG["thermal_comfort"]["equivalent_temperature_c"][season]
    return (
        tuple(float(value) for value in thermal_config["comfortable_range"]),
        tuple(float(value) for value in thermal_config["acceptable_range"]),
    )


def get_humidity_range(season: Season) -> tuple[float, float]:
    air_config = STANDARD_CONFIG["indoor_air_quality"]["physical_requirements"][season]
    return tuple(float(value) for value in air_config["humidity_percent_range"])


def get_lighting_range(room: RoomState) -> tuple[float, float]:
    lighting_config = STANDARD_CONFIG["lighting"]["residential_illuminance_lux"]
    room_config = lighting_config.get(room.room_id, lighting_config["living_room"])
    target = room_config.get(room.activity, room_config["idle"])
    return tuple(float(value) for value in target)


def _month_from_timestamp(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).month
    except ValueError:
        return None
