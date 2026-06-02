from typing import Any

from app.agents.llm_client import LLMClient
from app.schemas.state_schema import SmartHomeState


class SemanticAgent:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def parse(
        self,
        user_command: str,
        current_state: SmartHomeState,
        user_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.llm_client.parse_command(user_command, current_state, user_context)
        result["agent"] = "semantic_agent"
        result["user_command"] = user_command
        return result
