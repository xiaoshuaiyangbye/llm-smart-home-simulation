from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any


HEALTH_SIGNALS = {
    "cold": ["感冒", "着凉", "受凉", "鼻塞", "流鼻涕", "打喷嚏", "cold"],
    "fever": ["发烧", "发热", "低烧", "高烧", "体温高", "fever"],
    "cough": ["咳嗽", "咳", "cough"],
    "sore_throat": ["嗓子疼", "喉咙痛", "咽喉痛", "throat"],
    "allergy": ["过敏", "鼻炎", "allergy"],
}

RECOVERY_SIGNALS = ["好了", "恢复了", "康复", "退烧", "不发烧", "没发烧", "不感冒", "感冒好了"]
AIRFLOW_SENSITIVITY_SIGNALS = ["怕风", "不能吹风", "不想吹风", "别吹风", "不要直吹", "怕冷风"]
HOT_SIGNALS = ["很热", "太热", "热", "闷热", "发热", "燥热", "hot"]
COLD_SIGNALS = ["很冷", "太冷", "冷", "怕冷", "cold"]

HOME_CONTROL_SIGNALS = [
    "帮我",
    "调整",
    "调",
    "打开",
    "开启",
    "关闭",
    "关掉",
    "空调",
    "风扇",
    "窗户",
    "窗帘",
    "灯",
    "照明",
    "舒适",
    "舒服",
    "凉快",
    "暖和",
    "处理",
    "turn on",
    "turn off",
    "switch",
    "ac",
    "fan",
    "window",
    "light",
]


class UserContextMemory:
    def __init__(self) -> None:
        self._day_key = self._today_key()
        self._memory = self._new_memory(self._day_key)

    def update(self, user_command: str, current_room_id: str | None = None) -> dict[str, Any]:
        self._ensure_today()
        signals = self._extract_signals(user_command)

        if signals["recovery"]:
            self._memory["health_conditions"] = []
        for condition in signals["health_conditions"]:
            if condition not in self._memory["health_conditions"]:
                self._memory["health_conditions"].append(condition)

        if signals["airflow_sensitive"]:
            self._memory["airflow_sensitive"] = True
        if current_room_id:
            self._memory["latest_room"] = current_room_id

        event = {
            "time": self._now_iso(),
            "room": current_room_id,
            "text": user_command,
            "signals": signals,
        }
        self._memory["recent_events"].append(event)
        self._memory["recent_events"] = self._memory["recent_events"][-20:]

        snapshot = self.snapshot()
        snapshot["current_utterance_signals"] = signals
        snapshot["context_update_only"] = self._is_context_update_only(user_command, signals)
        snapshot["planning_constraints"] = self._build_planning_constraints(signals)
        snapshot["day_summary"] = self._build_day_summary(snapshot)
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        self._ensure_today()
        memory = deepcopy(self._memory)
        memory["planning_constraints"] = self._build_planning_constraints({})
        memory["day_summary"] = self._build_day_summary(memory)
        return memory

    def reset(self) -> dict[str, Any]:
        self._day_key = self._today_key()
        self._memory = self._new_memory(self._day_key)
        return self.snapshot()

    def _extract_signals(self, user_command: str) -> dict[str, Any]:
        text = user_command.lower()
        health_conditions = [
            condition
            for condition, keywords in HEALTH_SIGNALS.items()
            if any(keyword in user_command or keyword in text for keyword in keywords)
        ]
        return {
            "health_conditions": health_conditions,
            "recovery": any(keyword in user_command for keyword in RECOVERY_SIGNALS),
            "airflow_sensitive": any(keyword in user_command for keyword in AIRFLOW_SENSITIVITY_SIGNALS),
            "thermal_feeling": self._thermal_feeling(user_command, text),
        }

    def _thermal_feeling(self, user_command: str, text: str) -> str | None:
        if any(keyword in user_command or keyword in text for keyword in HOT_SIGNALS):
            return "hot"
        if any(keyword in user_command or keyword in text for keyword in COLD_SIGNALS):
            return "cold"
        return None

    def _is_context_update_only(self, user_command: str, signals: dict[str, Any]) -> bool:
        has_profile_signal = bool(
            signals["health_conditions"] or signals["recovery"] or signals["airflow_sensitive"]
        )
        if not has_profile_signal:
            return False
        text = user_command.lower()
        return not any(keyword in user_command or keyword in text for keyword in HOME_CONTROL_SIGNALS)

    def _build_planning_constraints(self, current_signals: dict[str, Any]) -> dict[str, Any]:
        active_conditions = set(self._memory["health_conditions"])
        current_conditions = set(current_signals.get("health_conditions", []))
        effective_conditions = active_conditions | current_conditions
        active_illness = bool(effective_conditions & {"cold", "fever", "cough", "sore_throat"})
        airflow_sensitive = bool(self._memory["airflow_sensitive"] or current_signals.get("airflow_sensitive"))
        thermal_feeling = current_signals.get("thermal_feeling")

        constraints: dict[str, Any] = {}
        if active_illness or airflow_sensitive:
            constraints.update(
                {
                    "health_context_active": True,
                    "active_health_conditions": sorted(effective_conditions),
                    "avoid_window_opening": True,
                    "avoid_strong_fan": True,
                    "fan_speed_limit_pct": 30,
                    "avoid_overcooling": True,
                    "cooling_setpoint_floor_c": 26,
                    "recommended_temperature_c_range": [25, 27],
                    "reason": "用户当天健康/怕风上下文要求避免开窗、强风和过度降温。",
                }
            )
        if thermal_feeling == "hot" and active_illness:
            constraints["subjective_heat_interpretation"] = "possible_fever_or_illness_related_heat"
            constraints["reason"] = "用户有感冒/发烧等上下文，当前说热时优先按可能发热处理，采用温和降温策略。"
        return constraints

    def _build_day_summary(self, snapshot: dict[str, Any]) -> str:
        conditions = snapshot.get("health_conditions", [])
        if not conditions and not snapshot.get("airflow_sensitive"):
            return "当天暂无特殊用户健康或偏好约束。"
        parts = []
        if conditions:
            parts.append(f"健康状态: {', '.join(conditions)}")
        if snapshot.get("airflow_sensitive"):
            parts.append("怕风/避免直吹")
        return "；".join(parts)

    def _ensure_today(self) -> None:
        today = self._today_key()
        if today != self._day_key:
            self._day_key = today
            self._memory = self._new_memory(today)

    def _new_memory(self, day_key: str) -> dict[str, Any]:
        return {
            "day_key": day_key,
            "latest_room": None,
            "health_conditions": [],
            "airflow_sensitive": False,
            "recent_events": [],
        }

    def _today_key(self) -> str:
        return datetime.now(timezone(timedelta(hours=8))).date().isoformat()

    def _now_iso(self) -> str:
        return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
