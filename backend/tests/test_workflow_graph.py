from pathlib import Path

from app.agents.workflow_graph import DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH


def test_default_graph_accepts_the_normal_blackboard_stage_order() -> None:
    stages = [{"agent": node} for node in DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.nodes]

    result = DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.validate_stage_order(stages)

    assert result == {"valid": True, "violations": []}


def test_default_graph_rejects_a_trace_that_skips_a_declared_stage() -> None:
    skipped_node = "planning_agent"
    stages = [
        {"agent": node}
        for node in DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.nodes
        if node != skipped_node
    ]

    result = DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.validate_stage_order(stages)

    assert result["valid"] is False
    assert "comfort_agent -> energy_agent" not in result["violations"]
    assert "unexpected edge: energy_agent -> collaboration_agent" in result["violations"]


def test_default_graph_description_is_versioned_and_machine_readable() -> None:
    description = DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.describe()

    assert description["version"] == "multi_agent_workflow_v1"
    assert description["nodes"] == list(DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH.nodes)
    assert {
        "source": "critic_agent",
        "target": "execution_agent",
        "condition": "candidate_approved_or_revised",
    } in description["edges"]


def test_collaboration_documentation_names_the_graph_contract() -> None:
    text = Path("docs/multi_agent_collaboration.md").read_text(encoding="utf-8")

    assert "multi_agent_workflow_v1" in text
    assert "不是去中心化" in text
