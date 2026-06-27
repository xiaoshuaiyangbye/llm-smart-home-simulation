from fastapi.testclient import TestClient

from app.main import app


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
