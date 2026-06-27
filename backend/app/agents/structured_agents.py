from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.agents.planning_agent import PlanningAgent
from app.schemas.state_schema import SmartHomeState
from app.tools.device_tools import DEVICE_CONTROL_TOOL
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolCall


class PlannerDecision(BaseModel):
    agent: Literal["planner_agent"] = "planner_agent"
    intent: str
    room: str
    plan_id: str
    steps: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    rationale: str = ""


class ExecutorDecision(BaseModel):
    agent: Literal["executor_agent"] = "executor_agent"
    plan_id: str
    executed_count: int
    results: list[dict[str, Any]]


class CriticDecision(BaseModel):
    agent: Literal["critic_agent"] = "critic_agent"
    approved: bool
    findings: list[dict[str, Any]] = Field(default_factory=list)


PLANNER_DECISION_ADAPTER = TypeAdapter(PlannerDecision)
EXECUTOR_DECISION_ADAPTER = TypeAdapter(ExecutorDecision)
CRITIC_DECISION_ADAPTER = TypeAdapter(CriticDecision)


class StructuredPlannerAgent:
    def __init__(self) -> None:
        self._legacy_planner = PlanningAgent()

    def plan(self, semantic_result: dict[str, Any], state: SmartHomeState) -> PlannerDecision:
        plan = self._legacy_planner.plan(semantic_result, state)
        calls = [
            ToolCall(
                tool_name=DEVICE_CONTROL_TOOL,
                arguments={
                    "entity_id": action["entity_id"],
                    "action": action["action"],
                    "parameters": action.get("parameters", {}),
                },
                reason=action.get("reason", ""),
            )
            for action in plan.get("actions", [])
        ]
        return PLANNER_DECISION_ADAPTER.validate_python(
            {
                "intent": str(plan.get("intent", semantic_result.get("intent", "unknown"))),
                "room": str(plan.get("room", semantic_result.get("room", "living_room"))),
                "plan_id": str(plan.get("plan_id", "structured-plan")),
                "steps": [call.reason or call.arguments["action"] for call in calls],
                "tool_calls": [call.model_dump() for call in calls],
                "rationale": "Deterministic planner converted the semantic result into tool calls.",
            }
        )


class StructuredExecutorAgent:
    def execute(
        self,
        decision: PlannerDecision,
        tools: ToolRegistry,
    ) -> ExecutorDecision:
        results = [
            tools.execute(call.tool_name, call.arguments).model_dump()
            for call in decision.tool_calls
        ]
        return EXECUTOR_DECISION_ADAPTER.validate_python(
            {
                "plan_id": decision.plan_id,
                "executed_count": sum(1 for item in results if item["success"]),
                "results": results,
            }
        )

    def summarize(
        self,
        decision: PlannerDecision,
        tool_results: list[dict[str, Any]],
    ) -> ExecutorDecision:
        return EXECUTOR_DECISION_ADAPTER.validate_python(
            {
                "plan_id": decision.plan_id,
                "executed_count": sum(1 for item in tool_results if item.get("success")),
                "results": tool_results,
            }
        )


class StructuredCriticAgent:
    def review(
        self,
        planner_decision: PlannerDecision,
        executor_decision: ExecutorDecision,
    ) -> CriticDecision:
        findings = [
            {
                "severity": "high",
                "message": result["message"],
                "tool_name": result["tool_name"],
            }
            for result in executor_decision.results
            if not result.get("success")
        ]
        if not planner_decision.tool_calls:
            findings.append(
                {
                    "severity": "low",
                    "message": "No tool calls were required for this decision.",
                }
            )
        return CRITIC_DECISION_ADAPTER.validate_python(
            {
                "approved": not any(item["severity"] == "high" for item in findings),
                "findings": findings,
            }
        )
