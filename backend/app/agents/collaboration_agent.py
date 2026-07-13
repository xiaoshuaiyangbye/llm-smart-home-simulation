from __future__ import annotations

from copy import deepcopy
from typing import Any


class CollaborationAgent:
    """Reconciles specialist messages into an executable candidate plan.

    This is deliberately deterministic: it makes the contribution of each
    specialist inspectable and keeps the experimental controller reproducible.
    The orchestrator owns call order, while this agent owns the message-to-plan
    contract and a single bounded critic-revision pass.
    """

    def coordinate(
        self,
        plan_result: dict[str, Any],
        comfort_result: dict[str, Any],
        energy_result: dict[str, Any],
    ) -> dict[str, Any]:
        plan = deepcopy(plan_result)
        actions = list(plan.get("actions", []))
        intent = plan.get("intent", "")
        decisions: list[dict[str, Any]] = []

        # Energy specialists may propose shutdowns only for explicitly
        # energy-oriented modes.  This prevents a background observation from
        # countermanding a direct user request such as "turn on all lights".
        if intent in {"away_mode", "energy_saving_mode"}:
            for entity_id in energy_result.get("waste_candidates", []):
                proposal = self._shutdown_proposal(str(entity_id))
                adopted = self._append_if_not_already_controlled(actions, proposal["action"])
                decisions.append(
                    {
                        "source_agent": "energy_agent",
                        "proposal_id": proposal["proposal_id"],
                        "adopted": adopted,
                        "reason": "added shutdown for an active device in an unoccupied room"
                        if adopted
                        else "planner already controls this device",
                    }
                )

        comfort_gaps = [
            item
            for item in comfort_result.get("rooms", [])
            if float(item.get("temperature_gap", 0)) > 0 or float(item.get("illuminance_gap", 0)) > 0
        ]
        decisions.append(
            {
                "source_agent": "comfort_agent",
                "proposal_id": "comfort-gap-observation",
                "adopted": False,
                "reason": "comfort gaps supplied to the planner and critic",
                "affected_room_count": len(comfort_gaps),
            }
        )

        plan["actions"] = actions
        summary = {
            "agent": "collaboration_agent",
            "phase": "specialist_proposal_reconciliation",
            "proposal_decisions": decisions,
            "action_count_before": len(plan_result.get("actions", [])),
            "action_count_after": len(actions),
        }
        plan["collaboration_context"] = deepcopy(summary)
        return {"plan_result": plan, **summary}

    def apply_critic_revision(
        self,
        plan_result: dict[str, Any],
        critic_result: dict[str, Any],
    ) -> dict[str, Any]:
        plan = deepcopy(plan_result)
        actions = list(plan.get("actions", []))
        decisions: list[dict[str, Any]] = []
        for request in critic_result.get("revision_requests", []):
            action = request.get("action") if isinstance(request, dict) else None
            if not isinstance(action, dict) or not action.get("entity_id"):
                continue
            entity_id = str(action["entity_id"])
            existing_index = next(
                (index for index, existing in enumerate(actions) if str(existing.get("entity_id")) == entity_id),
                None,
            )
            revised_action = {
                **action,
                "reason": f"{action.get('reason', '')}; applied from critic revision".strip("; "),
            }
            if existing_index is None:
                actions.append(revised_action)
                decision = "added"
            elif actions[existing_index] != revised_action:
                actions[existing_index] = revised_action
                decision = "replaced"
            else:
                decision = "already_applied"
            decisions.append(
                {
                    "source_agent": "critic_agent",
                    "request_id": request.get("request_id", "critic-revision"),
                    "entity_id": entity_id,
                    "decision": decision,
                }
            )

        plan["actions"] = actions
        result = {
            "agent": "collaboration_agent",
            "phase": "critic_revision",
            "revision_decisions": decisions,
            "actions_changed": actions != plan_result.get("actions", []),
        }
        plan.setdefault("collaboration_context", {})["critic_revision"] = deepcopy(result)
        return {"plan_result": plan, **result}

    def _shutdown_proposal(self, entity_id: str) -> dict[str, Any]:
        return {
            "proposal_id": f"energy-shutdown-{entity_id}",
            "action": {
                "entity_id": entity_id,
                "action": "turn_off",
                "parameters": {},
                "reason": "energy agent shutdown proposal for an unoccupied room",
            },
        }

    def _append_if_not_already_controlled(self, actions: list[dict[str, Any]], proposal: dict[str, Any]) -> bool:
        if any(str(action.get("entity_id")) == str(proposal["entity_id"]) for action in actions):
            return False
        actions.append(proposal)
        return True
