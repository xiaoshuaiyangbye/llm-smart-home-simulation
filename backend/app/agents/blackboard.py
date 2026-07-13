from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable


class MultiAgentBlackboard:
    def __init__(self, user_command: str, on_stage: Callable[[dict[str, Any]], None] | None = None) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        self.data: dict[str, Any] = {
            "blackboard_id": f"bb-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            "created_at": timestamp,
            "user_command": user_command,
            "stages": [],
            "agent_outputs": {},
            "warnings": [],
            "metrics": {},
        }
        self._on_stage = on_stage

    def add_stage(self, agent: str, output: dict[str, Any]) -> dict[str, Any]:
        output_snapshot = deepcopy(output)
        entry = {
            "agent": agent,
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            "output": output_snapshot,
        }
        self.data["stages"].append(entry)
        self.data["agent_outputs"][agent] = output_snapshot
        if self._on_stage:
            self._on_stage(deepcopy(entry))
        return entry

    def add_warning(self, message: str) -> None:
        self.data["warnings"].append(message)

    def set_metric(self, key: str, value: Any) -> None:
        self.data["metrics"][key] = value

    def snapshot(self) -> dict[str, Any]:
        return self.data
