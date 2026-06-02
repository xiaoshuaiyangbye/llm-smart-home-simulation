from typing import Annotated, Literal

from pydantic import BaseModel, Field

RoomId = Literal[
    "living_room",
    "bedroom",
    "study_room",
    "dining_room",
    "kitchen",
    "bathroom",
    "laundry",
    "balcony",
    "corridor",
]
ActivityType = Literal["idle", "study", "movie", "sleep", "away"]
WeatherType = Literal["sunny", "cloudy", "overcast", "rainy"]
AcMode = Literal["cool", "heat", "fan", "dry", "off"]
SensorType = Literal["illuminance", "temperature", "humidity", "occupancy"]
ComfortLevel = Literal["comfortable", "acceptable", "uncomfortable"]
EvaluationSeason = Literal["summer", "winter", "transition"]
OutdoorDataSource = Literal[
    "simulation_formula",
    "realtime_open_meteo",
    "historical_week_log",
]
IlluminanceDataSource = Literal[
    "simulation_formula",
    "estimated_from_realtime_solar_radiation",
    "historical_week_log",
]


class RoomState(BaseModel):
    room_id: RoomId
    name: str
    indoor_illuminance_lux: float = Field(ge=0)
    indoor_temperature_c: float
    indoor_humidity_percent: float = Field(ge=0, le=100)
    occupancy: bool
    activity: ActivityType


class OutdoorEnvironmentState(BaseModel):
    weather: WeatherType
    time_hour: int = Field(ge=0, le=23)
    outdoor_illuminance_lux: float = Field(ge=0)
    solar_radiation_w_m2: float = Field(ge=0)
    outdoor_temperature_c: float
    outdoor_humidity_percent: float = Field(ge=0, le=100)
    outdoor_data_source: OutdoorDataSource = "simulation_formula"
    illuminance_data_source: IlluminanceDataSource = "simulation_formula"
    data_updated_at: str | None = None


class BaseDeviceState(BaseModel):
    entity_id: str
    room: RoomId
    name: str


class LightDeviceState(BaseDeviceState):
    device_type: Literal["light"] = "light"
    is_on: bool
    brightness_pct: float = Field(ge=0, le=100)
    color_temperature_k: int = Field(ge=2700, le=6500)
    max_lux_contribution: float = Field(ge=0)


class CurtainDeviceState(BaseDeviceState):
    device_type: Literal["curtain"] = "curtain"
    opening_pct: float = Field(ge=0, le=100)


class AcDeviceState(BaseDeviceState):
    device_type: Literal["ac"] = "ac"
    is_on: bool
    mode: AcMode
    setpoint_c: float


class FanDeviceState(BaseDeviceState):
    device_type: Literal["fan"] = "fan"
    is_on: bool
    speed_pct: float = Field(ge=0, le=100)


class WindowDeviceState(BaseDeviceState):
    device_type: Literal["window"] = "window"
    opening_pct: float = Field(ge=0, le=100)


class SensorDeviceState(BaseDeviceState):
    device_type: Literal["sensor"] = "sensor"
    sensor_type: SensorType
    value: float | bool


DeviceState = Annotated[
    LightDeviceState
    | CurtainDeviceState
    | AcDeviceState
    | FanDeviceState
    | WindowDeviceState
    | SensorDeviceState,
    Field(discriminator="device_type"),
]


class DeviceEnergySnapshot(BaseModel):
    entity_id: str
    room: RoomId
    device_type: str
    current_power_w: float = Field(ge=0)
    operating_power_w: float = Field(default=0, ge=0)
    standby_power_w: float = Field(default=0, ge=0)
    power_state: str = "off"


class RoomEnergySnapshot(BaseModel):
    room_id: RoomId
    current_power_w: float = Field(ge=0)


class RoomComfortSnapshot(BaseModel):
    room_id: RoomId
    apparent_temperature_c: float
    thermal_comfort_score: float = Field(ge=0, le=100)
    lighting_comfort_score: float = Field(ge=0, le=100)
    humidity_comfort_score: float = Field(ge=0, le=100)
    overall_comfort_score: float = Field(ge=0, le=100)
    comfort_level: ComfortLevel
    thermal_standard_range_c: list[float] = Field(default_factory=list)
    lighting_standard_range_lux: list[float] = Field(default_factory=list)
    humidity_standard_range_percent: list[float] = Field(default_factory=list)


class ComfortState(BaseModel):
    average_overall_score: float = Field(default=0, ge=0, le=100)
    average_thermal_score: float = Field(default=0, ge=0, le=100)
    average_lighting_score: float = Field(default=0, ge=0, le=100)
    average_humidity_score: float = Field(default=0, ge=0, le=100)
    comfortable_room_count: int = Field(default=0, ge=0)
    evaluation_season: EvaluationSeason = "transition"
    standard_basis: list[str] = Field(default_factory=list)
    rooms: list[RoomComfortSnapshot] = Field(default_factory=list)


class EnergyState(BaseModel):
    current_power_w: float = Field(default=0, ge=0)
    operating_power_w: float = Field(default=0, ge=0)
    standby_power_w: float = Field(default=0, ge=0)
    cumulative_energy_kwh: float = Field(default=0, ge=0)
    baseline_power_w: float = Field(default=0, ge=0)
    energy_saving_rate_percent: float = 0
    baseline_definition: str = "固定策略对照：有人或任务房间按固定亮度和固定温控策略运行，不采用智能体节能规划。"
    estimated_cost_cny: float = Field(default=0, ge=0)
    estimated_carbon_kg: float = Field(default=0, ge=0)
    projected_hourly_energy_kwh: float = Field(default=0, ge=0)
    baseline_projected_hourly_energy_kwh: float = Field(default=0, ge=0)
    comfort_adjusted_efficiency_score: float = Field(default=0, ge=0)
    by_device_type_w: dict[str, float] = Field(default_factory=dict)
    by_room_w: list[RoomEnergySnapshot] = Field(default_factory=list)
    devices: list[DeviceEnergySnapshot] = Field(default_factory=list)


class SmartHomeState(BaseModel):
    current_time_step: int = Field(ge=0)
    rooms: list[RoomState]
    outdoor_environment: OutdoorEnvironmentState
    devices: list[DeviceState]
    energy_metrics: EnergyState = Field(default_factory=EnergyState)
    comfort_metrics: ComfortState = Field(default_factory=ComfortState)
