import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.schemas.task_schema import AgentCommandRequest
from app.schemas.state_schema import SmartHomeState
from app.simulation.environment import SmartHomeEnvironment


MINUTES_PER_DAY = 24 * 60
WEEKDAY_WEATHER = ["sunny", "cloudy", "overcast", "rainy", "cloudy", "sunny", "overcast"]


@dataclass(frozen=True)
class LifeEvent:
    minute: int
    room_id: str
    command: str
    activity: str


class WeeklyLifeSimulation:
    def __init__(self, days: int, output_dir: Path, llm_mode: str) -> None:
        self.days = days
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.environment = SmartHomeEnvironment()
        self.runner = TaskRunner(
            environment=self.environment,
            experiment_logger=ExperimentLogger(self.output_dir),
            refresh_realtime=False,
        )
        self.llm_mode = llm_mode
        self.current_abs_minute = 0
        self.baseline_energy_kwh = 0.0
        self.event_records: list[dict[str, Any]] = []
        self.hourly_records: list[dict[str, Any]] = []

    def run(self) -> dict[str, Any]:
        self.runner.reset_context_memory()
        self._sync_time(0)
        for day_index in range(self.days):
            for event in _events_for_day(day_index):
                target_abs_minute = day_index * MINUTES_PER_DAY + event.minute
                self._advance_to(target_abs_minute)
                self._sync_time(target_abs_minute)
                self._run_event(day_index, event)

        self._advance_to(self.days * MINUTES_PER_DAY)
        summary = self._build_summary()
        return self._write_outputs(summary)

    def _run_event(self, day_index: int, event: LifeEvent) -> None:
        started_at = time.perf_counter()
        response = self.runner.run_agent_command(
            AgentCommandRequest(
                user_command=event.command,
                current_room_id=event.room_id,
            )
        )
        response_time_ms = round((time.perf_counter() - started_at) * 1000, 2)
        state = response.final_state or self.environment.get_state(refresh_realtime=False)
        self.event_records.append(
            {
                **self._base_record(
                    state=state,
                    day_index=day_index,
                    abs_minute=self.current_abs_minute,
                    record_type="event",
                    activity=event.activity,
                ),
                "command": event.command,
                "success": response.success,
                "completed": bool(response.feedback_result.get("completed", False)),
                "intent": response.semantic_result.get("intent", ""),
                "room": response.semantic_result.get("room", ""),
                "scope": response.semantic_result.get("scope", ""),
                "control_goal": response.semantic_result.get("control_goal", ""),
                "devices": ",".join(str(device) for device in response.semantic_result.get("devices", [])),
                "action_count": len(response.plan_result.get("actions", [])),
                "executed_count": response.execution_result.get("executed_count", 0),
                "response_time_ms": response_time_ms,
                "error": response.error or "",
            }
        )

    def _advance_to(self, target_abs_minute: int) -> None:
        while self.current_abs_minute < target_abs_minute:
            next_hour = ((self.current_abs_minute // 60) + 1) * 60
            step_to = min(target_abs_minute, next_hour)
            minutes = step_to - self.current_abs_minute
            if minutes <= 0:
                break
            state_before = self.environment.get_state(refresh_realtime=False)
            self.baseline_energy_kwh += state_before.energy_metrics.baseline_power_w * minutes / 60 / 1000
            self.environment.step(minutes=minutes, refresh_realtime=False)
            self.current_abs_minute = step_to
            self._sync_time(self.current_abs_minute)
            if self.current_abs_minute % 60 == 0:
                state = self.environment.get_state(refresh_realtime=False)
                day_index = min(self.days - 1, self.current_abs_minute // MINUTES_PER_DAY)
                self.hourly_records.append(
                    {
                        **self._base_record(
                            state=state,
                            day_index=day_index,
                            abs_minute=self.current_abs_minute,
                            record_type="hourly",
                            activity="state_sample",
                        ),
                        "command": "",
                        "success": "",
                        "completed": "",
                        "intent": "",
                        "room": self._occupied_room_id(state),
                        "scope": "",
                        "control_goal": "",
                        "devices": "",
                        "action_count": 0,
                        "executed_count": 0,
                        "response_time_ms": 0,
                        "error": "",
                    }
                )

    def _sync_time(self, abs_minute: int) -> None:
        day_index = abs_minute // MINUTES_PER_DAY
        minute_of_day = abs_minute % MINUTES_PER_DAY
        self.environment.set_outdoor_environment(
            weather=_weather_for_day(day_index),
            time_hour=minute_of_day // 60,
        )

    def _base_record(
        self,
        state: SmartHomeState,
        day_index: int,
        abs_minute: int,
        record_type: str,
        activity: str,
    ) -> dict[str, Any]:
        minute_of_day = abs_minute % MINUTES_PER_DAY
        occupied_room_id = self._occupied_room_id(state)
        occupied_comfort = self._room_comfort(state, occupied_room_id)
        saving_vs_baseline = self._saving_vs_baseline(state.energy_metrics.cumulative_energy_kwh)
        satisfaction = _satisfaction_score(
            occupied_comfort=occupied_comfort.get("overall_comfort_score", 0.0),
            energy_saving_percent=saving_vs_baseline,
            completed=True if record_type == "hourly" else None,
        )
        return {
            "record_type": record_type,
            "day": day_index + 1,
            "day_name": _day_name(day_index),
            "abs_minute": abs_minute,
            "time": _format_time(minute_of_day),
            "weather": state.outdoor_environment.weather,
            "outdoor_temperature_c": state.outdoor_environment.outdoor_temperature_c,
            "outdoor_humidity_percent": state.outdoor_environment.outdoor_humidity_percent,
            "outdoor_illuminance_lux": state.outdoor_environment.outdoor_illuminance_lux,
            "activity": activity,
            "occupied_room": occupied_room_id,
            "current_power_w": state.energy_metrics.current_power_w,
            "baseline_power_w": state.energy_metrics.baseline_power_w,
            "agent_cumulative_energy_kwh": state.energy_metrics.cumulative_energy_kwh,
            "baseline_cumulative_energy_kwh": round(self.baseline_energy_kwh, 5),
            "energy_saving_vs_baseline_percent": saving_vs_baseline,
            "average_overall_comfort": state.comfort_metrics.average_overall_score,
            "average_thermal_comfort": state.comfort_metrics.average_thermal_score,
            "average_lighting_comfort": state.comfort_metrics.average_lighting_score,
            "average_humidity_comfort": state.comfort_metrics.average_humidity_score,
            "occupied_overall_comfort": occupied_comfort.get("overall_comfort_score", 0.0),
            "occupied_thermal_comfort": occupied_comfort.get("thermal_comfort_score", 0.0),
            "occupied_lighting_comfort": occupied_comfort.get("lighting_comfort_score", 0.0),
            "occupied_humidity_comfort": occupied_comfort.get("humidity_comfort_score", 0.0),
            "comfortable_room_count": state.comfort_metrics.comfortable_room_count,
            "resident_satisfaction_score": satisfaction,
            "active_device_count": _active_device_count(state),
        }

    def _build_summary(self) -> dict[str, Any]:
        records = self.hourly_records
        event_records = self.event_records
        final_state = self.environment.get_state(refresh_realtime=False)
        agent_energy = final_state.energy_metrics.cumulative_energy_kwh
        baseline_energy = self.baseline_energy_kwh
        by_day = []
        for day in range(1, self.days + 1):
            day_records = [record for record in records if record["day"] == day]
            day_events = [record for record in event_records if record["day"] == day]
            by_day.append(
                {
                    "day": day,
                    "day_name": _day_name(day - 1),
                    "weather": _weather_for_day(day - 1),
                    "hourly_samples": len(day_records),
                    "event_count": len(day_events),
                    "average_occupied_comfort": _mean_field(day_records, "occupied_overall_comfort"),
                    "average_satisfaction": _mean_field(day_records + day_events, "resident_satisfaction_score"),
                    "average_current_power_w": _mean_field(day_records, "current_power_w"),
                    "average_baseline_power_w": _mean_field(day_records, "baseline_power_w"),
                    "task_completion_rate_percent": _rate(day_events, "completed"),
                }
            )

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "llm_mode": self.llm_mode,
            "days": self.days,
            "hourly_sample_count": len(records),
            "event_count": len(event_records),
            "task_success_rate_percent": _rate(event_records, "success"),
            "task_completion_rate_percent": _rate(event_records, "completed"),
            "average_action_count": round(mean(float(record["action_count"]) for record in event_records), 2) if event_records else 0.0,
            "agent_energy_kwh": round(agent_energy, 5),
            "baseline_energy_kwh": round(baseline_energy, 5),
            "energy_saving_vs_baseline_percent": self._saving_vs_baseline(agent_energy),
            "average_current_power_w": _mean_field(records, "current_power_w"),
            "average_baseline_power_w": _mean_field(records, "baseline_power_w"),
            "average_overall_comfort": _mean_field(records, "average_overall_comfort"),
            "average_occupied_comfort": _mean_field(records, "occupied_overall_comfort"),
            "average_thermal_comfort": _mean_field(records, "average_thermal_comfort"),
            "average_lighting_comfort": _mean_field(records, "average_lighting_comfort"),
            "average_humidity_comfort": _mean_field(records, "average_humidity_comfort"),
            "comfortable_hour_rate_percent": round(
                sum(1 for record in records if float(record["occupied_overall_comfort"]) >= 80) / len(records) * 100,
                2,
            ) if records else 0.0,
            "average_resident_satisfaction_score": _mean_field(records + event_records, "resident_satisfaction_score"),
            "by_day": by_day,
            "baseline_definition": final_state.energy_metrics.baseline_definition,
        }

    def _write_outputs(self, summary: dict[str, Any]) -> dict[str, Any]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        event_csv = self.output_dir / f"weekly_life_events_{timestamp}.csv"
        hourly_csv = self.output_dir / f"weekly_life_hourly_{timestamp}.csv"
        summary_json = self.output_dir / f"weekly_life_summary_{timestamp}.json"
        report_md = self.output_dir / f"weekly_life_report_{timestamp}.md"
        _write_csv(event_csv, self.event_records)
        _write_csv(hourly_csv, self.hourly_records)
        summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        report_md.write_text(_render_report(summary, event_csv, hourly_csv, summary_json), encoding="utf-8")
        return {
            "summary": summary,
            "event_csv": event_csv,
            "hourly_csv": hourly_csv,
            "summary_json": summary_json,
            "report_md": report_md,
        }

    def _occupied_room_id(self, state: SmartHomeState) -> str:
        for room in state.rooms:
            if room.occupancy:
                return room.room_id
        return "living_room"

    def _room_comfort(self, state: SmartHomeState, room_id: str) -> dict[str, float]:
        for room in state.comfort_metrics.rooms:
            if room.room_id == room_id:
                return room.model_dump()
        return {}

    def _saving_vs_baseline(self, agent_energy_kwh: float) -> float:
        if self.baseline_energy_kwh <= 0:
            return 0.0
        return round((self.baseline_energy_kwh - agent_energy_kwh) / self.baseline_energy_kwh * 100, 2)


def _events_for_day(day_index: int) -> list[LifeEvent]:
    if day_index < 5:
        evening_activity = LifeEvent(
            minute=20 * 60,
            room_id="study_room",
            command="我现在在书房学习，请把光线和温度调到适合阅读写作的状态",
            activity="evening_study",
        )
        daytime_events = [
            LifeEvent(8 * 60 + 15, "living_room", "我要出门上班了，家里进入离家节能模式", "away_to_work"),
            LifeEvent(18 * 60 + 20, "living_room", "我回家了，现在在客厅，有点闷热，帮我调整舒适", "return_home"),
        ]
    else:
        evening_activity = LifeEvent(
            minute=20 * 60,
            room_id="living_room",
            command="我现在在客厅看电影，灯光暗一点，温度舒服一点",
            activity="movie_time",
        )
        daytime_events = [
            LifeEvent(9 * 60 + 30, "living_room", "周末我在客厅休息，家里保持节能但别不舒服", "weekend_rest"),
            LifeEvent(11 * 60 + 30, "kitchen", "我现在在厨房做饭，有点热，保持照明并注意通风", "weekend_cooking"),
            LifeEvent(15 * 60, "laundry", "我在洗衣区整理衣物，有点潮，帮我改善湿度", "laundry"),
        ]

    return [
        LifeEvent(0, "bedroom", "我在卧室睡觉，请保持睡眠模式", "sleep"),
        LifeEvent(6 * 60 + 30, "bedroom", "我醒了，卧室有点暗，温度保持舒适", "wake_up"),
        LifeEvent(6 * 60 + 50, "bathroom", "我现在在卫生间洗漱，灯光亮一点，湿度别太高", "wash"),
        LifeEvent(7 * 60 + 15, "kitchen", "我现在在厨房做早餐，打开厨房灯，保持通风舒适", "breakfast_cooking"),
        LifeEvent(7 * 60 + 40, "dining_room", "我现在在餐厅吃早饭，灯光明亮一点", "breakfast"),
        *daytime_events,
        LifeEvent(19 * 60, "dining_room", "我在餐厅吃晚饭，灯光明亮一些，温度不要太高", "dinner"),
        evening_activity,
        LifeEvent(21 * 60 + 45, "bathroom", "我现在在卫生间洗澡，湿度有点高，帮我处理一下", "shower"),
        LifeEvent(22 * 60 + 30, "bedroom", "我要睡觉了，请把卧室调到睡眠模式", "sleep"),
    ]


def _weather_for_day(day_index: int) -> str:
    return WEEKDAY_WEATHER[day_index % len(WEEKDAY_WEATHER)]


def _day_name(day_index: int) -> str:
    return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][day_index % 7]


def _format_time(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _active_device_count(state: SmartHomeState) -> int:
    count = 0
    for device in state.devices:
        if device.device_type == "light" and device.is_on and device.brightness_pct > 0:
            count += 1
        elif device.device_type == "ac" and device.is_on:
            count += 1
        elif device.device_type == "fan" and device.is_on and device.speed_pct > 0:
            count += 1
    return count


def _satisfaction_score(
    occupied_comfort: float,
    energy_saving_percent: float,
    completed: bool | None,
) -> float:
    energy_score = _clamp(50 + energy_saving_percent, 0, 100)
    if completed is None:
        return round(occupied_comfort * 0.8 + energy_score * 0.2, 2)
    completion_score = 100.0 if completed else 45.0
    return round(occupied_comfort * 0.65 + completion_score * 0.25 + energy_score * 0.10, 2)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _mean_field(records: list[dict[str, Any]], field: str) -> float:
    values = [float(record[field]) for record in records if record.get(field) not in {"", None}]
    return round(mean(values), 2) if values else 0.0


def _rate(records: list[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    return round(sum(1 for record in records if record.get(field) is True) / len(records) * 100, 2)


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def _render_report(summary: dict[str, Any], event_csv: Path, hourly_csv: Path, summary_json: Path) -> str:
    lines = [
        "# 一周正常居住智能家居仿真实验报告",
        "",
        f"生成时间：{summary['generated_at']}",
        f"LLM 模式：`{summary['llm_mode']}`",
        "",
        "## 数据文件",
        "",
        f"- 事件日志：`{event_csv}`",
        f"- 小时级状态日志：`{hourly_csv}`",
        f"- 汇总 JSON：`{summary_json}`",
        "",
        "## 总体结果",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 仿真天数 | {summary['days']} |",
        f"| 自然语言事件数 | {summary['event_count']} |",
        f"| 小时级样本数 | {summary['hourly_sample_count']} |",
        f"| 任务成功率 | {summary['task_success_rate_percent']:.2f}% |",
        f"| 任务完成率 | {summary['task_completion_rate_percent']:.2f}% |",
        f"| 平均动作数 | {summary['average_action_count']:.2f} |",
        f"| 智能体累计能耗 | {summary['agent_energy_kwh']:.5f} kWh |",
        f"| 固定策略基线能耗 | {summary['baseline_energy_kwh']:.5f} kWh |",
        f"| 相对基线节能率 | {summary['energy_saving_vs_baseline_percent']:.2f}% |",
        f"| 平均实时功率 | {summary['average_current_power_w']:.2f} W |",
        f"| 基线平均功率 | {summary['average_baseline_power_w']:.2f} W |",
        f"| 全屋平均舒适度 | {summary['average_overall_comfort']:.2f} |",
        f"| 人所在房间平均舒适度 | {summary['average_occupied_comfort']:.2f} |",
        f"| 热舒适度 | {summary['average_thermal_comfort']:.2f} |",
        f"| 光舒适度 | {summary['average_lighting_comfort']:.2f} |",
        f"| 湿度舒适度 | {summary['average_humidity_comfort']:.2f} |",
        f"| 舒适小时占比 | {summary['comfortable_hour_rate_percent']:.2f}% |",
        f"| 平均满意度 | {summary['average_resident_satisfaction_score']:.2f} |",
        "",
        "## 每日对比",
        "",
        "| 日期 | 天气 | 事件数 | 人所在房间舒适度 | 满意度 | 平均功率 W | 基线功率 W | 完成率 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["by_day"]:
        lines.append(
            f"| 第{item['day']}天 {item['day_name']} | {item['weather']} | {item['event_count']} | "
            f"{item['average_occupied_comfort']:.2f} | {item['average_satisfaction']:.2f} | "
            f"{item['average_current_power_w']:.2f} | {item['average_baseline_power_w']:.2f} | "
            f"{item['task_completion_rate_percent']:.2f}% |"
        )
    lines.extend(
        [
            "",
            "## 对照说明",
            "",
            summary["baseline_definition"],
            "",
            "满意度为实验统计指标，综合人所在房间舒适度、任务完成情况和相对基线节能表现计算，用于观察连续生活场景下智能体控制策略的综合效果。",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a one-week human-life smart home simulation.")
    parser.add_argument("--days", type=int, default=7, help="Number of simulated days.")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "results" / "weekly_life"),
        help="Directory for weekly simulation logs and reports.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["real", "env"],
        default="real",
        help="LLM mode. Use real for the configured API, env to keep .env/defaults.",
    )
    args = parser.parse_args()

    load_dotenv(BACKEND_ROOT / ".env")
    if args.llm_mode != "env":
        os.environ["LLM_MODE"] = args.llm_mode
    effective_llm_mode = os.environ.get("LLM_MODE", "real")

    simulation = WeeklyLifeSimulation(
        days=max(1, args.days),
        output_dir=Path(args.output_dir),
        llm_mode=effective_llm_mode,
    )
    result = simulation.run()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"\nEvent CSV: {result['event_csv']}")
    print(f"Hourly CSV: {result['hourly_csv']}")
    print(f"Summary JSON: {result['summary_json']}")
    print(f"Report: {result['report_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
