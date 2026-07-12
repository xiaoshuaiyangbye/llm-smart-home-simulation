import hashlib
import json
import random
from pathlib import Path
from typing import Any

from app.agents.structured_agents import (
    CriticDecision,
    ExecutorDecision,
    PlannerDecision,
    StructuredCriticAgent,
    StructuredExecutorAgent,
    StructuredPlannerAgent,
)
from app.config.simulation import SimulationConfig
from app.runtime.events import Event, EventBus
from app.runtime.logging import JsonlSimulationLogger
from app.runtime.state_diff import state_diff
from app.tools.device_tools import build_default_tool_registry
from app.tools.schemas import ToolCall
from app.world.smart_home_world import SmartHomeWorld


class SimulationEngine:
    """Deterministic tick scheduler with event, tool, snapshot, and log support."""

    def __init__(
        self,
        world: SmartHomeWorld | None = None,
        config: SimulationConfig | None = None,
        event_bus: EventBus | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.config = config or SimulationConfig()
        self.random = random.Random(self.config.seed)
        self.world = world or SmartHomeWorld()
        self.event_bus = event_bus or EventBus()
        self.tools = build_default_tool_registry(self.world)
        self.planner_agent = StructuredPlannerAgent()
        self.executor_agent = StructuredExecutorAgent()
        self.critic_agent = StructuredCriticAgent()
        self.tick_index = 0
        self.logger = JsonlSimulationLogger(
            log_path or Path("data/logs/research_simulation.jsonl"),
            run_id=self.config.log_run_id,
        )

    def reset(self) -> dict[str, Any]:
        state = self.world.reset()
        snapshot = state.model_dump(mode="json")
        payload = {
            "seed": self.config.seed,
            "tick_minutes": self.config.tick_minutes,
            "state": snapshot,
            "state_hash": stable_state_hash(snapshot),
        }
        self.logger.write("run_started", self.tick_index, payload)
        self.event_bus.publish(Event("run_started", self.tick_index, payload))
        return payload

    def tick(
        self,
        tool_calls: list[ToolCall] | None = None,
        minutes: int | None = None,
    ) -> dict[str, Any]:
        minutes = minutes or self.config.tick_minutes
        before = self.world.snapshot().model_dump(mode="json")
        calls = tool_calls or []
        self.event_bus.publish(
            Event(
                "tick_started",
                self.tick_index,
                {"minutes": minutes, "before_hash": stable_state_hash(before)},
            )
        )

        tool_results = []
        for call in calls:
            self.event_bus.publish(Event("tool_call_requested", self.tick_index, call.model_dump()))
            result = self.tools.execute(call.tool_name, call.arguments)
            tool_results.append(result.model_dump())
            self.logger.write(
                "tool_call_completed",
                self.tick_index,
                {"call": call.model_dump(), "result": result.model_dump()},
            )
            self.event_bus.publish(Event("tool_call_completed", self.tick_index, result.model_dump()))

        state = self.world.step(minutes=minutes)
        after = state.model_dump(mode="json")
        diff = state_diff(before, after)
        payload = {
            "minutes": minutes,
            "before_hash": stable_state_hash(before),
            "after_hash": stable_state_hash(after),
            "actions": [call.model_dump() for call in calls],
            "tool_results": tool_results,
            "state": after,
            "diff": diff,
        }
        self.logger.write("tick_completed", self.tick_index, payload)
        self.event_bus.publish(Event("state_changed", self.tick_index, {"diff": diff}))
        self.event_bus.publish(Event("tick_completed", self.tick_index, payload))
        self.tick_index += 1
        return payload

    def run_agent_step(
        self,
        semantic_result: dict[str, Any],
        minutes: int | None = None,
    ) -> dict[str, Any]:
        # Persist the structured input before planning so a replay can verify
        # the semantic-to-plan boundary, rather than merely re-applying the
        # actions that happened to be logged afterwards.
        semantic_payload = {
            "semantic_result": semantic_result,
            "semantic_input_sha256": stable_state_hash(semantic_result),
        }
        self.logger.write("agent_semantic_input", self.tick_index, semantic_payload)
        self.event_bus.publish(Event("agent_semantic_input", self.tick_index, semantic_payload))
        planner = self.plan(semantic_result)
        tick_result = self.tick(planner.tool_calls, minutes=minutes)
        executor = self.executor_agent.summarize(planner, tick_result["tool_results"])
        critic = self.critic_agent.review(planner, executor)
        payload = {
            "semantic_input_sha256": semantic_payload["semantic_input_sha256"],
            "planner_sha256": stable_state_hash(planner.model_dump(mode="json")),
            "planner": planner.model_dump(),
            "executor": executor.model_dump(),
            "critic": critic.model_dump(),
            "tick": tick_result,
        }
        self.logger.write("agent_step_completed", self.tick_index - 1, payload)
        self.event_bus.publish(Event("agent_decision_recorded", self.tick_index - 1, payload))
        return payload

    def plan(self, semantic_result: dict[str, Any]) -> PlannerDecision:
        decision = self.planner_agent.plan(semantic_result, self.world.snapshot())
        decision = decision.model_copy(
            update={"plan_id": f"plan-seed-{self.config.seed}-tick-{self.tick_index}"}
        )
        self.logger.write("agent_planned", self.tick_index, decision.model_dump())
        self.event_bus.publish(Event("agent_planned", self.tick_index, decision.model_dump()))
        return decision

    def execute_plan(self, decision: PlannerDecision) -> tuple[ExecutorDecision, CriticDecision]:
        tick_result = self.tick(decision.tool_calls)
        executor = self.executor_agent.summarize(decision, tick_result["tool_results"])
        critic = self.critic_agent.review(decision, executor)
        self.logger.write(
            "agent_executed",
            self.tick_index - 1,
            {"executor": executor.model_dump(), "critic": critic.model_dump()},
        )
        return executor, critic


def stable_state_hash(state: dict[str, Any]) -> str:
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
