import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.main import get_runtime
from app.energyplus.contracts import RunRequest
from app.energyplus.routes import create_run
from app.agents.llm_client import RealLLMClient
from app.simulation.environment import get_initial_state


@pytest.mark.parametrize("mode", ["mock", "typo", ""])
def test_online_runtime_rejects_non_real_configuration(monkeypatch, mode):
    monkeypatch.setenv("LLM_MODE", mode)
    with pytest.raises(HTTPException) as error:
        get_runtime(Request({"type": "http", "headers": []}))
    assert error.value.status_code == 503


def test_online_energyplus_rejects_mock_before_job_creation():
    with pytest.raises(HTTPException) as error:
        create_run(RunRequest(controller="harness_mock"), "real-only-test")
    assert error.value.status_code == 400


def test_model_failure_stays_real_and_does_not_return_mock_actions(monkeypatch):
    monkeypatch.setenv("REAL_LLM_API_KEY", "local-test")
    monkeypatch.setenv("REAL_LLM_MAX_RETRIES", "0")
    client = RealLLMClient()

    def unavailable(*args):
        raise OSError("model service unavailable")

    monkeypatch.setattr(client, "_chat_completion", unavailable)
    result = client.parse_command("打开客厅灯", get_initial_state())
    assert result["llm_mode"] == "real"
    assert "model service unavailable" in result["error"]
    assert result["devices"] == []


@pytest.mark.parametrize("whole_home", [False, True])
def test_real_energyplus_semantics_fail_closed_without_mock(monkeypatch, tmp_path, whole_home):
    import io
    import json
    from app.agents.llm_client import MockLLMClient
    from app.energyplus.controllers import Controller
    from app.energyplus.whole_controller import WholeController
    from app.energyplus.spatial import inventory

    def forbidden_mock(*args, **kwargs):
        pytest.fail("Real Harness invoked mock semantics")

    monkeypatch.setattr(MockLLMClient, "parse_command", forbidden_mock)
    monkeypatch.setattr(RealLLMClient, "parse_command", lambda *args, **kwargs: {
        "llm_mode": "real", "error": "real semantic endpoint unavailable"})
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps({
        "output": {"explanation": "test plan", "tool_calls": []}}).encode()))
    request = RunRequest(controller="harness_real")
    room_observation = {"temperature_c": 25, "relative_humidity_pct": 50,
        "total_illuminance_lux": 0, "daylight_lux": 0, "occupants": 1, "co2_ppm": 430}
    observation = {"minute": 0, "outdoor_temperature_c": 25, **room_observation}
    if whole_home:
        _, rooms = inventory()
        bindings = {r["room_id"]: {"devices": r["devices"],
            "capabilities": sorted({d["device_type"] for d in r["devices"]}),
            "exterior_windows": [], "full_lamp_lux": 600} for r in rooms}
        observation["rooms"] = {rid: dict(room_observation) for rid in bindings}
        controller = WholeController(request, tmp_path, bindings)
    else:
        controller = Controller(request, tmp_path)
    with pytest.raises(RuntimeError, match="real semantic endpoint unavailable"):
        controller.propose(observation)
