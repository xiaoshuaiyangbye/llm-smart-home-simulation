import json

from fastapi.testclient import TestClient

from app.config.simulation import SimulationConfig
from app.main import app
from app.runtime.engine import SimulationEngine
from app.runtime.replay import ReplayEngine


def test_research_run_and_replay_api() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/research/run",
        json={
            "seed": 123,
            "tick_minutes": 5,
            "run_id": "pytest-research-api",
            "semantic_result": {
                "intent": "basic_light_control",
                "room": "living_room",
                "control_goal": "turn_on",
                "targets": {
                    "illuminance_lux_range": [300, 700],
                    "temperature_c_range": [22, 27],
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["executor"]["executed_count"] >= 1

    replay = client.post("/api/research/replay", json={"log_file": payload["log_file"]})
    assert replay.status_code == 200
    assert replay.json()["matched"] is True
    assert replay.json()["checked_plans"] == 1
    assert replay.json()["unverified_plans"] == []


def test_replay_rejects_tampered_semantic_input(tmp_path) -> None:
    log_path = tmp_path / "tampered-semantic.jsonl"
    engine = SimulationEngine(
        config=SimulationConfig(seed=123, tick_minutes=5, log_run_id="tampered-semantic"),
        log_path=log_path,
    )
    engine.reset()
    engine.run_agent_step(
        {
            "intent": "basic_light_control",
            "room": "living_room",
            "control_goal": "turn_on",
            "targets": {"illuminance_lux_range": [300, 700], "temperature_c_range": [22, 27]},
        }
    )

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    semantic_input = next(record for record in records if record["event_type"] == "agent_semantic_input")
    semantic_input["payload"]["semantic_result"]["room"] = "study_room"
    log_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    result = ReplayEngine().replay(log_path)

    assert result.matched is False
    assert result.checked_plans == 0
    assert result.mismatches[0]["reason"] == "semantic input hash mismatch"
