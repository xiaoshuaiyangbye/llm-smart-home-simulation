from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.tools.schemas import ToolResult


ToolHandler = Callable[[dict[str, Any]], ToolResult]


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(
                tool_name=name,
                success=False,
                message=f"Tool '{name}' is not registered.",
            )
        return handler(arguments)

    def definitions(self) -> list[ToolDefinition]:
        return [self._definitions[name] for name in sorted(self._definitions)]

