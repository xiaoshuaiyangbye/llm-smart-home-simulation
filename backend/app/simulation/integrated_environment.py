"""Opt-in minute-resolution accounting; legacy environment remains unchanged.

Device batches consume one configured control interval, not one interval per
individual action. Energy uses existing end-of-minute power and rounding.
This is a numerical accounting policy, not a calibrated physical model.
"""
from typing import Any

from app.simulation.environment import SmartHomeEnvironment


class IntegratedSmartHomeEnvironment(SmartHomeEnvironment):
    accounting_version = "minute_integrated_control_clock_v1"

    @staticmethod
    def _duration(minutes: int) -> int:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            raise ValueError("duration must be a non-negative integer number of minutes")
        return minutes

    def step(self, minutes: int = 1, refresh_realtime: bool = True):
        minutes = self._duration(minutes)
        for _ in range(minutes):
            super().step(minutes=1, refresh_realtime=refresh_realtime)
        return self.get_state(refresh_realtime=False)

    def apply_device_actions_batch(self, actions: list[dict[str, Any]], *, dt_minutes: int = 5):
        dt_minutes = self._duration(dt_minutes)
        # Apply device settings instantaneously, then advance one shared clock.
        results, state = super().apply_device_actions_batch(actions, dt_minutes=0)
        if any(result['success'] for result in results):
            state = self.step(dt_minutes, refresh_realtime=False)
        return results, state

    def apply_device_action(self, entity_id: str, action: str, parameters: dict[str, Any]):
        before = self.get_state(refresh_realtime=False)
        results, after = self.apply_device_actions_batch([
            {'entity_id': entity_id, 'action': action, 'parameters': parameters}])
        result = results[0]
        return result['success'], result['message'], before, after
