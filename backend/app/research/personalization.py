from __future__ import annotations

import json
import random
import base64
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field, field_validator

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


class PrivateAttributeUpdate(BaseModel):
    attributes: dict[str, str | None] = Field(default_factory=dict, max_length=30)

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, attributes: dict[str, str | None]) -> dict[str, str | None]:
        cleaned: dict[str, str | None] = {}
        for raw_key, raw_value in attributes.items():
            key = raw_key.strip()
            if not key or len(key) > 50:
                raise ValueError("Private attribute keys must contain 1-50 characters.")
            if raw_value is None:
                cleaned[key] = None
                continue
            value = raw_value.strip()
            if not value or len(value) > 200:
                raise ValueError("Private attribute values must contain 1-200 characters or be null for deletion.")
            cleaned[key] = value
        return cleaned


class PrivateMemoryResetRequest(BaseModel):
    confirmation: Literal["RESET_PRIVATE_MEMORY"]


class RobustnessConfig(BaseModel):
    enabled: bool = False
    seed: int = 42
    temperature_sensor_noise_c: float = Field(default=0.0, ge=0, le=3)
    illuminance_sensor_noise_lux: float = Field(default=0.0, ge=0, le=200)
    actuator_failure_probability: float = Field(default=0.0, ge=0, le=0.5)


class UserPreferenceService:
    """Session-scoped personalization with optional local durable memory.

    Reflection records are evidence, not free-form model mutations. Explicit
    user feedback may update control targets; autonomous outcomes only update
    bounded experience statistics so one simulated run cannot silently rewrite
    a resident's safety or comfort preferences.
    """

    MEMORY_SCHEMA_VERSION = "private_user_memory_v1"
    ENCRYPTED_FILE_FORMAT = "encrypted_private_memory_v1"
    MAX_FEEDBACK_HISTORY = 100
    MAX_REFLECTIONS = 200

    def __init__(
        self,
        storage_path: Path | None = None,
        *,
        encryption_key: str | bytes | None = None,
    ) -> None:
        self.storage_path = storage_path
        self._fernet = self._build_fernet(encryption_key)
        self._lock = RLock()
        self.profile = UserPreferenceProfile()
        self.feedback_history: list[dict[str, Any]] = []
        self.private_attributes: dict[str, str] = {}
        self.reflections: list[dict[str, Any]] = []
        self.learned_patterns: dict[str, dict[str, Any]] = {}
        self._persistence_success_count = 0
        self._persistence_failure_count = 0
        self._last_persistence_success_at: str | None = None
        self._last_persistence_error_at: str | None = None
        self._load()

    def update(self, update: UserPreferenceUpdate) -> UserPreferenceProfile:
        with self._lock:
            previous_profile = self.profile
            values = {key: value for key, value in update.model_dump().items() if value is not None}
            self.profile = self.profile.model_copy(update={**values, "updated_at": _now()})
            try:
                self._persist()
            except OSError:
                self.profile = previous_profile
                raise
            return self.profile

    def apply_feedback(self, feedback: UserFeedbackRequest) -> UserPreferenceProfile:
        with self._lock:
            previous_profile = self.profile
            previous_feedback_history = deepcopy(self.feedback_history)
            previous_reflections = deepcopy(self.reflections)
            previous_patterns = deepcopy(self.learned_patterns)
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
            feedback_record = {
                "feedback_id": f"feedback-{uuid4().hex[:12]}",
                **feedback.model_dump(),
                "recorded_at": _now(),
            }
            self.feedback_history.append(feedback_record)
            self.feedback_history = self.feedback_history[-self.MAX_FEEDBACK_HISTORY :]
            self._link_feedback_to_latest_reflection(feedback_record)
            try:
                self._persist()
            except OSError:
                self.profile = previous_profile
                self.feedback_history = previous_feedback_history
                self.reflections = previous_reflections
                self.learned_patterns = previous_patterns
                raise
            return self.profile

    def update_private_attributes(self, update: PrivateAttributeUpdate) -> dict[str, Any]:
        with self._lock:
            previous_attributes = deepcopy(self.private_attributes)
            for key, value in update.attributes.items():
                if value is None:
                    self.private_attributes.pop(key, None)
                else:
                    self.private_attributes[key] = value
            try:
                self._persist()
            except OSError:
                self.private_attributes = previous_attributes
                raise
            return self.private_memory_snapshot()

    def reset_private_memory(self, request: PrivateMemoryResetRequest) -> dict[str, Any]:
        del request  # Validation of the explicit confirmation is the authorization guard.
        with self._lock:
            previous_profile = self.profile
            previous_feedback_history = deepcopy(self.feedback_history)
            previous_attributes = deepcopy(self.private_attributes)
            previous_reflections = deepcopy(self.reflections)
            previous_patterns = deepcopy(self.learned_patterns)
            self.profile = UserPreferenceProfile()
            self.feedback_history = []
            self.private_attributes = {}
            self.reflections = []
            self.learned_patterns = {}
            try:
                self._persist()
            except OSError:
                self.profile = previous_profile
                self.feedback_history = previous_feedback_history
                self.private_attributes = previous_attributes
                self.reflections = previous_reflections
                self.learned_patterns = previous_patterns
                raise
            return self.private_memory_snapshot()

    def record_reflection(
        self,
        *,
        trigger: str,
        user_command: str,
        semantic_result: dict[str, Any],
        plan_result: dict[str, Any],
        execution_result: dict[str, Any],
        feedback_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Store an auditable post-decision reflection and bounded pattern stats."""
        with self._lock:
            previous_reflections = deepcopy(self.reflections)
            previous_patterns = deepcopy(self.learned_patterns)
            intent = str(semantic_result.get("intent") or "unknown")
            room = str(semantic_result.get("room") or "unknown")
            completed = bool(feedback_result.get("completed", False))
            executed_count = int(execution_result.get("executed_count", 0) or 0)
            correction_round = int(feedback_result.get("correction_round", 0) or 0)
            evaluation = feedback_result.get("multi_objective_evaluation", {})
            pattern_key = f"{intent}:{room}"
            pattern = dict(
                self.learned_patterns.get(
                    pattern_key,
                    {
                        "intent": intent,
                        "room": room,
                        "observations": 0,
                        "completed_count": 0,
                        "failed_count": 0,
                    },
                )
            )
            pattern["observations"] = int(pattern["observations"]) + 1
            outcome_key = "completed_count" if completed else "failed_count"
            pattern[outcome_key] = int(pattern[outcome_key]) + 1
            pattern["completion_rate"] = round(
                int(pattern["completed_count"]) / int(pattern["observations"]),
                4,
            )
            # Confidence describes evidence volume, not truth or real-home validity.
            pattern["confidence"] = round(min(0.95, int(pattern["observations"]) / 10), 2)
            pattern["last_observed_at"] = _now()
            pattern["pattern_key"] = pattern_key
            self.learned_patterns[pattern_key] = pattern

            conclusion = (
                "目标已达到，保留当前策略作为同类情境的正向经验。"
                if completed
                else "目标未完全达到，记录失败与校正轨迹；不自动修改关键偏好。"
            )
            reflection = {
                "reflection_id": f"reflection-{uuid4().hex[:12]}",
                "recorded_at": _now(),
                "trigger": trigger,
                "user_command": user_command,
                "intent": intent,
                "room": room,
                "completed": completed,
                "planned_action_count": len(plan_result.get("actions", [])),
                "executed_action_count": executed_count,
                "correction_round": correction_round,
                "estimated_user_satisfaction": (
                    evaluation.get("estimated_user_satisfaction")
                    if isinstance(evaluation, dict)
                    else None
                ),
                "conclusion": conclusion,
                "learning_policy": "experience_statistics_only_until_explicit_feedback",
                "pattern_key": pattern_key,
                "pattern_confidence": pattern["confidence"],
            }
            self.reflections.append(reflection)
            self.reflections = self.reflections[-self.MAX_REFLECTIONS :]
            try:
                self._persist()
            except OSError:
                # The caller treats a persistence failure as "no learning".
                # Restore in-memory evidence as well so subsequent decisions
                # cannot consume a pattern that was never durably recorded.
                self.reflections = previous_reflections
                self.learned_patterns = previous_patterns
                raise
            return deepcopy(reflection)

    def private_memory_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": self.MEMORY_SCHEMA_VERSION,
                "scope": "session_isolated_local_private_memory",
                "persistence_enabled": self.storage_path is not None,
                "storage_security": {
                    "encrypted_at_rest": self._fernet is not None,
                    "cipher": "fernet_aes128_cbc_hmac_sha256" if self._fernet else None,
                    "key_source": "PRIVATE_MEMORY_ENCRYPTION_KEY" if self._fernet else None,
                    "identity_boundary": "session_identifier_not_authentication",
                },
                "storage_health": {
                    "persistence_success_count": self._persistence_success_count,
                    "persistence_failure_count": self._persistence_failure_count,
                    "last_persistence_success_at": self._last_persistence_success_at,
                    "last_persistence_error_at": self._last_persistence_error_at,
                    "status": (
                        "degraded"
                        if self._last_persistence_error_at
                        and (
                            self._last_persistence_success_at is None
                            or self._last_persistence_error_at > self._last_persistence_success_at
                        )
                        else "healthy_or_not_yet_written"
                    ),
                },
                "profile": self.profile.model_dump(mode="json"),
                "private_attributes": deepcopy(self.private_attributes),
                "feedback_history": deepcopy(self.feedback_history),
                "reflections": deepcopy(self.reflections),
                "learned_patterns": deepcopy(self.learned_patterns),
                "reflection_policy": {
                    "autonomous_updates": "experience_statistics_only",
                    "preference_updates": "explicit_user_feedback_or_profile_edit",
                    "experience_confirmation": "latest_reflection_linked_to_explicit_feedback",
                    "safety_boundary": "never_relaxed_by_reflection",
                },
            }

    def _link_feedback_to_latest_reflection(self, feedback_record: dict[str, Any]) -> None:
        if not self.reflections:
            return
        latest = dict(self.reflections[-1])
        latest["explicit_user_feedback"] = deepcopy(feedback_record)
        satisfaction = int(feedback_record.get("satisfaction", 0) or 0)
        latest["feedback_interpretation"] = (
            "positive_confirmation"
            if satisfaction >= 4
            else "negative_correction"
            if satisfaction <= 2
            else "neutral_observation"
        )
        self.reflections[-1] = latest

        pattern_key = str(latest.get("pattern_key") or "")
        if not pattern_key or pattern_key not in self.learned_patterns:
            return
        pattern = dict(self.learned_patterns[pattern_key])
        pattern["explicit_feedback_count"] = int(pattern.get("explicit_feedback_count", 0)) + 1
        if satisfaction >= 4:
            pattern["positive_feedback_count"] = int(pattern.get("positive_feedback_count", 0)) + 1
        elif satisfaction <= 2:
            pattern["negative_feedback_count"] = int(pattern.get("negative_feedback_count", 0)) + 1
        explicit_count = int(pattern["explicit_feedback_count"])
        positive_count = int(pattern.get("positive_feedback_count", 0))
        pattern["positive_feedback_rate"] = round(positive_count / explicit_count, 4)
        pattern["promotion_status"] = (
            "user_confirmed_pattern"
            if explicit_count >= 3 and pattern["positive_feedback_rate"] >= 0.67
            else "collecting_explicit_feedback"
        )
        pattern["last_feedback_at"] = str(feedback_record["recorded_at"])
        pattern["pattern_key"] = pattern_key
        self.learned_patterns[pattern_key] = pattern

    def personalize_semantic_result(self, semantic_result: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(semantic_result)
        targets = dict(result.get("targets", {}))
        intent = str(result.get("intent", ""))
        room = str(result.get("room", "unknown"))
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
        private_constraints = self._private_attribute_constraints()
        if private_constraints:
            constraints = result.setdefault("constraints", {})
            constraints.update(private_constraints)
        learned_pattern = self.learned_patterns.get(f"{intent}:{room}", {})
        result["user_preference_context"] = {
            "profile_id": self.profile.profile_id,
            "energy_saving_preference": self.profile.energy_saving_preference,
            "objective_weights": self.profile.objective_weights.normalized(),
            "adapted_targets": targets,
            "private_attributes": deepcopy(self.private_attributes),
            "learned_pattern": deepcopy(learned_pattern),
            # Only evidence explicitly confirmed by the resident is exposed as
            # a planning prior.  It never changes targets or safety limits.
            "confirmed_experience": self._confirmed_experience(learned_pattern),
        }
        return result

    @staticmethod
    def _confirmed_experience(pattern: object) -> dict[str, Any] | None:
        if not isinstance(pattern, dict):
            return None
        if pattern.get("promotion_status") != "user_confirmed_pattern":
            return None
        return {
            "pattern_key": pattern.get("pattern_key"),
            "intent": pattern.get("intent"),
            "room": pattern.get("room"),
            "observations": pattern.get("observations"),
            "completion_rate": pattern.get("completion_rate"),
            "explicit_feedback_count": pattern.get("explicit_feedback_count"),
            "positive_feedback_rate": pattern.get("positive_feedback_rate"),
            "promotion_status": "user_confirmed_pattern",
            "usage": "planning_context_only_no_target_or_safety_override",
        }

    def _private_attribute_constraints(self) -> dict[str, Any]:
        attributes_text = " ".join(self.private_attributes.values()).lower()
        airflow_signals = [
            "怕风",
            "避免直吹",
            "不要直吹",
            "不能吹风",
            "浅睡",
            "avoid direct airflow",
            "airflow sensitive",
            "light sleeper",
        ]
        if not any(signal in attributes_text for signal in airflow_signals):
            return {}
        return {
            "health_context_active": True,
            "private_attribute_constraint_active": True,
            "avoid_window_opening": True,
            "avoid_strong_fan": True,
            "fan_speed_limit_pct": 30,
            "avoid_overcooling": True,
            "cooling_setpoint_floor_c": 26,
            "reason": "用户私有知识库明确记录怕风、避免直吹或浅睡约束。",
        }

    def _load(self) -> None:
        if self.storage_path is None or not self.storage_path.exists():
            return
        try:
            stored_payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            payload = self._decode_stored_payload(stored_payload)
            if payload.get("schema_version") != self.MEMORY_SCHEMA_VERSION:
                return
            self.profile = UserPreferenceProfile.model_validate(payload.get("profile", {}))
            self.feedback_history = list(payload.get("feedback_history", []))[-self.MAX_FEEDBACK_HISTORY :]
            self.private_attributes = dict(payload.get("private_attributes", {}))
            self.reflections = list(payload.get("reflections", []))[-self.MAX_REFLECTIONS :]
            self.learned_patterns = dict(payload.get("learned_patterns", {}))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # A corrupt or incompatible private-memory file must not make the
            # control API unavailable; keep conservative defaults and replace
            # it only after the next explicit write.
            return

    def _persist(self) -> None:
        if self.storage_path is None:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self.private_memory_snapshot()
            temporary_path = self.storage_path.with_suffix(f"{self.storage_path.suffix}.tmp")
            serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            if self._fernet is not None:
                encrypted = self._fernet.encrypt(serialized.encode("utf-8")).decode("ascii")
                serialized = json.dumps(
                    {
                        "format": self.ENCRYPTED_FILE_FORMAT,
                        "cipher": "fernet",
                        "token": encrypted,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            temporary_path.write_text(serialized, encoding="utf-8")
            temporary_path.replace(self.storage_path)
        except OSError:
            self._persistence_failure_count += 1
            self._last_persistence_error_at = _now()
            raise
        self._persistence_success_count += 1
        self._last_persistence_success_at = _now()

    @staticmethod
    def _build_fernet(encryption_key: str | bytes | None) -> Fernet | None:
        if encryption_key is None or not str(encryption_key).strip():
            return None
        raw_key = encryption_key.encode("ascii") if isinstance(encryption_key, str) else encryption_key
        try:
            decoded = base64.urlsafe_b64decode(raw_key)
            if len(decoded) != 32:
                raise ValueError
            return Fernet(raw_key)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "PRIVATE_MEMORY_ENCRYPTION_KEY must be a URL-safe base64 Fernet key encoding 32 bytes."
            ) from exc

    def _decode_stored_payload(self, stored_payload: object) -> dict[str, Any]:
        if not isinstance(stored_payload, dict):
            raise ValueError("Private-memory payload must be a JSON object.")
        if stored_payload.get("format") != self.ENCRYPTED_FILE_FORMAT:
            return stored_payload
        if self._fernet is None:
            raise RuntimeError(
                "Encrypted private memory exists but PRIVATE_MEMORY_ENCRYPTION_KEY is unavailable."
            )
        token = stored_payload.get("token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Encrypted private-memory token is missing.")
        try:
            decrypted = self._fernet.decrypt(token.encode("ascii"))
            payload = json.loads(decrypted.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Private-memory decryption failed; refusing to replace unreadable resident data."
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Decrypted private-memory payload must be a JSON object.")
        return payload

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
