from pathlib import Path

from app.agents.structured_agents import (
    CRITIC_DECISION_ADAPTER,
    EXECUTOR_DECISION_ADAPTER,
    PLANNER_DECISION_ADAPTER,
)
from app.config.simulation import SimulationConfig
from app.runtime.engine import SimulationEngine
from app.runtime.events import EventBus
from app.runtime.replay import ReplayEngine
from app.tools.schemas import ToolCall


def test_event_bus_publish_subscribe() -> None:
    bus = EventBus()
    seen = []
    bus.subscribe("tick_completed", lambda event: seen.append(event.payload["ok"]))
    bus.publish(type("EventLike", (), {"event_type": "tick_completed", "tick": 0, "payload": {"ok": True}})())
    assert seen == [True]


def test_deterministic_tick_with_same_seed(tmp_path: Path) -> None:
    log_a = tmp_path / "a.jsonl"
    log_b = tmp_path / "b.jsonl"
    call = ToolCall(
        tool_name="device.control",
        arguments={
            "entity_id": "light.living_room_main",
            "action": "turn_on",
            "parameters": {"brightness_pct": 55},
        },
    )

    engine_a = SimulationEngine(config=SimulationConfig(seed=7), log_path=log_a)
    engine_b = SimulationEngine(config=SimulationConfig(seed=7), log_path=log_b)
    engine_a.reset()
    engine_b.reset()
    result_a = engine_a.tick([call])
    result_b = engine_b.tick([call])

    assert result_a["after_hash"] == result_b["after_hash"]
    assert result_a["diff"] == result_b["diff"]


def test_structured_agent_schema_validation(tmp_path: Path) -> None:
    engine = SimulationEngine(log_path=tmp_path / "agents.jsonl")
    engine.reset()
    planner = engine.plan(
        {
            "intent": "basic_light_control",
            "room": "living_room",
            "control_goal": "turn_on",
            "targets": {"illuminance_lux_range": [300, 700], "temperature_c_range": [22, 27]},
        }
    )
    executor, critic = engine.execute_plan(planner)

    assert PLANNER_DECISION_ADAPTER.validate_python(planner.model_dump()).agent == "planner_agent"
    assert EXECUTOR_DECISION_ADAPTER.validate_python(executor.model_dump()).agent == "executor_agent"
    assert CRITIC_DECISION_ADAPTER.validate_python(critic.model_dump()).agent == "critic_agent"


def test_replay_matches_recorded_run(tmp_path: Path) -> None:
    log_path = tmp_path / "run.jsonl"
    engine = SimulationEngine(config=SimulationConfig(seed=11, tick_minutes=5), log_path=log_path)
    engine.reset()
    engine.tick(
        [
            ToolCall(
                tool_name="device.control",
                arguments={
                    "entity_id": "curtain.living_room_main",
                    "action": "set_opening",
                    "parameters": {"opening_pct": 20},
                },
            )
        ]
    )

    result = ReplayEngine().replay(log_path)

    assert result.matched is True
    assert result.checked_ticks == 1


def test_world_removes_wall_clock_weather_metadata(tmp_path: Path) -> None:
    log_path = tmp_path / "clock.jsonl"
    engine = SimulationEngine(config=SimulationConfig(seed=13, tick_minutes=5), log_path=log_path)
    engine.reset()
    result = engine.tick([])

    assert result["state"]["outdoor_environment"]["data_updated_at"] == "deterministic-step-5"
