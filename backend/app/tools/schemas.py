from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    message: str
    output: dict[str, Any] = Field(default_factory=dict)


class DeviceControlInput(BaseModel):
    entity_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class DeviceControlOutput(BaseModel):
    success: bool
    message: str
    entity_id: str
    action: str

