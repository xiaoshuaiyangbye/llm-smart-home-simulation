from __future__ import annotations

import random
from copy import deepcopy
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.state_schema import SmartHomeState


class ObjectiveWeights(BaseModel):
    comfort: float = Field(default=0.45, ge=0, le=1)
    energy: float = Field(default=0.25, ge=0, le=1)
    safety: float = Field(default=0.2, ge=0, le=1)
    stability: float = Field(default=0.1, ge=0, le=1)

    def normalized(self) -> dict[str, float]:
        raw = self.model_dump()
        total = sum(raw.values()) or 1.0
        return {key: round(value / total, 4) for key, value in raw.items()}


class UserPreferenceProfile(BaseModel):
    profile_id: str = "default"
    display_name: str = "论文实验用户"
    preferred_temperature_c: float = Field(default=25.0, ge=16, le=30)
    temperature_tolerance_c: float = Field(default=1.0, ge=0.5, le=4)
    preferred_illuminance_lux: float = Field(default=500, ge=50, le=1200)
    preferred_humidity_percent: float = Field(default=50, ge=25, le=75)
    energy_saving_preference: float = Field(default=0.5, ge=0, le=1)
    objective_weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights)
    feedback_count: int = Field(default=0, ge=0)
    satisfaction_ema: float = Field(default=75, ge=0, le=100)
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class UserPreferenceUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    preferred_temperature_c: float | None = Field(default=None, ge=16, le=30)
    temperature_tolerance_c: float | None = Field(default=None, ge=0.5, le=4)
    preferred_illuminance_lux: float | None = Field(default=None, ge=50, le=1200)
    preferred_humidity_percent: float | None = Field(default=None, ge=25, le=75)
    energy_saving_preference: float | None = Field(default=None, ge=0, le=1)
    objective_weights: ObjectiveWeights | None = None


class UserFeedbackRequest(BaseModel):
    satisfaction: int = Field(ge=1, le=5)
    desired_temperature_c: float | None = Field(default=None, ge=16, le=30)
    desired_illuminance_lux: float | None = Field(default=None, ge=50, le=1200)
    note: str = Field(default="", max_length=300)


class RobustnessConfig(BaseModel):
    enabled: bool = False
    seed: int = 42
    temperature_sensor_noise_c: float = Field(default=0.0, ge=0, le=3)
    illuminance_sensor_noise_lux: float = Field(default=0.0, ge=0, le=200)
    actuator_failure_probability: float = Field(default=0.0, ge=0, le=0.5)


class UserPreferenceService:
    def __init__(self) -> None:
        self.profile = UserPreferenceProfile()
        self.feedback_history: list[dict[str, Any]] = []

    def update(self, update: UserPreferenceUpdate) -> UserPreferenceProfile:
        values = {key: value for key, value in update.model_dump().items() if value is not None}
        self.profile = self.profile.model_copy(update={**values, "updated_at": _now()})
        return self.profile

    def apply_feedback(self, feedback: UserFeedbackRequest) -> UserPreferenceProfile:
        learning_rate = 0.3
        updates: dict[str, Any] = {
            "feedback_count": self.profile.feedback_count + 1,
            "satisfaction_ema": round(self.profile.satisfaction_ema * 0.8 + feedback.satisfaction * 20 * 0.2, 2),
            "updated_at": _now(),
        }
        if feedback.desired_temperature_c is not None:
            updates["preferred_temperature_c"] = _move_towards(self.profile.preferred_temperature_c, feedback.desired_temperature_c, learning_rate)
        if feedback.desired_illuminance_lux is not None:
            updates["preferred_illuminance_lux"] = _move_towards(self.profile.preferred_illuminance_lux, feedback.desired_illuminance_lux, learning_rate)
        self.profile = self.profile.model_copy(update=updates)
        self.feedback_history.append({**feedback.model_dump(), "recorded_at": _now()})
        return self.profile

    def personalize_semantic_result(self, semantic_result: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(semantic_result)
        targets = dict(result.get("targets", {}))
        intent = str(result.get("intent", ""))
        if intent in {"thermal_comfort_control", "study_mode", "movie_mode", "sleep_mode", "basic_ac_control"}:
            target = self.profile.preferred_temperature_c
            tolerance = self.profile.temperature_tolerance_c
            targets["temperature_c_range"] = [round(target - tolerance, 1), round(target + tolerance, 1)]
        if intent in {"lighting_comfort_control", "study_mode", "movie_mode", "basic_light_control"}:
            preferred_lux = self.profile.preferred_illuminance_lux
            if intent == "movie_mode":
                preferred_lux = min(preferred_lux, 120)
            targets["illuminance_lux_range"] = [round(preferred_lux * 0.85), round(preferred_lux * 1.15)]
        result["targets"] = targets
        result["user_preference_context"] = {
            "profile_id": self.profile.profile_id,
            "energy_saving_preference": self.profile.energy_saving_preference,
            "objective_weights": self.profile.objective_weights.normalized(),
            "adapted_targets": targets,
        }
        return result

    def evaluate_multi_objective(
        self,
        state: SmartHomeState,
        *,
        action_count: int,
        safety_passed: bool,
        safety_issues: list[dict[str, Any]] | None = None,
        energy_kwh: float | None = None,
        baseline_energy_kwh: float | None = None,
    ) -> dict[str, Any]:
        """Evaluate a profile against explicit, traceable outcome measurements.

        ``energy_kwh`` and ``baseline_energy_kwh`` are supplied by an
        experiment when it has a fixed post-control observation horizon.  The
        fallback remains useful for live UI feedback, but is labelled as an
        instantaneous-power proxy rather than a cumulative-energy outcome.
        """
        occupied = [room for room in state.rooms if room.occupancy and room.activity != "away"]
        comfort_by_room = {room.room_id: room.overall_comfort_score for room in state.comfort_metrics.rooms}
        # A command-level outcome must describe the resident exposed to that
        # command, rather than averaging unrelated empty rooms into the score.
        # Keep the whole-home value only as an explicit fallback for dashboard
        # states in which no resident location is known.
        if occupied:
            comfort = sum(comfort_by_room.get(room.room_id, 0) for room in occupied) / len(occupied)
            comfort_measurement = "occupied_room_overall_score"
        else:
            comfort = state.comfort_metrics.average_overall_score
            comfort_measurement = "whole_home_overall_score_fallback"
        if energy_kwh is not None and baseline_energy_kwh is not None:
            actual_energy_kwh = max(0.0, float(energy_kwh))
            reference_energy_kwh = max(0.0, float(baseline_energy_kwh))
            energy_measurement = "post_control_horizon_kwh"
        else:
            # The live dashboard has no matched horizon baseline. Keep its
            # score available, but do not let callers mistake it for a
            # cumulative experimental outcome.
            actual_energy_kwh = state.energy_metrics.current_power_w / 1000
            reference_energy_kwh = state.energy_metrics.baseline_power_w / 1000
            energy_measurement = "instantaneous_power_proxy"

        if reference_energy_kwh > 0:
            energy_saving_rate_percent = (reference_energy_kwh - actual_energy_kwh) / reference_energy_kwh * 100
            # Equal energy receives 50; zero energy receives 100; twice the
            # reference energy receives 0. This bounded linear transform makes
            # the utility component traceable to the same measurement used in
            # the ablation CSV, without the previous early saturation at 100.
            energy = max(0.0, min(100.0, 50 + energy_saving_rate_percent / 2))
        else:
            energy_saving_rate_percent = 0.0
            energy = 50.0
        # Score the final executable plan, not merely whether a reviewer was
        # invoked.  The ordinal penalties deliberately remain a simulated,
        # traceable construct rather than a calibrated real-world risk model:
        # no issue=100, one medium issue=60, any high issue=20.
        remaining_issues = safety_issues or []
        high_safety_issue_count = sum(
            1
            for issue in remaining_issues
            if isinstance(issue, dict) and issue.get("severity") == "high"
        )
        medium_safety_issue_count = sum(
            1
            for issue in remaining_issues
            if isinstance(issue, dict) and issue.get("severity") == "medium"
        )
        if remaining_issues:
            safety = max(20.0, 100.0 - 80.0 * high_safety_issue_count - 40.0 * medium_safety_issue_count)
        else:
            # Keep backward-compatible live callers meaningful when they can
            # only provide a boolean assessment.
            safety = 100.0 if safety_passed else 20.0
        stability = max(0.0, 100.0 - max(0, action_count - 1) * 12)
        scores = {"comfort": comfort, "energy": energy, "safety": safety, "stability": stability}
        weights = self.profile.objective_weights.normalized()
        weighted = sum(scores[name] * weights[name] for name in scores)
        satisfaction = min(100.0, weighted * 0.75 + self.profile.satisfaction_ema * 0.25)
        return {
            "method": "profile_weighted_multi_objective_v1",
            "scores": {name: round(value, 2) for name, value in scores.items()},
            "weights": weights,
            "weighted_utility": round(weighted, 2),
            "estimated_user_satisfaction": round(satisfaction, 2),
            "profile_feedback_count": self.profile.feedback_count,
            "comfort_measurement": comfort_measurement,
            "energy_measurement": energy_measurement,
            "safety_measurement": "final_executable_plan_severity_penalty_v1",
            "safety_high_issue_count": high_safety_issue_count,
            "safety_medium_issue_count": medium_safety_issue_count,
            "energy_actual_kwh": round(actual_energy_kwh, 5),
            "energy_baseline_kwh": round(reference_energy_kwh, 5),
            "energy_saving_rate_percent": round(energy_saving_rate_percent, 2),
        }

    @staticmethod
    def observe(state: SmartHomeState, config: RobustnessConfig) -> tuple[SmartHomeState, dict[str, Any]]:
        if not config.enabled:
            return state, {"enabled": False, "applied": []}
        rng = random.Random(config.seed + state.current_time_step)
        rooms = []
        applied: list[dict[str, Any]] = []
        for room in state.rooms:
            temperature_noise = rng.uniform(-config.temperature_sensor_noise_c, config.temperature_sensor_noise_c)
            illuminance_noise = rng.uniform(-config.illuminance_sensor_noise_lux, config.illuminance_sensor_noise_lux)
            rooms.append(room.model_copy(update={
                "indoor_temperature_c": round(room.indoor_temperature_c + temperature_noise, 2),
                "indoor_illuminance_lux": max(0, round(room.indoor_illuminance_lux + illuminance_noise, 2)),
            }))
            if temperature_noise or illuminance_noise:
                applied.append({"room_id": room.room_id, "temperature_noise_c": round(temperature_noise, 3), "illuminance_noise_lux": round(illuminance_noise, 2)})
        return state.model_copy(update={"rooms": rooms}), {"enabled": True, "applied": applied}

    @staticmethod
    def filter_failed_actions(actions: list[dict[str, Any]], config: RobustnessConfig, time_step: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not config.enabled or config.actuator_failure_probability == 0:
            return actions, []
        rng = random.Random(config.seed + time_step + 10_000)
        retained: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for action in actions:
            if rng.random() < config.actuator_failure_probability:
                failures.append({"entity_id": action.get("entity_id"), "action": action.get("action"), "reason": "simulated_actuator_failure"})
            else:
                retained.append(action)
        return retained, failures


def _move_towards(current: float, desired: float, rate: float) -> float:
    return round(current + (desired - current) * rate, 2)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
