from pathlib import Path

from app.agents.reflection_agent import ReflectionAgent
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.research import UserPreferenceService
from app.simulation.environment import SmartHomeEnvironment
from app.simulation.life_simulation import LifeEvent, LifeSimulationService


def test_life_event_records_reflection_persistence_degradation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    environment = SmartHomeEnvironment()
    preferences = UserPreferenceService(storage_path=tmp_path / "memory.json")
    service = LifeSimulationService(
        environment=environment,
        experiment_logger=ExperimentLogger(tmp_path / "logs"),
        project_root=Path.cwd(),
        output_dir=tmp_path / "output",
        preference_service=preferences,
        reflection_agent=ReflectionAgent(preferences),
    )
    service.runner = TaskRunner(environment, service.experiment_logger, refresh_realtime=False)

    def fail_persistence(**_kwargs) -> dict:
        raise OSError("synthetic private-memory persistence failure")

    monkeypatch.setattr(preferences, "record_reflection", fail_persistence)
    service._run_event(
        LifeEvent(
            minute=0,
            room_id="living_room",
            activity="休息",
            activity_type="idle",
            command="打开客厅灯",
        )
    )

    record = service.event_records[-1]
    assert record["success"] is True
    assert record["reflection_recorded"] is False
    assert record["reflection_reason"] == "persistence_failed"
    assert record["reflection_id"] == ""
