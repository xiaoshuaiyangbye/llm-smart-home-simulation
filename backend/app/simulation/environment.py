from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from app.schemas.action_schema import AgentAction
from app.schemas.state_schema import (
    ActivityType,
    DeviceState,
    EnergyState,
    ComfortState,
    OutdoorEnvironmentState,
    WeatherType,
    RoomState,
    SmartHomeState,
)
from app.simulation.device_model import apply_action_to_devices, apply_device_control_action
from app.simulation.comfort_model import update_comfort_metrics
from app.simulation.energy_model import update_energy_metrics
from app.simulation.humidity_model import update_all_room_humidity
from app.simulation.lighting_model import update_all_room_illuminance
from app.simulation.thermal_model import update_all_room_temperature
from app.simulation.weather_model import sync_realtime_environment, update_weather_environment

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
DEVICE_STATE_ADAPTER = TypeAdapter(DeviceState)


def get_initial_state() -> SmartHomeState:
    rooms_config = _load_yaml(CONFIG_DIR / "rooms.yaml")
    devices_config = _load_yaml(CONFIG_DIR / "devices.yaml")
    weather_config = _load_yaml(CONFIG_DIR / "weather.yaml")

    rooms = [RoomState.model_validate(item) for item in rooms_config["rooms"]]
    devices = [DEVICE_STATE_ADAPTER.validate_python(item) for item in devices_config["devices"]]
    outdoor_environment = OutdoorEnvironmentState.model_validate(
        weather_config["outdoor_environment"]
    )

    state = SmartHomeState(
        current_time_step=0,
        rooms=rooms,
        outdoor_environment=outdoor_environment,
        devices=devices,
    )
    state = recalculate_room_illuminance(state)
    state = update_comfort_metrics(state)
    state = update_energy_metrics(state)
    return recalculate_sensor_values(state)


class SmartHomeEnvironment:
    def __init__(self, initial_state: SmartHomeState | None = None) -> None:
        self._state = initial_state.model_copy(deep=True) if initial_state is not None else get_initial_state()
        self._revision = 0

    @property
    def revision(self) -> int:
        """Monotonic mutation version used for optimistic runtime commits."""
        return self._revision

    def _commit_state(self, state: SmartHomeState) -> SmartHomeState:
        self._state = state
        self._revision += 1
        return self._state

    def get_state(self, refresh_realtime: bool = True) -> SmartHomeState:
        if refresh_realtime:
            self._commit_state(self._refresh_realtime_environment(self._state))
        return self._state

    def reset(self, refresh_realtime: bool = True) -> SmartHomeState:
        self._commit_state(get_initial_state())
        if refresh_realtime:
            self._commit_state(self._refresh_realtime_environment(self._state))
        return self._state

    def set_current_room(self, room_id: str, activity: ActivityType | None = None) -> SmartHomeState:
        if not any(room.room_id == room_id for room in self._state.rooms):
            return self._state

        rooms = []
        for room in self._state.rooms:
            is_current_room = room.room_id == room_id
            if is_current_room:
                next_activity = activity or ("idle" if room.activity == "away" else room.activity)
            else:
                next_activity = "away"
            rooms.append(
                room.model_copy(
                    update={
                        "occupancy": is_current_room,
                        "activity": next_activity,
                    }
                )
            )

        next_state = self._state.model_copy(update={"rooms": rooms})
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state)
        return self._commit_state(next_state)

    def set_outdoor_snapshot(
        self,
        *,
        weather: WeatherType,
        time_hour: int,
        outdoor_illuminance_lux: float,
        solar_radiation_w_m2: float,
        outdoor_temperature_c: float,
        outdoor_humidity_percent: float,
        data_updated_at: str | None = None,
    ) -> SmartHomeState:
        next_environment = self._state.outdoor_environment.model_copy(
            update={
                "weather": weather,
                "time_hour": max(0, min(23, time_hour)),
                "time_minute": 0,
                "outdoor_illuminance_lux": max(0.0, outdoor_illuminance_lux),
                "solar_radiation_w_m2": max(0.0, solar_radiation_w_m2),
                "outdoor_temperature_c": outdoor_temperature_c,
                "outdoor_humidity_percent": max(0.0, min(100.0, outdoor_humidity_percent)),
                "outdoor_data_source": "historical_week_log",
                "illuminance_data_source": "historical_week_log",
                "data_updated_at": data_updated_at,
            }
        )
        next_state = self._state.model_copy(update={"outdoor_environment": next_environment})
        next_state = update_all_room_illuminance(next_state)
        next_state = update_all_room_temperature(next_state, dt_minutes=5)
        next_state = update_all_room_humidity(next_state, dt_minutes=5)
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state)
        return self._commit_state(next_state)

    def set_away(self) -> SmartHomeState:
        rooms = [
            room.model_copy(update={"occupancy": False, "activity": "away"})
            for room in self._state.rooms
        ]
        next_state = self._state.model_copy(update={"rooms": rooms})
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state)
        return self._commit_state(next_state)

    def set_outdoor_environment(
        self,
        weather: str | None = None,
        time_hour: int | None = None,
    ) -> SmartHomeState:
        updates: dict[str, Any] = {}
        if weather is not None:
            updates["weather"] = weather
        if time_hour is not None:
            updates["time_hour"] = max(0, min(23, time_hour))
            updates["time_minute"] = 0

        next_environment = self._state.outdoor_environment.model_copy(update=updates)
        next_state = self._state.model_copy(update={"outdoor_environment": next_environment})
        next_state = update_weather_environment(next_state)
        next_state = update_all_room_illuminance(next_state)
        next_state = update_all_room_temperature(next_state, dt_minutes=5)
        next_state = update_all_room_humidity(next_state, dt_minutes=5)
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state)
        return self._commit_state(next_state)

    def apply_actions(self, actions: list[AgentAction]) -> SmartHomeState:
        devices = self._state.devices
        for action in actions:
            devices = apply_action_to_devices(devices, action)

        next_state = self._state.model_copy(
            update={
                "current_time_step": self._state.current_time_step + 1,
                "devices": devices,
            }
        )
        next_state = update_all_room_illuminance(next_state)
        next_state = update_all_room_temperature(next_state, dt_minutes=3)
        next_state = update_all_room_humidity(next_state, dt_minutes=3)
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state)
        return self._commit_state(next_state)

    def step(self, minutes: int = 1, refresh_realtime: bool = True) -> SmartHomeState:
        minutes = max(1, minutes)
        next_state = self._advance_time(self._state, minutes)
        if refresh_realtime:
            next_state = sync_realtime_environment(next_state)
        else:
            next_state = update_weather_environment(next_state)
        next_state = update_all_room_illuminance(next_state)
        next_state = update_all_room_temperature(next_state, dt_minutes=minutes)
        next_state = update_all_room_humidity(next_state, dt_minutes=minutes)
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state, dt_minutes=minutes)
        return self._commit_state(next_state)

    def step_with_outdoor_snapshot(
        self,
        *,
        minutes: int = 1,
        weather: WeatherType,
        time_hour: int,
        outdoor_illuminance_lux: float,
        solar_radiation_w_m2: float,
        outdoor_temperature_c: float,
        outdoor_humidity_percent: float,
        data_updated_at: str | None = None,
    ) -> SmartHomeState:
        minutes = max(1, minutes)
        next_state = self._advance_time(self._state, minutes)
        next_environment = next_state.outdoor_environment.model_copy(
            update={
                "weather": weather,
                "time_hour": max(0, min(23, time_hour)),
                "time_minute": 0,
                "outdoor_illuminance_lux": max(0.0, outdoor_illuminance_lux),
                "solar_radiation_w_m2": max(0.0, solar_radiation_w_m2),
                "outdoor_temperature_c": outdoor_temperature_c,
                "outdoor_humidity_percent": max(0.0, min(100.0, outdoor_humidity_percent)),
                "outdoor_data_source": "historical_week_log",
                "illuminance_data_source": "historical_week_log",
                "data_updated_at": data_updated_at,
            }
        )
        next_state = next_state.model_copy(update={"outdoor_environment": next_environment})
        next_state = update_all_room_illuminance(next_state)
        next_state = update_all_room_temperature(next_state, dt_minutes=minutes)
        next_state = update_all_room_humidity(next_state, dt_minutes=minutes)
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state, dt_minutes=minutes)
        return self._commit_state(next_state)

    def apply_device_action(
        self,
        entity_id: str,
        action: str,
        parameters: dict[str, Any],
    ) -> tuple[bool, str, SmartHomeState, SmartHomeState]:
        before_state = self._state
        success, devices, message = apply_device_control_action(
            devices=before_state.devices,
            entity_id=entity_id,
            action=action,
            parameters=parameters,
        )
        if not success:
            return False, message, before_state, before_state

        next_state = before_state.model_copy(update={"devices": devices})
        next_state = update_all_room_illuminance(next_state)
        next_state = update_all_room_temperature(next_state, dt_minutes=5)
        next_state = update_all_room_humidity(next_state, dt_minutes=5)
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state)
        return True, message, before_state, self._commit_state(next_state)

    def apply_device_actions_batch(
        self,
        actions: list[dict[str, Any]],
        *,
        dt_minutes: int = 5,
    ) -> tuple[list[dict[str, Any]], SmartHomeState]:
        before_state = self._state
        devices = before_state.devices
        results: list[dict[str, Any]] = []

        for index, action in enumerate(actions, start=1):
            entity_id = str(action.get("entity_id", ""))
            action_name = str(action.get("action", ""))
            parameters = action.get("parameters", {})
            if not isinstance(parameters, dict):
                parameters = {}
            success, next_devices, message = apply_device_control_action(
                devices=devices,
                entity_id=entity_id,
                action=action_name,
                parameters=parameters,
            )
            results.append(
                {
                    "sequence": index,
                    "success": success,
                    "message": message,
                    "action": {
                        "entity_id": entity_id,
                        "action": action_name,
                        "parameters": parameters,
                        "reason": action.get("reason", ""),
                    },
                }
            )
            if not success:
                break
            devices = next_devices

        if not results:
            return results, self._state

        next_state = before_state.model_copy(update={"devices": devices})
        next_state = update_all_room_illuminance(next_state)
        next_state = update_all_room_temperature(next_state, dt_minutes=dt_minutes)
        next_state = update_all_room_humidity(next_state, dt_minutes=dt_minutes)
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state)
        return results, self._commit_state(next_state)

    def _advance_time(self, state: SmartHomeState, minutes: int) -> SmartHomeState:
        next_time_step = state.current_time_step + minutes
        current_clock_minutes = (
            state.outdoor_environment.time_hour * 60
            + state.outdoor_environment.time_minute
        )
        next_clock_minutes = (current_clock_minutes + minutes) % (24 * 60)
        next_outdoor_environment = state.outdoor_environment.model_copy(
            update={
                "time_hour": next_clock_minutes // 60,
                "time_minute": next_clock_minutes % 60,
            }
        )
        return state.model_copy(
            update={
                "current_time_step": next_time_step,
                "outdoor_environment": next_outdoor_environment,
            }
        )

    def _refresh_realtime_environment(self, state: SmartHomeState) -> SmartHomeState:
        next_state = sync_realtime_environment(state)
        next_state = update_all_room_illuminance(next_state)
        next_state = recalculate_sensor_values(next_state)
        next_state = update_comfort_metrics(next_state)
        next_state = update_energy_metrics(next_state)
        return next_state

    def get_energy_metrics(self) -> EnergyState:
        return self._commit_state(update_energy_metrics(self._state)).energy_metrics

    def get_comfort_metrics(self) -> ComfortState:
        return self._commit_state(update_comfort_metrics(self._state)).comfort_metrics


def recalculate_room_illuminance(state: SmartHomeState) -> SmartHomeState:
    return update_all_room_illuminance(state)


def recalculate_sensor_values(state: SmartHomeState) -> SmartHomeState:
    room_by_id = {room.room_id: room for room in state.rooms}
    devices: list[DeviceState] = []

    for device in state.devices:
        if device.device_type != "sensor":
            devices.append(device)
            continue

        room = room_by_id[device.room]
        sensor_value: float | bool
        if device.sensor_type == "illuminance":
            sensor_value = room.indoor_illuminance_lux
        elif device.sensor_type == "temperature":
            sensor_value = room.indoor_temperature_c
        elif device.sensor_type == "humidity":
            sensor_value = room.indoor_humidity_percent
        else:
            sensor_value = room.occupancy

        devices.append(device.model_copy(update={"value": sensor_value}))

    return state.model_copy(update={"devices": devices})


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML object in {path}")
    return data
