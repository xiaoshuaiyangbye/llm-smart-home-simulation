from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.state_schema import SmartHomeState


class AgentAction(BaseModel):
    action_id: str
    device_id: str
    action_type: Literal["turn_on", "turn_off", "set_level"]
    value: float | bool | None = None
    reason: str


class AgentOutput(BaseModel):
    semantic_result: dict[str, Any]
    planning_result: dict[str, Any]
    execution_result: dict[str, Any]
    feedback_result: dict[str, Any]
    actions: list[Any]
    multi_agent_blackboard: dict[str, Any] = Field(default_factory=dict)


class PlannedDeviceAction(BaseModel):
    entity_id: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str


class DeviceActionRequest(BaseModel):
    entity_id: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class DeviceActionResponse(BaseModel):
    success: bool
    message: str
    before_state: SmartHomeState
    after_state: SmartHomeState
    action: DeviceActionRequest
    timestamp: str
