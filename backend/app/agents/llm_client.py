import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.schemas.state_schema import SmartHomeState


ALLOWED_INTENTS = {
    "basic_light_control",
    "basic_curtain_control",
    "basic_ac_control",
    "study_mode",
    "movie_mode",
    "sleep_mode",
    "away_mode",
    "energy_saving_mode",
    "thermal_comfort_control",
    "lighting_comfort_control",
}

ROOM_ALIASES = {
    "living_room": ["客厅", "起居室", "living room", "living_room"],
    "bedroom": ["卧室", "睡觉", "睡眠", "bedroom"],
    "study_room": ["书房", "学习", "看书", "阅读", "study", "study room", "study_room"],
    "dining_room": ["餐厅", "吃饭", "用餐", "dining", "dining room", "dining_room"],
    "kitchen": ["厨房", "做饭", "kitchen"],
    "bathroom": ["卫生间", "浴室", "厕所", "bathroom"],
    "laundry": ["洗衣区", "洗衣房", "洗衣", "laundry"],
    "balcony": ["阳台", "balcony"],
    "corridor": ["走廊", "过道", "玄关", "corridor"],
}

ALL_ROOM_MARKERS = [
    "全屋",
    "全家",
    "整个家",
    "家里",
    "家中",
    "屋里",
    "屋内",
    "所有房间",
    "全部房间",
    "每个房间",
    "所有灯",
    "全部灯",
    "所有灯光",
    "全部灯光",
    "所有窗户",
    "全部窗户",
    "所有窗帘",
    "全部窗帘",
    "所有空调",
    "全部空调",
]
TURN_ON_MARKERS = ["打开", "开启", "开灯", "点亮", "亮起来", "turn on", "switch on"]
TURN_OFF_MARKERS = ["关闭", "关掉", "关灯", "熄灭", "全关", "turn off", "switch off"]
LOCATION_UPDATE_MARKERS = ["我现在在", "我在", "现在在", "到了", "来到", "移动到", "走到", "去到", "去", "到"]
CONTROL_KEYWORDS = [
    "打开",
    "开启",
    "关闭",
    "关掉",
    "调",
    "降低",
    "升高",
    "变",
    "热",
    "冷",
    "闷",
    "舒适",
    "凉快",
    "暖和",
    "温度",
    "湿度",
    "灯",
    "照明",
    "光线",
    "亮",
    "暗",
    "窗帘",
    "遮光",
    "空调",
    "风扇",
    "窗户",
    "通风",
    "节能",
    "省电",
    "模式",
    "学习",
    "看书",
    "阅读",
    "写报告",
    "工作",
    "睡觉",
    "睡眠",
    "准备睡觉",
    "观影",
    "电影",
    "看电视",
    "洗澡",
    "洗漱",
    "潮",
    "turn on",
    "turn off",
    "switch",
    "temperature",
    "hot",
    "cold",
    "light",
    "ac",
]

TARGETS_BY_INTENT: dict[str, dict[str, list[float]]] = {
    "study_mode": {"illuminance_lux_range": [300, 500], "temperature_c_range": [24, 26.7]},
    "movie_mode": {"illuminance_lux_range": [100, 200], "temperature_c_range": [24, 27]},
    "sleep_mode": {"illuminance_lux_range": [0, 50], "temperature_c_range": [25, 27.5]},
    "away_mode": {"illuminance_lux_range": [0, 80], "temperature_c_range": [18, 30]},
    "energy_saving_mode": {"illuminance_lux_range": [100, 500], "temperature_c_range": [24, 28]},
    "thermal_comfort_control": {"illuminance_lux_range": [100, 500], "temperature_c_range": [24, 26.7]},
    "lighting_comfort_control": {"illuminance_lux_range": [100, 500], "temperature_c_range": [20, 30]},
    "basic_light_control": {"illuminance_lux_range": [100, 500], "temperature_c_range": [20, 30]},
    "basic_curtain_control": {"illuminance_lux_range": [100, 500], "temperature_c_range": [20, 30]},
    "basic_ac_control": {"illuminance_lux_range": [0, 1200], "temperature_c_range": [24, 26.7]},
}


def get_agent_prompt_template() -> dict[str, Any]:
    return {
        "system_role": (
            "你是智能家居仿真实验平台中的大语言模型智能体，负责把用户自然语言指令"
            "转换为可执行的语义 JSON。"
        ),
        "platform_context": (
            "系统用于在可控、可重复的智能家居仿真环境中验证语义理解、任务规划、"
            "虚拟设备联动以及光热环境闭环控制能力。系统不直接控制真实硬件。"
        ),
        "home_context": {
            "rooms": list(ROOM_ALIASES.keys()),
            "room_names": {
                "living_room": "客厅",
                "bedroom": "卧室",
                "study_room": "书房",
                "dining_room": "餐厅",
                "kitchen": "厨房",
                "bathroom": "卫生间",
                "laundry": "洗衣区",
                "balcony": "阳台",
                "corridor": "走廊",
            },
            "device_types": ["light", "curtain", "ac", "fan", "window"],
            "global_scope_rule": "当用户说全屋、家里、家中、所有房间、所有灯光、全部灯光、所有窗户、全部窗户、所有窗帘、全部窗帘、所有空调、全部空调，或没有指定单个房间但要求窗户/窗帘/空调全部打开/关闭时，room 必须输出 all_rooms，scope 必须输出 all_rooms。",
        },
        "environment_coupling_rules": [
            "窗户和窗帘会共同影响自然采光：窗帘越开、窗户越开，室内自然照度越高，但受天气、室外照度和房间采光系数限制。",
            "窗户打开会加强室内外空气交换，室温会更快向室外温度靠拢，室内湿度也会更快向室外湿度靠拢。",
            "空调开启时开窗会增加冷热负荷和除湿负荷；如果用户要求舒适或节能，应优先协调窗户、窗帘、空调和风扇，而不是孤立控制单个设备。",
            "阴天或雨天打开窗帘/窗户带来的照度提升有限；雨天或室外湿度高时开窗可能降低湿度舒适度。",
        ],
        "output_rule": "必须只输出一个标准 JSON 对象，不要输出 Markdown、代码块、解释文字或思考过程。",
        "required_schema": {
            "intent": sorted(ALLOWED_INTENTS),
            "room": [*ROOM_ALIASES.keys(), "all_rooms"],
            "scope": ["single_room", "all_rooms"],
            "control_goal": ["turn_on", "turn_off", "set_target"],
            "task_type": ["device_control", "scene_control"],
            "targets": {
                "illuminance_lux_range": [0, 1200],
                "temperature_c_range": [18, 30],
            },
            "devices": ["light", "curtain", "ac", "fan", "window"],
            "constraints": {
                "comfort_first": True,
                "energy_saving": False,
            },
        },
        "semantic_examples": [
            {
                "user_command": "家里窗户窗帘全部打开",
                "intent": "basic_curtain_control",
                "room": "all_rooms",
                "scope": "all_rooms",
                "control_goal": "turn_on",
                "task_type": "device_control",
                "devices": ["curtain", "window"],
            },
            {
                "user_command": "把所有窗户都关上",
                "intent": "basic_curtain_control",
                "room": "all_rooms",
                "scope": "all_rooms",
                "control_goal": "turn_off",
                "task_type": "device_control",
                "devices": ["window"],
            },
        ],
    }


class LLMClientProtocol(Protocol):
    def parse_command(
        self,
        user_command: str,
        current_state: SmartHomeState,
        user_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


def _available_room_ids(current_state: SmartHomeState) -> set[str]:
    return {room.room_id for room in current_state.rooms}


def _default_room(current_state: SmartHomeState) -> str:
    for room in current_state.rooms:
        if room.occupancy:
            return room.room_id
    return "living_room"


def _detect_explicit_room_from_text(user_command: str) -> str | None:
    normalized_text = user_command.lower()
    for room_id, aliases in ROOM_ALIASES.items():
        if any(alias.lower() in normalized_text for alias in aliases):
            return room_id
    return None


def _detect_room_from_text(user_command: str, current_state: SmartHomeState) -> str:
    explicit_room = _detect_explicit_room_from_text(user_command)
    if explicit_room:
        return explicit_room
    return _default_room(current_state)


def _detect_scope(user_command: str) -> str:
    return "all_rooms" if any(marker in user_command for marker in ALL_ROOM_MARKERS) else "single_room"


def _detect_control_goal(user_command: str, intent: str) -> str | None:
    normalized_text = user_command.lower()
    if any(marker in user_command for marker in TURN_OFF_MARKERS) or any(marker in normalized_text for marker in TURN_OFF_MARKERS):
        return "turn_off"
    if any(marker in user_command for marker in TURN_ON_MARKERS) or any(marker in normalized_text for marker in TURN_ON_MARKERS):
        return "turn_on"
    if intent == "basic_light_control":
        return "turn_on"
    return None


def _has_away_command(user_command: str) -> bool:
    normalized_text = user_command.lower()
    return any(keyword in user_command for keyword in ["离家", "外出", "出门", "不在家", "上班去了", "去上班"]) or "away" in normalized_text


def _forced_scene_intent_from_text(user_command: str) -> str | None:
    normalized_text = user_command.lower()
    if any(keyword in user_command for keyword in ["睡眠模式", "睡觉", "准备睡觉", "入睡", "休息"]) or "sleep" in normalized_text:
        return "sleep_mode"
    if any(keyword in user_command for keyword in ["学习模式", "学习", "看书", "阅读", "写报告", "工作"]) or "study" in normalized_text:
        return "study_mode"
    if any(keyword in user_command for keyword in ["观影模式", "观影", "电影", "看电视"]) or "movie" in normalized_text:
        return "movie_mode"
    if any(keyword in user_command for keyword in ["节能模式", "省电模式"]) or "energy saving" in normalized_text:
        return "energy_saving_mode"
    return None


def _is_humidity_focused_command(user_command: str) -> bool:
    return any(keyword in user_command for keyword in ["湿度", "潮", "潮湿", "洗澡后", "洗澡"])


def _has_explicit_ac_request(user_command: str) -> bool:
    normalized_text = user_command.lower()
    return "空调" in user_command or "ac" in normalized_text or "air conditioner" in normalized_text


def _forced_basic_device_intent_from_text(user_command: str) -> str | None:
    """Keep unqualified single-device switches from being promoted to a scene."""
    normalized_text = user_command.lower()
    if _forced_scene_intent_from_text(user_command) or _has_away_command(user_command):
        return None
    if any(keyword in user_command for keyword in ["舒适", "节能", "省电", "温度", "湿度", "采光", "光线", "明亮"]):
        return None
    if "空调" in user_command or "ac" in normalized_text or "air conditioner" in normalized_text:
        return "basic_ac_control"
    if "灯" in user_command or "照明" in user_command or "light" in normalized_text:
        return "basic_light_control"
    return None


def _is_transition_or_mild_context(current_state: SmartHomeState) -> bool:
    source = current_state.outdoor_environment.data_updated_at or ""
    if "mild_may_typical_profile" in source:
        return True
    month = _month_from_timestamp(source)
    if month in {4, 5, 10}:
        return True
    return current_state.outdoor_environment.outdoor_temperature_c <= 30


def _month_from_timestamp(value: str) -> int | None:
    if not value:
        return None
    normalized = value.split(";", 1)[0].replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).month
    except ValueError:
        return None


def _adaptive_temperature_range(intent: str) -> list[float]:
    if intent == "sleep_mode":
        return [20.0, 28.0]
    if intent in {"study_mode", "movie_mode", "thermal_comfort_control", "lighting_comfort_control"}:
        return [20.0, 28.5]
    return [18.0, 29.0]


def is_location_update_command(user_command: str) -> bool:
    if not _detect_explicit_room_from_text(user_command):
        return False
    if _forced_scene_intent_from_text(user_command):
        return False
    normalized_text = user_command.lower()
    has_location_marker = any(marker in user_command for marker in LOCATION_UPDATE_MARKERS)
    has_control_keyword = any(keyword in user_command for keyword in CONTROL_KEYWORDS) or any(
        keyword in normalized_text for keyword in CONTROL_KEYWORDS
    )
    return has_location_marker and not has_control_keyword


def _extract_temperature_target(user_command: str) -> list[float] | None:
    match = re.search(r"(\d{1,2}(?:\.\d+)?)\s*(?:度|℃|c|C)", user_command)
    if not match:
        return None
    target = max(16.0, min(32.0, float(match.group(1))))
    return [round(target - 0.5, 1), round(target + 0.5, 1)]


def _devices_for_intent(intent: str) -> list[str]:
    if intent == "basic_light_control":
        return ["light"]
    if intent == "basic_curtain_control":
        return ["curtain"]
    if intent == "basic_ac_control":
        return ["ac"]
    if intent == "lighting_comfort_control":
        return ["light", "curtain"]
    if intent == "thermal_comfort_control":
        return ["light", "curtain", "ac", "fan"]
    if intent == "away_mode":
        return ["light", "curtain", "ac", "fan"]
    return ["light", "curtain", "ac"]


def _detect_opening_devices_from_text(user_command: str) -> list[str]:
    devices: list[str] = []
    if "窗帘" in user_command or "遮光" in user_command:
        devices.append("curtain")
    if "窗户" in user_command or "窗子" in user_command or "通风" in user_command:
        devices.append("window")
    return devices


def _devices_for_command(user_command: str, intent: str, result: dict[str, Any] | None = None) -> list[str]:
    opening_devices = _detect_opening_devices_from_text(user_command)
    if opening_devices:
        return opening_devices

    result_devices = result.get("devices") if isinstance(result, dict) else None
    if isinstance(result_devices, list) and result_devices:
        return [str(device) for device in result_devices]

    return _devices_for_intent(intent)


def _devices_from_result(result: dict[str, Any], intent: str) -> list[str]:
    result_devices = result.get("devices")
    if isinstance(result_devices, list):
        devices = [str(device) for device in result_devices if str(device) in {"light", "curtain", "ac", "fan", "window"}]
        if devices:
            return devices
    return _devices_for_intent(intent)


def _task_type_for_intent(intent: str) -> str:
    return "device_control" if intent.startswith("basic_") else "scene_control"


def _normalize_semantic_result(
    result: dict[str, Any],
    user_command: str,
    current_state: SmartHomeState,
    llm_mode: str,
    user_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intent = result.get("intent")
    if intent not in ALLOWED_INTENTS:
        intent = MockLLMClient.detect_intent(user_command)
    forced_scene_intent = _forced_scene_intent_from_text(user_command)
    if forced_scene_intent:
        intent = forced_scene_intent
    if _has_away_command(user_command):
        intent = "away_mode"
    forced_basic_device_intent = _forced_basic_device_intent_from_text(user_command)
    if forced_basic_device_intent:
        intent = forced_basic_device_intent
    explicit_opening_devices = _detect_opening_devices_from_text(user_command)
    if (
        not forced_basic_device_intent
        and explicit_opening_devices
        and _detect_control_goal(user_command, "basic_curtain_control") in {"turn_on", "turn_off"}
    ):
        intent = "basic_curtain_control"

    detected_scope = _detect_scope(user_command)
    scope = result.get("scope") if result.get("scope") in {"single_room", "all_rooms"} else detected_scope
    if detected_scope == "all_rooms":
        scope = "all_rooms"
    if intent == "away_mode":
        scope = "all_rooms"
    room = result.get("room")
    explicit_room = _detect_explicit_room_from_text(user_command)
    if scope == "all_rooms":
        room = "all_rooms"
    elif explicit_room:
        room = explicit_room
    elif room not in _available_room_ids(current_state):
        room = _default_room(current_state)

    targets = result.get("targets") if isinstance(result.get("targets"), dict) else {}
    normalized_targets = TARGETS_BY_INTENT[intent].copy()
    if not forced_basic_device_intent and isinstance(targets.get("illuminance_lux_range"), list) and len(targets["illuminance_lux_range"]) == 2:
        normalized_targets["illuminance_lux_range"] = [
            float(targets["illuminance_lux_range"][0]),
            float(targets["illuminance_lux_range"][1]),
        ]
    if not forced_basic_device_intent and isinstance(targets.get("temperature_c_range"), list) and len(targets["temperature_c_range"]) == 2:
        normalized_targets["temperature_c_range"] = [
            float(targets["temperature_c_range"][0]),
            float(targets["temperature_c_range"][1]),
        ]

    explicit_temperature = _extract_temperature_target(user_command)
    if explicit_temperature and intent in {"basic_ac_control", "thermal_comfort_control"}:
        normalized_targets["temperature_c_range"] = explicit_temperature
    elif (
        not forced_basic_device_intent
        and
        intent not in {"away_mode", "basic_ac_control"}
        and _is_transition_or_mild_context(current_state)
        and not _has_explicit_ac_request(user_command)
    ):
        normalized_targets["temperature_c_range"] = _adaptive_temperature_range(intent)
    if _is_humidity_focused_command(user_command) and not any(keyword in user_command for keyword in ["热", "冷", "温度"]):
        normalized_targets["temperature_c_range"] = [18, 30]
        normalized_targets["humidity_percent_range"] = [40, 70]

    constraints = result.get("constraints") if isinstance(result.get("constraints"), dict) else {}
    task_type = result.get("task_type") if result.get("task_type") in {"device_control", "scene_control"} else _task_type_for_intent(intent)
    if not intent.startswith("basic_"):
        task_type = "scene_control"
    semantic_result = {
        "intent": intent,
        "room": room,
        "scope": scope,
        "control_goal": (
            _detect_control_goal(user_command, intent) or result.get("control_goal")
            if forced_basic_device_intent
            else result.get("control_goal") or _detect_control_goal(user_command, intent)
        ),
        "task_type": task_type,
        "targets": normalized_targets,
        "devices": _devices_for_command(user_command, intent, result),
        "constraints": {
            "comfort_first": bool(constraints.get("comfort_first", intent not in {"away_mode", "energy_saving_mode"})),
            "energy_saving": bool(constraints.get("energy_saving", intent in {"away_mode", "energy_saving_mode"})),
        },
        "llm_mode": llm_mode,
    }
    semantic_result["prompt_template"] = get_agent_prompt_template()
    semantic_result["prompt_payload_summary"] = _build_prompt_payload_summary(user_command, current_state, user_context)
    return semantic_result


def _build_prompt_payload_summary(
    user_command: str,
    current_state: SmartHomeState,
    user_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "user_command": user_command,
        "room_count": len(current_state.rooms),
        "rooms": [{"room_id": room.room_id, "name": room.name, "occupancy": room.occupancy, "activity": room.activity} for room in current_state.rooms],
        "outdoor_environment": current_state.outdoor_environment.model_dump(),
        "device_count": len([device for device in current_state.devices if device.device_type != "sensor"]),
        "available_device_types": sorted({device.device_type for device in current_state.devices if device.device_type != "sensor"}),
        "user_context_memory": user_context or {},
    }


def _compact_state_for_prompt(current_state: SmartHomeState) -> dict[str, Any]:
    return {
        "rooms": [
            {
                "id": room.room_id,
                "name": room.name,
                "lux": round(room.indoor_illuminance_lux, 1),
                "temp_c": round(room.indoor_temperature_c, 1),
                "humidity": round(room.indoor_humidity_percent, 1),
                "occupied": room.occupancy,
                "activity": room.activity,
            }
            for room in current_state.rooms
        ],
        "outdoor": {
            "weather": current_state.outdoor_environment.weather,
            "hour": current_state.outdoor_environment.time_hour,
            "lux": round(current_state.outdoor_environment.outdoor_illuminance_lux, 1),
            "solar_w_m2": round(current_state.outdoor_environment.solar_radiation_w_m2, 1),
            "temp_c": round(current_state.outdoor_environment.outdoor_temperature_c, 1),
            "humidity": round(current_state.outdoor_environment.outdoor_humidity_percent, 1),
        },
        "devices": [
            _compact_device_for_prompt(device)
            for device in current_state.devices
            if device.device_type != "sensor"
        ],
    }


def _compact_device_for_prompt(device) -> dict[str, Any]:
    payload = {
        "id": device.entity_id,
        "room": device.room,
        "type": device.device_type,
    }
    if device.device_type == "light":
        payload.update({"on": device.is_on, "brightness": round(device.brightness_pct, 1)})
    elif device.device_type == "ac":
        payload.update({"on": device.is_on, "mode": device.mode, "setpoint": round(device.setpoint_c, 1)})
    elif device.device_type == "fan":
        payload.update({"on": device.is_on, "speed": round(device.speed_pct, 1)})
    elif device.device_type in {"curtain", "window"}:
        payload.update({"opening": round(device.opening_pct, 1)})
    return payload


def _compact_user_context_for_prompt(user_context: dict[str, Any] | None) -> dict[str, Any]:
    if not user_context:
        return {}
    keys = [
        "latest_room",
        "day_summary",
        "health_context",
        "planning_constraints",
        "recent_events",
    ]
    return {key: user_context[key] for key in keys if key in user_context}


def _has_complete_json_object(content: str) -> bool:
    start = content.find("{")
    if start < 0:
        return False

    depth = 0
    in_string = False
    escaped = False
    for char in content[start:]:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return True
    return False


class MockLLMClient:
    def parse_command(
        self,
        user_command: str,
        current_state: SmartHomeState,
        user_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        intent = self.detect_intent(user_command)
        scope = _detect_scope(user_command)
        room = "all_rooms" if scope == "all_rooms" else _detect_room_from_text(user_command, current_state)
        targets = TARGETS_BY_INTENT[intent].copy()

        if self._has_light_keyword(user_command) and self._has_thermal_keyword(user_command):
            targets = {
                **targets,
                "illuminance_lux_range": [100, 500],
                "temperature_c_range": [24, 26],
            }

        explicit_temperature = _extract_temperature_target(user_command)
        if explicit_temperature and intent in {"basic_ac_control", "thermal_comfort_control"}:
            targets["temperature_c_range"] = explicit_temperature

        semantic_result = {
            "intent": intent,
            "room": room,
            "scope": scope,
            "control_goal": _detect_control_goal(user_command, intent),
            "task_type": _task_type_for_intent(intent),
            "targets": targets,
            "devices": _devices_for_command(user_command, intent),
            "constraints": {
                "comfort_first": intent not in {"away_mode", "energy_saving_mode"},
                "energy_saving": intent in {"away_mode", "energy_saving_mode"},
            },
            "llm_mode": "mock",
        }
        semantic_result["prompt_template"] = get_agent_prompt_template()
        semantic_result["prompt_payload_summary"] = _build_prompt_payload_summary(user_command, current_state, user_context)
        return semantic_result

    @staticmethod
    def detect_intent(user_command: str) -> str:
        text = user_command.lower()
        if any(keyword in user_command for keyword in ["学习", "看书", "阅读", "写报告"]) or "study" in text:
            return "study_mode"
        if any(keyword in user_command for keyword in ["观影", "电影", "看电视"]) or "movie" in text:
            return "movie_mode"
        if any(keyword in user_command for keyword in ["睡眠", "睡觉", "休息"]) or "sleep" in text:
            return "sleep_mode"
        if _has_away_command(user_command):
            return "away_mode"
        if any(keyword in user_command for keyword in ["节能", "省电", "低能耗"]) or "energy" in text:
            return "energy_saving_mode"
        if any(keyword in user_command for keyword in ["空调"]) and not any(keyword in user_command for keyword in ["温度", "热", "冷", "舒适"]):
            return "basic_ac_control"
        if any(keyword in user_command for keyword in ["窗帘", "遮光"]):
            return "basic_curtain_control"
        if any(keyword in user_command for keyword in ["空调", "温度", "热", "冷", "凉快", "暖和", "舒适"]):
            return "thermal_comfort_control"
        if any(keyword in user_command for keyword in ["灯", "照明", "光线", "亮", "暗"]):
            return "lighting_comfort_control"
        return "basic_light_control"

    def _has_light_keyword(self, user_command: str) -> bool:
        return any(keyword in user_command for keyword in ["灯", "照明", "光线", "亮", "暗"])

    def _has_thermal_keyword(self, user_command: str) -> bool:
        return any(keyword in user_command for keyword in ["空调", "温度", "热", "冷", "凉快", "暖和", "舒适"])


class RealLLMClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("REAL_LLM_API_KEY", "")
        self.base_url = os.getenv("REAL_LLM_BASE_URL", "https://spark-api-open.xf-yun.com/x2").rstrip("/")
        self.model = os.getenv("REAL_LLM_MODEL", "spark-x")
        self.model_revision = os.getenv("REAL_LLM_MODEL_REVISION", "").strip() or None
        self.resource_id = os.getenv("REAL_LLM_RESOURCE_ID", "")
        self.timeout_seconds = float(os.getenv("REAL_LLM_TIMEOUT_SECONDS", "12"))
        self.max_tokens = int(os.getenv("REAL_LLM_MAX_TOKENS", "320"))
        self.max_retries = int(os.getenv("REAL_LLM_MAX_RETRIES", "2"))
        self.stream = os.getenv("REAL_LLM_STREAM", "true").lower() in {"1", "true", "yes", "on"}
        # Keep real semantic runs reproducible when the endpoint supports OpenAI
        # compatible decoding controls (including local Ollama).  The effective
        # values are also retained in every semantic trace and experiment
        # provenance record; a zero temperature alone does not identify the
        # sampling stream.
        self.temperature = float(os.getenv("REAL_LLM_TEMPERATURE", "0.0"))
        self.seed = int(os.getenv("REAL_LLM_SEED", "42"))
        self._last_transport = "openai_compatible"
        self._semantic_cache: dict[str, dict[str, Any]] = {}
        self._raw_semantic_cache: dict[str, dict[str, Any]] = {}

    def parse_command(
        self,
        user_command: str,
        current_state: SmartHomeState,
        user_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key or not self.base_url:
            return self._error("Real LLM API is not configured.")

        prompt = self._build_prompt(user_command, current_state, user_context)
        cache_key = self._cache_key(user_command, current_state, user_context)
        template_cache_key = self._template_cache_key(user_command, current_state, user_context)
        if template_cache_key and template_cache_key in self._raw_semantic_cache:
            parsed = json.loads(json.dumps(self._raw_semantic_cache[template_cache_key], ensure_ascii=False))
            semantic_result = _normalize_semantic_result(parsed, user_command, current_state, "real", user_context)
            semantic_result["llm_metrics"] = {
                "cache_hit": True,
                "prompt_bytes": len(prompt.encode("utf-8")),
                "request_ms": 0.0,
                "stream": self.stream,
                "temperature": self.temperature,
                "seed": self.seed,
                "transport": "cache",
                "thinking_disabled": self._is_local_ollama(),
            }
            return semantic_result
        if cache_key in self._semantic_cache:
            cached = json.loads(json.dumps(self._semantic_cache[cache_key], ensure_ascii=False))
            cached["llm_metrics"] = {
                "cache_hit": True,
                "prompt_bytes": len(prompt.encode("utf-8")),
                "request_ms": 0.0,
                "stream": self.stream,
                "temperature": self.temperature,
                "seed": self.seed,
                "transport": "cache",
                "thinking_disabled": self._is_local_ollama(),
            }
            return cached

        started_at = time.perf_counter()
        metrics = {
            "cache_hit": False,
            "prompt_bytes": len(prompt.encode("utf-8")),
            "request_ms": 0.0,
            "stream": self.stream,
            "temperature": self.temperature,
            "seed": self.seed,
            "attempts": 0,
            "retried": False,
            "transport": "openai_compatible",
            "thinking_disabled": self._is_local_ollama(),
        }
        last_error = ""
        last_content = ""
        total_attempts = max(1, self.max_retries + 1)
        for attempt in range(1, total_attempts + 1):
            metrics["attempts"] = attempt
            metrics["retried"] = attempt > 1
            try:
                attempt_prompt = prompt if attempt == 1 else self._build_retry_prompt(prompt, last_content, last_error)
                content = self._chat_completion(attempt_prompt)
                metrics["transport"] = self._last_transport
                last_content = content
                parsed = self._parse_json_content(content)
                if not isinstance(parsed, dict):
                    last_error = "Real LLM response is not a JSON object."
                    continue
                metrics["request_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
                if template_cache_key:
                    self._raw_semantic_cache[template_cache_key] = parsed
                semantic_result = _normalize_semantic_result(parsed, user_command, current_state, "real", user_context)
                semantic_result["llm_metrics"] = metrics
                self._semantic_cache[cache_key] = semantic_result
                return semantic_result
            except json.JSONDecodeError as exc:
                last_error = f"invalid JSON: {exc}"
            except (HTTPError, URLError, TimeoutError, RuntimeError, OSError) as exc:
                last_error = str(exc)

        metrics["request_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        if last_content:
            metrics["last_response_preview"] = last_content[:240]
        return self._error(f"Real LLM request failed after {metrics['attempts']} attempts: {last_error}", metrics)

    def validate_connection(self, current_state: SmartHomeState) -> dict[str, Any]:
        sample_command = "打开所有灯光"
        result = self.parse_command(sample_command, current_state)
        return {
            "success": "error" not in result,
            "llm_mode": "real",
            "base_url": self.base_url,
            "model": self.model,
            "model_revision": self.model_revision,
            "resource_id": self.resource_id,
            "timeout_seconds": self.timeout_seconds,
            "max_tokens": self.max_tokens,
            "max_retries": self.max_retries,
            "stream": self.stream,
            "temperature": self.temperature,
            "seed": self.seed,
            "sample_command": sample_command,
            "semantic_result": result if "error" not in result else {},
            "error": result.get("error"),
        }

    def _chat_completion(self, prompt: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是智能家居仿真实验平台中的语义理解智能体。"
                    "必须只输出一个符合 RFC 8259 的 JSON 对象，不要输出 Markdown、代码块、解释文字或思考过程。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": self.model,
            "user": "llm-smart-home-simulation",
            "messages": messages,
            "stream": self.stream,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.resource_id:
            headers["lora_id"] = self.resource_id
        if self._is_local_ollama():
            # Qwen3 can otherwise consume its generation budget in hidden
            # reasoning and return an empty assistant content field. Ollama's
            # OpenAI-compatible endpoint documents "none" for this control.
            payload["reasoning_effort"] = "none"

        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if self.stream:
                    content = self._read_streaming_response(response)
                else:
                    response_payload = json.loads(response.read().decode("utf-8"))
                    content = self._content_from_response_payload(response_payload)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP {exc.code}: {error_body}") from exc
        except RuntimeError as exc:
            if self._is_local_ollama() and "Empty" in str(exc):
                return self._ollama_native_completion(messages)
            raise

        self._last_transport = "openai_compatible"
        return content

    def _is_local_ollama(self) -> bool:
        return urlsplit(self.base_url).hostname in {"127.0.0.1", "localhost", "host.docker.internal"}

    def _ollama_native_completion(self, messages: list[dict[str, str]]) -> str:
        parsed = urlsplit(self.base_url)
        base_path = parsed.path.rstrip("/")
        if base_path.endswith("/v1"):
            base_path = base_path[:-3]
        endpoint = urlunsplit((parsed.scheme, parsed.netloc, f"{base_path}/api/chat", "", ""))
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": self.temperature, "seed": self.seed, "num_predict": self.max_tokens},
        }
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        try:
            content = response_payload["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Ollama native response structure: {response_payload}") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Empty Ollama native response content.")
        self._last_transport = "ollama_native_fallback"
        return content

    def _read_streaming_response(self, response) -> str:
        chunks: list[str] = []
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            content = self._content_delta_from_stream_payload(payload)
            if content:
                chunks.append(content)
                current_content = "".join(chunks).strip()
                if _has_complete_json_object(current_content):
                    return current_content

        content = "".join(chunks).strip()
        if not content:
            raise RuntimeError("Empty streaming response content.")
        return content

    def _content_delta_from_stream_payload(self, response_payload: dict[str, Any]) -> str:
        try:
            choice = response_payload["choices"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected streaming response structure: {response_payload}") from exc

        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content", "")
            return content if isinstance(content, str) else ""

        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
        return ""

    def _content_from_response_payload(self, response_payload: dict[str, Any]) -> str:
        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected response structure: {response_payload}") from exc

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Empty response content.")
        return content

    def _build_retry_prompt(self, original_prompt: str, invalid_content: str, error_message: str) -> str:
        return json.dumps(
            {
                "role": "智能家居语义解析智能体 JSON 修复重试。",
                "instruction": "上一次输出不是合法 JSON。请重新解析同一个任务，只输出一个 JSON 对象，不要输出解释、Markdown、代码块或思考过程。",
                "last_error": error_message,
                "last_invalid_response": invalid_content[:500],
                "original_prompt": json.loads(original_prompt),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _cache_key(
        self,
        user_command: str,
        current_state: SmartHomeState,
        user_context: dict[str, Any] | None,
    ) -> str:
        occupied_room = _default_room(current_state)
        health_context = {}
        planning_constraints = {}
        if isinstance(user_context, dict):
            health_context = user_context.get("health_context", {}) if isinstance(user_context.get("health_context"), dict) else {}
            planning_constraints = user_context.get("planning_constraints", {}) if isinstance(user_context.get("planning_constraints"), dict) else {}
        return json.dumps(
            {
                "command": user_command.strip(),
                "occupied_room": occupied_room,
                "health_context": health_context,
                "planning_constraints": planning_constraints,
                "state_signature": self._semantic_cache_state_signature(user_command, current_state),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _template_cache_key(
        self,
        user_command: str,
        current_state: SmartHomeState,
        user_context: dict[str, Any] | None,
    ) -> str | None:
        command_has_stable_target = bool(
            _detect_explicit_room_from_text(user_command)
            or _detect_scope(user_command) == "all_rooms"
            or _has_away_command(user_command)
        )
        if not command_has_stable_target:
            return None

        health_context = {}
        planning_constraints = {}
        if isinstance(user_context, dict):
            health_context = user_context.get("health_context", {}) if isinstance(user_context.get("health_context"), dict) else {}
            planning_constraints = user_context.get("planning_constraints", {}) if isinstance(user_context.get("planning_constraints"), dict) else {}

        return json.dumps(
            {
                "command": user_command.strip(),
                "health_context": health_context,
                "planning_constraints": planning_constraints,
                "state_signature": self._semantic_cache_state_signature(user_command, current_state),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _semantic_cache_state_signature(
        self,
        user_command: str,
        current_state: SmartHomeState,
    ) -> dict[str, Any]:
        room_id = _detect_explicit_room_from_text(user_command) or _default_room(current_state)
        room = next((item for item in current_state.rooms if item.room_id == room_id), None)
        outdoor = current_state.outdoor_environment
        return {
            "room": room_id,
            "weather": outdoor.weather,
            "hour": outdoor.time_hour,
            "outdoor_temp_c": round(outdoor.outdoor_temperature_c, 1),
            "outdoor_humidity": round(outdoor.outdoor_humidity_percent, 1),
            "room_temp_c": round(room.indoor_temperature_c, 1) if room else None,
            "room_humidity": round(room.indoor_humidity_percent, 1) if room else None,
            "room_lux": round(room.indoor_illuminance_lux, 0) if room else None,
        }

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        stripped = re.sub(r"<think>.*?</think>", "", content.strip(), flags=re.IGNORECASE | re.DOTALL).strip()
        candidates = [stripped]
        candidates.extend(match.group(1).strip() for match in re.finditer(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL | re.IGNORECASE))

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        decoder = json.JSONDecoder()
        for candidate in candidates:
            for index, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    parsed, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed

        raise json.JSONDecodeError("No JSON object found in real LLM response.", stripped, 0)

    def _build_prompt(
        self,
        user_command: str,
        current_state: SmartHomeState,
        user_context: dict[str, Any] | None = None,
    ) -> str:
        return json.dumps(
            {
                "role": "智能家居语义解析智能体。只输出一个 JSON 对象。",
                "user_command": user_command,
                "state": _compact_state_for_prompt(current_state),
                "memory": _compact_user_context_for_prompt(user_context),
                "rules": [
                    "输出字段: intent, room, scope, control_goal, task_type, targets, devices, constraints。",
                    "intent/room/scope/control_goal/task_type/devices 只能使用 allowed_values。",
                    "家里/全屋/全部/所有房间/所有灯/所有窗户/所有窗帘/所有空调 => scope=all_rooms, room=all_rooms。",
                    "离家/出门/外出/上班 => intent=away_mode, scope=all_rooms, room=all_rooms。",
                    "同时提到窗户和窗帘时 devices 必须同时包含 window 与 curtain。",
                    "健康记忆存在时避免开窗、强风和过度降温，constraints 标记 health_context_active/avoid_window_opening/avoid_strong_fan/avoid_overcooling。",
                    "舒适/节能/热/冷/闷/潮湿/光线暗要结合天气、室外温湿度、照度、窗户开度、空调状态联动判断。",
                    "空调制冷/制热时不要主动大开窗，除非用户明确要求开窗。",
                ],
                "allowed_values": {
                    "intent": sorted(ALLOWED_INTENTS),
                    "room": [*ROOM_ALIASES.keys(), "all_rooms"],
                    "scope": ["single_room", "all_rooms"],
                    "control_goal": ["turn_on", "turn_off", "set_target"],
                    "task_type": ["device_control", "scene_control"],
                    "device_type": ["light", "curtain", "ac", "fan", "window"],
                },
                "schema_example": {
                    "intent": "study_mode",
                    "room": "study_room",
                    "scope": "single_room",
                    "control_goal": "set_target",
                    "task_type": "scene_control",
                    "targets": {
                        "illuminance_lux_range": [300, 500],
                        "temperature_c_range": [24, 26],
                    },
                    "devices": ["light", "curtain", "ac"],
                    "constraints": {
                        "comfort_first": True,
                        "energy_saving": False,
                    },
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _error(self, message: str, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "intent": "unsupported",
            "room": "living_room",
            "task_type": "error",
            "targets": {},
            "devices": [],
            "constraints": {"comfort_first": False, "energy_saving": False},
            "llm_mode": "real",
            "llm_metrics": metrics or {},
            "error": message,
        }


class LLMClient:
    def __init__(self) -> None:
        try:
            from dotenv import load_dotenv

            backend_root = Path(__file__).resolve().parents[2]
            load_dotenv(backend_root / ".env.local")
            env_path = backend_root / ".env"
            load_dotenv(env_path if env_path.exists() else None)
        except Exception:
            pass
        self.mode = os.getenv("LLM_MODE", "real").lower()
        self.client: LLMClientProtocol = RealLLMClient() if self.mode == "real" else MockLLMClient()

    def parse_command(
        self,
        user_command: str,
        current_state: SmartHomeState,
        user_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.client.parse_command(user_command, current_state, user_context)

    def validate_connection(self, current_state: SmartHomeState) -> dict[str, Any]:
        if self.mode != "real" or not isinstance(self.client, RealLLMClient):
            return {
                "success": False,
                "llm_mode": self.mode,
                "error": "LLM_MODE must be real for connectivity verification.",
            }
        return self.client.validate_connection(current_state)

    def generate_json(self, prompt: str) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "status": "real_llm_required" if self.mode == "real" else "mock_configured",
            "prompt_summary": prompt[:120],
        }
