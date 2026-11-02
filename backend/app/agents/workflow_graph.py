"""Versioned, inspectable workflow contract for the multi-agent controller.

This module deliberately describes the existing center-orchestrated stages.
It is not a decentralized negotiation runtime and does not change agent logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowEdge:
    source: str
    target: str
    condition: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "source": self.source,
            "target": self.target,
            "condition": self.condition,
        }


@dataclass(frozen=True)
class MultiAgentWorkflowGraph:
    version: str
    nodes: tuple[str, ...]
    edges: tuple[WorkflowEdge, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nodes": list(self.nodes),
            "edges": [edge.as_dict() for edge in self.edges],
        }

    def validate_stage_order(self, stages: list[dict[str, Any]]) -> dict[str, Any]:
        observed_nodes = [str(stage.get("agent", "")) for stage in stages]
        known_nodes = set(self.nodes)
        allowed_edges = {(edge.source, edge.target) for edge in self.edges}
        violations: list[str] = []

        for node in observed_nodes:
            if node not in known_nodes:
                violations.append(f"unknown node: {node}")
        for source, target in zip(observed_nodes, observed_nodes[1:]):
            if (source, target) not in allowed_edges:
                violations.append(f"unexpected edge: {source} -> {target}")

        return {"valid": not violations, "violations": violations}


DEFAULT_MULTI_AGENT_WORKFLOW_GRAPH = MultiAgentWorkflowGraph(
    version="multi_agent_workflow_v1",
    nodes=(
        "orchestrator",
        "context_agent",
        "knowledge_agent",
        "semantic_agent",
        "robustness_observation",
        "comfort_agent",
        "energy_agent",
        "planning_agent",
        "collaboration_agent",
        "safety_agent",
        "critic_agent",
        "execution_agent",
        "feedback_agent",
        "personalization_evaluator",
    ),
    edges=(
        WorkflowEdge("orchestrator", "context_agent"),
        WorkflowEdge("context_agent", "knowledge_agent"),
        WorkflowEdge("knowledge_agent", "semantic_agent"),
        WorkflowEdge("semantic_agent", "robustness_observation"),
        WorkflowEdge("robustness_observation", "comfort_agent"),
        WorkflowEdge("comfort_agent", "energy_agent"),
        WorkflowEdge("energy_agent", "planning_agent"),
        WorkflowEdge("planning_agent", "collaboration_agent"),
        WorkflowEdge("collaboration_agent", "safety_agent"),
        WorkflowEdge("safety_agent", "critic_agent"),
        WorkflowEdge("critic_agent", "execution_agent", condition="candidate_approved_or_revised"),
        WorkflowEdge("execution_agent", "feedback_agent"),
        WorkflowEdge("feedback_agent", "personalization_evaluator", condition="objective_evaluation_enabled"),
    ),
)
