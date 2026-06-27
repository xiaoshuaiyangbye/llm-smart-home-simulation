from __future__ import annotations

from typing import Any

from app.schemas.state_schema import SmartHomeState
from app.simulation.thermal_model import calculate_apparent_temperature


class ComfortAgent:
    def analyze(self, semantic_result: dict[str, Any], state: SmartHomeState) -> dict[str, Any]:
        room_id = semantic_result.get("room", "living_room")
        target_rooms = state.rooms if room_id == "all_rooms" else [room for room in state.rooms if room.room_id == room_id]
        targets = semantic_result.get("targets", {}) if isinstance(semantic_result.get("targets"), dict) else {}
        temperature_range = targets.get("temperature_c_range", [18, 30])
        illuminance_range = targets.get("illuminance_lux_range", [0, 1200])
        room_reviews = []
        for room in target_rooms:
            fan = next((device for device in state.devices if device.room == room.room_id and device.device_type == "fan"), None)
            apparent_temperature = calculate_apparent_temperature(room, fan)
            room_reviews.append(
                {
                    "room": room.room_id,
                    "illuminance_lux": room.indoor_illuminance_lux,
                    "apparent_temperature_c": apparent_temperature,
                    "humidity_percent": room.indoor_humidity_percent,
                    "temperature_gap": _range_gap(apparent_temperature, temperature_range),
                    "illuminance_gap": _range_gap(room.indoor_illuminance_lux, illuminance_range),
                }
            )
        return {
            "agent": "comfort_agent",
            "target_room_count": len(room_reviews),
            "targets": targets,
            "rooms": room_reviews,
            "recommendation": self._recommendation(room_reviews),
        }

    def _recommendation(self, room_reviews: list[dict[str, Any]]) -> str:
        if any(item["temperature_gap"] > 0 for item in room_reviews):
            return "Prioritize staged thermal comfort before aggressive device changes."
        if any(item["illuminance_gap"] > 0 for item in room_reviews):
            return "Balance natural daylight and artificial lighting to reach the target lux range."
        return "Current target rooms are already close to requested comfort ranges."


def _range_gap(value: float, target_range: Any) -> float:
    if not isinstance(target_range, list) or len(target_range) != 2:
        return 0.0
    if value < target_range[0]:
        return round(target_range[0] - value, 2)
    if value > target_range[1]:
        return round(value - target_range[1], 2)
    return 0.0
