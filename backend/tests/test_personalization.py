from fastapi.testclient import TestClient

from app.main import app
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.research import RobustnessConfig, UserFeedbackRequest, UserPreferenceService
from app.research.personalization import UserPreferenceUpdate
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
