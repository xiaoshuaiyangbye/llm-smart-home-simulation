from typing import Any

from app.schemas.state_schema import SmartHomeState
from app.simulation.environment import SmartHomeEnvironment


class SmartHomeWorld:
    """Deterministic facade over the legacy smart-home environment."""

    def __init__(self, environment: SmartHomeEnvironment | None = None) -> None:
        self.environment = environment or SmartHomeEnvironment()

    def reset(self) -> SmartHomeState:
        return self.environment.reset(refresh_realtime=False)

    def snapshot(self) -> SmartHomeState:
        return self.environment.get_state(refresh_realtime=False)

    def step(self, minutes: int) -> SmartHomeState:
        return self.environment.step(minutes=minutes, refresh_realtime=False)

    def apply_device_action(
        self,
        entity_id: str,
        action: str,
        parameters: dict[str, Any] | None = None,
    ) -> tuple[bool, str, SmartHomeState, SmartHomeState]:
        return self.environment.apply_device_action(
            entity_id=entity_id,
            action=action,
            parameters=parameters or {},
        )

