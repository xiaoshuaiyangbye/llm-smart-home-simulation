from datetime import datetime
from typing import Any

from app.schemas.action_schema import DeviceActionRequest
from app.simulation.environment import SmartHomeEnvironment


class ExecutionAgent:
    def execute(self, plan_result: dict[str, Any], environment: SmartHomeEnvironment) -> dict[str, Any]:
        normalized_actions = [
            DeviceActionRequest(
                entity_id=action["entity_id"],
                action=action["action"],
                parameters=action.get("parameters", {}),
            ).model_dump()
            | {"reason": action.get("reason", "")}
            for action in plan_result.get("actions", [])
        ]
        results, final_state = environment.apply_device_actions_batch(normalized_actions)
        return {
            "agent": "execution_agent",
            "executed_at": datetime.now().isoformat(timespec="seconds"),
            "executed_count": sum(1 for item in results if item["success"]),
            "results": results,
            "final_state": final_state.model_dump(),
        }

    def generate_actions(self, planning_result: dict[str, Any]) -> list:
        return planning_result.get("actions", [])

    def summarize(self, actions: list) -> dict[str, Any]:
        return {"agent": "execution_agent", "action_count": len(actions), "action_ids": [action.get("entity_id", "") if isinstance(action, dict) else str(action) for action in actions]}
