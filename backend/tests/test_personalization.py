from fastapi.testclient import TestClient
import pytest
import time
from uuid import uuid4

from cryptography.fernet import Fernet

from app.main import app, session_store
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.research import (
    PrivateAttributeUpdate,
    PrivateMemoryResetRequest,
    RobustnessConfig,
    UserFeedbackRequest,
    UserPreferenceService,
)
from app.research.personalization import UserPreferenceUpdate
from app.research.autonomy import propose_sensor_driven_decision
from app.schemas.task_schema import AgentCommandRequest
from app.simulation.environment import SmartHomeEnvironment


def test_feedback_updates_preference_toward_explicit_target() -> None:
    service = UserPreferenceService()
    profile = service.apply_feedback(
        UserFeedbackRequest(
            satisfaction=2,
            desired_temperature_c=27,
            desired_illuminance_lux=650,
        )
    )
    assert profile.feedback_count == 1
    assert profile.preferred_temperature_c > 25
    assert profile.preferred_illuminance_lux > 500
    assert profile.satisfaction_ema < 75


def test_feedback_persistence_failure_does_not_mutate_the_active_profile(monkeypatch) -> None:
    service = UserPreferenceService()
    before = service.private_memory_snapshot()

    def fail_persistence() -> None:
        raise OSError("synthetic private-memory persistence failure")

    monkeypatch.setattr(service, "_persist", fail_persistence)

    with pytest.raises(OSError):
        service.apply_feedback(
            UserFeedbackRequest(
                satisfaction=5,
                desired_temperature_c=28,
                desired_illuminance_lux=700,
            )
        )

    assert service.private_memory_snapshot() == before


def test_profile_edit_persistence_failure_does_not_mutate_the_active_profile(monkeypatch) -> None:
    service = UserPreferenceService()
    before = service.private_memory_snapshot()

    def fail_persistence() -> None:
        raise OSError("synthetic private-memory persistence failure")

    monkeypatch.setattr(service, "_persist", fail_persistence)

    with pytest.raises(OSError):
        service.update(UserPreferenceUpdate(preferred_temperature_c=28))

    assert service.private_memory_snapshot() == before


def test_private_attribute_persistence_failure_does_not_mutate_active_constraints(monkeypatch) -> None:
    service = UserPreferenceService()
    before = service.private_memory_snapshot()

    def fail_persistence() -> None:
        raise OSError("synthetic private-memory persistence failure")

    monkeypatch.setattr(service, "_persist", fail_persistence)

    with pytest.raises(OSError):
        service.update_private_attributes(
            PrivateAttributeUpdate(attributes={"health_constraints": "怕风，避免直吹"})
        )

    assert service.private_memory_snapshot() == before


def test_private_memory_reset_persistence_failure_keeps_the_active_memory(monkeypatch) -> None:
    service = UserPreferenceService()
    service.update_private_attributes(PrivateAttributeUpdate(attributes={"resident_notes": "保留的私有记忆"}))
    before = service.private_memory_snapshot()

    def fail_persistence() -> None:
        raise OSError("synthetic private-memory persistence failure")

    monkeypatch.setattr(service, "_persist", fail_persistence)

    with pytest.raises(OSError):
        service.reset_private_memory(PrivateMemoryResetRequest(confirmation="RESET_PRIVATE_MEMORY"))

    assert service.private_memory_snapshot() == before


def test_private_memory_persists_profile_attributes_feedback_and_reflection(tmp_path) -> None:
    storage_path = tmp_path / "resident-1" / "user_memory.json"
    service = UserPreferenceService(storage_path=storage_path)
    service.update(UserPreferenceUpdate(preferred_temperature_c=26.5))
    service.update_private_attributes(
        PrivateAttributeUpdate(attributes={"sleep_airflow": "avoid_direct_airflow"})
    )
    service.apply_feedback(UserFeedbackRequest(satisfaction=4, note="睡眠模式比较舒适"))
    reflection = service.record_reflection(
        trigger="autonomous_sensor_tick",
        user_command="检测到卧室偏热，自动调节",
        semantic_result={"intent": "thermal_comfort_control", "room": "bedroom"},
        plan_result={"actions": [{"entity_id": "ac.bedroom_main"}]},
        execution_result={"executed_count": 1},
        feedback_result={"completed": True, "correction_round": 0},
    )

    restored = UserPreferenceService(storage_path=storage_path)
    snapshot = restored.private_memory_snapshot()

    assert storage_path.exists()
    assert restored.profile.preferred_temperature_c == 26.5
    assert snapshot["private_attributes"]["sleep_airflow"] == "avoid_direct_airflow"
    assert len(snapshot["feedback_history"]) == 1
    assert snapshot["reflections"][0]["reflection_id"] == reflection["reflection_id"]
    assert snapshot["learned_patterns"]["thermal_comfort_control:bedroom"]["observations"] == 1
    assert snapshot["reflection_policy"]["safety_boundary"] == "never_relaxed_by_reflection"


def test_autonomous_reflection_does_not_silently_change_explicit_targets() -> None:
    service = UserPreferenceService()
    initial_temperature = service.profile.preferred_temperature_c

    service.record_reflection(
        trigger="autonomous_life_event",
        user_command="系统自动调节卧室温度",
        semantic_result={"intent": "thermal_comfort_control", "room": "bedroom"},
        plan_result={"actions": []},
        execution_result={"executed_count": 0},
        feedback_result={"completed": False, "correction_round": 3},
    )

    assert service.profile.preferred_temperature_c == initial_temperature
    assert service.learned_patterns["thermal_comfort_control:bedroom"]["failed_count"] == 1


def test_explicit_feedback_confirms_latest_reflection_before_pattern_promotion() -> None:
    service = UserPreferenceService()
    service.record_reflection(
        trigger="autonomous_backend_scheduler",
        user_command="卧室温度偏高，自动调节",
        semantic_result={"intent": "thermal_comfort_control", "room": "bedroom"},
        plan_result={"actions": [{"entity_id": "ac.bedroom_main"}]},
        execution_result={"executed_count": 1},
        feedback_result={"completed": True},
    )

    for _ in range(3):
        service.apply_feedback(UserFeedbackRequest(satisfaction=5))

    reflection = service.reflections[-1]
    pattern = service.learned_patterns["thermal_comfort_control:bedroom"]
    assert reflection["feedback_interpretation"] == "positive_confirmation"
    assert pattern["explicit_feedback_count"] == 3
    assert pattern["positive_feedback_rate"] == 1.0
    assert pattern["promotion_status"] == "user_confirmed_pattern"


def test_only_user_confirmed_experience_becomes_a_planning_prior() -> None:
    service = UserPreferenceService()
    semantic_input = {
        "intent": "thermal_comfort_control",
        "room": "bedroom",
        "targets": {},
    }
    service.record_reflection(
        trigger="autonomous_backend_scheduler",
        user_command="卧室温度偏高，自动调节",
        semantic_result=semantic_input,
        plan_result={"actions": [{"entity_id": "ac.bedroom_main"}]},
        execution_result={"executed_count": 1},
        feedback_result={"completed": True},
    )

    before_confirmation = service.personalize_semantic_result(semantic_input)
    assert before_confirmation["user_preference_context"]["confirmed_experience"] is None

    for _ in range(3):
        service.apply_feedback(UserFeedbackRequest(satisfaction=5))

    after_confirmation = service.personalize_semantic_result(semantic_input)
    confirmed = after_confirmation["user_preference_context"]["confirmed_experience"]
    assert confirmed["promotion_status"] == "user_confirmed_pattern"
    assert confirmed["pattern_key"] == "thermal_comfort_control:bedroom"
    assert confirmed["usage"] == "planning_context_only_no_target_or_safety_override"
    assert after_confirmation["targets"] == before_confirmation["targets"]


def test_private_memory_reset_requires_typed_confirmation_and_clears_all_state(tmp_path) -> None:
    service = UserPreferenceService(storage_path=tmp_path / "memory.json")
    service.update_private_attributes(PrivateAttributeUpdate(attributes={"resident_notes": "怕风"}))
    service.apply_feedback(UserFeedbackRequest(satisfaction=4))

    snapshot = service.reset_private_memory(
        PrivateMemoryResetRequest(confirmation="RESET_PRIVATE_MEMORY")
    )

    assert snapshot["private_attributes"] == {}
    assert snapshot["feedback_history"] == []
    assert snapshot["reflections"] == []
    assert snapshot["profile"]["feedback_count"] == 0


def test_explicit_private_airflow_attribute_becomes_bounded_planning_constraint() -> None:
    service = UserPreferenceService()
    service.update_private_attributes(
        PrivateAttributeUpdate(attributes={"resident_notes": "怕风，夜间浅睡，睡眠时避免直吹"})
    )

    semantic = service.personalize_semantic_result(
        {
            "intent": "thermal_comfort_control",
            "room": "bedroom",
            "targets": {"temperature_c_range": [20, 24]},
        }
    )

    assert semantic["constraints"]["private_attribute_constraint_active"] is True
    assert semantic["constraints"]["avoid_strong_fan"] is True
    assert semantic["constraints"]["fan_speed_limit_pct"] == 30
    assert semantic["constraints"]["cooling_setpoint_floor_c"] == 26


def test_personalized_targets_and_robust_observation_are_deterministic() -> None:
    service = UserPreferenceService()
    service.update(UserPreferenceUpdate(preferred_temperature_c=26, temperature_tolerance_c=0.5))
    semantic = service.personalize_semantic_result({"intent": "thermal_comfort_control", "targets": {}})
    assert semantic["targets"]["temperature_c_range"] == [25.5, 26.5]

    state = SmartHomeEnvironment().get_state(refresh_realtime=False)
    config = RobustnessConfig(enabled=True, seed=7, temperature_sensor_noise_c=0.4)
    observed_a, _ = service.observe(state, config)
    observed_b, _ = service.observe(state, config)
    assert observed_a.rooms == observed_b.rooms
    assert observed_a.rooms != state.rooms


def test_sensor_driven_decision_uses_private_profile_thresholds() -> None:
    state = SmartHomeEnvironment().get_state(refresh_realtime=False)
    rooms = [
        room.model_copy(
            update={
                "occupancy": room.room_id == "living_room",
                "activity": "idle" if room.room_id == "living_room" else "away",
                "indoor_temperature_c": 28.0 if room.room_id == "living_room" else room.indoor_temperature_c,
                "indoor_illuminance_lux": 500.0 if room.room_id == "living_room" else room.indoor_illuminance_lux,
            }
        )
        for room in state.rooms
    ]
    profile = UserPreferenceService().update(
        UserPreferenceUpdate(
            preferred_temperature_c=25.0,
            temperature_tolerance_c=0.5,
            preferred_illuminance_lux=500.0,
        )
    )

    decision = propose_sensor_driven_decision(state.model_copy(update={"rooms": rooms}), profile)

    assert decision["triggered"] is True
    assert decision["trigger_type"] == "temperature_high"
    assert decision["room_id"] == "living_room"
    assert decision["target"] == [24.5, 25.5]


def test_sensor_driven_decision_detects_dark_occupied_bathroom() -> None:
    environment = SmartHomeEnvironment()
    state = environment.set_current_room("bathroom")
    state = state.model_copy(
        update={
            "rooms": [
                room.model_copy(update={"indoor_illuminance_lux": 0.0})
                if room.room_id == "bathroom"
                else room
                for room in state.rooms
            ]
        }
    )
    profile = UserPreferenceService().profile

    decision = propose_sensor_driven_decision(state, profile)

    assert decision["triggered"] is True
    assert decision["trigger_type"] == "illuminance_low"
    assert decision["room_id"] == "bathroom"


def test_preference_and_robustness_api_are_session_scoped() -> None:
    client = TestClient(app)
    headers = {"X-Simulation-Session": "personalization-test"}
    update = client.put("/api/research/profile", headers=headers, json={"preferred_temperature_c": 26.5})
    assert update.status_code == 200
    assert update.json()["preferred_temperature_c"] == 26.5

    robustness = client.put(
        "/api/research/robustness",
        headers=headers,
        json={"enabled": True, "seed": 12, "temperature_sensor_noise_c": 0.2},
    )
    assert robustness.status_code == 200
    assert robustness.json()["enabled"] is True
    assert client.get("/api/research/profile", headers=headers).json()["preferred_temperature_c"] == 26.5


def test_presence_api_updates_backend_occupancy_and_wakes_autonomy(monkeypatch) -> None:
    client = TestClient(app)
    session_id = f"presence-{uuid4().hex}"
    headers = {"X-Simulation-Session": session_id}
    runtime = session_store.get(session_id)
    wake_requests: list[bool] = []
    monkeypatch.setattr(
        runtime.autonomous_service,
        "request_immediate_cycle",
        lambda: wake_requests.append(True) or True,
    )

    response = client.put(
        "/api/presence/current-room",
        headers=headers,
        json={"current_room_id": "bathroom"},
    )

    assert response.status_code == 200
    payload = response.json()
    occupied = [room["room_id"] for room in payload["state"]["rooms"] if room["occupancy"]]
    assert occupied == ["bathroom"]
    assert payload["reflex_action"] is None
    assert payload["autonomy_woken"] is True
    assert wake_requests == [True]


def test_agent_health_network_probe_does_not_hold_resident_runtime_lock(monkeypatch) -> None:
    client = TestClient(app)
    session_id = f"health-lock-{uuid4().hex}"
    headers = {"X-Simulation-Session": session_id}
    runtime = session_store.get(session_id)

    def validate_without_runtime_lock(*, current_state) -> dict:
        assert current_state is not None
        assert not runtime.lock._is_owned()  # type: ignore[attr-defined]
        return {"success": True, "llm_mode": "mock", "error": None}

    monkeypatch.setattr(runtime.task_runner, "validate_llm_connection", validate_without_runtime_lock)

    response = client.get("/api/agent/health", headers=headers)

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_private_memory_api_is_session_isolated_and_records_command_reflection(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    client = TestClient(app)
    session_a = f"private-memory-a-{uuid4().hex}"
    session_b = f"private-memory-b-{uuid4().hex}"
    headers_a = {"X-Simulation-Session": session_a}
    headers_b = {"X-Simulation-Session": session_b}

    update = client.put(
        "/api/research/private-memory/attributes",
        headers=headers_a,
        json={"attributes": {"health_note": "怕风，睡眠时避免直吹"}},
    )
    assert update.status_code == 200

    command = client.post(
        "/api/agent/command",
        headers=headers_a,
        json={"user_command": "打开客厅灯", "current_room_id": "living_room"},
    )
    assert command.status_code == 200
    assert command.json()["feedback_result"]["self_reflection"]["trigger"] == "interactive_command"
    assert command.json()["multi_agent_blackboard"]["stages"][-1]["agent"] == "reflection_agent"

    memory_a = client.get("/api/research/private-memory", headers=headers_a).json()
    memory_b = client.get("/api/research/private-memory", headers=headers_b).json()
    assert memory_a["private_attributes"]["health_note"] == "怕风，睡眠时避免直吹"
    assert len(memory_a["reflections"]) == 1
    assert memory_b["private_attributes"] == {}
    assert memory_b["reflections"] == []


def test_autonomous_sensor_tick_runs_shared_agent_path_and_reflects(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    client = TestClient(app)
    session_id = f"autonomy-{uuid4().hex}"
    headers = {"X-Simulation-Session": session_id}
    profile = client.put(
        "/api/research/profile",
        headers=headers,
        json={"preferred_temperature_c": 16.0, "temperature_tolerance_c": 0.5},
    )
    assert profile.status_code == 200

    response = client.post("/api/autonomy/tick", headers=headers, json={"minutes": 1})
    payload = response.json()

    assert response.status_code == 200
    assert payload["mode"] == "backend_autonomous_runtime_v1"
    assert payload["decision"]["triggered"] is True
    assert payload["agent_response"]["success"] is True
    reflection = payload["agent_response"]["feedback_result"]["self_reflection"]
    assert reflection["trigger"] == "autonomous_diagnostic_tick"
    assert payload["agent_response"]["multi_agent_blackboard"]["stages"][-1]["agent"] == "reflection_agent"
    assert payload["reflection_count"] == 1


def test_backend_autonomy_start_status_stop_and_memory_reset_api(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    client = TestClient(app)
    session_id = f"formed-autonomy-{uuid4().hex}"
    headers = {"X-Simulation-Session": session_id}
    client.put(
        "/api/research/profile",
        headers=headers,
        json={"preferred_temperature_c": 16.0, "temperature_tolerance_c": 0.5},
    )
    client.put(
        "/api/research/private-memory/attributes",
        headers=headers,
        json={"attributes": {"resident_notes": "怕风"}},
    )

    started = client.post(
        "/api/autonomy/start",
        headers=headers,
        json={
            "interval_seconds": 1,
            "simulation_minutes_per_cycle": 1,
            "repeated_trigger_cooldown_seconds": 30,
            "max_consecutive_failures": 2,
        },
    )
    assert started.status_code == 200
    assert started.json()["active"] is True

    deadline = time.monotonic() + 3
    status = client.get("/api/autonomy/status", headers=headers).json()
    while status["cycle_count"] == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
        status = client.get("/api/autonomy/status", headers=headers).json()
    assert status["architecture"] == "backend_owned_autonomous_loop"
    assert status["cycle_count"] >= 1
    assert status["last_result"]["agent_response"]["success"] is True

    stopped = client.post("/api/autonomy/stop", headers=headers)
    assert stopped.status_code == 200
    assert stopped.json()["active"] is False

    reset = client.request(
        "DELETE",
        "/api/research/private-memory",
        headers=headers,
        json={"confirmation": "RESET_PRIVATE_MEMORY"},
    )
    assert reset.status_code == 200
    assert reset.json()["private_attributes"] == {}
    assert reset.json()["reflections"] == []


def test_personalized_multi_objective_evaluation_is_returned(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    environment = SmartHomeEnvironment()
    runner = TaskRunner(environment=environment, experiment_logger=ExperimentLogger(tmp_path))
    preferences = UserPreferenceService()
    preferences.update(UserPreferenceUpdate(preferred_temperature_c=26, preferred_illuminance_lux=600))

    response = runner.run_agent_command(
        AgentCommandRequest(user_command="书房学习", current_room_id="study_room"),
        preference_service=preferences,
        robustness_config=RobustnessConfig(enabled=True, seed=5, temperature_sensor_noise_c=0.2),
    )

    assert response.success is True
    evaluation = response.feedback_result["multi_objective_evaluation"]
    assert evaluation["method"] == "profile_weighted_multi_objective_v1"
    assert set(evaluation["scores"]) == {"comfort", "energy", "safety", "stability"}
    assert evaluation["comfort_measurement"] == "occupied_room_overall_score"


def test_task_comfort_uses_occupied_room_not_whole_home_average() -> None:
    state = SmartHomeEnvironment().get_state(refresh_realtime=False)
    selected_room_id = "study_room"
    rooms = [
        room.model_copy(update={"occupancy": room.room_id == selected_room_id, "activity": "studying" if room.room_id == selected_room_id else "away"})
        for room in state.rooms
    ]
    comfort_rooms = [
        room.model_copy(update={"overall_comfort_score": 12.0 if room.room_id == selected_room_id else 99.0})
        for room in state.comfort_metrics.rooms
    ]
    task_state = state.model_copy(update={
        "rooms": rooms,
        "comfort_metrics": state.comfort_metrics.model_copy(update={"rooms": comfort_rooms, "average_overall_score": 89.0}),
    })

    evaluation = UserPreferenceService().evaluate_multi_objective(
        task_state,
        action_count=1,
        safety_passed=True,
    )

    assert evaluation["comfort_measurement"] == "occupied_room_overall_score"
    assert evaluation["scores"]["comfort"] == 12.0


def test_static_controller_can_use_a_fixed_profile_for_outcome_evaluation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    runner = TaskRunner(environment=SmartHomeEnvironment(), experiment_logger=ExperimentLogger(tmp_path))
    evaluator = UserPreferenceService()

    response = runner.run_agent_command(
        AgentCommandRequest(user_command="打开客厅灯", current_room_id="living_room"),
        evaluation_preference_service=evaluator,
    )

    assert response.success is True
    assert response.semantic_result.get("user_preference_context") is None
    assert response.feedback_result["multi_objective_evaluation"]["method"] == "profile_weighted_multi_objective_v1"


def test_multi_objective_energy_score_uses_explicit_horizon_outcome() -> None:
    state = SmartHomeEnvironment().get_state(refresh_realtime=False)
    evaluation = UserPreferenceService().evaluate_multi_objective(
        state,
        action_count=1,
        safety_passed=True,
        energy_kwh=0.01,
        baseline_energy_kwh=0.02,
    )

    assert evaluation["energy_measurement"] == "post_control_horizon_kwh"
    assert evaluation["energy_actual_kwh"] == 0.01
    assert evaluation["energy_baseline_kwh"] == 0.02
    assert evaluation["energy_saving_rate_percent"] == 50.0
    assert evaluation["scores"]["energy"] == 75.0


def test_multi_objective_safety_score_uses_remaining_issue_severity() -> None:
    state = SmartHomeEnvironment().get_state(refresh_realtime=False)

    no_issue = UserPreferenceService().evaluate_multi_objective(
        state,
        action_count=1,
        safety_passed=True,
        safety_issues=[],
    )
    medium_issue = UserPreferenceService().evaluate_multi_objective(
        state,
        action_count=1,
        safety_passed=True,
        safety_issues=[{"severity": "medium"}],
    )
    high_issue = UserPreferenceService().evaluate_multi_objective(
        state,
        action_count=1,
        safety_passed=False,
        safety_issues=[{"severity": "high"}],
    )

    assert no_issue["scores"]["safety"] == 100.0
    assert medium_issue["scores"]["safety"] == 60.0
    assert high_issue["scores"]["safety"] == 20.0
    assert high_issue["safety_measurement"] == "final_executable_plan_severity_penalty_v1"
    assert high_issue["safety_high_issue_count"] == 1


def test_private_memory_encryption_round_trip_hides_resident_content(tmp_path) -> None:
    storage_path = tmp_path / "resident-memory.json"
    key = Fernet.generate_key()
    service = UserPreferenceService(storage_path=storage_path, encryption_key=key)

    service.update_private_attributes(
        PrivateAttributeUpdate(attributes={"sleep_note": "浅睡，避免直吹"})
    )

    stored_text = storage_path.read_text(encoding="utf-8")
    assert "浅睡" not in stored_text
    assert "encrypted_private_memory_v1" in stored_text
    restored = UserPreferenceService(storage_path=storage_path, encryption_key=key)
    snapshot = restored.private_memory_snapshot()
    assert snapshot["private_attributes"]["sleep_note"] == "浅睡，避免直吹"
    assert snapshot["storage_security"]["encrypted_at_rest"] is True


def test_encrypted_private_memory_fails_closed_without_key(tmp_path) -> None:
    storage_path = tmp_path / "resident-memory.json"
    service = UserPreferenceService(
        storage_path=storage_path,
        encryption_key=Fernet.generate_key(),
    )
    service.update_private_attributes(
        PrivateAttributeUpdate(attributes={"sleep_note": "resident-only"})
    )

    with pytest.raises(RuntimeError, match="PRIVATE_MEMORY_ENCRYPTION_KEY is unavailable"):
        UserPreferenceService(storage_path=storage_path)


def test_plaintext_private_memory_migrates_on_next_explicit_write(tmp_path) -> None:
    storage_path = tmp_path / "resident-memory.json"
    plaintext_service = UserPreferenceService(storage_path=storage_path)
    plaintext_service.update_private_attributes(
        PrivateAttributeUpdate(attributes={"sleep_note": "legacy plaintext"})
    )
    assert "legacy plaintext" in storage_path.read_text(encoding="utf-8")

    encrypted_service = UserPreferenceService(
        storage_path=storage_path,
        encryption_key=Fernet.generate_key(),
    )
    encrypted_service.update_private_attributes(
        PrivateAttributeUpdate(attributes={"sleep_note": "migrated"})
    )

    stored_text = storage_path.read_text(encoding="utf-8")
    assert "legacy plaintext" not in stored_text
    assert "migrated" not in stored_text
    assert "encrypted_private_memory_v1" in stored_text
