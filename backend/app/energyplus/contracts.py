import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Controls(BaseModel):
    model_config = ConfigDict(extra="forbid")
    light_fraction: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    cooling_setpoint_c: float = Field(default=25, ge=18, le=30, allow_inf_nan=False)
    heating_setpoint_c: float = Field(default=20, ge=12, le=24, allow_inf_nan=False)
    hvac_enabled: bool = True
    ventilation_fraction: float = Field(default=0.3, ge=0, le=1, allow_inf_nan=False)
    window_fraction: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def deadband(self):
        if self.cooling_setpoint_c - self.heating_setpoint_c < 1:
            raise ValueError("Cooling/heating deadband must be at least 1 degree C")
        return self


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spatial_scope: Literal["whole_home", "single_room"] = "whole_home"
    current_room_id: str = "living_room"
    controller: Literal["rule", "manual", "harness_mock", "harness_real"] = "rule"
    season: Literal["summer", "winter"] = "summer"
    days: int = Field(default=1, ge=1, le=7)
    control_interval_minutes: int = Field(default=30, ge=5, le=120)
    user_command: str = Field(default="客厅看书，保持舒适，注意通风并节约能源", min_length=1, max_length=1000)
    temperature_target_c: float = Field(default=25, ge=20, le=28, allow_inf_nan=False)
    illuminance_target_lux: float = Field(default=500, ge=100, le=1000, allow_inf_nan=False)
    co2_limit_ppm: float = Field(default=1000, ge=600, le=2000, allow_inf_nan=False)
    manual_controls: Controls = Field(default_factory=Controls)
    manual_room_controls: dict[str, Controls] = Field(default_factory=dict)
    calibration_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def time_grid(self):
        if self.control_interval_minutes % 5:
            raise ValueError("Control interval must be a multiple of the 5-minute zone step")
        return self


class CalibrationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimming_fraction: float = Field(ge=0, le=1, allow_inf_nan=False)
    electric_illuminance_lux: float = Field(ge=0, le=100000, allow_inf_nan=False)
    power_w: float = Field(ge=0, le=10000, allow_inf_nan=False)


class CalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_description: str = Field(min_length=5, max_length=1000)
    sensor_location: str = Field(min_length=2, max_length=300)
    ambient_subtracted: Literal[True]
    points: list[CalibrationPoint] = Field(min_length=6, max_length=10000)

    @model_validator(mode="after")
    def variation(self):
        if len({p.dimming_fraction for p in self.points}) < 3:
            raise ValueError("At least three distinct dimming levels are required")
        return self


def finite_observation(values):
    for key, value in values.items():
        if isinstance(value, (float, int)) and not isinstance(value, bool) and not math.isfinite(value):
            raise ValueError(f"Non-finite engine observation: {key}")
    return values
