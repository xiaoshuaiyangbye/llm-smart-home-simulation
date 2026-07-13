import json

from fastapi.testclient import TestClient

from app.main import app
from app.agents.collaboration_agent import CollaborationAgent
from app.agents.critic_agent import CriticAgent
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.schemas.task_schema import AgentCommandRequest
from app.simulation.environment import SmartHomeEnvironment


def test_energy_specialist_proposal_becomes_an_executable_plan_action() -> None:
    result = CollaborationAgent().coordinate(
        {"intent": "energy_saving_mode", "actions": []},
        {"rooms": []},
        {"waste_candidates": ["light.bedroom_main"]},
    )

    assert result["action_count_after"] == 1
    assert result["plan_result"]["actions"] == [
        {
            "entity_id": "light.bedroom_main",
            "action": "turn_off",
            "parameters": {},
            "reason": "energy agent shutdown proposal for an unoccupied room",
        }
    ]
    assert result["proposal_decisions"][0]["adopted"] is True


def test_critic_request_revises_window_action_and_is_visible_in_trace() -> None:
    plan = {
        "actions": [
            {"entity_id": "ac.study_room_main", "action": "turn_on", "parameters": {"mode": "cool"}},
            {"entity_id": "window.study_room_main", "action": "set_opening", "parameters": {"opening_pct": 60}},
        ]
    }
    safety = {
        "issues": [
            {
                "severity": "medium",
                "room": "study_room",
                "message": "Cooling and wide window opening in the same room may waste energy.",
            }
        ],
    }
    critic = CriticAgent().review({"intent": "thermal_comfort_control"}, plan, safety, {}, {}, {})
    result = CollaborationAgent().apply_critic_revision(plan, critic)

    assert critic["revision_requests"]
    assert result["actions_changed"] is True
    window = next(action for action in result["plan_result"]["actions"] if action["entity_id"].startswith("window."))
    assert window["parameters"] == {"opening_pct": 10}


def test_runner_records_collaboration_stages_and_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    runner = TaskRunner(SmartHomeEnvironment(), ExperimentLogger(tmp_path))

    response = runner.run_agent_command(AgentCommandRequest(user_command="turn on the living room light"))

    assert response.success is True
    assert "collaboration_agent" in response.multi_agent_blackboard["agent_outputs"]
    context = response.plan_result["multi_agent_context"]
    assert context["collaboration_result"]["phase"] == "specialist_proposal_reconciliation"
    assert context["critic_result"]["revision"]["phase"] == "critic_revision"


def test_agent_command_stream_emits_live_stages_and_completion(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    client = TestClient(app)

    with client.stream("POST", "/api/agent/command/stream", json={"user_command": "turn on the living room light"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: stage" in body
    assert "event: complete" in body
    complete_payload = json.loads(body.split("event: complete\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert complete_payload["success"] is True
