from __future__ import annotations

from typing import Any

from app.research.personalization import UserPreferenceProfile
from app.schemas.state_schema import SmartHomeState


def propose_sensor_driven_decision(
    state: SmartHomeState,
    profile: UserPreferenceProfile,
) -> dict[str, Any]:
    """Turn the current sensor snapshot into one bounded autonomous trigger.

    The priority order is deterministic and intentionally conservative. It
    proposes a normal agent command, so planning, safety review, execution,
    feedback, and reflection still use the same inspectable control path.
    """
    occupied = [room for room in state.rooms if room.occupancy and room.activity != "away"]
    if not occupied:
        active_devices = [
            device.entity_id
            for device in state.devices
            if device.device_type not in {"sensor"} and bool(getattr(device, "is_on", False))
        ]
        if active_devices:
            return {
                "triggered": True,
                "trigger_type": "occupancy",
                "room_id": None,
                "reason": "检测到住宅无人但仍有设备运行。",
                "command": "当前住宅无人，请自主进入离家节能模式并关闭不必要设备。",
                "observed_value": len(active_devices),
                "target": 0,
            }
        return _no_decision("住宅无人且未检测到需要处理的运行设备。")

    room = occupied[0]
    lower_illuminance = profile.preferred_illuminance_lux * 0.75
    if room.indoor_illuminance_lux < lower_illuminance:
        return {
            "triggered": True,
            "trigger_type": "illuminance_low",
            "room_id": room.room_id,
            "reason": "有人房间照度低于该用户个性化照度目标的 75%。",
            "command": f"系统检测到我进入{room.name}且光线不足，请立即开灯并调节到适合当前活动的亮度。",
            "observed_value": room.indoor_illuminance_lux,
            "target": profile.preferred_illuminance_lux,
        }

    lower_temperature = profile.preferred_temperature_c - profile.temperature_tolerance_c
    upper_temperature = profile.preferred_temperature_c + profile.temperature_tolerance_c
    if room.indoor_temperature_c > upper_temperature:
        return {
            "triggered": True,
            "trigger_type": "temperature_high",
            "room_id": room.room_id,
            "reason": "占用房间温度高于该用户的个性化舒适上限。",
            "command": f"系统检测到我在{room.name}且温度偏高，请自主调节到舒适范围。",
            "observed_value": room.indoor_temperature_c,
            "target": [lower_temperature, upper_temperature],
        }
    if room.indoor_temperature_c < lower_temperature:
        return {
            "triggered": True,
            "trigger_type": "temperature_low",
            "room_id": room.room_id,
            "reason": "占用房间温度低于该用户的个性化舒适下限。",
            "command": f"系统检测到我在{room.name}且温度偏低，请自主调节到舒适范围。",
            "observed_value": room.indoor_temperature_c,
            "target": [lower_temperature, upper_temperature],
        }

    humidity_delta = room.indoor_humidity_percent - profile.preferred_humidity_percent
    if abs(humidity_delta) > 10:
        direction = "偏高" if humidity_delta > 0 else "偏低"
        return {
            "triggered": True,
            "trigger_type": "humidity_deviation",
            "room_id": room.room_id,
            "reason": f"占用房间湿度相对个性化目标{direction}超过 10%。",
            "command": f"系统检测到我在{room.name}且湿度{direction}，请自主调节到舒适范围。",
            "observed_value": room.indoor_humidity_percent,
            "target": profile.preferred_humidity_percent,
        }

    return _no_decision("温度、湿度、照度和占用状态均未越过个性化触发阈值。")


def _no_decision(reason: str) -> dict[str, Any]:
    return {
        "triggered": False,
        "trigger_type": "none",
        "room_id": None,
        "reason": reason,
        "command": None,
        "observed_value": None,
        "target": None,
    }
