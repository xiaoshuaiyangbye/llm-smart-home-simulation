import json
import os
from datetime import datetime, timedelta, timezone
from math import pi, sin
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.schemas.state_schema import OutdoorEnvironmentState, SmartHomeState

WEATHER_FACTORS = {
    "sunny": 1.0,
    "cloudy": 0.6,
    "overcast": 0.35,
    "rainy": 0.2,
}

WEATHER_TEMPERATURE_OFFSETS = {
    "sunny": 4.0,
    "cloudy": 1.0,
    "overcast": -1.0,
    "rainy": -3.0,
}

WEATHER_HUMIDITY_BASE = {
    "sunny": 48.0,
    "cloudy": 58.0,
    "overcast": 68.0,
    "rainy": 82.0,
}


def default_weather() -> OutdoorEnvironmentState:
    return OutdoorEnvironmentState(
        weather="sunny",
        time_hour=14,
        outdoor_illuminance_lux=70000,
        solar_radiation_w_m2=750,
        outdoor_temperature_c=33,
        outdoor_humidity_percent=62,
        outdoor_data_source="simulation_formula",
        illuminance_data_source="simulation_formula",
    )


def update_weather_environment(state: SmartHomeState) -> SmartHomeState:
    environment = state.outdoor_environment
    time_factor = calculate_time_factor(environment.time_hour)
    weather_factor = WEATHER_FACTORS[environment.weather]

    # Outdoor illuminance follows a simplified daylight curve:
    # E_out = 80000 * time_factor * weather_factor.
    outdoor_illuminance_lux = 80000 * time_factor * weather_factor

    # Solar radiation uses the same solar-height factor with a 900 W/m2 peak.
    solar_radiation_w_m2 = 900 * time_factor * weather_factor

    # Outdoor temperature uses a daily sinusoidal trend plus weather offset.
    # The peak is around 14:00, while rainy weather lowers temperature.
    daily_temperature_factor = max(0.0, sin(pi * (environment.time_hour - 5) / 14))
    outdoor_temperature_c = (
        24.0
        + 6.0 * daily_temperature_factor
        + WEATHER_TEMPERATURE_OFFSETS[environment.weather]
    )

    # Humidity is higher at night and during rainy/overcast weather.
    humidity_night_bonus = (1.0 - time_factor) * 10.0
    outdoor_humidity_percent = min(
        100.0,
        WEATHER_HUMIDITY_BASE[environment.weather] + humidity_night_bonus,
    )

    updated_environment = environment.model_copy(
        update={
            "outdoor_illuminance_lux": round(outdoor_illuminance_lux, 2),
            "solar_radiation_w_m2": round(solar_radiation_w_m2, 2),
            "outdoor_temperature_c": round(outdoor_temperature_c, 2),
            "outdoor_humidity_percent": round(outdoor_humidity_percent, 2),
            "outdoor_data_source": "simulation_formula",
            "illuminance_data_source": "simulation_formula",
            "data_updated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(
                timespec="minutes"
            ),
        }
    )
    return state.model_copy(update={"outdoor_environment": updated_environment})


def sync_realtime_environment(state: SmartHomeState) -> SmartHomeState:
    current_time = datetime.now(timezone(timedelta(hours=8)))
    state_with_current_time = state.model_copy(
        update={
            "outdoor_environment": state.outdoor_environment.model_copy(
                update={
                    "time_hour": current_time.hour,
                    "time_minute": current_time.minute,
                }
            )
        }
    )
    try:
        return _sync_open_meteo_environment(state_with_current_time)
    except (HTTPError, URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError):
        return update_weather_environment(state_with_current_time)


def calculate_time_factor(time_hour: int) -> float:
    # Before 6:00 and after 18:00 the sine value is clamped to zero.
    return max(0.0, sin(pi * (time_hour - 6) / 12))


def _sync_open_meteo_environment(state: SmartHomeState) -> SmartHomeState:
    latitude = os.getenv("REALTIME_WEATHER_LATITUDE", "").strip()
    longitude = os.getenv("REALTIME_WEATHER_LONGITUDE", "").strip()
    if not latitude or not longitude:
        raise ValueError("Realtime weather coordinates are not configured.")
    query = urlencode(
        {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "current": "temperature_2m,relative_humidity_2m,weather_code,shortwave_radiation",
            "timezone": "Asia/Shanghai",
        }
    )
    with urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))

    current = payload["current"]
    weather = _map_weather_code(int(current["weather_code"]))
    solar_radiation = max(0.0, float(current.get("shortwave_radiation") or 0.0))
    outdoor_illuminance = _estimate_illuminance_from_radiation(
        solar_radiation=solar_radiation,
        weather=weather,
        time_hour=state.outdoor_environment.time_hour,
    )
    environment = state.outdoor_environment.model_copy(
        update={
            "weather": weather,
            "outdoor_illuminance_lux": round(outdoor_illuminance, 2),
            "solar_radiation_w_m2": round(solar_radiation, 2),
            "outdoor_temperature_c": round(float(current["temperature_2m"]), 2),
            "outdoor_humidity_percent": round(float(current["relative_humidity_2m"]), 2),
            "outdoor_data_source": "realtime_open_meteo",
            "illuminance_data_source": "estimated_from_realtime_solar_radiation",
            "data_updated_at": current.get("time"),
        }
    )
    return state.model_copy(update={"outdoor_environment": environment})


def _map_weather_code(weather_code: int) -> str:
    if weather_code == 0:
        return "sunny"
    if weather_code in {1, 2}:
        return "cloudy"
    if weather_code == 3 or 45 <= weather_code <= 48:
        return "overcast"
    if 51 <= weather_code <= 99:
        return "rainy"
    return "cloudy"


def _estimate_illuminance_from_radiation(
    solar_radiation: float,
    weather: str,
    time_hour: int,
) -> float:
    # Open weather APIs usually provide solar shortwave radiation in W/m2,
    # not outdoor illuminance in lux. The platform converts radiation with a
    # simplified luminous-efficacy coefficient for visualization and control.
    if solar_radiation > 0:
        return min(80000.0, solar_radiation * 90.0)
    return 80000 * calculate_time_factor(time_hour) * WEATHER_FACTORS[weather]
