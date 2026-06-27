from __future__ import annotations

from typing import Any

from app.rag import RagDocumentStore
from app.schemas.state_schema import SmartHomeState


class KnowledgeAgent:
    def __init__(self, rag_store: RagDocumentStore) -> None:
        self.rag_store = rag_store

    def retrieve(
        self,
        user_command: str,
        current_state: SmartHomeState,
        memory_context: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        query = self._build_query(user_command, current_state, memory_context)
        result = self.rag_store.query(query, top_k=top_k)
        return {
            "agent": "knowledge_agent",
            "query": query,
            "rag_context": result,
            "used_sources": [match["source"] for match in result.get("matches", [])],
            "guidance": self._guidance_from_matches(result.get("matches", [])),
        }

    def _build_query(
        self,
        user_command: str,
        current_state: SmartHomeState,
        memory_context: dict[str, Any] | None,
    ) -> str:
        occupied_rooms = [room.room_id for room in current_state.rooms if room.occupancy]
        outdoor = current_state.outdoor_environment
        memory_summary = ""
        if isinstance(memory_context, dict):
            memory_summary = str(memory_context.get("day_summary", ""))
        return " ".join(
            [
                user_command,
                f"occupied_rooms:{','.join(occupied_rooms)}",
                f"weather:{outdoor.weather}",
                f"hour:{outdoor.time_hour}",
                f"outdoor_temp:{outdoor.outdoor_temperature_c}",
                f"outdoor_humidity:{outdoor.outdoor_humidity_percent}",
                memory_summary,
                "comfort energy safety standards devices rooms scenes",
            ]
        )

    def _guidance_from_matches(self, matches: list[dict[str, Any]]) -> list[str]:
        guidance: list[str] = []
        sources = {match.get("source", "") for match in matches}
        if any("standards" in source for source in sources):
            guidance.append("Use configured comfort and humidity ranges as soft simulation targets.")
        if any("devices" in source for source in sources):
            guidance.append("Limit planned actions to virtual devices declared in configuration/state.")
        if any("multi_agent" in source for source in sources):
            guidance.append("Keep semantic, planning, execution, feedback, and review outputs separately inspectable.")
        if any("system_description" in source for source in sources):
            guidance.append("Do not imply real hardware control; this platform is a reproducible simulation sandbox.")
        return guidance
