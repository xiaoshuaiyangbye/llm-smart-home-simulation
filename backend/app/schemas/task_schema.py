from pydantic import BaseModel, Field

from typing import Any

from app.schemas.action_schema import AgentOutput
from app.schemas.state_schema import RoomId, SmartHomeState


class TaskRequest(BaseModel):
    user_command: str = Field(min_length=1)
    experiment_id: str = "local-demo"


class TaskResponse(BaseModel):
    experiment_id: str
    user_command: str
    success: bool = True
    agent_output: AgentOutput
    state: SmartHomeState
    error: str | None = None


class AgentCommandRequest(BaseModel):
    user_command: str = Field(min_length=1)
    current_room_id: RoomId | None = None


class AgentCommandResponse(BaseModel):
    success: bool
    semantic_result: dict[str, Any] = Field(default_factory=dict)
    plan_result: dict[str, Any] = Field(default_factory=dict)
    execution_result: dict[str, Any] = Field(default_factory=dict)
    feedback_result: dict[str, Any] = Field(default_factory=dict)
    multi_agent_blackboard: dict[str, Any] = Field(default_factory=dict)
    final_state: SmartHomeState | None = None
    error: str | None = None


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
