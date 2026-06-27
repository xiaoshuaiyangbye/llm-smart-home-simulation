from __future__ import annotations

from typing import Any

from app.schemas.state_schema import SmartHomeState


class EnergyAgent:
    def analyze(self, semantic_result: dict[str, Any], state: SmartHomeState) -> dict[str, Any]:
        active_devices = [
            device
            for device in state.devices
            if (
                (device.device_type == "light" and getattr(device, "is_on", False) and getattr(device, "brightness_pct", 0) > 0)
                or (device.device_type == "ac" and getattr(device, "is_on", False))
                or (device.device_type == "fan" and getattr(device, "is_on", False) and getattr(device, "speed_pct", 0) > 0)
            )
        ]
        unoccupied_rooms = {room.room_id for room in state.rooms if not room.occupancy or room.activity == "away"}
        waste_candidates = [device.entity_id for device in active_devices if device.room in unoccupied_rooms]
        return {
            "agent": "energy_agent",
            "current_power_w": state.energy_metrics.current_power_w,
            "baseline_power_w": state.energy_metrics.baseline_power_w,
            "energy_saving_rate_percent": state.energy_metrics.energy_saving_rate_percent,
            "active_device_count": len(active_devices),
            "waste_candidates": waste_candidates,
            "recommendation": self._recommendation(semantic_result, waste_candidates),
        }

    def _recommendation(self, semantic_result: dict[str, Any], waste_candidates: list[str]) -> str:
        if waste_candidates:
            return "Turn off active energy devices in unoccupied rooms unless the user explicitly requested otherwise."
        if semantic_result.get("intent") == "energy_saving_mode":
            return "Prefer daylight, relaxed AC setpoints, and occupancy-aware shutdown."
        return "No major energy conflict detected before planning."
