from __future__ import annotations

import json
import hashlib
import time
from copy import deepcopy
from datetime import datetime
from math import ceil
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from typing import Any

from pydantic import BaseModel, Field

from app.experiments.task_runner import TaskRunner
from app.agents.reflection_agent import ReflectionAgent
from app.research import RobustnessConfig, UserPreferenceService
from app.research.autonomy import propose_sensor_driven_decision
from app.schemas.task_schema import AgentCommandRequest
from app.schemas.action_schema import DeviceActionRequest
from app.schemas.action_schema import AgentOutput
from app.schemas.state_schema import RoomId
from app.simulation.environment import SmartHomeEnvironment
from app.runtime.snapshot_commit import evaluate_snapshot_commit


class AutonomousRuntimeConfig(BaseModel):
    interval_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    simulation_minutes_per_cycle: int = Field(default=5, ge=1, le=60)
    repeated_trigger_cooldown_seconds: float = Field(default=30.0, ge=0.0, le=3600.0)
    max_consecutive_failures: int = Field(default=3, ge=1, le=20)


class AutonomousRuntimeService:
    """Backend-owned autonomous perception and decision loop.

    One service belongs to one simulation/resident runtime. The scheduler is
    deliberately not auto-resumed after a process restart: persisted settings
    are restored, but actuator authority requires an explicit start request.
    """

    STOP_JOIN_TIMEOUT_SECONDS = 2.0

    def __init__(
        self,
        *,
        environment: SmartHomeEnvironment,
        task_runner: TaskRunner,
        preference_service: UserPreferenceService,
        reflection_agent: ReflectionAgent,
        robustness_config: RobustnessConfig,
        runtime_lock: RLock,
        config_path: Path | None = None,
    ) -> None:
        self.environment = environment
        self.task_runner = task_runner
        self.preference_service = preference_service
        self.reflection_agent = reflection_agent
        self.robustness_config = robustness_config
        self.runtime_lock = runtime_lock
        self.config_path = config_path
        self.config = self._load_config()
        self._state_lock = RLock()
        self._stop_event = Event()
        self._wake_event = Event()
        self._worker: Thread | None = None
        self._active = False
        self._stop_requested = False
        self._requested_stop_reason: str | None = None
        self._started_at: str | None = None
        self._stopped_at: str | None = None
        self._stop_reason = "not_started"
        self._cycle_count = 0
        self._decision_count = 0
        self._suppressed_count = 0
        self._failure_count = 0
        self._consecutive_failures = 0
        self._last_cycle_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._cooldown_until: dict[str, float] = {}
        self._manual_override_until: dict[str, float] = {}
        self._last_reflex: dict[str, Any] | None = None
        self._stale_plan_count = 0
        self._committed_action_ids: list[str] = []

    def start(self, config: AutonomousRuntimeConfig | None = None) -> dict[str, Any]:
        with self._state_lock:
            if self._active:
                return self.status()
            if self._worker and self._worker.is_alive():
                raise RuntimeError("Previous autonomous cycle is still shutting down.")
            if config is not None:
                self.config = config
                self._persist_config()
            self._stop_event = Event()
            self._wake_event = Event()
            self._active = True
            self._stop_requested = False
            self._requested_stop_reason = None
            self._started_at = _now()
            self._stopped_at = None
            self._stop_reason = "running"
            self._consecutive_failures = 0
            self._worker = Thread(
                target=self._run_loop,
                name="smart-home-autonomous-runtime",
                daemon=True,
            )
            self._worker.start()
            return self.status()

    def stop(self, reason: str = "user_requested") -> dict[str, Any]:
        with self._state_lock:
            worker = self._worker
            if not self._active and not (worker and worker.is_alive()):
                return self.status()
            self._stop_requested = True
            self._requested_stop_reason = reason
            self._stop_reason = "stop_requested"
            self._stop_event.set()
            self._wake_event.set()
        if worker and worker is not current_thread():
            worker.join(timeout=self.STOP_JOIN_TIMEOUT_SECONDS)
        return self.status()

    def request_immediate_cycle(self) -> bool:
        """Wake the scheduler after a new sensor or presence event."""
        with self._state_lock:
            if not self._active or self._stop_requested:
                return False
            self._wake_event.set()
            return True

    def update_presence(self, room_id: RoomId) -> dict[str, Any]:
        """Apply one presence event and an explicit bounded lighting reflex."""
        with self.runtime_lock:
            state = self.environment.set_current_room(room_id)
            reflex: dict[str, Any] | None = None
            with self._state_lock:
                reflex_enabled = self._active and not self._stop_requested
            room = next(item for item in state.rooms if item.room_id == room_id)
            light = next(
                (
                    item
                    for item in state.devices
                    if item.room == room_id and item.device_type == "light"
                ),
                None,
            )
            trigger_key = self._trigger_key("illuminance_low", room_id)
            if (
                reflex_enabled
                and light is not None
                and not self._is_manual_override_active(trigger_key)
            ):
                threshold_lux = self.preference_service.profile.preferred_illuminance_lux * 0.75
                if room.indoor_illuminance_lux < threshold_lux:
                    missing_lux = threshold_lux - room.indoor_illuminance_lux
                    brightness_pct = min(
                        100,
                        max(20, ceil(missing_lux / max(light.max_lux_contribution, 1) * 100) + 1),
                    )
                    action = DeviceActionRequest(
                        entity_id=light.entity_id,
                        action="turn_on",
                        parameters={"brightness_pct": brightness_pct, "color_temperature_k": 4000},
                    )
                    success, message, _before_state, state = self.environment.apply_device_action(
                        entity_id=action.entity_id,
                        action=action.action,
                        parameters=action.parameters,
                    )
                    self.task_runner.experiment_logger.log_device_action(
                        action=action,
                        success=success,
                        message=f"presence reflex: {message}",
                        state=state,
                    )
                    reflex = {
                        "policy": "bounded_presence_lighting_reflex_v1",
                        "trigger_type": "illuminance_low",
                        "room_id": room_id,
                        "action": action.model_dump(mode="json"),
                        "success": success,
                        "message": message,
                    }
                    if success:
                        self._mark_successful_trigger(
                            {"trigger_type": "illuminance_low", "room_id": room_id}
                        )
                    with self._state_lock:
                        self._last_reflex = deepcopy(reflex)
        autonomy_woken = self.request_immediate_cycle()
        return {
            "state": state.model_dump(mode="json"),
            "reflex_action": reflex,
            "autonomy_woken": autonomy_woken,
        }

    def register_manual_override(
        self,
        *,
        room_id: str,
        device_type: str,
        duration_seconds: float = 300.0,
    ) -> None:
        trigger_types = {
            "light": {"illuminance_low"},
            "ac": {"temperature_high", "temperature_low"},
            "fan": {"temperature_high", "humidity_deviation"},
            "window": {"temperature_high", "humidity_deviation"},
        }.get(device_type, set())
        if not trigger_types:
            return
        expires_at = time.monotonic() + max(0.0, duration_seconds)
        with self._state_lock:
            for trigger_type in trigger_types:
                self._manual_override_until[self._trigger_key(trigger_type, room_id)] = expires_at

    def run_once(
        self,
        *,
        trigger: str = "autonomous_backend_scheduler",
        simulation_minutes: int | None = None,
    ) -> dict[str, Any]:
        try:
            with self.runtime_lock:
                perceived_state = self.environment.step(
                    minutes=simulation_minutes or self.config.simulation_minutes_per_cycle,
                    refresh_realtime=False,
                )
                snapshot_revision = self.environment.revision
            preference_fingerprint = self._preference_fingerprint()
            decision = propose_sensor_driven_decision(
                perceived_state,
                self.preference_service.profile,
            )
            decision = self._apply_repeated_trigger_cooldown(decision)
            response_payload: dict[str, Any] | None = None
            commit_status = "not_required"
            if decision["triggered"]:
                command_request = AgentCommandRequest(
                    user_command=str(decision["command"]),
                    current_room_id=decision["room_id"],
                )
                planning_environment = SmartHomeEnvironment(initial_state=perceived_state)
                planning_runner = TaskRunner(
                    environment=planning_environment,
                    experiment_logger=self.task_runner.experiment_logger,
                    refresh_realtime=False,
                    enable_feedback_correction=False,
                    enable_context_memory=False,
                    enable_multi_agent_review=self.task_runner.enable_multi_agent_review,
                    execute_actions=False,
                    log_task_results=False,
                    rag_store=self.task_runner.rag_store,
                )
                response = planning_runner.run_agent_command(
                    command_request,
                    preference_service=self.preference_service,
                    robustness_config=self.robustness_config,
                )
                if not response.success:
                    final_state = self.environment.get_state(refresh_realtime=False)
                    succeeded = False
                    commit_status = "planning_failed"
                else:
                    actions = response.plan_result.get("actions", [])
                    commit_id = self._action_commit_id(snapshot_revision, actions)
                    with self.runtime_lock:
                        commit_evaluation = evaluate_snapshot_commit(
                            snapshot_revision=snapshot_revision,
                            current_revision=self.environment.revision,
                            snapshot_preference_fingerprint=preference_fingerprint,
                            current_preference_fingerprint=self._preference_fingerprint(),
                            commit_id=commit_id,
                            committed_action_ids=self._committed_action_ids,
                        )
                        if not commit_evaluation.allowed:
                            final_state = self.environment.get_state(refresh_realtime=False)
                            succeeded = True
                            commit_status = commit_evaluation.status
                        else:
                            execution_results, final_state = self.environment.apply_device_actions_batch(actions)
                            succeeded = all(item.get("success") for item in execution_results)
                            commit_status = "committed" if succeeded else "device_action_failed"
                            response.execution_result = {
                                "agent": "execution_agent",
                                "execution_mode": "optimistic_snapshot_commit_v1",
                                "commit_id": commit_id,
                                "snapshot_revision": snapshot_revision,
                                "committed_revision": self.environment.revision,
                                "executed_count": sum(
                                    bool(item.get("success")) for item in execution_results
                                ),
                                "results": execution_results,
                                "final_state": final_state.model_dump(mode="json"),
                            }
                            response.feedback_result = self.task_runner.feedback_agent.evaluate(
                                response.semantic_result,
                                final_state,
                                revision_round=0,
                            )
                            safety_result = (
                                response.plan_result.get("multi_agent_context", {}).get(
                                    "safety_result", {}
                                )
                            )
                            multi_objective = self.preference_service.evaluate_multi_objective(
                                final_state,
                                action_count=len(actions),
                                safety_passed=bool(safety_result.get("passed", True)),
                                safety_issues=safety_result.get("remaining_issues", []),
                            )
                            response.plan_result["multi_objective_evaluation"] = multi_objective
                            response.feedback_result["multi_objective_evaluation"] = multi_objective
                            response.success = succeeded
                            response.error = None if succeeded else "Autonomous device action failed."
                            response.final_state = final_state
                            if succeeded:
                                self._committed_action_ids.append(commit_id)
                                self._committed_action_ids = self._committed_action_ids[-256:]
                    if commit_status == "stale_snapshot_replan_required":
                        with self._state_lock:
                            self._stale_plan_count += 1
                        decision = {
                            **decision,
                            "triggered": False,
                            "suppressed": True,
                            "suppression_reason": "stale_snapshot_replan_required",
                        }
                        self.request_immediate_cycle()
                    elif commit_status == "committed" and response.success:
                        response = self.reflection_agent.reflect(
                            response,
                            trigger=trigger,
                            user_command=command_request.user_command,
                        )
                        self._mark_successful_trigger(decision)
                        self.task_runner.experiment_logger.log_task(
                            experiment_id="autonomous-command",
                            user_command=command_request.user_command,
                            agent_output=AgentOutput(
                                semantic_result=response.semantic_result,
                                planning_result=response.plan_result,
                                execution_result=response.execution_result,
                                feedback_result=response.feedback_result,
                                actions=response.plan_result.get("actions", []),
                                multi_agent_blackboard=response.multi_agent_blackboard,
                            ),
                            state=final_state,
                        )
                response_payload = response.model_dump(mode="json")
                response_payload["runtime_commit"] = {
                    "status": commit_status,
                    "snapshot_revision": snapshot_revision,
                    "current_revision": self.environment.revision,
                }
            else:
                final_state = perceived_state
                succeeded = True

            result = {
                "mode": "backend_autonomous_runtime_v1",
                "cycle_at": _now(),
                "decision": decision,
                "agent_response": response_payload,
                "runtime_commit_status": commit_status,
                "state": final_state.model_dump(mode="json"),
                "reflection_count": len(self.preference_service.reflections),
                "success": succeeded,
                "error": None if succeeded else (response_payload or {}).get("error"),
            }
            self._record_cycle(result)
            return deepcopy(result)
        except Exception as exc:  # Keep the scheduler observable and fail bounded.
            result = {
                "mode": "backend_autonomous_runtime_v1",
                "cycle_at": _now(),
                "decision": None,
                "agent_response": None,
                "state": self.environment.get_state(refresh_realtime=False).model_dump(mode="json"),
                "reflection_count": len(self.preference_service.reflections),
                "success": False,
                "error": str(exc),
            }
            self._record_cycle(result)
            return deepcopy(result)

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            worker_alive = bool(self._worker and self._worker.is_alive())
            return {
                "architecture": "backend_owned_autonomous_loop",
                "active": self._active,
                "stopping": self._stop_requested and worker_alive,
                "config": self.config.model_dump(mode="json"),
                "started_at": self._started_at,
                "stopped_at": self._stopped_at,
                "stop_reason": self._stop_reason,
                "cycle_count": self._cycle_count,
                "decision_count": self._decision_count,
                "suppressed_count": self._suppressed_count,
                "failure_count": self._failure_count,
                "consecutive_failures": self._consecutive_failures,
                "last_cycle_at": self._last_cycle_at,
                "last_result": deepcopy(self._last_result),
                "last_reflex": deepcopy(self._last_reflex),
                "planning_commit_mode": "optimistic_snapshot_commit_v1",
                "stale_plan_count": self._stale_plan_count,
                "settings_persisted": self.config_path is not None,
                "auto_resume_after_restart": False,
                "worker_alive": worker_alive,
            }

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            with self._state_lock:
                should_stop = self._consecutive_failures >= self.config.max_consecutive_failures
                if should_stop:
                    self._stop_requested = True
                    self._requested_stop_reason = "max_consecutive_failures"
                    self._stop_event.set()
            if should_stop:
                break
            self._wake_event.wait(self.config.interval_seconds)
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
        with self._state_lock:
            self._active = False
            self._stopped_at = _now()
            self._stop_reason = self._requested_stop_reason or "worker_exited"
            self._stop_requested = False
            self._requested_stop_reason = None

    def _apply_repeated_trigger_cooldown(self, decision: dict[str, Any]) -> dict[str, Any]:
        if not decision.get("triggered"):
            return decision
        trigger_key = self._trigger_key(decision.get("trigger_type"), decision.get("room_id"))
        now = time.monotonic()
        with self._state_lock:
            self._prune_expired_cooldowns(now)
            automatic_until = self._cooldown_until.get(trigger_key, 0.0)
            manual_until = self._manual_override_until.get(trigger_key, 0.0)
        cooldown_until = max(automatic_until, manual_until)
        if cooldown_until > now:
            return {
                **decision,
                "triggered": False,
                "suppressed": True,
                "suppression_reason": (
                    "manual_override" if manual_until >= automatic_until else "repeated_trigger_cooldown"
                ),
                "cooldown_remaining_seconds": round(cooldown_until - now, 2),
            }
        return {**decision, "suppressed": False}

    def _mark_successful_trigger(self, decision: dict[str, Any]) -> None:
        if not decision.get("trigger_type"):
            return
        trigger_key = self._trigger_key(decision.get("trigger_type"), decision.get("room_id"))
        with self._state_lock:
            self._cooldown_until[trigger_key] = (
                time.monotonic() + self.config.repeated_trigger_cooldown_seconds
            )

    def _is_manual_override_active(self, trigger_key: str) -> bool:
        now = time.monotonic()
        with self._state_lock:
            self._prune_expired_cooldowns(now)
            return self._manual_override_until.get(trigger_key, 0.0) > now

    def _prune_expired_cooldowns(self, now: float) -> None:
        self._cooldown_until = {
            key: expiry for key, expiry in self._cooldown_until.items() if expiry > now
        }
        self._manual_override_until = {
            key: expiry for key, expiry in self._manual_override_until.items() if expiry > now
        }

    @staticmethod
    def _trigger_key(trigger_type: object, room_id: object) -> str:
        return f"{trigger_type}:{room_id}"

    def _preference_fingerprint(self) -> str:
        payload = self.preference_service.private_memory_snapshot()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _action_commit_id(snapshot_revision: int, actions: object) -> str:
        payload = json.dumps(
            {"snapshot_revision": snapshot_revision, "actions": actions},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _record_cycle(self, result: dict[str, Any]) -> None:
        with self._state_lock:
            self._cycle_count += 1
            decision = result.get("decision") or {}
            if decision.get("triggered"):
                self._decision_count += 1
            if decision.get("suppressed"):
                self._suppressed_count += 1
            if result.get("success"):
                self._consecutive_failures = 0
            else:
                self._failure_count += 1
                self._consecutive_failures += 1
            self._last_cycle_at = str(result.get("cycle_at") or _now())
            self._last_result = deepcopy(result)

    def _load_config(self) -> AutonomousRuntimeConfig:
        if self.config_path is None or not self.config_path.exists():
            return AutonomousRuntimeConfig()
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            return AutonomousRuntimeConfig.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return AutonomousRuntimeConfig()

    def _persist_config(self) -> None:
        if self.config_path is None:
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(f"{self.config_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self.config.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.config_path)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
