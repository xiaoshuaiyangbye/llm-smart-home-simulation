from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app, session_store
from app.simulation.environment import SmartHomeEnvironment


def test_repeated_short_steps_advance_the_simulated_clock() -> None:
    environment = SmartHomeEnvironment()
    environment.set_outdoor_environment(weather="cloudy", time_hour=21)

    for _ in range(12):
        state = environment.step(minutes=5, refresh_realtime=False)

    assert state.current_time_step == 60
    assert state.outdoor_environment.time_hour == 22
    assert state.outdoor_environment.time_minute == 0


def test_simulated_clock_preserves_minutes_and_wraps_at_midnight() -> None:
    environment = SmartHomeEnvironment()
    environment.set_outdoor_environment(weather="cloudy", time_hour=23)

    state = environment.step(minutes=75, refresh_realtime=False)

    assert state.outdoor_environment.time_hour == 0
    assert state.outdoor_environment.time_minute == 15


def test_read_endpoints_do_not_mutate_the_resident_environment(monkeypatch) -> None:
    client = TestClient(app)
    session_id = f"pure-read-{uuid4().hex}"
    headers = {"X-Simulation-Session": session_id}
    runtime = session_store.get(session_id)
    with runtime.lock:
        runtime.environment.set_outdoor_environment(weather="cloudy", time_hour=21)
        before = runtime.environment.get_state(refresh_realtime=False).model_dump(mode="json")

    monkeypatch.setattr(
        runtime.task_runner,
        "validate_llm_connection",
        lambda *, current_state: {"success": True, "llm_mode": "mock", "state_step": current_state.current_time_step},
    )
    for path in (
        "/api/state",
        "/api/devices",
        "/api/rooms",
        "/api/energy",
        "/api/comfort",
        "/api/agent/health",
    ):
        assert client.get(path, headers=headers).status_code == 200

    after = runtime.environment.get_state(refresh_realtime=False).model_dump(mode="json")
    assert after == before


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/state/reset", None),
        ("POST", "/api/environment", {"time_hour": 21}),
        ("POST", "/api/simulation/step", {"minutes": 1}),
        ("POST", "/api/autonomy/tick", {"minutes": 1}),
        ("PUT", "/api/presence/current-room", {"current_room_id": "bathroom"}),
        (
            "POST",
            "/api/device/action",
            {"entity_id": "light.living_room_main", "action": "turn_on", "parameters": {}},
        ),
        ("POST", "/api/tasks", {"user_command": "打开客厅灯"}),
        (
            "POST",
            "/api/agent/command",
            {"user_command": "打开客厅灯", "current_room_id": "living_room"},
        ),
        ("PUT", "/api/research/profile", {"preferred_temperature_c": 26}),
        ("PUT", "/api/research/private-memory/attributes", {"attributes": {"note": "test"}}),
        ("PUT", "/api/research/robustness", {"enabled": False, "seed": 42}),
    ],
)
def test_life_simulation_freezes_external_mutation_paths(method, path, payload) -> None:
    client = TestClient(app)
    session_id = f"life-freeze-{uuid4().hex}"
    headers = {"X-Simulation-Session": session_id}
    runtime = session_store.get(session_id)
    runtime.life_simulation.active = True
    try:
        response = client.request(method, path, headers=headers, json=payload)
    finally:
        runtime.life_simulation.active = False

    assert response.status_code == 409
    assert "生活快速仿真运行中" in response.json()["detail"]
