from __future__ import annotations

from typing import Any


class SafetyAgent:
    def review(
        self,
        semantic_result: dict[str, Any],
        plan_result: dict[str, Any],
        knowledge_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        actions = plan_result.get("actions", [])
        issues: list[dict[str, Any]] = []
        blocked_entities: set[str] = set()

        constraints = semantic_result.get("constraints", {}) if isinstance(semantic_result.get("constraints"), dict) else {}
        if constraints.get("avoid_window_opening"):
            for action in actions:
                if _device_type(action) == "window" and _opening_pct(action) > 10:
                    issues.append(
                        {
                            "severity": "high",
                            "entity_id": action.get("entity_id"),
                            "message": "Window opening conflicts with active health or airflow constraints.",
                        }
                    )
                    blocked_entities.add(str(action.get("entity_id")))

        by_room = _actions_by_room(actions)
        for room_id, room_actions in by_room.items():
            ac_cooling = any(_device_type(action) == "ac" and action.get("action") == "turn_on" and action.get("parameters", {}).get("mode") == "cool" for action in room_actions)
            wide_window = any(_device_type(action) == "window" and _opening_pct(action) >= 35 for action in room_actions)
            if ac_cooling and wide_window:
                issues.append(
                    {
                        "severity": "medium",
                        "room": room_id,
                        "message": "Cooling and wide window opening in the same room may waste energy.",
                    }
                )

        reviewed_actions = [
            self._block_action(action, "blocked by safety review")
            if str(action.get("entity_id")) in blocked_entities
            else action
            for action in actions
        ]
        return {
            "agent": "safety_agent",
            "passed": not any(issue["severity"] == "high" for issue in issues),
            "issues": issues,
            "action_count_before": len(actions),
            "action_count_after": len(reviewed_actions),
            "actions": reviewed_actions,
            "knowledge_sources": (knowledge_result or {}).get("used_sources", []),
        }

    def _block_action(self, action: dict[str, Any], reason: str) -> dict[str, Any]:
        device_type = _device_type(action)
        blocked = {**action, "reason": f"{action.get('reason', '')}; {reason}"}
        if device_type == "window":
            blocked["action"] = "set_opening"
            blocked["parameters"] = {"opening_pct": 0}
        return blocked


def _device_type(action: dict[str, Any]) -> str:
    entity_id = str(action.get("entity_id", ""))
    return entity_id.split(".", 1)[0]


def _room_id(action: dict[str, Any]) -> str:
    entity_id = str(action.get("entity_id", ""))
    tail = entity_id.split(".", 1)[-1]
    return tail.removesuffix("_main")


def _opening_pct(action: dict[str, Any]) -> float:
    if action.get("action") == "open":
        return 100.0
    if action.get("action") == "close":
        return 0.0
    parameters = action.get("parameters", {})
    if isinstance(parameters, dict):
        return float(parameters.get("opening_pct", 0))
    return 0.0


def _actions_by_room(actions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        grouped.setdefault(_room_id(action), []).append(action)
    return grouped
