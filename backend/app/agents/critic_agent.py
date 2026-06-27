from __future__ import annotations

from typing import Any


class CriticAgent:
    def review(
        self,
        semantic_result: dict[str, Any],
        plan_result: dict[str, Any],
        safety_result: dict[str, Any],
        comfort_result: dict[str, Any],
        energy_result: dict[str, Any],
        knowledge_result: dict[str, Any],
    ) -> dict[str, Any]:
        actions = safety_result.get("actions", plan_result.get("actions", []))
        findings: list[dict[str, Any]] = []
        if not actions and semantic_result.get("intent") not in {"context_update", "occupancy_update"}:
            findings.append({"severity": "medium", "message": "The plan produced no executable actions."})
        if safety_result.get("issues"):
            findings.extend(
                {
                    "severity": issue.get("severity", "low"),
                    "message": f"Safety review: {issue.get('message', '')}",
                }
                for issue in safety_result["issues"]
            )
        if energy_result.get("waste_candidates"):
            findings.append(
                {
                    "severity": "low",
                    "message": f"Energy review found {len(energy_result['waste_candidates'])} active devices in unoccupied rooms.",
                }
            )
        if knowledge_result.get("rag_context", {}).get("match_count", 0) == 0:
            findings.append({"severity": "low", "message": "No RAG knowledge matched this request."})

        needs_revision = any(item["severity"] in {"high", "medium"} for item in findings)
        return {
            "agent": "critic_agent",
            "approved": not any(item["severity"] == "high" for item in findings),
            "needs_revision": needs_revision,
            "findings": findings,
            "final_action_count": len(actions),
            "comfort_recommendation": comfort_result.get("recommendation"),
            "energy_recommendation": energy_result.get("recommendation"),
            "rag_match_count": knowledge_result.get("rag_context", {}).get("match_count", 0),
        }
