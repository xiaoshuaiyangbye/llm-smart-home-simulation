import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import pi, sin
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.schemas.state_schema import ActivityType, RoomId, SmartHomeState, WeatherType
from app.schemas.task_schema import AgentCommandRequest
from app.simulation.baseline_policy import plan_conventional_baseline_actions
from app.simulation.environment import SmartHomeEnvironment


MINUTES_PER_DAY = 24 * 60
SICK_DAY_OFFSETS = {8, 9}
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@dataclass(frozen=True)
class SeasonMonth:
    season_id: str
    season_name: str
    month_label: str
    start_date: date
    days: int
    low_temperature_c: float
    high_temperature_c: float
    humidity_base_percent: float
    sunrise_hour: float
    daylight_hours: float
    solar_factor: float
    weather_pattern: list[WeatherType]
    sick_profile: str


@dataclass(frozen=True)
class DayInfo:
    index: int
    month_day: int
    scenario: SeasonMonth
    current_date: date
    day_type: str


@dataclass(frozen=True)
class LifeEvent:
    minute: int
    room_id: RoomId
    activity: str
    activity_type: ActivityType
    command: str
    demand_type: str


@dataclass(frozen=True)
class OutdoorSnapshot:
    weather: WeatherType
    time_hour: int
    outdoor_illuminance_lux: float
    solar_radiation_w_m2: float
    outdoor_temperature_c: float
    outdoor_humidity_percent: float
    source: str


SEASON_MONTHS = [
    SeasonMonth(
        season_id="spring",
        season_name="春季",
        month_label="4月",
        start_date=date(2026, 4, 1),
        days=30,
        low_temperature_c=16.0,
        high_temperature_c=25.0,
        humidity_base_percent=64.0,
        sunrise_hour=5.8,
        daylight_hours=12.8,
        solar_factor=0.86,
        weather_pattern=["cloudy", "sunny", "overcast", "rainy", "cloudy", "sunny", "rainy"],
        sick_profile="春季过敏和轻微咳嗽",
    ),
    SeasonMonth(
        season_id="summer",
        season_name="夏季",
        month_label="7月",
        start_date=date(2026, 7, 1),
        days=30,
        low_temperature_c=29.0,
        high_temperature_c=39.0,
        humidity_base_percent=79.0,
        sunrise_hour=5.1,
        daylight_hours=14.0,
        solar_factor=1.06,
        weather_pattern=["sunny", "sunny", "cloudy", "sunny", "rainy", "overcast", "sunny"],
        sick_profile="夏季低烧且怕冷风",
    ),
    SeasonMonth(
        season_id="autumn",
        season_name="秋季",
        month_label="10月",
        start_date=date(2026, 10, 1),
        days=30,
        low_temperature_c=16.0,
        high_temperature_c=26.0,
        humidity_base_percent=58.0,
        sunrise_hour=6.1,
        daylight_hours=11.5,
        solar_factor=0.82,
        weather_pattern=["sunny", "cloudy", "sunny", "overcast", "cloudy", "rainy", "sunny"],
        sick_profile="秋季感冒和嗓子疼",
    ),
    SeasonMonth(
        season_id="winter",
        season_name="冬季",
        month_label="1月",
        start_date=date(2026, 1, 1),
        days=30,
        low_temperature_c=0.0,
        high_temperature_c=9.0,
        humidity_base_percent=48.0,
        sunrise_hour=7.0,
        daylight_hours=10.2,
        solar_factor=0.62,
        weather_pattern=["sunny", "cloudy", "overcast", "sunny", "cloudy", "rainy", "overcast"],
        sick_profile="冬季感冒发烧且怕冷",
    ),
]


class SeasonalLifeSimulation:
    def __init__(self, months: list[SeasonMonth], output_dir: Path, llm_mode: str) -> None:
        self.months = months
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.environment = SmartHomeEnvironment()
        self.baseline_environment = SmartHomeEnvironment()
        self.runner = TaskRunner(
            environment=self.environment,
            experiment_logger=ExperimentLogger(self.output_dir),
            refresh_realtime=False,
        )
        self.llm_mode = llm_mode
        self.day_infos = _build_day_infos(months)
        self.total_days = len(self.day_infos)
        self.total_minutes = self.total_days * MINUTES_PER_DAY
        self.current_abs_minute = 0
        self.memory_day_index: int | None = None
        self.baseline_energy_kwh = 0.0
        self.event_records: list[dict[str, Any]] = []
        self.hourly_records: list[dict[str, Any]] = []

    def run(self) -> dict[str, Any]:
        self.environment.reset(refresh_realtime=False)
        self.baseline_environment.reset(refresh_realtime=False)
        self.runner.reset_context_memory()
        self._sync_weather(0)
        for day_info in self.day_infos:
            self._reset_memory_for_day(day_info.index)
            for event in _events_for_day(day_info):
                target_abs_minute = day_info.index * MINUTES_PER_DAY + event.minute
                self._advance_to(target_abs_minute)
                self._sync_weather(target_abs_minute)
                self._run_event(day_info, event)
        self._advance_to(self.total_minutes)
        return self._write_outputs()

    def _advance_to(self, target_abs_minute: int) -> None:
        while self.current_abs_minute < target_abs_minute:
            next_hour = ((self.current_abs_minute // 60) + 1) * 60
            next_day = ((self.current_abs_minute // MINUTES_PER_DAY) + 1) * MINUTES_PER_DAY
            step_to = min(target_abs_minute, next_hour, next_day, self.total_minutes)
            minutes = step_to - self.current_abs_minute
            if minutes <= 0:
                break
            self._step_minutes(minutes)
            if self.current_abs_minute % MINUTES_PER_DAY == 0 and self.current_abs_minute < self.total_minutes:
                self._reset_memory_for_day(self.current_abs_minute // MINUTES_PER_DAY)

    def _step_minutes(self, minutes: int) -> None:
        self._apply_conventional_baseline_policy()
        baseline_before = self.baseline_environment.get_state(refresh_realtime=False)
        self.baseline_energy_kwh += baseline_before.energy_metrics.current_power_w * minutes / 60 / 1000

        target_minute = self.current_abs_minute + minutes
        snapshot = self._snapshot_for_abs_minute(target_minute)
        self.environment.step_with_outdoor_snapshot(
            minutes=minutes,
            weather=snapshot.weather,
            time_hour=snapshot.time_hour,
            outdoor_illuminance_lux=snapshot.outdoor_illuminance_lux,
            solar_radiation_w_m2=snapshot.solar_radiation_w_m2,
            outdoor_temperature_c=snapshot.outdoor_temperature_c,
            outdoor_humidity_percent=snapshot.outdoor_humidity_percent,
            data_updated_at=snapshot.source,
        )
        self._apply_agent_maintenance_policy(self._day_info_for_abs_minute(target_minute))
        self.baseline_environment.step_with_outdoor_snapshot(
            minutes=minutes,
            weather=snapshot.weather,
            time_hour=snapshot.time_hour,
            outdoor_illuminance_lux=snapshot.outdoor_illuminance_lux,
            solar_radiation_w_m2=snapshot.solar_radiation_w_m2,
            outdoor_temperature_c=snapshot.outdoor_temperature_c,
            outdoor_humidity_percent=snapshot.outdoor_humidity_percent,
            data_updated_at=snapshot.source,
        )
        self.current_abs_minute = target_minute
        if self.current_abs_minute % 60 == 0:
            self._record_hourly_sample()

    def _run_event(self, day_info: DayInfo, event: LifeEvent) -> None:
        started_at = time.perf_counter()
        state_before = self.environment.get_state(refresh_realtime=False)
        previous_rooms = [
            room.room_id
            for room in state_before.rooms
            if room.occupancy and room.activity != "away" and room.room_id != event.room_id
        ]
        current_room_id = None if event.activity_type == "away" else event.room_id
        response = self.runner.run_agent_command(
            AgentCommandRequest(
                user_command=event.command,
                current_room_id=current_room_id,
            )
        )
        response_time_ms = round((time.perf_counter() - started_at) * 1000, 2)
        state = self.environment.set_away() if event.activity_type == "away" else self.environment.set_current_room(event.room_id, event.activity_type)
        state = self._apply_life_event_safety(event, day_info, previous_rooms)
        baseline_state = self._apply_baseline_event(event)

        feedback_result = response.feedback_result
        if response.success and response.semantic_result:
            feedback_result = self.runner.feedback_agent.evaluate(
                response.semantic_result,
                state,
                revision_round=99,
            )
        llm_metrics = response.semantic_result.get("llm_metrics", {}) if isinstance(response.semantic_result, dict) else {}
        record = {
            **self._base_record(
                state=state,
                baseline_state=baseline_state,
                record_type="event",
                activity=event.activity,
                demand_type=event.demand_type,
                completed=feedback_result.get("completed"),
            ),
            "command": event.command,
            "success": response.success,
            "completed": bool(feedback_result.get("completed", False)),
            "intent": response.semantic_result.get("intent", ""),
            "room": response.semantic_result.get("room", ""),
            "scope": response.semantic_result.get("scope", ""),
            "control_goal": response.semantic_result.get("control_goal", ""),
            "devices": ",".join(str(device) for device in response.semantic_result.get("devices", [])),
            "action_count": len(response.plan_result.get("actions", [])),
            "executed_count": response.execution_result.get("executed_count", 0),
            "response_time_ms": response_time_ms,
            "llm_request_ms": llm_metrics.get("request_ms", ""),
            "llm_prompt_bytes": llm_metrics.get("prompt_bytes", ""),
            "llm_cache_hit": llm_metrics.get("cache_hit", ""),
            "llm_stream": llm_metrics.get("stream", ""),
            "error": response.error or "",
        }
        self.event_records.append(record)

    def _record_hourly_sample(self) -> None:
        state = self.environment.get_state(refresh_realtime=False)
        baseline_state = self.baseline_environment.get_state(refresh_realtime=False)
        self.hourly_records.append(
            {
                **self._base_record(
                    state=state,
                    baseline_state=baseline_state,
                    record_type="hourly",
                    activity="state_sample",
                    demand_type="hourly_state",
                    completed=True,
                ),
                "command": "",
                "success": "",
                "completed": "",
                "intent": "",
                "room": _occupied_room_id(state) or "",
                "scope": "",
                "control_goal": "",
                "devices": "",
                "action_count": 0,
                "executed_count": 0,
                "response_time_ms": 0,
                "llm_request_ms": "",
                "llm_prompt_bytes": "",
                "llm_cache_hit": "",
                "llm_stream": "",
                "error": "",
            }
        )

    def _base_record(
        self,
        *,
        state: SmartHomeState,
        baseline_state: SmartHomeState,
        record_type: str,
        activity: str,
        demand_type: str,
        completed: bool | None,
    ) -> dict[str, Any]:
        day_info = self._day_info_for_abs_minute(self.current_abs_minute)
        occupied_room_id = _occupied_room_id(state) or "away"
        baseline_occupied_room_id = _occupied_room_id(baseline_state) or "away"
        occupied_score = _room_comfort_score(state, occupied_room_id)
        baseline_occupied_score = _room_comfort_score(baseline_state, baseline_occupied_room_id)
        if occupied_room_id == "away":
            occupied_score = None
        if baseline_occupied_room_id == "away":
            baseline_occupied_score = None
        saving = _saving_vs_baseline(self.baseline_energy_kwh, state.energy_metrics.cumulative_energy_kwh)
        satisfaction = _satisfaction_score(occupied_score, saving, completed)
        snapshot = state.outdoor_environment
        return {
            "record_type": record_type,
            "season": day_info.scenario.season_id,
            "season_name": day_info.scenario.season_name,
            "month": day_info.scenario.month_label,
            "date": day_info.current_date.isoformat(),
            "day": day_info.index + 1,
            "month_day": day_info.month_day,
            "weekday": WEEKDAY_NAMES[day_info.current_date.weekday()],
            "day_type": day_info.day_type,
            "abs_minute": self.current_abs_minute,
            "time": _format_time(self.current_abs_minute % MINUTES_PER_DAY),
            "weather": snapshot.weather,
            "outdoor_temperature_c": snapshot.outdoor_temperature_c,
            "outdoor_humidity_percent": snapshot.outdoor_humidity_percent,
            "outdoor_illuminance_lux": snapshot.outdoor_illuminance_lux,
            "solar_radiation_w_m2": snapshot.solar_radiation_w_m2,
            "activity": activity,
            "demand_type": demand_type,
            "occupied_room": occupied_room_id,
            "baseline_occupied_room": baseline_occupied_room_id,
            "current_power_w": state.energy_metrics.current_power_w,
            "baseline_power_w": baseline_state.energy_metrics.current_power_w,
            "agent_cumulative_energy_kwh": state.energy_metrics.cumulative_energy_kwh,
            "baseline_cumulative_energy_kwh": round(self.baseline_energy_kwh, 5),
            "energy_saving_vs_baseline_percent": saving,
            "average_overall_comfort": state.comfort_metrics.average_overall_score,
            "average_thermal_comfort": state.comfort_metrics.average_thermal_score,
            "average_lighting_comfort": state.comfort_metrics.average_lighting_score,
            "average_humidity_comfort": state.comfort_metrics.average_humidity_score,
            "occupied_overall_comfort": "" if occupied_score is None else occupied_score,
            "baseline_occupied_overall_comfort": "" if baseline_occupied_score is None else baseline_occupied_score,
            "comfortable_room_count": state.comfort_metrics.comfortable_room_count,
            "resident_satisfaction_score": satisfaction,
            "active_device_count": _active_device_count(state),
            "baseline_active_device_count": _active_device_count(baseline_state),
        }

    def _apply_baseline_event(self, event: LifeEvent) -> SmartHomeState:
        if event.activity_type == "away":
            self.baseline_environment.set_away()
        else:
            self.baseline_environment.set_current_room(event.room_id, event.activity_type)
        return self._apply_conventional_baseline_policy()

    def _apply_conventional_baseline_policy(self) -> SmartHomeState:
        actions = plan_conventional_baseline_actions(
            self.baseline_environment.get_state(refresh_realtime=False)
        )
        if actions:
            self.baseline_environment.apply_device_actions_batch(actions, dt_minutes=1)
        return self.baseline_environment.get_state(refresh_realtime=False)

    def _apply_life_event_safety(
        self,
        event: LifeEvent,
        day_info: DayInfo,
        previous_rooms: list[str],
    ) -> SmartHomeState:
        state = self.environment.get_state(refresh_realtime=False)
        actions: list[dict[str, Any]] = []
        if event.activity_type == "away":
            actions.extend(_away_safety_actions(state))
        elif event.activity_type == "sleep":
            actions.extend(_vacated_room_shutdown_actions(state, keep_room_id=event.room_id))
            actions.extend(_sleep_safety_actions(state, event.room_id, day_info.day_type == "sick_day"))
        else:
            actions.extend(_vacated_room_shutdown_actions(state, keep_room_id=event.room_id, room_ids=previous_rooms))
        if day_info.day_type == "sick_day":
            actions.extend(_health_safety_actions(state, event.room_id))
        if actions:
            self.environment.apply_device_actions_batch(actions, dt_minutes=1)
        return self._apply_agent_maintenance_policy(day_info)

    def _apply_agent_maintenance_policy(self, day_info: DayInfo) -> SmartHomeState:
        state = self.environment.get_state(refresh_realtime=False)
        actions = _agent_maintenance_actions(state, day_info.day_type == "sick_day")
        if actions:
            self.environment.apply_device_actions_batch(actions, dt_minutes=0)
        return self.environment.get_state(refresh_realtime=False)

    def _sync_weather(self, abs_minute: int) -> None:
        snapshot = self._snapshot_for_abs_minute(abs_minute)
        for environment in [self.environment, self.baseline_environment]:
            environment.set_outdoor_snapshot(
                weather=snapshot.weather,
                time_hour=snapshot.time_hour,
                outdoor_illuminance_lux=snapshot.outdoor_illuminance_lux,
                solar_radiation_w_m2=snapshot.solar_radiation_w_m2,
                outdoor_temperature_c=snapshot.outdoor_temperature_c,
                outdoor_humidity_percent=snapshot.outdoor_humidity_percent,
                data_updated_at=snapshot.source,
            )

    def _snapshot_for_abs_minute(self, abs_minute: int) -> OutdoorSnapshot:
        day_info = self._day_info_for_abs_minute(abs_minute)
        hour = (abs_minute % MINUTES_PER_DAY) // 60
        return _seasonal_snapshot(day_info, hour)

    def _day_info_for_abs_minute(self, abs_minute: int) -> DayInfo:
        day_index = min(self.total_days - 1, max(0, abs_minute // MINUTES_PER_DAY))
        return self.day_infos[day_index]

    def _reset_memory_for_day(self, day_index: int) -> None:
        if self.memory_day_index == day_index:
            return
        self.runner.reset_context_memory()
        self.memory_day_index = day_index

    def _build_summary(self) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        daily_metrics = self._build_daily_metrics()
        season_metrics = _group_metrics(daily_metrics, "season", "season_name")
        day_type_metrics = _group_metrics(daily_metrics, "day_type", "day_type")
        final_state = self.environment.get_state(refresh_realtime=False)
        summary = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "llm_mode": self.llm_mode,
            "months": [month.month_label for month in self.months],
            "total_days": self.total_days,
            "simulated_month_count": len(self.months),
            "hourly_sample_count": len(self.hourly_records),
            "event_count": len(self.event_records),
            "workday_count": sum(1 for item in self.day_infos if item.day_type == "workday"),
            "weekend_count": sum(1 for item in self.day_infos if item.day_type == "weekend"),
            "sick_day_count": sum(1 for item in self.day_infos if item.day_type == "sick_day"),
            "task_success_rate_percent": _rate(self.event_records, "success"),
            "task_completion_rate_percent": _rate(self.event_records, "completed"),
            "agent_energy_kwh": round(final_state.energy_metrics.cumulative_energy_kwh, 5),
            "baseline_energy_kwh": round(self.baseline_energy_kwh, 5),
            "energy_saving_vs_baseline_percent": _saving_vs_baseline(
                self.baseline_energy_kwh,
                final_state.energy_metrics.cumulative_energy_kwh,
            ),
            "average_power_w": _average_power_from_energy(final_state.energy_metrics.cumulative_energy_kwh, self.total_minutes),
            "average_baseline_power_w": _average_power_from_energy(self.baseline_energy_kwh, self.total_minutes),
            "average_outdoor_temperature_c": _mean_field(self.hourly_records, "outdoor_temperature_c"),
            "average_outdoor_humidity_percent": _mean_field(self.hourly_records, "outdoor_humidity_percent"),
            "average_overall_comfort": _mean_field(self.hourly_records, "average_overall_comfort"),
            "average_occupied_comfort": _mean_field(self.hourly_records, "occupied_overall_comfort"),
            "average_baseline_occupied_comfort": _mean_field(self.hourly_records, "baseline_occupied_overall_comfort"),
            "comfortable_hour_rate_percent": _comfortable_hour_rate(self.hourly_records),
            "average_satisfaction_score": _mean_field(self.hourly_records + self.event_records, "resident_satisfaction_score"),
            "average_response_time_ms": _mean_field(self.event_records, "response_time_ms"),
            "baseline_definition": "独立并行粗放人工基线：使用相同四季天气、工作日/周末/生病日生活轨迹和房间占用，但按固定人工习惯控制灯光、窗帘、窗户、空调和风扇，不读取智能体调节后的状态。",
            "season_metrics": season_metrics,
            "day_type_metrics": day_type_metrics,
        }
        return summary, daily_metrics, season_metrics, day_type_metrics

    def _build_daily_metrics(self) -> list[dict[str, Any]]:
        all_records = sorted(self.hourly_records + self.event_records, key=lambda record: int(record.get("abs_minute", 0)))
        daily_metrics: list[dict[str, Any]] = []
        for day_info in self.day_infos:
            day = day_info.index + 1
            day_hourly = [record for record in self.hourly_records if int(record["day"]) == day]
            day_events = [record for record in self.event_records if int(record["day"]) == day]
            agent_energy = _day_energy_delta(all_records, day, "agent_cumulative_energy_kwh")
            baseline_energy = _day_energy_delta(all_records, day, "baseline_cumulative_energy_kwh")
            daily_metrics.append(
                {
                    "season": day_info.scenario.season_id,
                    "season_name": day_info.scenario.season_name,
                    "month": day_info.scenario.month_label,
                    "date": day_info.current_date.isoformat(),
                    "day": day,
                    "month_day": day_info.month_day,
                    "weekday": WEEKDAY_NAMES[day_info.current_date.weekday()],
                    "day_type": day_info.day_type,
                    "event_count": len(day_events),
                    "agent_energy_kwh": round(agent_energy, 5),
                    "baseline_energy_kwh": round(baseline_energy, 5),
                    "energy_saving_vs_baseline_percent": _saving_vs_baseline(baseline_energy, agent_energy),
                    "average_power_w": _average_power_from_energy(agent_energy, MINUTES_PER_DAY),
                    "average_baseline_power_w": _average_power_from_energy(baseline_energy, MINUTES_PER_DAY),
                    "average_outdoor_temperature_c": _mean_field(day_hourly, "outdoor_temperature_c"),
                    "average_outdoor_humidity_percent": _mean_field(day_hourly, "outdoor_humidity_percent"),
                    "average_occupied_comfort": _mean_field(day_hourly, "occupied_overall_comfort"),
                    "average_baseline_occupied_comfort": _mean_field(day_hourly, "baseline_occupied_overall_comfort"),
                    "comfortable_hour_rate_percent": _comfortable_hour_rate(day_hourly),
                    "average_satisfaction_score": _mean_field(day_hourly + day_events, "resident_satisfaction_score"),
                    "task_completion_rate_percent": _rate(day_events, "completed"),
                    "task_success_rate_percent": _rate(day_events, "success"),
                }
            )
        return daily_metrics

    def _write_outputs(self) -> dict[str, Any]:
        summary, daily_metrics, season_metrics, day_type_metrics = self._build_summary()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.output_dir / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        event_csv = run_dir / f"seasonal_life_events_{timestamp}.csv"
        hourly_csv = run_dir / f"seasonal_life_hourly_{timestamp}.csv"
        daily_csv = run_dir / f"seasonal_life_daily_{timestamp}.csv"
        season_csv = run_dir / f"seasonal_life_season_metrics_{timestamp}.csv"
        day_type_csv = run_dir / f"seasonal_life_day_type_metrics_{timestamp}.csv"
        summary_json = run_dir / f"seasonal_life_summary_{timestamp}.json"
        report_md = run_dir / f"seasonal_life_report_{timestamp}.md"
        _write_csv(event_csv, self.event_records)
        _write_csv(hourly_csv, self.hourly_records)
        _write_csv(daily_csv, daily_metrics)
        _write_csv(season_csv, season_metrics)
        _write_csv(day_type_csv, day_type_metrics)
        output_paths = {
            "event_csv": str(event_csv),
            "hourly_csv": str(hourly_csv),
            "daily_csv": str(daily_csv),
            "season_csv": str(season_csv),
            "day_type_csv": str(day_type_csv),
            "summary_json": str(summary_json),
            "report_md": str(report_md),
        }
        summary["output_paths"] = output_paths
        summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        report_md.write_text(_render_report(summary, season_metrics, day_type_metrics, output_paths), encoding="utf-8")
        return {
            "summary": summary,
            "output_paths": output_paths,
        }


def _build_day_infos(months: list[SeasonMonth]) -> list[DayInfo]:
    day_infos: list[DayInfo] = []
    for scenario in months:
        for offset in range(scenario.days):
            current_date = scenario.start_date + timedelta(days=offset)
            if offset in SICK_DAY_OFFSETS:
                day_type = "sick_day"
            elif current_date.weekday() >= 5:
                day_type = "weekend"
            else:
                day_type = "workday"
            day_infos.append(
                DayInfo(
                    index=len(day_infos),
                    month_day=offset + 1,
                    scenario=scenario,
                    current_date=current_date,
                    day_type=day_type,
                )
            )
    return day_infos


def _events_for_day(day_info: DayInfo) -> list[LifeEvent]:
    if day_info.day_type == "sick_day":
        return _sick_day_events(day_info)
    if day_info.day_type == "weekend":
        return _weekend_events(day_info)
    return _workday_events(day_info)


def _workday_events(day_info: DayInfo) -> list[LifeEvent]:
    return [
        _event(0, "bedroom", "睡眠", "sleep", "我在卧室睡觉，请保持睡眠模式", "sleep"),
        _event(6 * 60 + 35, "bedroom", "起床", "idle", _wake_command(day_info), "wake"),
        _event(6 * 60 + 55, "bathroom", "洗漱", "idle", "我在卫生间洗漱，灯光明亮一点，湿度别太高", "wash"),
        _event(7 * 60 + 20, "kitchen", "做早餐", "idle", _kitchen_command(day_info, "早餐"), "cooking"),
        _event(7 * 60 + 45, "dining_room", "早餐", "idle", "我在餐厅吃早饭，保持用餐舒适和适当照明", "meal"),
        _event(8 * 60 + 30, "corridor", "离家上班", "away", "我要出门上班了，家里进入离家节能模式", "away_to_work"),
        _event(18 * 60 + 20, "living_room", "下班回家", "idle", _return_home_command(day_info), "return_home"),
        _event(19 * 60, "dining_room", "晚餐", "idle", "我在餐厅吃晚饭，光线和温度都调到舒服", "meal"),
        _event(20 * 60, "study_room", "阅读学习", "study", _study_command(day_info), "study"),
        _event(22 * 60 + 10, "bathroom", "洗澡", "idle", "我在卫生间洗澡后有点潮，帮我把湿度处理到舒适", "shower"),
        _event(22 * 60 + 45, "bedroom", "睡眠", "sleep", _sleep_command(day_info), "sleep"),
    ]


def _weekend_events(day_info: DayInfo) -> list[LifeEvent]:
    return [
        _event(0, "bedroom", "睡眠", "sleep", "周末我在卧室睡觉，请保持睡眠模式", "sleep"),
        _event(8 * 60 + 20, "bedroom", "自然醒", "idle", _wake_command(day_info), "weekend_wake"),
        _event(9 * 60, "kitchen", "做早餐", "idle", _kitchen_command(day_info, "早午餐"), "cooking"),
        _event(10 * 60, "living_room", "周末休息", "idle", _weekend_rest_command(day_info), "weekend_rest"),
        _event(12 * 60 + 15, "dining_room", "午餐", "idle", "我在餐厅吃午饭，保持用餐照明和温度舒适", "meal"),
        _event(14 * 60, "laundry", "洗衣晾衣", "idle", "我在洗衣区洗衣晾衣，保持通风但别太潮", "laundry"),
        _event(16 * 60, "study_room", "阅读整理", "study", _study_command(day_info), "reading"),
        _event(18 * 60 + 30, "kitchen", "做晚餐", "idle", _kitchen_command(day_info, "晚餐"), "cooking"),
        _event(20 * 60, "living_room", "观影", "movie", "我在客厅看电影，请进入观影模式，灯光暗一点且温度舒适", "movie"),
        _event(22 * 60 + 20, "bathroom", "洗澡", "idle", "我在卫生间洗澡后有点潮，帮我处理到舒适", "shower"),
        _event(23 * 60, "bedroom", "睡眠", "sleep", _sleep_command(day_info), "sleep"),
    ]


def _sick_day_events(day_info: DayInfo) -> list[LifeEvent]:
    profile = day_info.scenario.sick_profile
    recovery_text = "晚上感觉好多了，但仍然不要强风直吹" if day_info.month_day == 10 else "今天请假在家，需要全天温和舒适"
    return [
        _event(0, "bedroom", "病中睡眠", "sleep", "我身体不舒服，在卧室睡觉，请保持安静和睡眠模式", "sick_sleep"),
        _event(8 * 60, "bedroom", "病中起床", "idle", f"我今天{profile}，{recovery_text}，卧室保持温和舒适，避免开窗太大和强风直吹", "sick_health"),
        _event(9 * 60 + 30, "living_room", "客厅休息", "idle", _sick_rest_command(day_info), "sick_rest"),
        _event(11 * 60 + 45, "dining_room", "清淡午餐", "idle", "我身体不舒服，在餐厅吃点清淡的，灯光柔和，温度舒服", "sick_meal"),
        _event(13 * 60, "bedroom", "午休", "sleep", "我想午休一会儿，卧室暗一些，温度保持舒适，不要直吹", "sick_nap"),
        _event(16 * 60, "living_room", "恢复休息", "idle", _sick_ventilation_command(day_info), "sick_recovery"),
        _event(18 * 60, "dining_room", "晚餐", "idle", "我还在恢复，在餐厅吃晚饭，保持柔和照明和舒适温度", "sick_meal"),
        _event(20 * 60, "bedroom", "病中阅读", "study", "我在卧室看一会儿资料，光线柔和一点，温度不要忽冷忽热", "sick_reading"),
        _event(22 * 60, "bedroom", "提前睡觉", "sleep", "我准备早点睡，还是有点不舒服，请保持睡眠模式并避免过冷过热", "sick_sleep"),
    ]


def _event(
    minute: int,
    room_id: RoomId,
    activity: str,
    activity_type: ActivityType,
    command: str,
    demand_type: str,
) -> LifeEvent:
    return LifeEvent(
        minute=minute,
        room_id=room_id,
        activity=activity,
        activity_type=activity_type,
        command=command,
        demand_type=demand_type,
    )


def _wake_command(day_info: DayInfo) -> str:
    if day_info.scenario.season_id == "winter":
        return "我醒了，卧室有点冷，灯光柔和一点，温度暖和但不要太耗电"
    if day_info.scenario.season_id == "summer":
        return "我醒了，卧室有点闷热，灯光柔和一点，优先舒适和节能"
    return "我醒了，卧室有点暗，温度保持舒适，灯光柔和一点"


def _kitchen_command(day_info: DayInfo, meal: str) -> str:
    if day_info.scenario.season_id == "summer":
        return f"我在厨房做{meal}，有点热，保持明亮并注意通风降温"
    if day_info.scenario.season_id == "winter":
        return f"我在厨房做{meal}，保持明亮，温度别太冷，通风适度"
    return f"我在厨房做{meal}，保持明亮、通风和舒适"


def _return_home_command(day_info: DayInfo) -> str:
    if day_info.scenario.season_id == "summer":
        return "我下班回家了，客厅很闷热，帮我降温但避免浪费电"
    if day_info.scenario.season_id == "winter":
        return "我下班回家了，客厅有点冷，帮我调暖和但注意节能"
    if day_info.scenario.season_id == "spring":
        return "我下班回家了，客厅有点闷，优先自然通风和舒适照明"
    return "我下班回家了，客厅光线有点暗，温度保持舒适"


def _study_command(day_info: DayInfo) -> str:
    if day_info.scenario.season_id == "winter":
        return "我在书房写报告，光线要适合阅读，温度保持暖和舒适"
    if day_info.scenario.season_id == "summer":
        return "我在书房写报告，光线适合阅读，温度凉快但不要过冷"
    return "我在书房写报告，请把光线和温度调到适合阅读写作"


def _weekend_rest_command(day_info: DayInfo) -> str:
    if day_info.scenario.season_id == "summer":
        return "周末我在客厅休息，待在家时间比较长，保持凉快舒适但尽量省电"
    if day_info.scenario.season_id == "winter":
        return "周末我在客厅休息，保持暖和舒适，同时不要让空调一直高负荷运行"
    return "周末我在客厅休息，家里保持节能但别不舒服"


def _sleep_command(day_info: DayInfo) -> str:
    if day_info.scenario.season_id == "summer":
        return "我要睡觉了，卧室进入睡眠模式，避免过冷和强风直吹"
    if day_info.scenario.season_id == "winter":
        return "我要睡觉了，卧室进入睡眠模式，保持不冷但不要过热"
    return "我要睡觉了，请把卧室调到睡眠模式"


def _sick_rest_command(day_info: DayInfo) -> str:
    if day_info.scenario.season_id == "summer":
        return "我有点发烧，在客厅休息，感觉热但不要把空调开得太低，也不要强风直吹"
    if day_info.scenario.season_id == "winter":
        return "我感冒发烧，在客厅休息，怕冷，帮我保持暖和和柔和照明"
    if day_info.scenario.season_id == "spring":
        return "我有点过敏咳嗽，在客厅休息，保持空气舒服，但不要大风直吹"
    return "我感冒嗓子疼，在客厅休息，温度稳定一点，避免强风直吹"


def _sick_ventilation_command(day_info: DayInfo) -> str:
    if day_info.scenario.season_id == "winter":
        return "我想稍微换气但还怕冷，窗户不要开太大，保持温暖舒适"
    if day_info.scenario.season_id == "summer":
        return "我还在低烧，想舒服一点，优先温和降温，避免过度降温和强风"
    return "我还在咳嗽，想稍微通风但不要直吹，湿度和温度保持舒适"


def _seasonal_snapshot(day_info: DayInfo, hour: int) -> OutdoorSnapshot:
    scenario = day_info.scenario
    weather = scenario.weather_pattern[(day_info.month_day - 1) % len(scenario.weather_pattern)]
    daylight = _daylight_factor(hour, scenario.sunrise_hour, scenario.daylight_hours)
    weather_light_factor = {
        "sunny": 1.0,
        "cloudy": 0.66,
        "overcast": 0.38,
        "rainy": 0.22,
    }[weather]
    weather_temp_offset = {
        "sunny": 1.2,
        "cloudy": 0.0,
        "overcast": -1.0,
        "rainy": -2.2,
    }[weather]
    weather_humidity_offset = {
        "sunny": -7.0,
        "cloudy": 0.0,
        "overcast": 6.0,
        "rainy": 14.0,
    }[weather]
    temperature_curve = max(0.0, sin(pi * (hour - 5) / 14))
    multi_day_variation = 1.6 * sin(2 * pi * ((day_info.month_day - 1) % 10) / 10)
    low = scenario.low_temperature_c + weather_temp_offset + multi_day_variation
    high = scenario.high_temperature_c + weather_temp_offset + multi_day_variation
    outdoor_temperature = low + (high - low) * temperature_curve
    humidity_night_bonus = (1.0 - daylight) * 8.0
    humidity = scenario.humidity_base_percent + weather_humidity_offset + humidity_night_bonus - temperature_curve * 4.0
    outdoor_illuminance = 80000 * daylight * weather_light_factor * scenario.solar_factor
    solar_radiation = 900 * daylight * weather_light_factor * scenario.solar_factor
    source = f"{day_info.current_date.isoformat()}T{hour:02d}:00:00+08:00;seasonal_{scenario.season_id}_synthetic_profile"
    return OutdoorSnapshot(
        weather=weather,
        time_hour=hour,
        outdoor_illuminance_lux=round(outdoor_illuminance, 2),
        solar_radiation_w_m2=round(solar_radiation, 2),
        outdoor_temperature_c=round(outdoor_temperature, 2),
        outdoor_humidity_percent=round(max(25.0, min(96.0, humidity)), 2),
        source=source,
    )


def _daylight_factor(hour: int, sunrise_hour: float, daylight_hours: float) -> float:
    if hour < sunrise_hour or hour > sunrise_hour + daylight_hours:
        return 0.0
    return max(0.0, sin(pi * (hour - sunrise_hour) / daylight_hours))


def _agent_maintenance_actions(state: SmartHomeState, sick_day: bool) -> list[dict[str, Any]]:
    occupied_room_id = _occupied_room_id(state)
    if occupied_room_id is None:
        return _away_safety_actions(state)
    occupied = next(room for room in state.rooms if room.room_id == occupied_room_id)
    if occupied.activity == "away":
        return _away_safety_actions(state)
    actions = _vacated_room_shutdown_actions(state, keep_room_id=occupied_room_id)
    actions.extend(_occupied_room_maintenance_actions(state, occupied_room_id, occupied.activity, sick_day))
    return actions


def _occupied_room_maintenance_actions(
    state: SmartHomeState,
    room_id: str,
    activity: str,
    sick_day: bool,
) -> list[dict[str, Any]]:
    room = next((item for item in state.rooms if item.room_id == room_id), None)
    if room is None:
        return []
    actions: list[dict[str, Any]] = []
    light = _device_in_room(state, room_id, "light")
    ac = _device_in_room(state, room_id, "ac")
    fan = _device_in_room(state, room_id, "fan")
    window = _device_in_room(state, room_id, "window")

    if light and getattr(light, "is_on", False):
        target_brightness = 45 if activity == "study" else 40
        if activity == "movie":
            target_brightness = 20
        if room.room_id in {"kitchen", "bathroom"}:
            target_brightness = 55
        if room.indoor_illuminance_lux >= 350 and getattr(light, "brightness_pct", 0) > target_brightness:
            actions.append(_action_dict(light.entity_id, "set_brightness", {"brightness_pct": target_brightness}, "seasonal simulation maintenance: reduce lighting after target illuminance is reached"))

    if fan and getattr(fan, "is_on", False):
        if sick_day and getattr(fan, "speed_pct", 0) > 30:
            actions.append(_action_dict(fan.entity_id, "set_speed", {"speed_pct": 30}, "seasonal simulation health maintenance: avoid strong airflow"))
        elif room.indoor_temperature_c <= 26.7:
            actions.append(_action_dict(fan.entity_id, "turn_off", {}, "seasonal simulation maintenance: stop fan after thermal comfort is reached"))
        elif room.indoor_temperature_c <= 27.8 and getattr(fan, "speed_pct", 0) > 35:
            actions.append(_action_dict(fan.entity_id, "set_speed", {"speed_pct": 35}, "seasonal simulation maintenance: reduce fan speed in comfort band"))

    if window and sick_day and getattr(window, "opening_pct", 0) > 15:
        actions.append(_action_dict(window.entity_id, "set_opening", {"opening_pct": 10}, "seasonal simulation health maintenance: limit window opening while sick"))

    if ac and getattr(ac, "is_on", False):
        mode = getattr(ac, "mode", "")
        setpoint = getattr(ac, "setpoint_c", 25)
        if mode == "cool":
            floor = 26.0 if sick_day else 25.5
            if setpoint < floor:
                actions.append(_action_dict(ac.entity_id, "set_temperature", {"setpoint_c": floor}, "seasonal simulation maintenance: avoid overcooling"))
            elif room.indoor_temperature_c <= floor - 0.2:
                actions.append(_action_dict(ac.entity_id, "turn_off", {}, "seasonal simulation maintenance: stop cooling after comfort is reached"))
            elif room.indoor_temperature_c <= 26.8 and setpoint < 27:
                actions.append(_action_dict(ac.entity_id, "set_temperature", {"setpoint_c": 27}, "seasonal simulation maintenance: relax cooling setpoint in comfort band"))
        elif mode == "heat":
            upper = 24.5 if sick_day else 24.0
            relaxed = 23.5 if sick_day else 23.0
            if room.indoor_temperature_c >= upper:
                actions.append(_action_dict(ac.entity_id, "turn_off", {}, "seasonal simulation maintenance: stop heating after comfort is reached"))
            elif room.indoor_temperature_c >= relaxed and setpoint > relaxed:
                actions.append(_action_dict(ac.entity_id, "set_temperature", {"setpoint_c": relaxed}, "seasonal simulation maintenance: relax heating setpoint in comfort band"))
    elif ac and sick_day and room.indoor_temperature_c < 21.0:
        actions.append(_action_dict(ac.entity_id, "turn_on", {"mode": "heat", "setpoint_c": 23.0}, "seasonal simulation health maintenance: keep sick resident warm"))

    return actions


def _apply_opening_health_limit(action: dict[str, Any]) -> dict[str, Any]:
    if action.get("action") != "set_opening":
        return action
    parameters = action.get("parameters", {})
    if not isinstance(parameters, dict):
        return action
    if float(parameters.get("opening_pct", 0)) > 15:
        action = {**action, "parameters": {**parameters, "opening_pct": 10}}
    return action


def _health_safety_actions(state: SmartHomeState, room_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    fan = _device_in_room(state, room_id, "fan")
    window = _device_in_room(state, room_id, "window")
    ac = _device_in_room(state, room_id, "ac")
    if fan and getattr(fan, "is_on", False) and getattr(fan, "speed_pct", 0) > 30:
        actions.append(_action_dict(fan.entity_id, "set_speed", {"speed_pct": 30}, "seasonal simulation health safety: limit fan speed"))
    if window and getattr(window, "opening_pct", 0) > 15:
        actions.append(_action_dict(window.entity_id, "set_opening", {"opening_pct": 10}, "seasonal simulation health safety: avoid strong drafts"))
    if ac and getattr(ac, "is_on", False) and getattr(ac, "mode", "") == "cool" and getattr(ac, "setpoint_c", 30) < 26:
        actions.append(_action_dict(ac.entity_id, "set_temperature", {"setpoint_c": 26}, "seasonal simulation health safety: avoid overcooling"))
    return [_apply_opening_health_limit(action) for action in actions]


def _away_safety_actions(state: SmartHomeState) -> list[dict[str, Any]]:
    actions = _vacated_room_shutdown_actions(state, keep_room_id=None)
    hot_sunny = state.outdoor_environment.weather == "sunny" and state.outdoor_environment.outdoor_temperature_c >= 29
    cold_day = state.outdoor_environment.outdoor_temperature_c <= 8
    for device in state.devices:
        if device.device_type == "curtain":
            target = 30 if hot_sunny else 55 if cold_day else 45
            if abs(device.opening_pct - target) > 2:
                actions.append(_action_dict(device.entity_id, "set_opening", {"opening_pct": target}, "seasonal simulation away safety: adjust solar gain"))
        elif device.device_type == "window":
            target = 5 if state.outdoor_environment.weather == "rainy" or cold_day else 12
            if device.opening_pct > target:
                actions.append(_action_dict(device.entity_id, "set_opening", {"opening_pct": target}, "seasonal simulation away safety: limit ventilation while away"))
    return actions


def _sleep_safety_actions(state: SmartHomeState, sleep_room_id: str, sick_day: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    room = next((item for item in state.rooms if item.room_id == sleep_room_id), None)
    for device in state.devices:
        if device.room != sleep_room_id:
            continue
        if device.device_type == "light" and getattr(device, "is_on", False):
            actions.append(_action_dict(device.entity_id, "turn_off", {}, "seasonal simulation sleep safety: lights off"))
        elif device.device_type == "fan" and getattr(device, "is_on", False):
            target = 20 if room and room.indoor_temperature_c > 28.5 and not sick_day else 0
            action = "turn_off" if target == 0 else "set_speed"
            parameters = {} if target == 0 else {"speed_pct": target}
            actions.append(_action_dict(device.entity_id, action, parameters, "seasonal simulation sleep safety: quiet airflow"))
        elif device.device_type == "window":
            target = 5 if sick_day or state.outdoor_environment.weather == "rainy" else 12
            if getattr(device, "opening_pct", 0) > target:
                actions.append(_action_dict(device.entity_id, "set_opening", {"opening_pct": target}, "seasonal simulation sleep safety: quiet ventilation"))
        elif device.device_type == "curtain" and getattr(device, "opening_pct", 100) > 12:
            actions.append(_action_dict(device.entity_id, "set_opening", {"opening_pct": 10}, "seasonal simulation sleep safety: darken room"))
        elif device.device_type == "ac" and getattr(device, "is_on", False):
            if getattr(device, "mode", "") == "cool" and getattr(device, "setpoint_c", 30) < (26 if sick_day else 25.5):
                actions.append(_action_dict(device.entity_id, "set_temperature", {"setpoint_c": 26 if sick_day else 25.5}, "seasonal simulation sleep safety: avoid overcooling"))
            elif getattr(device, "mode", "") == "heat" and room and room.indoor_temperature_c >= (24.5 if sick_day else 24.0):
                actions.append(_action_dict(device.entity_id, "turn_off", {}, "seasonal simulation sleep safety: avoid overheating"))
    return actions


def _vacated_room_shutdown_actions(
    state: SmartHomeState,
    *,
    keep_room_id: str | None,
    room_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    target_rooms = set(room_ids or [])
    if not target_rooms:
        target_rooms = {
            room.room_id
            for room in state.rooms
            if room.room_id != keep_room_id and not room.occupancy
        }
    actions: list[dict[str, Any]] = []
    for device in state.devices:
        if keep_room_id is not None and device.room == keep_room_id:
            continue
        if device.room not in target_rooms:
            continue
        if device.device_type == "light" and getattr(device, "is_on", False) and getattr(device, "brightness_pct", 0) > 0:
            actions.append(_action_dict(device.entity_id, "turn_off", {}, "seasonal simulation safety: turn off vacated-room light"))
        elif device.device_type == "ac" and getattr(device, "is_on", False):
            actions.append(_action_dict(device.entity_id, "turn_off", {}, "seasonal simulation safety: turn off vacated-room AC"))
        elif device.device_type == "fan" and getattr(device, "is_on", False) and getattr(device, "speed_pct", 0) > 0:
            actions.append(_action_dict(device.entity_id, "turn_off", {}, "seasonal simulation safety: turn off vacated-room fan"))
    return actions


def _device_in_room(state: SmartHomeState, room_id: str, device_type: str):
    return next((device for device in state.devices if device.room == room_id and device.device_type == device_type), None)


def _action_dict(entity_id: str, action: str, parameters: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "action": action,
        "parameters": parameters,
        "reason": reason,
    }


def _occupied_room_id(state: SmartHomeState) -> str | None:
    occupied = next((room for room in state.rooms if room.occupancy), None)
    return occupied.room_id if occupied else None


def _room_comfort_score(state: SmartHomeState, room_id: str) -> float | None:
    for room in state.comfort_metrics.rooms:
        if room.room_id == room_id:
            return room.overall_comfort_score
    return None


def _active_device_count(state: SmartHomeState) -> int:
    count = 0
    for device in state.devices:
        if device.device_type in {"sensor", "curtain", "window"}:
            continue
        if getattr(device, "is_on", False):
            count += 1
    return count


def _satisfaction_score(
    occupied_comfort: float | None,
    energy_saving_percent: float,
    completed: bool | None,
) -> float:
    saving_score = max(0.0, min(100.0, 50.0 + energy_saving_percent / 2))
    completion_score = 100.0 if completed is not False else 40.0
    if occupied_comfort is None:
        if completed is None:
            return round(saving_score, 2)
        return round(completion_score * 0.45 + saving_score * 0.55, 2)
    if completed is None:
        return round(occupied_comfort * 0.72 + saving_score * 0.28, 2)
    return round(occupied_comfort * 0.62 + completion_score * 0.2 + saving_score * 0.18, 2)


def _group_metrics(rows: list[dict[str, Any]], key: str, label_key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[key]), []).append(row)
    result: list[dict[str, Any]] = []
    for group_key, items in groups.items():
        agent_energy = sum(float(item["agent_energy_kwh"]) for item in items)
        baseline_energy = sum(float(item["baseline_energy_kwh"]) for item in items)
        result.append(
            {
                key: group_key,
                label_key: items[0].get(label_key, group_key),
                "day_count": len(items),
                "event_count": sum(int(item["event_count"]) for item in items),
                "agent_energy_kwh": round(agent_energy, 5),
                "baseline_energy_kwh": round(baseline_energy, 5),
                "energy_saving_vs_baseline_percent": _saving_vs_baseline(baseline_energy, agent_energy),
                "average_power_w": _average_power_from_energy(agent_energy, len(items) * MINUTES_PER_DAY),
                "average_baseline_power_w": _average_power_from_energy(baseline_energy, len(items) * MINUTES_PER_DAY),
                "average_outdoor_temperature_c": _mean_field(items, "average_outdoor_temperature_c"),
                "average_outdoor_humidity_percent": _mean_field(items, "average_outdoor_humidity_percent"),
                "average_occupied_comfort": _mean_field(items, "average_occupied_comfort"),
                "average_baseline_occupied_comfort": _mean_field(items, "average_baseline_occupied_comfort"),
                "comfortable_hour_rate_percent": _mean_field(items, "comfortable_hour_rate_percent"),
                "average_satisfaction_score": _mean_field(items, "average_satisfaction_score"),
                "task_completion_rate_percent": _mean_field(items, "task_completion_rate_percent"),
                "task_success_rate_percent": _mean_field(items, "task_success_rate_percent"),
            }
        )
    return result


def _day_energy_delta(records: list[dict[str, Any]], day: int, field: str) -> float:
    start_minute = (day - 1) * MINUTES_PER_DAY
    end_minute = day * MINUTES_PER_DAY
    before_or_at_start = [
        record
        for record in records
        if int(record.get("abs_minute", 0)) <= start_minute and record.get(field) not in {"", None}
    ]
    within_day = [
        record
        for record in records
        if start_minute <= int(record.get("abs_minute", 0)) <= end_minute and record.get(field) not in {"", None}
    ]
    if not within_day:
        return 0.0
    start_value = float(before_or_at_start[-1][field]) if before_or_at_start else 0.0
    end_value = float(within_day[-1][field])
    return max(0.0, end_value - start_value)


def _saving_vs_baseline(baseline_energy_kwh: float, agent_energy_kwh: float) -> float:
    if baseline_energy_kwh <= 0:
        return 0.0
    return round((baseline_energy_kwh - agent_energy_kwh) / baseline_energy_kwh * 100, 2)


def _average_power_from_energy(energy_kwh: float, minutes: int) -> float:
    if minutes <= 0:
        return 0.0
    return round(energy_kwh * 1000 * 60 / minutes, 2)


def _mean_field(records: list[dict[str, Any]], field: str) -> float:
    values = [float(record[field]) for record in records if record.get(field) not in {"", None}]
    return round(mean(values), 2) if values else 0.0


def _rate(records: list[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    return round(sum(1 for record in records if record.get(field) is True) / len(records) * 100, 2)


def _comfortable_hour_rate(records: list[dict[str, Any]]) -> float:
    values = [float(record["occupied_overall_comfort"]) for record in records if record.get("occupied_overall_comfort") not in {"", None}]
    if not values:
        return 0.0
    return round(sum(1 for value in values if value >= 80) / len(values) * 100, 2)


def _format_time(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _render_report(
    summary: dict[str, Any],
    season_metrics: list[dict[str, Any]],
    day_type_metrics: list[dict[str, Any]],
    output_paths: dict[str, str],
) -> str:
    strongest_energy = max(season_metrics, key=lambda item: float(item["agent_energy_kwh"]))
    lowest_energy = min(season_metrics, key=lambda item: float(item["agent_energy_kwh"]))
    day_type_by_key = {item["day_type"]: item for item in day_type_metrics}
    lines = [
        "# 四季四个月智能家居生活仿真数据分析",
        "",
        f"- 生成时间：{summary['generated_at']}",
        f"- 语义模式：`{summary['llm_mode']}`",
        f"- 仿真范围：{summary['simulated_month_count']} 个代表月份，共 {summary['total_days']} 天",
        f"- 生活轨迹：工作日上班、周末居家休息、每月 2 天生病/恢复需求",
        "",
        "## 数据文件",
        "",
    ]
    for label, path in [
        ("事件日志", output_paths["event_csv"]),
        ("小时日志", output_paths["hourly_csv"]),
        ("每日汇总", output_paths["daily_csv"]),
        ("四季汇总", output_paths["season_csv"]),
        ("日类型汇总", output_paths["day_type_csv"]),
        ("摘要 JSON", output_paths["summary_json"]),
    ]:
        lines.append(f"- {label}: `{path}`")

    lines.extend(
        [
            "",
            "## 总体结果",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| 事件数 | {summary['event_count']} |",
            f"| 小时样本数 | {summary['hourly_sample_count']} |",
            f"| 工作日 / 周末 / 生病日 | {summary['workday_count']} / {summary['weekend_count']} / {summary['sick_day_count']} |",
            f"| 任务成功率 | {summary['task_success_rate_percent']:.2f}% |",
            f"| 任务完成率 | {summary['task_completion_rate_percent']:.2f}% |",
            f"| 智能体总能耗 | {summary['agent_energy_kwh']:.5f} kWh |",
            f"| 人工基线总能耗 | {summary['baseline_energy_kwh']:.5f} kWh |",
            f"| 相对基线节能率 | {summary['energy_saving_vs_baseline_percent']:.2f}% |",
            f"| 人所在房间平均舒适度 | {summary['average_occupied_comfort']:.2f} |",
            f"| 人工基线人所在房间舒适度 | {summary['average_baseline_occupied_comfort']:.2f} |",
            f"| 舒适小时占比 | {summary['comfortable_hour_rate_percent']:.2f}% |",
            f"| 居住满意度 | {summary['average_satisfaction_score']:.2f} |",
            "",
            "## 四季对比",
            "",
            "| 季节 | 天数 | 平均室外温度 C | 智能体能耗 kWh | 人工基线 kWh | 节能率 | 人在房间舒适度 | 满意度 | 完成率 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in season_metrics:
        lines.append(
            f"| {item['season_name']} | {item['day_count']} | {item['average_outdoor_temperature_c']:.2f} | "
            f"{item['agent_energy_kwh']:.5f} | {item['baseline_energy_kwh']:.5f} | "
            f"{item['energy_saving_vs_baseline_percent']:.2f}% | {item['average_occupied_comfort']:.2f} | "
            f"{item['average_satisfaction_score']:.2f} | {item['task_completion_rate_percent']:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## 生活状态对比",
            "",
            "| 日类型 | 天数 | 事件数 | 智能体能耗 kWh | 平均功率 W | 人在房间舒适度 | 满意度 | 完成率 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in day_type_metrics:
        lines.append(
            f"| {_day_type_label(item['day_type'])} | {item['day_count']} | {item['event_count']} | "
            f"{item['agent_energy_kwh']:.5f} | {item['average_power_w']:.2f} | "
            f"{item['average_occupied_comfort']:.2f} | {item['average_satisfaction_score']:.2f} | "
            f"{item['task_completion_rate_percent']:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## Analysis Notes",
            "",
            f"- 四季能耗差异明显：{strongest_energy['season_name']}智能体能耗最高，为 {strongest_energy['agent_energy_kwh']:.2f} kWh；{lowest_energy['season_name']}最低，为 {lowest_energy['agent_energy_kwh']:.2f} kWh。该差异主要由室外温度、太阳辐射、湿度和在家时长共同造成。",
        ]
    )
    negative_saving = [item for item in season_metrics if float(item["energy_saving_vs_baseline_percent"]) < 0]
    if negative_saving:
        names = "、".join(item["season_name"] for item in negative_saving)
        lines.append(
            f"- {names}出现轻微负节能率，说明温和季节中系统可能为了提高人所在房间舒适度而多使用温控设备，可解释为舒适性和节能性的权衡。"
        )
    if "weekend" in day_type_by_key and "workday" in day_type_by_key:
        weekend = day_type_by_key["weekend"]
        workday = day_type_by_key["workday"]
        lines.append(
            f"- 周末休息日平均功率为 {weekend['average_power_w']:.2f} W，工作日为 {workday['average_power_w']:.2f} W，体现了居家时长增加后照明、通风和温控需求上升。"
        )
    if "sick_day" in day_type_by_key:
        sick = day_type_by_key["sick_day"]
        lines.append(
            f"- 生病日共 {sick['day_count']} 天，脚本加入感冒、发烧、咳嗽、过敏、怕风等自然语言需求；系统会限制强风、过度开窗和过度降温，生病日人在房间舒适度为 {sick['average_occupied_comfort']:.2f}。"
        )
    lines.extend(
        [
            f"- 对照基线采用独立环境并行运行，节能率不是从同一状态即时估算，而是用同一生活轨迹下的人工固定策略能耗计算：{summary['baseline_definition']}",
            "- 本结果用于长周期生活仿真与能耗/舒适度趋势分析；如需评估外部 LLM 语义能力，建议另取少量代表性事件使用 `--llm-mode real` 做补充验证，避免长周期批量调用受网络和 API 波动影响。",
        ]
    )
    return "\n".join(lines)


def _day_type_label(value: str) -> str:
    return {
        "workday": "工作日",
        "weekend": "周末休息日",
        "sick_day": "生病/恢复日",
    }.get(value, value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run four representative seasonal months of smart-home life simulation.")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "results" / "seasonal_life"),
        help="Directory for seasonal simulation outputs.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["mock", "real", "env"],
        default="mock",
        help="Use mock for reproducible long-run data, real for API validation, env to keep backend/.env.",
    )
    args = parser.parse_args()

    load_dotenv(BACKEND_ROOT / ".env")
    if args.llm_mode != "env":
        os.environ["LLM_MODE"] = args.llm_mode
    effective_llm_mode = os.environ.get("LLM_MODE", "real").lower()

    simulation = SeasonalLifeSimulation(
        months=SEASON_MONTHS,
        output_dir=Path(args.output_dir),
        llm_mode=effective_llm_mode,
    )
    result = simulation.run()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("\nOutputs:")
    for key, value in result["output_paths"].items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
