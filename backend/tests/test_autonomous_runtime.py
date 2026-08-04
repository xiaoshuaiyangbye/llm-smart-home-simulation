import time
from threading import Event, RLock, Thread

from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.agents.reflection_agent import ReflectionAgent
from app.research import RobustnessConfig, UserPreferenceService
from app.research.personalization import UserPreferenceUpdate
from app.runtime.autonomous_service import AutonomousRuntimeConfig, AutonomousRuntimeService
from app.schemas.task_schema import AgentCommandResponse
from app.simulation.environment import SmartHomeEnvironment


def _service(tmp_path) -> AutonomousRuntimeService:
    environment = SmartHomeEnvironment()
    runner = TaskRunner(environment, ExperimentLogger(tmp_path / "logs"))
    preferences = UserPreferenceService(storage_path=tmp_path / "memory.json")
    preferences.update(
        UserPreferenceUpdate(
            preferred_temperature_c=16.0,
            temperature_tolerance_c=0.5,
            preferred_illuminance_lux=50.0,
        )
    )
    return AutonomousRuntimeService(
        environment=environment,
        task_runner=runner,
        preference_service=preferences,
        reflection_agent=ReflectionAgent(preferences),
        robustness_config=RobustnessConfig(),
        runtime_lock=RLock(),
        config_path=tmp_path / "autonomy_config.json",
    )


def test_backend_autonomous_cycle_reflects_and_suppresses_repeated_trigger(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)
    service.config = AutonomousRuntimeConfig(
        interval_seconds=1,
        simulation_minutes_per_cycle=1,
        repeated_trigger_cooldown_seconds=60,
    )

    first = service.run_once()
    second = service.run_once()
    assert first["decision"]["triggered"] is True
    assert first["agent_response"]["success"] is True
    assert first["agent_response"]["feedback_result"]["self_reflection"]
    assert second["decision"]["triggered"] is False
    assert second["decision"]["suppression_reason"] == "repeated_trigger_cooldown"
    assert service.status()["cycle_count"] == 2
    assert service.status()["decision_count"] == 1
    assert service.status()["suppressed_count"] == 1


def test_reflection_persistence_failure_does_not_reclassify_successful_control(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)
    service.config = AutonomousRuntimeConfig(
        interval_seconds=1,
        simulation_minutes_per_cycle=1,
        repeated_trigger_cooldown_seconds=60,
    )

    def fail_persistence() -> None:
        raise OSError("synthetic private-memory persistence failure")

    monkeypatch.setattr(service.preference_service, "_persist", fail_persistence)

    first = service.run_once()
    second = service.run_once()

    assert first["success"] is True
    assert first["agent_response"]["success"] is True
    assert first["agent_response"]["feedback_result"]["self_reflection"]["recorded"] is False
    assert first["agent_response"]["feedback_result"]["self_reflection"]["reason"] == "persistence_failed"
    assert service.preference_service.reflections == []
    assert service.preference_service.learned_patterns == {}
    assert second["decision"]["suppression_reason"] == "repeated_trigger_cooldown"
    assert service.status()["failure_count"] == 0


def test_backend_scheduler_runs_without_browser_and_persists_settings(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)
    config = AutonomousRuntimeConfig(
        interval_seconds=1,
        simulation_minutes_per_cycle=2,
        repeated_trigger_cooldown_seconds=45,
        max_consecutive_failures=2,
    )

    started = service.start(config)
    deadline = time.monotonic() + 3
    while service.status()["cycle_count"] == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    stopped = service.stop()

    assert started["active"] is True
    assert stopped["active"] is False
    assert stopped["cycle_count"] >= 1
    assert stopped["stop_reason"] == "user_requested"
    restored = _service(tmp_path)
    assert restored.config == config
    assert restored.status()["auto_resume_after_restart"] is False


def test_presence_event_wakes_scheduler_before_periodic_interval(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)
    service.start(
        AutonomousRuntimeConfig(
            interval_seconds=300,
            simulation_minutes_per_cycle=1,
            repeated_trigger_cooldown_seconds=0,
        )
    )
    deadline = time.monotonic() + 3
    while service.status()["cycle_count"] < 1 and time.monotonic() < deadline:
        time.sleep(0.02)

    service.environment.set_current_room("bathroom")
    assert service.request_immediate_cycle() is True
    deadline = time.monotonic() + 3
    while service.status()["cycle_count"] < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    status = service.stop()

    assert status["cycle_count"] >= 2
    assert status["last_result"]["decision"]["room_id"] == "bathroom"


def test_backend_scheduler_stops_after_bounded_consecutive_failures(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)

    def fail_command(*args, **kwargs) -> AgentCommandResponse:
        del args, kwargs
        return AgentCommandResponse(
            success=False,
            error="synthetic scheduler failure",
            final_state=service.environment.get_state(refresh_realtime=False),
        )

    monkeypatch.setattr(TaskRunner, "run_agent_command", fail_command)
    service.start(
        AutonomousRuntimeConfig(
            interval_seconds=1,
            simulation_minutes_per_cycle=1,
            repeated_trigger_cooldown_seconds=0,
            max_consecutive_failures=1,
        )
    )
    deadline = time.monotonic() + 3
    while service.status()["active"] and time.monotonic() < deadline:
        time.sleep(0.02)
    status = service.status()

    assert status["active"] is False
    assert status["stop_reason"] == "max_consecutive_failures"
    assert status["failure_count"] == 1
    assert status["consecutive_failures"] == 1


def test_failed_trigger_is_retried_instead_of_hidden_by_cooldown(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)
    service.config = AutonomousRuntimeConfig(
        interval_seconds=1,
        simulation_minutes_per_cycle=1,
        repeated_trigger_cooldown_seconds=60,
        max_consecutive_failures=3,
    )

    def fail_command(*args, **kwargs) -> AgentCommandResponse:
        del args, kwargs
        return AgentCommandResponse(
            success=False,
            error="synthetic repeated failure",
            final_state=service.environment.get_state(refresh_realtime=False),
        )

    monkeypatch.setattr(TaskRunner, "run_agent_command", fail_command)
    first = service.run_once()
    second = service.run_once()

    assert first["decision"]["triggered"] is True
    assert second["decision"]["triggered"] is True
    assert second["decision"].get("suppressed") is False
    assert service.status()["failure_count"] == 2
    assert service.status()["consecutive_failures"] == 2


def test_stop_reports_stopping_until_inflight_cycle_releases_control(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)
    service.STOP_JOIN_TIMEOUT_SECONDS = 0.01
    entered = Event()
    release = Event()

    def blocking_cycle(*args, **kwargs):
        del args, kwargs
        entered.set()
        release.wait(timeout=2)
        result = {
            "mode": "backend_autonomous_runtime_v1",
            "cycle_at": "synthetic",
            "decision": {"triggered": False},
            "agent_response": None,
            "state": service.environment.get_state(refresh_realtime=False).model_dump(mode="json"),
            "reflection_count": 0,
            "success": True,
            "error": None,
        }
        service._record_cycle(result)
        return result

    monkeypatch.setattr(service, "run_once", blocking_cycle)
    service.start()
    assert entered.wait(timeout=1)

    stopping = service.stop()

    assert stopping["active"] is True
    assert stopping["stopping"] is True
    assert stopping["worker_alive"] is True
    release.set()
    deadline = time.monotonic() + 1
    status = service.status()
    while status["worker_alive"] and time.monotonic() < deadline:
        time.sleep(0.01)
        status = service.status()
    assert status["active"] is False
    assert status["stopping"] is False
    assert status["stop_reason"] == "user_requested"


def test_presence_reflex_is_observable_and_manual_override_can_suppress_it(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)
    service.start(
        AutonomousRuntimeConfig(
            interval_seconds=300,
            simulation_minutes_per_cycle=1,
            repeated_trigger_cooldown_seconds=30,
        )
    )
    deadline = time.monotonic() + 2
    while service.status()["cycle_count"] < 1 and time.monotonic() < deadline:
        time.sleep(0.01)

    first_presence = service.update_presence("bathroom")
    assert first_presence["reflex_action"]["policy"] == "bounded_presence_lighting_reflex_v1"
    assert next(
        room["occupancy"]
        for room in first_presence["state"]["rooms"]
        if room["room_id"] == "bathroom"
    ) is True
    assert first_presence["reflex_action"]["success"] is True

    deadline = time.monotonic() + 2
    while service.status()["cycle_count"] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    with service.runtime_lock:
        service.environment.apply_device_action(
            "light.bathroom_main",
            "turn_off",
            {},
        )
    service.register_manual_override(room_id="bathroom", device_type="light", duration_seconds=60)
    second_presence = service.update_presence("bathroom")
    bathroom_light = next(
        device
        for device in second_presence["state"]["devices"]
        if device["entity_id"] == "light.bathroom_main"
    )
    assert second_presence["reflex_action"] is None
    assert bathroom_light["is_on"] is False
    service.stop()


def test_inflight_plan_does_not_block_presence_and_stale_commit_is_rejected(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    service = _service(tmp_path)
    entered_planning = Event()
    release_planning = Event()
    original_run = TaskRunner.run_agent_command

    def blocking_plan(runner, *args, **kwargs):
        entered_planning.set()
        assert release_planning.wait(timeout=2)
        return original_run(runner, *args, **kwargs)

    monkeypatch.setattr(TaskRunner, "run_agent_command", blocking_plan)
    result_holder: dict[str, object] = {}

    worker = Thread(target=lambda: result_holder.update(service.run_once()), daemon=True)
    worker.start()
    assert entered_planning.wait(timeout=1)

    acquired = service.runtime_lock.acquire(timeout=0.2)
    assert acquired is True
    try:
        service.environment.set_current_room("bathroom")
    finally:
        service.runtime_lock.release()
    release_planning.set()
    worker.join(timeout=2)

    assert worker.is_alive() is False
    assert result_holder["runtime_commit_status"] == "stale_snapshot_replan_required"
    assert result_holder["decision"]["suppression_reason"] == "stale_snapshot_replan_required"
    assert service.status()["stale_plan_count"] == 1
    state = service.environment.get_state(refresh_realtime=False)
    assert next(room for room in state.rooms if room.room_id == "bathroom").occupancy is True
