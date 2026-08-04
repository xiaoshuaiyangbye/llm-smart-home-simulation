from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from app.research import UserPreferenceService
from app.schemas.task_schema import AgentCommandResponse


class ReflectionAgent:
    """Turns a completed control run into durable, inspectable experience."""

    def __init__(self, preference_service: UserPreferenceService) -> None:
        self.preference_service = preference_service

    def reflect(
        self,
        response: AgentCommandResponse,
        *,
        user_command: str,
        trigger: str,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentCommandResponse:
        if not response.success:
            return response
        try:
            reflection = self.preference_service.record_reflection(
                trigger=trigger,
                user_command=user_command,
                semantic_result=response.semantic_result,
                plan_result=response.plan_result,
                execution_result=response.execution_result,
                feedback_result=response.feedback_result,
            )
            reflection = {**reflection, "recorded": True}
        except OSError:
            # A completed device action must not be retried or reported as a
            # control failure solely because its post-action audit record could
            # not be persisted.  The degraded reflection is still observable.
            reflection = {
                "recorded": False,
                "reason": "persistence_failed",
                "learning_policy": "no_experience_update_until_persistence_recovers",
            }
        response.feedback_result["self_reflection"] = reflection
        entry = {
            "agent": "reflection_agent",
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            "output": deepcopy(reflection),
        }
        blackboard = response.multi_agent_blackboard
        if isinstance(blackboard, dict):
            stages = blackboard.setdefault("stages", [])
            if isinstance(stages, list):
                stages.append(entry)
            agent_outputs = blackboard.setdefault("agent_outputs", {})
            if isinstance(agent_outputs, dict):
                agent_outputs["reflection_agent"] = deepcopy(reflection)
            metrics = blackboard.setdefault("metrics", {})
            if isinstance(metrics, dict):
                metrics["reflection_recorded"] = bool(reflection["recorded"])
                metrics["reflection_persistence_failed"] = not bool(reflection["recorded"])
                metrics["private_memory_reflection_count"] = len(
                    self.preference_service.reflections
                )
            response.semantic_result["multi_agent_blackboard"] = deepcopy(blackboard)
            response.plan_result["multi_agent_blackboard"] = deepcopy(blackboard)
            summary = response.feedback_result.setdefault("multi_agent_blackboard_summary", {})
            if isinstance(summary, dict):
                summary["stage_count"] = len(stages) if isinstance(stages, list) else 0
                summary["metrics"] = deepcopy(metrics) if isinstance(metrics, dict) else {}
        if event_callback:
            event_callback(deepcopy(entry))
        return response
