from typing import Any

from pydantic import ValidationError

from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.schemas import DeviceControlInput, DeviceControlOutput, ToolResult
from app.world.smart_home_world import SmartHomeWorld


DEVICE_CONTROL_TOOL = "device.control"


def build_default_tool_registry(world: SmartHomeWorld) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name=DEVICE_CONTROL_TOOL,
            description="Apply a validated control action to a virtual smart-home device.",
            input_schema=DeviceControlInput.model_json_schema(),
            output_schema=DeviceControlOutput.model_json_schema(),
        ),
        _build_device_control_handler(world),
    )
    return registry


def _build_device_control_handler(world: SmartHomeWorld):
    def handle(arguments: dict[str, Any]) -> ToolResult:
        try:
            payload = DeviceControlInput.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                tool_name=DEVICE_CONTROL_TOOL,
                success=False,
                message="Invalid device control input.",
                output={"errors": exc.errors()},
            )

        success, message, _before, after = world.apply_device_action(
            entity_id=payload.entity_id,
            action=payload.action,
            parameters=payload.parameters,
        )
        return ToolResult(
            tool_name=DEVICE_CONTROL_TOOL,
            success=success,
            message=message,
            output=DeviceControlOutput(
                success=success,
                message=message,
                entity_id=payload.entity_id,
                action=payload.action,
            ).model_dump()
            | {"state": after.model_dump(mode="json")},
        )

    return handle

