from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime
from math import pi, sin
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.schemas.state_schema import ActivityType, RoomId, SmartHomeState, WeatherType
from app.schemas.task_schema import AgentCommandRequest, AgentCommandResponse
from app.simulation.baseline_policy import plan_conventional_baseline_actions
from app.simulation.environment import SmartHomeEnvironment

LifeSimulationDuration = Literal["day", "week", "month"]

SIM_MINUTES_PER_REAL_SECOND = 1.0
MINUTES_PER_DAY = 24 * 60
DURATION_DAYS: dict[LifeSimulationDuration, int] = {
    "day": 1,
    "week": 7,
    "month": 30,
}
WEEKLY_WEATHER: list[WeatherType] = ["sunny", "cloudy", "overcast", "rainy", "cloudy", "sunny", "overcast"]
TYPICAL_MAY_SOURCE = "mild_may_typical_profile"


class LifeSimulationStartRequest(BaseModel):
    duration: LifeSimulationDuration = "week"


class LifeSimulationStatus(BaseModel):
    active: bool
    duration: LifeSimulationDuration | None = None
    total_days: int = 0
    simulated_minute: int = 0
    total_minutes: int = 0
    day: int = 0
    time: str = "00:00"
    progress_percent: float = 0
    speed_label: str = "24h sim = 24min real"
    current_activity: str = ""
    current_room_id: RoomId | None = None
    current_room_name: str = ""
    weather_source: str = "synthetic_weekly_profile"
    event_count: int = 0
    completed_event_count: int = 0
    error_count: int = 0
    last_event: dict[str, Any] | None = None
    last_agent_output: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    output_paths: dict[str, str] = Field(default_factory=dict)
    state: SmartHomeState


@dataclass(frozen=True)
class LifeEvent:
    minute: int
    room_id: RoomId
    activity: str
    activity_type: ActivityType
    command: str


@dataclass(frozen=True)
class WeatherSnapshot:
    weather: WeatherType
    time_hour: int
    outdoor_illuminance_lux: float
    solar_radiation_w_m2: float
    outdoor_temperature_c: float
    outdoor_humidity_percent: float
    source: str


class HistoricalWeatherProfile:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.snapshots: dict[tuple[int, int], WeatherSnapshot] = {}
        self.source_label = TYPICAL_MAY_SOURCE
        self._load_latest_weekly_log()

    def get(self, day_index: int, hour: int) -> WeatherSnapshot | None:
        if not self.snapshots:
            return None
        source_days = max(day for day, _hour in self.snapshots) + 1
        return self.snapshots.get((day_index % source_days, hour))

    def _load_latest_weekly_log(self) -> None:
        candidates = [
            *self.project_root.glob("data/results/life_simulation/life_simulation_hourly_*.csv"),
            *self.project_root.glob("data/results/weekly_life/weekly_life_hourly_*.csv"),
        ]
        if not candidates:
            return

        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        loaded: dict[tuple[int, int], WeatherSnapshot] = {}
        try:
            with latest.open("r", encoding="utf-8", newline="") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    snapshot = _snapshot_from_row(row, latest.name)
                    if snapshot is None:
                        continue
                    day = max(0, int(float(row.get("day", "1"))) - 1)
                    loaded[(day, snapshot.time_hour)] = snapshot
        except (OSError, ValueError, KeyError):
            return

        if loaded:
            loaded_days = {day for day, _hour in loaded}
            if len(loaded_days) >= 7:
                self.snapshots = loaded
                self.source_label = f"historical_week_log:{latest.name}"


class LifeSimulationService:
    def __init__(
        self,
        *,
        environment: SmartHomeEnvironment,
        experiment_logger: ExperimentLogger,
        project_root: Path,
    ) -> None:
        self.environment = environment
        self.experiment_logger = experiment_logger
        self.project_root = project_root
        self.output_dir = project_root / "data" / "results" / "life_simulation"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.weather_profile = HistoricalWeatherProfile(project_root)
        self.baseline_environment = SmartHomeEnvironment()
        self.runner: TaskRunner | None = None
        self.active = False
        self.duration: LifeSimulationDuration | None = None
        self.total_days = 0
        self.total_minutes = 0
        self.simulated_minute = 0
        self.last_tick_at: float | None = None
        self.events: list[LifeEvent] = []
        self.next_event_index = 0
        self.baseline_energy_kwh = 0.0
        self.event_records: list[dict[str, Any]] = []
        self.hourly_records: list[dict[str, Any]] = []
        self.last_event: dict[str, Any] | None = None
        self.last_agent_output: dict[str, Any] | None = None
        self.output_paths: dict[str, str] = {}

    def start(self, duration: LifeSimulationDuration) -> LifeSimulationStatus:
        self.runner = TaskRunner(
            environment=self.environment,
            experiment_logger=self.experiment_logger,
            refresh_realtime=False,
        )
        llm_mode = getattr(self.runner.semantic_agent.llm_client, "mode", "real")
        if llm_mode != "real":
            raise RuntimeError("一周/一月生活仿真要求使用真实 API 大模型，请将 LLM_MODE 配置为 real。")

        self.duration = duration
        self.total_days = DURATION_DAYS[duration]
        self.total_minutes = self.total_days * MINUTES_PER_DAY
        self.simulated_minute = 0
        self.last_tick_at = time.monotonic()
        self.events = _build_events(self.total_days)
        self.next_event_index = 0
        self.baseline_energy_kwh = 0.0
        self.event_records = []
        self.hourly_records = []
        self.last_event = None
        self.last_agent_output = None
        self.output_paths = {}
        self.active = True

        self.environment.reset()
        self.baseline_environment.reset()
        self.runner.reset_context_memory()
        self._sync_weather(0)
        return self.status()

    def tick(self) -> LifeSimulationStatus:
        if not self.active:
            return self.status()

        now = time.monotonic()
        if self.last_tick_at is None:
            self.last_tick_at = now
            return self.status()

        elapsed_seconds = now - self.last_tick_at
        minutes = int(elapsed_seconds * SIM_MINUTES_PER_REAL_SECOND)
        if minutes <= 0:
            return self.status()

        self.last_tick_at += minutes / SIM_MINUTES_PER_REAL_SECOND
        target_minute = min(self.total_minutes, self.simulated_minute + minutes)
        self._advance_to(target_minute)
        self.last_tick_at = time.monotonic()
        if self.simulated_minute >= self.total_minutes:
            self.active = False
            self._write_outputs()
        return self.status()

    def stop(self) -> LifeSimulationStatus:
        self.active = False
        if self.event_records or self.hourly_records:
            self._write_outputs()
        return self.status()

    def back_to_today(self) -> SmartHomeState:
        self.active = False
        if self.runner:
            self.runner.reset_context_memory()
        self.output_paths = {}
        return self.environment.reset()

    def status(self) -> LifeSimulationStatus:
        state = self.environment.get_state(refresh_realtime=False)
        total_minutes = self.total_minutes or 0
        progress = (self.simulated_minute / total_minutes * 100) if total_minutes else 0.0
        current_room = _occupied_room(state)
        return LifeSimulationStatus(
            active=self.active,
            duration=self.duration,
            total_days=self.total_days,
            simulated_minute=self.simulated_minute,
            total_minutes=total_minutes,
            day=(self.simulated_minute // MINUTES_PER_DAY) + 1 if total_minutes else 0,
            time=_format_time(self.simulated_minute % MINUTES_PER_DAY),
            progress_percent=round(min(100.0, progress), 2),
            current_activity=current_room.activity if current_room else "",
            current_room_id=current_room.room_id if current_room else None,
            current_room_name=current_room.name if current_room else "离家",
            weather_source=self.weather_profile.source_label,
            event_count=len(self.event_records),
            completed_event_count=sum(1 for record in self.event_records if record.get("completed") is True),
            error_count=sum(1 for record in self.event_records if record.get("success") is False),
            last_event=self.last_event,
            last_agent_output=self.last_agent_output,
            summary=self._build_summary(),
            output_paths=self.output_paths,
            state=state,
        )

    def _advance_to(self, target_minute: int) -> None:
        while self.simulated_minute < target_minute:
            self._run_due_events()
            next_event_minute = self._next_event_minute()
            next_hour = ((self.simulated_minute // 60) + 1) * 60
            step_to = min(
                target_minute,
                next_hour,
                next_event_minute if next_event_minute is not None else target_minute,
            )
            if step_to <= self.simulated_minute:
                break
            self._step_minutes(step_to - self.simulated_minute)
        self._run_due_events()

    def _step_minutes(self, minutes: int) -> None:
        self._apply_conventional_baseline_policy()
        baseline_state_before = self.baseline_environment.get_state(refresh_realtime=False)
        self.baseline_energy_kwh += baseline_state_before.energy_metrics.current_power_w * minutes / 60 / 1000
        self.environment.step(minutes=minutes, refresh_realtime=False)
        self._apply_agent_maintenance_policy()
        self.baseline_environment.step(minutes=minutes, refresh_realtime=False)
        self.simulated_minute += minutes
        if self.simulated_minute % 60 == 0:
            self._sync_weather(self.simulated_minute)
            self._record_hourly_sample()

    def _sync_weather(self, abs_minute: int, target_environment: SmartHomeEnvironment | None = None) -> None:
        day_index = abs_minute // MINUTES_PER_DAY
        hour = (abs_minute % MINUTES_PER_DAY) // 60
        environments = [target_environment] if target_environment else [self.environment, self.baseline_environment]
        snapshot = self.weather_profile.get(day_index, hour)
        for environment in environments:
            if environment is None:
                continue
            if snapshot:
                environment.set_outdoor_snapshot(
                    weather=snapshot.weather,
                    time_hour=hour,
                    outdoor_illuminance_lux=snapshot.outdoor_illuminance_lux,
                    solar_radiation_w_m2=snapshot.solar_radiation_w_m2,
                    outdoor_temperature_c=snapshot.outdoor_temperature_c,
                    outdoor_humidity_percent=snapshot.outdoor_humidity_percent,
                    data_updated_at=snapshot.source,
                )
            else:
                snapshot = _typical_mild_may_snapshot(day_index, hour)
                environment.set_outdoor_snapshot(
                    weather=snapshot.weather,
                    time_hour=hour,
                    outdoor_illuminance_lux=snapshot.outdoor_illuminance_lux,
                    solar_radiation_w_m2=snapshot.solar_radiation_w_m2,
                    outdoor_temperature_c=snapshot.outdoor_temperature_c,
                    outdoor_humidity_percent=snapshot.outdoor_humidity_percent,
                    data_updated_at=snapshot.source,
                )

    def _next_event_minute(self) -> int | None:
        if self.next_event_index >= len(self.events):
            return None
        return self.events[self.next_event_index].minute

    def _run_due_events(self) -> None:
        while self.next_event_index < len(self.events):
            event = self.events[self.next_event_index]
            if event.minute > self.simulated_minute:
                break
            self.next_event_index += 1
            self._run_event(event)

    def _run_event(self, event: LifeEvent) -> None:
        if not self.runner:
            return

        started_at = time.perf_counter()
        state_before = self.environment.get_state(refresh_realtime=False)
        previously_occupied_rooms = [
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
        state = self._apply_life_event_safety(event, previously_occupied_rooms)
        baseline_state = self._apply_baseline_event(event)
        feedback_result = response.feedback_result
        if response.success and self.runner and response.semantic_result:
            feedback_result = self.runner.feedback_agent.evaluate(
                response.semantic_result,
                state,
                revision_round=99,
            )
        llm_metrics = response.semantic_result.get("llm_metrics", {}) if isinstance(response.semantic_result, dict) else {}
        record = {
            **self._base_record(state, "event", event.activity, completed=feedback_result.get("completed"), baseline_state=baseline_state),
            "command": event.command,
            "success": response.success,
            "completed": bool(feedback_result.get("completed", False)),
            "intent": response.semantic_result.get("intent", ""),
            "room": response.semantic_result.get("room", ""),
            "scope": response.semantic_result.get("scope", ""),
            "control_goal": response.semantic_result.get("control_goal", ""),
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
        self.last_event = record
        self.last_agent_output = _agent_output_from_response(response, feedback_result=feedback_result)

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

    def _apply_life_event_safety(self, event: LifeEvent, previously_occupied_rooms: list[str]) -> SmartHomeState:
        actions: list[dict[str, Any]] = []
        state = self.environment.get_state(refresh_realtime=False)

        if event.activity_type == "away":
            actions.extend(_away_safety_actions(state))
        elif event.activity_type == "sleep":
            actions.extend(_vacated_room_shutdown_actions(state, keep_room_id=event.room_id))
            actions.extend(_sleep_safety_actions(state, event.room_id))
        else:
            actions.extend(_vacated_room_shutdown_actions(state, keep_room_id=event.room_id, room_ids=previously_occupied_rooms))

        if actions:
            self.environment.apply_device_actions_batch(actions, dt_minutes=1)
        return self.environment.get_state(refresh_realtime=False)

    def _apply_agent_maintenance_policy(self) -> SmartHomeState:
        state = self.environment.get_state(refresh_realtime=False)
        actions = _agent_maintenance_actions(state)
        if actions:
            self.environment.apply_device_actions_batch(actions, dt_minutes=0)
        return self.environment.get_state(refresh_realtime=False)

    def _record_hourly_sample(self) -> None:
        state = self.environment.get_state(refresh_realtime=False)
        baseline_state = self.baseline_environment.get_state(refresh_realtime=False)
        self.hourly_records.append(
            {
                **self._base_record(state, "hourly", "state_sample", completed=True, baseline_state=baseline_state),
                "command": "",
                "success": "",
                "completed": "",
                "intent": "",
                "room": _occupied_room(state).room_id if _occupied_room(state) else "",
                "scope": "",
                "control_goal": "",
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
        state: SmartHomeState,
        record_type: str,
        activity: str,
        completed: bool | None,
        baseline_state: SmartHomeState | None = None,
    ) -> dict[str, Any]:
        if baseline_state is None:
            baseline_state = self.baseline_environment.get_state(refresh_realtime=False)
        occupied = _occupied_room(state)
        baseline_occupied = _occupied_room(baseline_state)
        occupied_room_id = occupied.room_id if occupied else "away"
        baseline_occupied_room_id = baseline_occupied.room_id if baseline_occupied else "away"
        occupied_comfort = next(
            (room for room in state.comfort_metrics.rooms if room.room_id == occupied_room_id),
            None,
        )
        occupied_score = occupied_comfort.overall_comfort_score if occupied_comfort and occupied and occupied.activity != "away" else None
        energy_saving = _saving_vs_baseline(
            baseline_energy_kwh=self.baseline_energy_kwh,
            agent_energy_kwh=state.energy_metrics.cumulative_energy_kwh,
        )
        return {
            "record_type": record_type,
            "day": _record_day(self.simulated_minute, self.total_days, record_type),
            "abs_minute": self.simulated_minute,
            "time": _format_time(self.simulated_minute % MINUTES_PER_DAY),
            "weather": state.outdoor_environment.weather,
            "outdoor_temperature_c": state.outdoor_environment.outdoor_temperature_c,
            "outdoor_humidity_percent": state.outdoor_environment.outdoor_humidity_percent,
            "outdoor_illuminance_lux": state.outdoor_environment.outdoor_illuminance_lux,
            "activity": activity,
            "occupied_room": occupied_room_id,
            "current_power_w": state.energy_metrics.current_power_w,
            "baseline_power_w": baseline_state.energy_metrics.current_power_w,
            "agent_cumulative_energy_kwh": state.energy_metrics.cumulative_energy_kwh,
            "baseline_cumulative_energy_kwh": round(self.baseline_energy_kwh, 5),
            "energy_saving_vs_baseline_percent": energy_saving,
            "average_overall_comfort": state.comfort_metrics.average_overall_score,
            "average_thermal_comfort": state.comfort_metrics.average_thermal_score,
            "average_lighting_comfort": state.comfort_metrics.average_lighting_score,
            "average_humidity_comfort": state.comfort_metrics.average_humidity_score,
            "occupied_overall_comfort": occupied_score,
            "resident_satisfaction_score": _satisfaction_score(occupied_score, energy_saving, completed),
            "active_device_count": _active_device_count(state),
            "baseline_active_device_count": _active_device_count(baseline_state),
            "baseline_occupied_room": baseline_occupied_room_id,
            "device_snapshot_json": json.dumps(_device_snapshot(state), ensure_ascii=False),
            "baseline_device_snapshot_json": json.dumps(_device_snapshot(baseline_state), ensure_ascii=False),
            "room_comfort_snapshot_json": json.dumps(_room_comfort_snapshot(state), ensure_ascii=False),
            "baseline_room_comfort_snapshot_json": json.dumps(_room_comfort_snapshot(baseline_state), ensure_ascii=False),
        }

    def _build_summary(self) -> dict[str, Any]:
        state = self.environment.get_state(refresh_realtime=False)
        records = self.hourly_records
        event_records = self.event_records
        all_records = sorted(records + event_records, key=lambda record: int(record.get("abs_minute", 0)))
        elapsed_minutes = max(1, self.simulated_minute)
        agent_energy_kwh = state.energy_metrics.cumulative_energy_kwh
        baseline_energy_kwh = self.baseline_energy_kwh
        by_day = []
        for day in range(1, self.total_days + 1):
            day_records = [record for record in records if record["day"] == day]
            day_events = [record for record in event_records if record["day"] == day]
            day_elapsed_minutes = _day_elapsed_minutes(day, self.simulated_minute)
            day_agent_energy_kwh = _day_energy_delta(all_records, day, "agent_cumulative_energy_kwh")
            day_baseline_energy_kwh = _day_energy_delta(all_records, day, "baseline_cumulative_energy_kwh")
            by_day.append(
                {
                    "day": day,
                    "weather": WEEKLY_WEATHER[(day - 1) % len(WEEKLY_WEATHER)],
                    "hourly_samples": len(day_records),
                    "event_count": len(day_events),
                    "average_power_w": _average_power_from_energy(day_agent_energy_kwh, day_elapsed_minutes),
                    "average_baseline_power_w": _average_power_from_energy(day_baseline_energy_kwh, day_elapsed_minutes),
                    "sample_average_power_w": _mean_field(day_records, "current_power_w"),
                    "sample_average_baseline_power_w": _mean_field(day_records, "baseline_power_w"),
                    "agent_energy_kwh": round(day_agent_energy_kwh, 5),
                    "baseline_energy_kwh": round(day_baseline_energy_kwh, 5),
                    "average_home_comfort": _mean_field(day_records, "average_overall_comfort"),
                    "average_occupied_comfort": _mean_field(day_records, "occupied_overall_comfort"),
                    "average_satisfaction_score": _mean_field(day_records + day_events, "resident_satisfaction_score"),
                    "task_completion_rate_percent": _rate(day_events, "completed"),
                }
            )

        return {
            "duration": self.duration,
            "total_days": self.total_days,
            "simulated_days_completed": round(self.simulated_minute / MINUTES_PER_DAY, 3),
            "simulated_minutes": self.simulated_minute,
            "agent_energy_kwh": round(agent_energy_kwh, 5),
            "baseline_energy_kwh": round(baseline_energy_kwh, 5),
            "energy_saving_vs_baseline_percent": _saving_vs_baseline(
                baseline_energy_kwh=baseline_energy_kwh,
                agent_energy_kwh=agent_energy_kwh,
            ),
            "average_power_w": _average_power_from_energy(agent_energy_kwh, elapsed_minutes),
            "average_baseline_power_w": _average_power_from_energy(baseline_energy_kwh, elapsed_minutes),
            "sample_average_power_w": _mean_field(records, "current_power_w"),
            "sample_average_baseline_power_w": _mean_field(records, "baseline_power_w"),
            "average_overall_comfort": _mean_field(records, "average_overall_comfort"),
            "average_occupied_comfort": _mean_field(records, "occupied_overall_comfort"),
            "average_satisfaction_score": _mean_field(records + event_records, "resident_satisfaction_score"),
            "comfortable_hour_rate_percent": _comfortable_hour_rate(records),
            "task_success_rate_percent": _rate(event_records, "success"),
            "task_completion_rate_percent": _rate(event_records, "completed"),
            "hourly_sample_count": len(records),
            "event_count": len(event_records),
            "error_count": sum(1 for record in event_records if record.get("success") is False),
            "baseline_definition": "独立并行粗放人工基线：同一天气和同一生活轨迹，回家后公共区灯光和风扇可能被顺手打开并在换房间后遗忘，空调仅在明显热负荷下按固定阈值开启，离家时关闭主要耗能设备；该基线不读取智能体已调好的环境状态。",
            "by_day": by_day,
            "log_directory": str(self.output_dir),
        }

    def _write_outputs(self) -> None:
        if self.output_paths:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        event_csv = self.output_dir / f"life_simulation_events_{timestamp}.csv"
        hourly_csv = self.output_dir / f"life_simulation_hourly_{timestamp}.csv"
        summary_json = self.output_dir / f"life_simulation_summary_{timestamp}.json"
        report_md = self.output_dir / f"life_simulation_report_{timestamp}.md"
        _write_csv(event_csv, self.event_records)
        _write_csv(hourly_csv, self.hourly_records)
        summary = self._build_summary()
        summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        report_md.write_text(_render_report(summary, event_csv, hourly_csv, self.event_records), encoding="utf-8")
        self.output_paths = {
            "event_csv": str(event_csv),
            "hourly_csv": str(hourly_csv),
            "summary_json": str(summary_json),
            "report_md": str(report_md),
        }


def _events_for_day(day_index: int) -> list[LifeEvent]:
    if day_index % 7 in {5, 6}:
        return [
            _event(0, "bedroom", "睡眠", "sleep", "我在卧室睡觉，请进入睡眠模式"),
            _event(8 * 60, "bedroom", "起床", "idle", "我醒了，卧室保持柔和明亮和舒适温度"),
            _event(9 * 60, "kitchen", "做早餐", "idle", "我在厨房做早餐，保持明亮、通风和舒适"),
            _event(10 * 60, "living_room", "周末休息", "idle", "我在客厅休息，在保证舒适的情况下尽量省电"),
            _event(12 * 60 + 15, "dining_room", "午餐", "idle", "我在餐厅吃午饭，保持用餐舒适"),
            _event(14 * 60, "laundry", "洗衣晾衣", "idle", "我在洗衣区洗衣晾衣，保持通风但别太潮"),
            _event(16 * 60, "study_room", "阅读", "study", "我在书房阅读，请进入学习阅读模式"),
            _event(18 * 60 + 30, "kitchen", "做晚餐", "idle", "我在厨房做晚餐，帮我保持舒适和适当通风"),
            _event(20 * 60, "living_room", "观影", "movie", "我在客厅看电影，请进入观影模式"),
            _event(22 * 60 + 20, "bathroom", "洗澡", "idle", "我在卫生间洗澡后有点潮，帮我处理到舒适"),
            _event(23 * 60, "bedroom", "睡眠", "sleep", "我准备睡觉了，卧室进入睡眠模式"),
        ]

    return [
        _event(0, "bedroom", "睡眠", "sleep", "我在卧室睡觉，请进入睡眠模式"),
        _event(6 * 60 + 45, "bedroom", "起床", "idle", "我醒了，卧室保持柔和明亮和舒适温度"),
        _event(7 * 60 + 5, "bathroom", "洗漱", "idle", "我在卫生间洗漱，湿度有点高，请保持舒适"),
        _event(7 * 60 + 25, "kitchen", "做早餐", "idle", "我在厨房做早餐，保持明亮、通风和舒适"),
        _event(7 * 60 + 45, "dining_room", "早餐", "idle", "我在餐厅吃早饭，保持用餐舒适"),
        _event(8 * 60 + 30, "corridor", "离家上班", "away", "我要出门上班了，家里进入离家节能模式"),
        _event(18 * 60 + 20, "living_room", "回家休息", "idle", "我回到客厅，感觉有点热，帮我调到舒适"),
        _event(19 * 60, "dining_room", "晚餐", "idle", "我在餐厅吃晚饭，光线和温度都调舒适"),
        _event(20 * 60, "study_room", "学习", "study", "我在书房学习，请进入学习模式"),
        _event(22 * 60 + 15, "bathroom", "洗澡", "idle", "我在卫生间洗澡后有点潮，帮我处理到舒适"),
        _event(22 * 60 + 45, "bedroom", "睡眠", "sleep", "我准备睡觉了，卧室进入睡眠模式"),
    ]


def _build_events(days: int) -> list[LifeEvent]:
    events: list[LifeEvent] = []
    for day_index in range(days):
        day_offset = day_index * MINUTES_PER_DAY
        events.extend(
            LifeEvent(
                minute=day_offset + event.minute,
                room_id=event.room_id,
                activity=event.activity,
                activity_type=event.activity_type,
                command=event.command,
            )
            for event in _events_for_day(day_index)
        )
    return sorted(events, key=lambda event: event.minute)


def _event(
    minute: int,
    room_id: RoomId,
    activity: str,
    activity_type: ActivityType,
    command: str,
) -> LifeEvent:
    return LifeEvent(minute=minute, room_id=room_id, activity=activity, activity_type=activity_type, command=command)


def _snapshot_from_row(row: dict[str, str], source: str) -> WeatherSnapshot | None:
    weather = row.get("weather")
    if weather not in {"sunny", "cloudy", "overcast", "rainy"}:
        return None
    time_text = row.get("time", "00:00")
    hour = int(time_text.split(":", 1)[0])
    return WeatherSnapshot(
        weather=weather,
        time_hour=max(0, min(23, hour)),
        outdoor_illuminance_lux=float(row.get("outdoor_illuminance_lux", 0) or 0),
        solar_radiation_w_m2=float(row.get("solar_radiation_w_m2", 0) or 0),
        outdoor_temperature_c=float(row.get("outdoor_temperature_c", 24) or 24),
        outdoor_humidity_percent=float(row.get("outdoor_humidity_percent", 60) or 60),
        source=source,
    )


def _typical_mild_may_snapshot(day_index: int, hour: int) -> WeatherSnapshot:
    weather = WEEKLY_WEATHER[day_index % len(WEEKLY_WEATHER)]
    daylight = max(0.0, sin(pi * (hour - 6) / 12))
    temp_curve = max(0.0, sin(pi * (hour - 6) / 14))
    weather_temp_offset = {
        "sunny": 1.2,
        "cloudy": 0.2,
        "overcast": -0.8,
        "rainy": -1.8,
    }[weather]
    visible_factor = {
        "sunny": 1.0,
        "cloudy": 0.68,
        "overcast": 0.42,
        "rainy": 0.24,
    }[weather]
    humidity_base = {
        "sunny": 54.0,
        "cloudy": 60.0,
        "overcast": 66.0,
        "rainy": 78.0,
    }[weather]
    outdoor_temperature = 18.5 + 7.2 * temp_curve + weather_temp_offset
    humidity = min(95.0, humidity_base + (1.0 - daylight) * 8.0)
    return WeatherSnapshot(
        weather=weather,
        time_hour=hour,
        outdoor_illuminance_lux=round(76000 * daylight * visible_factor, 2),
        solar_radiation_w_m2=round(760 * daylight * visible_factor, 2),
        outdoor_temperature_c=round(outdoor_temperature, 2),
        outdoor_humidity_percent=round(humidity, 2),
        source=f"2026-05-09T{hour:02d}:00:00+08:00;{TYPICAL_MAY_SOURCE}",
    )


def _agent_output_from_response(
    response: AgentCommandResponse,
    *,
    feedback_result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not response.semantic_result and not response.error:
        return None
    return {
        "semantic_result": response.semantic_result,
        "planning_result": response.plan_result,
        "execution_result": response.execution_result,
        "feedback_result": feedback_result or response.feedback_result,
        "actions": response.plan_result.get("actions", []),
        "error": response.error,
    }


def _occupied_room(state: SmartHomeState):
    return next((room for room in state.rooms if room.occupancy), None)


def _active_device_count(state: SmartHomeState) -> int:
    count = 0
    for device in state.devices:
        if device.device_type in {"sensor", "curtain", "window"}:
            continue
        if getattr(device, "is_on", False):
            count += 1
    return count


def _agent_maintenance_actions(state: SmartHomeState) -> list[dict[str, Any]]:
    occupied = _occupied_room(state)
    if occupied is None or occupied.activity == "away":
        return _away_safety_actions(state)

    actions = _vacated_room_shutdown_actions(state, keep_room_id=occupied.room_id)
    actions.extend(_occupied_room_maintenance_actions(state, occupied.room_id, occupied.activity))
    return actions


def _occupied_room_maintenance_actions(
    state: SmartHomeState,
    room_id: str,
    activity: str,
) -> list[dict[str, Any]]:
    room = next((item for item in state.rooms if item.room_id == room_id), None)
    if room is None:
        return []

    actions: list[dict[str, Any]] = []
    light = _device_in_room(state, room_id, "light")
    ac = _device_in_room(state, room_id, "ac")
    fan = _device_in_room(state, room_id, "fan")

    if activity == "sleep":
        if light and getattr(light, "is_on", False):
            actions.append(_action_dict(light.entity_id, "turn_off", {}, "life simulation maintenance: keep sleep room dark"))
        if fan and getattr(fan, "is_on", False):
            target_speed = 20 if room.indoor_temperature_c > 28.5 else 0
            if getattr(fan, "speed_pct", 0) != target_speed:
                action_name = "turn_off" if target_speed == 0 else "set_speed"
                parameters = {} if target_speed == 0 else {"speed_pct": target_speed}
                actions.append(_action_dict(fan.entity_id, action_name, parameters, "life simulation maintenance: quiet sleep airflow"))
        if ac and getattr(ac, "is_on", False) and getattr(ac, "mode", "") == "cool":
            if _mild_transition_context(state) and room.indoor_temperature_c <= 28.0:
                actions.append(_action_dict(ac.entity_id, "turn_off", {}, "life simulation maintenance: avoid sleep AC in mild May conditions"))
            elif room.indoor_temperature_c <= 26.2:
                actions.append(_action_dict(ac.entity_id, "turn_off", {}, "life simulation maintenance: stop sleep cooling after comfort is reached"))
            elif getattr(ac, "setpoint_c", 30) < 27 and room.indoor_temperature_c <= 27.5:
                actions.append(_action_dict(ac.entity_id, "set_temperature", {"setpoint_c": 27}, "life simulation maintenance: relax sleep cooling setpoint"))
        return actions

    if light and getattr(light, "is_on", False):
        target_brightness = 45 if activity == "study" else 40
        if room.room_id in {"kitchen", "bathroom"}:
            target_brightness = 55
        if room.indoor_illuminance_lux >= 350 and getattr(light, "brightness_pct", 0) > target_brightness:
            actions.append(
                _action_dict(
                    light.entity_id,
                    "set_brightness",
                    {"brightness_pct": target_brightness},
                    "life simulation maintenance: reduce lighting after target illuminance is reached",
                )
            )

    if fan and getattr(fan, "is_on", False):
        if room.indoor_temperature_c <= 26.7:
            actions.append(_action_dict(fan.entity_id, "turn_off", {}, "life simulation maintenance: stop fan after thermal comfort is reached"))
        elif room.indoor_temperature_c <= 27.5 and getattr(fan, "speed_pct", 0) > 30:
            actions.append(_action_dict(fan.entity_id, "set_speed", {"speed_pct": 30}, "life simulation maintenance: reduce fan speed in comfort band"))

    if ac and getattr(ac, "is_on", False) and getattr(ac, "mode", "") == "cool":
        if _mild_transition_context(state) and room.indoor_temperature_c <= 28.0:
            actions.append(_action_dict(ac.entity_id, "turn_off", {}, "life simulation maintenance: prefer passive comfort in mild May conditions"))
        elif room.indoor_temperature_c <= 25.8:
            actions.append(_action_dict(ac.entity_id, "turn_off", {}, "life simulation maintenance: stop cooling after comfort is reached"))
        elif room.indoor_temperature_c <= 26.8 and getattr(ac, "setpoint_c", 30) < 27:
            actions.append(_action_dict(ac.entity_id, "set_temperature", {"setpoint_c": 27}, "life simulation maintenance: relax cooling setpoint in comfort band"))

    return actions


def _device_in_room(state: SmartHomeState, room_id: str, device_type: str):
    return next((device for device in state.devices if device.room == room_id and device.device_type == device_type), None)


def _mild_transition_context(state: SmartHomeState) -> bool:
    source = state.outdoor_environment.data_updated_at or ""
    return "mild_may_typical_profile" in source or state.outdoor_environment.outdoor_temperature_c <= 30


def _action_dict(entity_id: str, action: str, parameters: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "action": action,
        "parameters": parameters,
        "reason": reason,
    }


def _away_safety_actions(state: SmartHomeState) -> list[dict[str, Any]]:
    actions = _vacated_room_shutdown_actions(state, keep_room_id=None)
    for device in state.devices:
        if device.device_type == "curtain" and device.opening_pct > 35:
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "set_opening",
                    "parameters": {"opening_pct": 30},
                    "reason": "life simulation safety: reduce solar gain while away",
                }
            )
        elif device.device_type == "window" and device.opening_pct > 15:
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "set_opening",
                    "parameters": {"opening_pct": 10},
                    "reason": "life simulation safety: close windows while away",
                }
            )
    return actions


def _sleep_safety_actions(state: SmartHomeState, sleep_room_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    room = next((item for item in state.rooms if item.room_id == sleep_room_id), None)
    for device in state.devices:
        if device.room != sleep_room_id:
            continue
        if device.device_type == "light" and getattr(device, "is_on", False):
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "turn_off",
                    "parameters": {},
                    "reason": "life simulation safety: lights off for sleep",
                }
            )
        elif device.device_type == "fan" and getattr(device, "speed_pct", 0) > 30:
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "set_speed",
                    "parameters": {"speed_pct": 20 if room and room.indoor_temperature_c > 28 else 0},
                    "reason": "life simulation safety: avoid strong airflow while sleeping",
                }
            )
        elif device.device_type == "ac" and getattr(device, "is_on", False) and getattr(device, "mode", "off") == "cool":
            if room and _mild_transition_context(state) and room.indoor_temperature_c <= 28:
                actions.append(
                    {
                        "entity_id": device.entity_id,
                        "action": "turn_off",
                        "parameters": {},
                        "reason": "life simulation safety: avoid unnecessary sleep AC in mild May conditions",
                    }
                )
            elif getattr(device, "setpoint_c", 30) < 26:
                actions.append(
                    {
                        "entity_id": device.entity_id,
                        "action": "set_temperature",
                        "parameters": {"setpoint_c": 26},
                        "reason": "life simulation safety: avoid overcooling while sleeping",
                    }
                )
        elif device.device_type == "window" and getattr(device, "opening_pct", 0) > 15:
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "set_opening",
                    "parameters": {"opening_pct": 10},
                    "reason": "life simulation safety: quiet minimal ventilation for sleep",
                }
            )
        elif device.device_type == "curtain" and getattr(device, "opening_pct", 100) > 15:
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "set_opening",
                    "parameters": {"opening_pct": 10},
                    "reason": "life simulation safety: darken room for sleep",
                }
            )
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
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "turn_off",
                    "parameters": {},
                    "reason": "life simulation safety: turn off vacated-room light",
                }
            )
        elif device.device_type == "ac" and getattr(device, "is_on", False):
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "turn_off",
                    "parameters": {},
                    "reason": "life simulation safety: turn off vacated-room AC",
                }
            )
        elif device.device_type == "fan" and getattr(device, "is_on", False) and getattr(device, "speed_pct", 0) > 0:
            actions.append(
                {
                    "entity_id": device.entity_id,
                    "action": "turn_off",
                    "parameters": {},
                    "reason": "life simulation safety: turn off vacated-room fan",
                }
            )
    return actions


def _saving_vs_baseline(baseline_energy_kwh: float, agent_energy_kwh: float) -> float:
    if baseline_energy_kwh <= 0:
        return 0.0
    return round((baseline_energy_kwh - agent_energy_kwh) / baseline_energy_kwh * 100, 2)


def _satisfaction_score(occupied_comfort: float | None, energy_saving_percent: float, completed: bool | None) -> float:
    completion_score = 100.0 if completed is not False else 40.0
    saving_score = max(0.0, min(100.0, 50.0 + energy_saving_percent / 2))
    if occupied_comfort is None:
        if completed is None:
            return round(saving_score, 2)
        return round(completion_score * 0.45 + saving_score * 0.55, 2)
    if completed is None:
        return round(occupied_comfort * 0.72 + saving_score * 0.28, 2)
    return round(occupied_comfort * 0.62 + completion_score * 0.2 + saving_score * 0.18, 2)


def _format_time(minute_of_day: int) -> str:
    hour = minute_of_day // 60
    minute = minute_of_day % 60
    return f"{hour:02d}:{minute:02d}"


def _mean_field(records: list[dict[str, Any]], field: str) -> float:
    values = [float(record[field]) for record in records if record.get(field) not in {"", None}]
    return round(mean(values), 2) if values else 0.0


def _average_power_from_energy(energy_kwh: float, minutes: int) -> float:
    if minutes <= 0:
        return 0.0
    return round(energy_kwh * 1000 * 60 / minutes, 2)


def _day_elapsed_minutes(day: int, simulated_minute: int) -> int:
    start = (day - 1) * MINUTES_PER_DAY
    end = min(day * MINUTES_PER_DAY, simulated_minute)
    return max(0, end - start)


def _record_day(abs_minute: int, total_days: int, record_type: str) -> int:
    if record_type == "hourly" and abs_minute > 0 and abs_minute % MINUTES_PER_DAY == 0:
        return min(max(1, total_days), ((abs_minute - 1) // MINUTES_PER_DAY) + 1)
    return min(max(1, total_days), (abs_minute // MINUTES_PER_DAY) + 1)


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


def _rate(records: list[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    return round(sum(1 for record in records if record.get(field) is True) / len(records) * 100, 2)


def _comfortable_hour_rate(records: list[dict[str, Any]]) -> float:
    scored_records = [record for record in records if record.get("occupied_overall_comfort") not in {"", None}]
    if not scored_records:
        return 0.0
    return round(sum(1 for record in scored_records if float(record.get("occupied_overall_comfort", 0)) >= 80) / len(scored_records) * 100, 2)


def _device_snapshot(state: SmartHomeState) -> list[dict[str, Any]]:
    devices = []
    for device in state.devices:
        if device.device_type == "sensor":
            continue
        payload = {
            "entity_id": device.entity_id,
            "room": device.room,
            "type": device.device_type,
        }
        if device.device_type == "light":
            payload.update({"is_on": device.is_on, "brightness_pct": device.brightness_pct})
        elif device.device_type == "ac":
            payload.update({"is_on": device.is_on, "mode": device.mode, "setpoint_c": device.setpoint_c})
        elif device.device_type == "fan":
            payload.update({"is_on": device.is_on, "speed_pct": device.speed_pct})
        elif device.device_type in {"curtain", "window"}:
            payload.update({"opening_pct": device.opening_pct})
        devices.append(payload)
    return devices


def _room_comfort_snapshot(state: SmartHomeState) -> list[dict[str, Any]]:
    return [
        {
            "room_id": room.room_id,
            "temperature_c": room.indoor_temperature_c,
            "humidity_percent": room.indoor_humidity_percent,
            "illuminance_lux": room.indoor_illuminance_lux,
            "occupancy": room.occupancy,
            "activity": room.activity,
            "comfort": next(
                (
                    {
                        "overall": comfort.overall_comfort_score,
                        "thermal": comfort.thermal_comfort_score,
                        "lighting": comfort.lighting_comfort_score,
                        "humidity": comfort.humidity_comfort_score,
                    }
                    for comfort in state.comfort_metrics.rooms
                    if comfort.room_id == room.room_id
                ),
                {},
            ),
        }
        for room in state.rooms
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _render_report(
    summary: dict[str, Any],
    event_csv: Path,
    hourly_csv: Path,
    event_records: list[dict[str, Any]],
) -> str:
    lines = [
        "# 正常人类生活快速仿真分析",
        "",
        f"- 事件日志：{event_csv}",
        f"- 小时日志：{hourly_csv}",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 请求时长 | {summary.get('duration', '')} |",
        f"| 计划天数 | {summary.get('total_days', 0)} |",
        f"| 已完成仿真天数 | {summary.get('simulated_days_completed', 0)} |",
        f"| 事件数 | {summary['event_count']} |",
        f"| 小时样本数 | {summary['hourly_sample_count']} |",
        f"| 任务成功率 | {summary['task_success_rate_percent']:.2f}% |",
        f"| 任务完成率 | {summary['task_completion_rate_percent']:.2f}% |",
        f"| 智能体能耗 | {summary['agent_energy_kwh']:.5f} kWh |",
        f"| 固定策略基线能耗 | {summary['baseline_energy_kwh']:.5f} kWh |",
        f"| 相对基线节能率 | {summary['energy_saving_vs_baseline_percent']:.2f}% |",
        f"| 智能体时间加权平均功率 | {summary['average_power_w']:.2f} W |",
        f"| 固定策略时间加权平均功率 | {summary['average_baseline_power_w']:.2f} W |",
        f"| 智能体采样平均功率 | {summary['sample_average_power_w']:.2f} W |",
        f"| 固定策略采样平均功率 | {summary['sample_average_baseline_power_w']:.2f} W |",
        f"| 平均舒适度 | {summary['average_overall_comfort']:.2f} |",
        f"| 人所在房间舒适度 | {summary['average_occupied_comfort']:.2f} |",
        f"| 舒适小时占比 | {summary['comfortable_hour_rate_percent']:.2f}% |",
        f"| 居住满意度 | {summary['average_satisfaction_score']:.2f} |",
        f"| 异常事件数 | {summary['error_count']} |",
        "",
        "## 每日对比",
        "",
        "| 天数 | 天气 | 事件数 | 人在房间舒适度 | 满意度 | 智能体平均功率 W | 固定策略平均功率 W | 完成率 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["by_day"]:
        lines.append(
            f"| 第{item['day']}天 | {item['weather']} | {item['event_count']} | "
            f"{item['average_occupied_comfort']:.2f} | {item['average_satisfaction_score']:.2f} | "
            f"{item['average_power_w']:.2f} | {item['average_baseline_power_w']:.2f} | "
            f"{item['task_completion_rate_percent']:.2f}% |"
        )
    lines.extend(
        [
            "",
            "## 事件明细",
            "",
            "| 天 | 时间 | 活动 | 房间 | 意图 | 动作 | 完成 | 智能体功率 W | 固定策略功率 W | 响应 ms |",
            "|---:|---|---|---|---|---:|---|---:|---:|---:|",
        ]
    )
    for record in event_records:
        lines.append(
            f"| {record.get('day', '')} | {record.get('time', '')} | {record.get('activity', '')} | "
            f"{record.get('occupied_room', '')} | {record.get('intent', '')} | {record.get('executed_count', '')} | "
            f"{record.get('completed', '')} | {float(record.get('current_power_w') or 0):.2f} | "
            f"{float(record.get('baseline_power_w') or 0):.2f} | {float(record.get('response_time_ms') or 0):.2f} |"
        )
    unfinished = [record for record in event_records if record.get("completed") is not True]
    if unfinished:
        lines.extend(["", "## 未完成事件", ""])
        for record in unfinished:
            lines.append(
                f"- 第{record.get('day')}天 {record.get('time')} {record.get('activity')}："
                f"{record.get('command')}；意图 {record.get('intent')}；动作 {record.get('executed_count')}/{record.get('action_count')}；"
                f"功率 {record.get('current_power_w')} W，对照 {record.get('baseline_power_w')} W。"
            )
    lines.extend(
        [
            "",
            "## 指标口径",
            "",
            "- 任务完成率表示智能体是否给出并执行了正确控制动作；温度、湿度等物理量的最终收敛由舒适度指标继续反映。",
            "- 全屋平均舒适度反映房屋物理环境，会在离家关闭空调后下降。",
            "- 人在房间舒适度只统计有人活动的房间，离家时不计入舒适小时。",
            f"- 固定策略基线口径：{summary.get('baseline_definition', '')}",
            "- 平均功率采用总能耗 / 仿真时长的时间加权算法；采样平均功率仅用于排查某些时刻的状态。",
            "- 居住满意度综合人在房间舒适度、任务完成情况和相对基线节能表现。",
            "",
            "## 日志字段",
            "",
            "- 事件日志记录每条生活指令、真实 API 语义结果、动作数、完成情况、响应耗时、设备快照和房间舒适度快照。",
            "- 小时日志记录每小时能耗、舒适度、天气边界和全屋设备状态，用于曲线绘制和结果分析。",
        ]
    )
    return "\n".join(lines)
