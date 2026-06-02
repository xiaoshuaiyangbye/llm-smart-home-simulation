from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

from app.agents.feedback_agent import FeedbackAgent
from app.agents.llm_client import TARGETS_BY_INTENT
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.schemas.task_schema import AgentCommandRequest
from app.simulation.baseline_policy import plan_conventional_baseline_actions
from app.simulation.environment import SmartHomeEnvironment


@dataclass(frozen=True)
class ExperimentGroup:
    group_id: str
    name: str
    description: str
    runner_kind: str
    llm_mode: str
    execute_actions: bool
    enable_feedback_correction: bool
    enable_context_memory: bool
    semantic_applicable: bool = True
    completion_applicable: bool = True


EXPERIMENT_GROUPS = [
    ExperimentGroup(
        group_id="fixed_policy_baseline",
        name="Fixed policy baseline",
        description="Uses deterministic household control rules without natural-language parsing.",
        runner_kind="baseline",
        llm_mode="none",
        execute_actions=True,
        enable_feedback_correction=False,
        enable_context_memory=False,
        semantic_applicable=False,
        completion_applicable=True,
    ),
    ExperimentGroup(
        group_id="rule_semantic_full",
        name="Rule semantic baseline",
        description="Uses mock semantic parsing with rule-based planning, execution, and feedback correction.",
        runner_kind="task_runner",
        llm_mode="mock",
        execute_actions=True,
        enable_feedback_correction=True,
        enable_context_memory=True,
    ),
    ExperimentGroup(
        group_id="real_semantic_planning",
        name="Real semantic parsing + planning",
        description="Uses a real LLM for semantic parsing and generates plans without executing device actions.",
        runner_kind="task_runner",
        llm_mode="real",
        execute_actions=False,
        enable_feedback_correction=False,
        enable_context_memory=True,
        completion_applicable=False,
    ),
    ExperimentGroup(
        group_id="real_no_feedback",
        name="Real parsing without feedback correction",
        description="Uses real semantic parsing, planning, and execution while disabling correction rounds.",
        runner_kind="task_runner",
        llm_mode="real",
        execute_actions=True,
        enable_feedback_correction=False,
        enable_context_memory=True,
    ),
    ExperimentGroup(
        group_id="real_no_context",
        name="Real parsing without context memory",
        description="Uses real semantic parsing, planning, execution, and feedback while disabling context memory.",
        runner_kind="task_runner",
        llm_mode="real",
        execute_actions=True,
        enable_feedback_correction=True,
        enable_context_memory=False,
    ),
    ExperimentGroup(
        group_id="full_system",
        name="Full workflow",
        description="Uses semantic parsing, rule-based planning, execution, feedback correction, and context memory.",
        runner_kind="task_runner",
        llm_mode="real",
        execute_actions=True,
        enable_feedback_correction=True,
        enable_context_memory=True,
    ),
]
GROUPS_BY_ID = {group.group_id: group for group in EXPERIMENT_GROUPS}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reproducible smart-home agent experiments.")
    parser.add_argument(
        "--tasks",
        default=str(PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"),
        help="Path to the fixed reproduction task JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "results" / "reproduction_experiments"),
        help="Directory where a timestamped reproduction result folder will be created.",
    )
    parser.add_argument(
        "--groups",
        default="all",
        help="Comma-separated group ids, or 'all'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N tasks for smoke tests.",
    )
    parser.add_argument(
        "--real-mode",
        choices=["real", "mock"],
        default="real",
        help="Use mock here only for local smoke tests without spending real LLM quota.",
    )
    args = parser.parse_args()

    load_dotenv(BACKEND_ROOT / ".env")
    tasks_path = Path(args.tasks)
    tasks = load_tasks(tasks_path)
    if args.limit is not None:
        tasks = tasks[: max(0, args.limit)]

    groups = resolve_groups(args.groups)
    if args.real_mode == "real":
        require_real_llm_if_needed(groups)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []
    for group in groups:
        group_records = run_group(group, tasks, output_dir, real_mode=args.real_mode)
        records.extend(group_records)
        group_summaries.append(summarize_records(group_records, group))

    records_csv = output_dir / "task_records.csv"
    summary_json = output_dir / "summary.json"
    chart_data_json = output_dir / "chart_data.json"
    report_md = output_dir / "reproduction_report.md"
    chart_csv_dir = output_dir / "chart_csv"
    chart_csv_dir.mkdir(parents=True, exist_ok=True)

    write_csv(records_csv, records)
    category_summaries = summarize_by_group_and_category(records)
    chart_data = build_chart_data(group_summaries, category_summaries, records)
    write_chart_csvs(chart_csv_dir, chart_data)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tasks_path": str(tasks_path),
        "task_count": len(tasks),
        "real_mode": args.real_mode,
        "groups": [group_to_dict(group) for group in groups],
        "group_summaries": group_summaries,
        "category_summaries": category_summaries,
        "output_paths": {
            "records_csv": str(records_csv),
            "summary_json": str(summary_json),
            "chart_data_json": str(chart_data_json),
            "chart_csv_dir": str(chart_csv_dir),
            "report_md": str(report_md),
        },
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    chart_data_json.write_text(json.dumps(chart_data, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(render_report(summary), encoding="utf-8")

    print(json.dumps({"output_dir": str(output_dir), **summary["output_paths"]}, ensure_ascii=False, indent=2))
    return 0


def load_tasks(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)
    tasks = payload["tasks"] if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("Task file must contain a list or a {'tasks': [...]} object.")
    return tasks


def resolve_groups(raw_groups: str) -> list[ExperimentGroup]:
    if raw_groups == "all":
        return EXPERIMENT_GROUPS
    group_ids = [item.strip() for item in raw_groups.split(",") if item.strip()]
    unknown = [group_id for group_id in group_ids if group_id not in GROUPS_BY_ID]
    if unknown:
        raise ValueError(f"Unknown experiment groups: {', '.join(unknown)}")
    return [GROUPS_BY_ID[group_id] for group_id in group_ids]


def require_real_llm_if_needed(groups: list[ExperimentGroup]) -> None:
    if not any(group.llm_mode == "real" for group in groups):
        return
    if not os.getenv("REAL_LLM_API_KEY"):
        raise RuntimeError(
            "Real LLM groups require REAL_LLM_API_KEY in backend/.env. "
            "For a quick local smoke test, pass --real-mode mock."
        )


def run_group(
    group: ExperimentGroup,
    tasks: list[dict[str, Any]],
    output_dir: Path,
    *,
    real_mode: str,
) -> list[dict[str, Any]]:
    environment = SmartHomeEnvironment()
    logger = ExperimentLogger(output_dir / "logs" / group.group_id)
    effective_llm_mode = "mock" if group.llm_mode == "real" and real_mode == "mock" else group.llm_mode
    records: list[dict[str, Any]] = []

    with temporary_llm_mode(effective_llm_mode):
        runner = None
        if group.runner_kind == "task_runner":
            runner = TaskRunner(
                environment=environment,
                experiment_logger=logger,
                refresh_realtime=False,
                enable_feedback_correction=group.enable_feedback_correction,
                enable_context_memory=group.enable_context_memory,
                execute_actions=group.execute_actions,
            )

        for task_index, task in enumerate(tasks, start=1):
            environment.reset(refresh_realtime=False)
            if runner is not None:
                runner.reset_context_memory()
            apply_task_setup(environment, task)

            started_at = time.perf_counter()
            pre_context_success = True
            if runner is not None:
                pre_context_success = run_pre_context_commands(runner, task)

            if group.runner_kind == "baseline":
                response = run_fixed_policy_baseline(environment, task)
            elif runner is not None:
                response = runner.run_agent_command(
                    AgentCommandRequest(
                        user_command=str(task["user_command"]),
                        current_room_id=task.get("current_room_id"),
                    )
                )
            else:
                raise RuntimeError(f"Unsupported runner_kind: {group.runner_kind}")

            response_time_ms = round((time.perf_counter() - started_at) * 1000, 2)
            record = build_record(
                group=group,
                task=task,
                task_index=task_index,
                response=response,
                environment=environment,
                response_time_ms=response_time_ms,
                pre_context_success=pre_context_success,
                effective_llm_mode=effective_llm_mode,
                real_mode=real_mode,
            )
            records.append(record)

    return records


@contextmanager
def temporary_llm_mode(mode: str):
    previous = os.environ.get("LLM_MODE")
    if mode != "none":
        os.environ["LLM_MODE"] = mode
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LLM_MODE", None)
        else:
            os.environ["LLM_MODE"] = previous


def apply_task_setup(environment: SmartHomeEnvironment, task: dict[str, Any]) -> None:
    env_updates = task.get("environment")
    if isinstance(env_updates, dict):
        environment.set_outdoor_environment(
            weather=env_updates.get("weather"),
            time_hour=env_updates.get("time_hour"),
        )

    expected_intent = str(task.get("expected_intent", ""))
    expected_room = str(task.get("expected_room", ""))
    current_room_id = task.get("current_room_id")
    if expected_intent == "away_mode":
        environment.set_away()
        return

    room_id = current_room_id if isinstance(current_room_id, str) else expected_room
    if room_id and room_id != "all_rooms":
        environment.set_current_room(room_id, activity_for_intent(expected_intent))


def activity_for_intent(intent: str) -> str:
    if intent == "study_mode":
        return "study"
    if intent == "movie_mode":
        return "movie"
    if intent == "sleep_mode":
        return "sleep"
    return "idle"


def run_pre_context_commands(runner: TaskRunner, task: dict[str, Any]) -> bool:
    commands = task.get("pre_context_commands", [])
    if not isinstance(commands, list):
        return True
    success = True
    for command in commands:
        if not isinstance(command, dict):
            continue
        response = runner.run_agent_command(
            AgentCommandRequest(
                user_command=str(command.get("user_command", "")),
                current_room_id=command.get("current_room_id"),
            )
        )
        success = success and response.success
    return success


def run_fixed_policy_baseline(environment: SmartHomeEnvironment, task: dict[str, Any]):
    state_before = environment.get_state(refresh_realtime=False)
    actions = plan_conventional_baseline_actions(state_before)
    results, final_state = environment.apply_device_actions_batch(actions, dt_minutes=5)
    semantic_result = expected_semantic_from_task(task)
    feedback_result = FeedbackAgent().evaluate(semantic_result, final_state, revision_round=0)

    success = all(item["success"] for item in results) if results else True
    return SimpleNamespace(
        success=success,
        semantic_result=semantic_result,
        plan_result={
            "plan_id": "fixed-policy-baseline",
            "agent": "fixed_policy_baseline",
            "intent": semantic_result["intent"],
            "room": semantic_result["room"],
            "scope": semantic_result["scope"],
            "control_goal": semantic_result["control_goal"],
            "actions": actions,
        },
        execution_result={
            "agent": "fixed_policy_baseline",
            "executed_count": sum(1 for item in results if item["success"]),
            "results": results,
            "final_state": final_state.model_dump(),
        },
        feedback_result=feedback_result,
        final_state=final_state,
        error="" if success else "fixed policy action failed",
    )


def expected_semantic_from_task(task: dict[str, Any]) -> dict[str, Any]:
    intent = str(task.get("expected_intent") or "basic_light_control")
    targets = dict(TARGETS_BY_INTENT.get(intent, TARGETS_BY_INTENT["basic_light_control"]))
    command = str(task.get("user_command", ""))
    if any(keyword in command for keyword in ["湿度", "潮", "洗澡"]):
        targets["humidity_percent_range"] = [40, 70]
    return {
        "intent": intent,
        "room": str(task.get("expected_room") or task.get("current_room_id") or "living_room"),
        "scope": str(task.get("expected_scope") or "single_room"),
        "control_goal": detect_control_goal(command, intent),
        "task_type": "device_control" if intent.startswith("basic_") else "scene_control",
        "targets": targets,
        "devices": list(task.get("expected_devices", [])),
        "constraints": {
            "comfort_first": intent not in {"away_mode", "energy_saving_mode"},
            "energy_saving": intent in {"away_mode", "energy_saving_mode"},
        },
        "llm_mode": "none",
    }


def detect_control_goal(command: str, intent: str) -> str:
    if any(keyword in command for keyword in ["关闭", "关掉", "关上", "全关", "不要"]):
        return "turn_off"
    if any(keyword in command for keyword in ["打开", "开启", "开到", "亮"]):
        return "turn_on"
    if intent.startswith("basic_"):
        return "turn_on"
    return "set_target"


def build_record(
    *,
    group: ExperimentGroup,
    task: dict[str, Any],
    task_index: int,
    response,
    environment: SmartHomeEnvironment,
    response_time_ms: float,
    pre_context_success: bool,
    effective_llm_mode: str,
    real_mode: str,
) -> dict[str, Any]:
    semantic = response.semantic_result or {}
    plan = response.plan_result or {}
    feedback = response.feedback_result or {}
    final_state = response.final_state or environment.get_state(refresh_realtime=False)
    expected_devices = [str(device) for device in task.get("expected_devices", [])]
    planned_actions = plan.get("actions", []) if isinstance(plan.get("actions", []), list) else []
    planned_device_types = sorted(device_types_from_actions(planned_actions))
    expected_device_accuracy = device_accuracy(expected_devices, planned_device_types)
    llm_metrics = semantic.get("llm_metrics", {}) if isinstance(semantic.get("llm_metrics"), dict) else {}

    intent_correct = bool(semantic.get("intent") == task.get("expected_intent")) if group.semantic_applicable else ""
    room_correct = bool(semantic.get("room") == task.get("expected_room")) if group.semantic_applicable else ""
    scope_correct = bool(semantic.get("scope") == task.get("expected_scope")) if group.semantic_applicable else ""
    completed = bool(feedback.get("completed", False)) if group.completion_applicable else ""
    occupied_comfort = occupied_comfort_score(final_state)
    failure_type = classify_failure(
        success=bool(response.success),
        semantic_applicable=group.semantic_applicable,
        completion_applicable=group.completion_applicable,
        intent_correct=intent_correct,
        room_correct=room_correct,
        scope_correct=scope_correct,
        device_accuracy_percent=expected_device_accuracy,
        completed=completed,
        error=str(response.error or ""),
    )

    return {
        "group_id": group.group_id,
        "group_name": group.name,
        "task_index": task_index,
        "task_id": task.get("task_id", f"P{task_index:03d}"),
        "category": task.get("category", "uncategorized"),
        "user_command": task.get("user_command", ""),
        "pre_context_count": len(task.get("pre_context_commands", []) or []),
        "pre_context_success": pre_context_success,
        "effective_llm_mode": effective_llm_mode,
        "real_mode": real_mode,
        "execute_actions": group.execute_actions,
        "feedback_correction_enabled": group.enable_feedback_correction,
        "context_memory_enabled": group.enable_context_memory,
        "success": bool(response.success),
        "completion_applicable": group.completion_applicable,
        "completed": completed,
        "semantic_applicable": group.semantic_applicable,
        "expected_intent": task.get("expected_intent", ""),
        "predicted_intent": semantic.get("intent", ""),
        "intent_correct": intent_correct,
        "expected_room": task.get("expected_room", ""),
        "predicted_room": semantic.get("room", ""),
        "room_correct": room_correct,
        "expected_scope": task.get("expected_scope", ""),
        "predicted_scope": semantic.get("scope", ""),
        "scope_correct": scope_correct,
        "expected_devices": "|".join(expected_devices),
        "planned_device_types": "|".join(planned_device_types),
        "device_selection_accuracy_percent": expected_device_accuracy,
        "action_count": len(planned_actions),
        "executed_count": int((response.execution_result or {}).get("executed_count", 0)),
        "correction_round": int(feedback.get("correction_round", 0) or 0),
        "response_time_ms": response_time_ms,
        "llm_request_ms": float(llm_metrics.get("request_ms", 0) or 0),
        "llm_prompt_bytes": int(llm_metrics.get("prompt_bytes", 0) or 0),
        "llm_cache_hit": bool(llm_metrics.get("cache_hit", False)),
        "current_power_w": final_state.energy_metrics.current_power_w,
        "baseline_power_w": final_state.energy_metrics.baseline_power_w,
        "energy_saving_rate_percent": final_state.energy_metrics.energy_saving_rate_percent,
        "average_comfort_score": final_state.comfort_metrics.average_overall_score,
        "occupied_comfort_score": occupied_comfort if occupied_comfort is not None else "",
        "comfort_retained": occupied_comfort >= 80 if occupied_comfort is not None and group.execute_actions else "",
        "failure_type": failure_type,
        "error": response.error or "",
    }


def device_types_from_actions(actions: list[dict[str, Any]]) -> set[str]:
    device_types: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        entity_id = str(action.get("entity_id", ""))
        if "." in entity_id:
            device_types.add(entity_id.split(".", 1)[0])
    return device_types


def device_accuracy(expected_devices: list[str], planned_device_types: list[str]) -> float | str:
    if not expected_devices:
        return ""
    planned = set(planned_device_types)
    expected = set(expected_devices)
    return round(len(expected & planned) / len(expected) * 100, 2)


def occupied_comfort_score(state) -> float | None:
    occupied_room = next((room for room in state.rooms if room.occupancy and room.activity != "away"), None)
    if occupied_room is None:
        return None
    comfort = next((item for item in state.comfort_metrics.rooms if item.room_id == occupied_room.room_id), None)
    return comfort.overall_comfort_score if comfort else None


def classify_failure(
    *,
    success: bool,
    semantic_applicable: bool,
    completion_applicable: bool,
    intent_correct: bool | str,
    room_correct: bool | str,
    scope_correct: bool | str,
    device_accuracy_percent: float | str,
    completed: bool | str,
    error: str,
) -> str:
    if not success:
        return "runtime_error" if error else "execution_error"
    if semantic_applicable:
        if intent_correct is False:
            return "semantic_intent_error"
        if room_correct is False:
            return "semantic_room_error"
        if scope_correct is False:
            return "semantic_scope_error"
    if isinstance(device_accuracy_percent, (int, float)) and device_accuracy_percent < 100:
        return "device_selection_mismatch"
    if completion_applicable and completed is False:
        return "feedback_not_completed"
    return "none"


def summarize_records(records: list[dict[str, Any]], group: ExperimentGroup) -> dict[str, Any]:
    return {
        "group_id": group.group_id,
        "group_name": group.name,
        "description": group.description,
        "sample_count": len(records),
        "success_rate_percent": rate(records, "success"),
        "task_completion_rate_percent": rate(records, "completed", "completion_applicable"),
        "intent_accuracy_percent": rate(records, "intent_correct", "semantic_applicable"),
        "room_accuracy_percent": rate(records, "room_correct", "semantic_applicable"),
        "scope_accuracy_percent": rate(records, "scope_correct", "semantic_applicable"),
        "device_selection_accuracy_percent": average(records, "device_selection_accuracy_percent"),
        "average_correction_round": average(records, "correction_round"),
        "average_response_time_ms": average(records, "response_time_ms"),
        "average_llm_request_ms": average(records, "llm_request_ms"),
        "llm_cache_hit_rate_percent": rate(records, "llm_cache_hit"),
        "average_current_power_w": average(records, "current_power_w"),
        "average_baseline_power_w": average(records, "baseline_power_w"),
        "average_energy_saving_rate_percent": average(records, "energy_saving_rate_percent"),
        "average_comfort_score": average(records, "average_comfort_score"),
        "average_occupied_comfort_score": average(records, "occupied_comfort_score"),
        "comfort_retention_rate_percent": rate(records, "comfort_retained"),
        "failure_counts": dict(Counter(record["failure_type"] for record in records)),
    }


def summarize_by_group_and_category(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    group_names = {record["group_id"]: record["group_name"] for record in records}
    for record in records:
        grouped[(record["group_id"], record["category"])].append(record)

    summaries = []
    for (group_id, category), items in sorted(grouped.items()):
        summaries.append(
            {
                "group_id": group_id,
                "group_name": group_names.get(group_id, group_id),
                "category": category,
                "sample_count": len(items),
                "success_rate_percent": rate(items, "success"),
                "task_completion_rate_percent": rate(items, "completed", "completion_applicable"),
                "intent_accuracy_percent": rate(items, "intent_correct", "semantic_applicable"),
                "room_accuracy_percent": rate(items, "room_correct", "semantic_applicable"),
                "scope_accuracy_percent": rate(items, "scope_correct", "semantic_applicable"),
                "device_selection_accuracy_percent": average(items, "device_selection_accuracy_percent"),
                "average_energy_saving_rate_percent": average(items, "energy_saving_rate_percent"),
                "average_occupied_comfort_score": average(items, "occupied_comfort_score"),
            }
        )
    return summaries


def rate(records: list[dict[str, Any]], field: str, applicability_field: str | None = None) -> float:
    applicable = [
        record
        for record in records
        if record.get(field) != ""
        and (applicability_field is None or record.get(applicability_field) is True)
    ]
    if not applicable:
        return 0.0
    return round(sum(1 for record in applicable if record.get(field) is True) / len(applicable) * 100, 2)


def average(records: list[dict[str, Any]], field: str) -> float:
    values = [
        float(record[field])
        for record in records
        if record.get(field) not in {"", None}
    ]
    return round(mean(values), 2) if values else 0.0


def build_chart_data(
    group_summaries: list[dict[str, Any]],
    category_summaries: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    correction_distribution = []
    grouped_rounds: dict[tuple[str, int], int] = Counter(
        (record["group_id"], int(record["correction_round"]))
        for record in records
        if record.get("completion_applicable") is True
    )
    group_names = {record["group_id"]: record["group_name"] for record in records}
    for (group_id, correction_round), count in sorted(grouped_rounds.items()):
        correction_distribution.append(
            {
                "group_id": group_id,
                "group_name": group_names.get(group_id, group_id),
                "correction_round": correction_round,
                "count": count,
            }
        )

    return {
        "method_completion_rate": [
            {
                "group_id": item["group_id"],
                "group_name": item["group_name"],
                "task_completion_rate_percent": item["task_completion_rate_percent"],
            }
            for item in group_summaries
        ],
        "method_energy_saving_rate": [
            {
                "group_id": item["group_id"],
                "group_name": item["group_name"],
                "average_energy_saving_rate_percent": item["average_energy_saving_rate_percent"],
            }
            for item in group_summaries
        ],
        "power_by_task": [
            {
                "task_index": record["task_index"],
                "task_id": record["task_id"],
                "group_id": record["group_id"],
                "group_name": record["group_name"],
                "current_power_w": record["current_power_w"],
                "baseline_power_w": record["baseline_power_w"],
            }
            for record in records
            if record.get("execute_actions") is True
        ],
        "comfort_by_task": [
            {
                "task_index": record["task_index"],
                "task_id": record["task_id"],
                "group_id": record["group_id"],
                "group_name": record["group_name"],
                "average_comfort_score": record["average_comfort_score"],
                "occupied_comfort_score": record["occupied_comfort_score"],
            }
            for record in records
            if record.get("execute_actions") is True
        ],
        "correction_round_distribution": correction_distribution,
        "semantic_accuracy_by_category": [
            {
                "group_id": item["group_id"],
                "group_name": item["group_name"],
                "category": item["category"],
                "intent_accuracy_percent": item["intent_accuracy_percent"],
                "room_accuracy_percent": item["room_accuracy_percent"],
                "scope_accuracy_percent": item["scope_accuracy_percent"],
            }
            for item in category_summaries
        ],
    }


def write_chart_csvs(chart_csv_dir: Path, chart_data: dict[str, list[dict[str, Any]]]) -> None:
    for name, rows in chart_data.items():
        write_csv(chart_csv_dir / f"{name}.csv", rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Reproduction Experiment Report",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Task file: `{summary['tasks_path']}`",
        f"- Task count: {summary['task_count']}",
        f"- LLM mode: `{summary['real_mode']}`",
        "",
        "## Experiment Groups",
        "",
        "| Group | Description | Executes actions | Feedback correction | Context memory |",
        "|---|---|---:|---:|---:|",
    ]
    for group in summary["groups"]:
        lines.append(
            f"| {group['name']} | {group['description']} | "
            f"{yes_no(group['execute_actions'])} | {yes_no(group['enable_feedback_correction'])} | "
            f"{yes_no(group['enable_context_memory'])} |"
        )

    lines.extend(
        [
            "",
            "## Overall Metrics",
            "",
            "| Group | Success % | Completion % | Intent accuracy % | Room accuracy % | Device selection accuracy % | Avg corrections | Avg response ms | Energy saving % | Occupied comfort | Comfort retention % |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summary["group_summaries"]:
        lines.append(
            f"| {item['group_name']} | {item['success_rate_percent']:.2f} | "
            f"{item['task_completion_rate_percent']:.2f} | {item['intent_accuracy_percent']:.2f} | "
            f"{item['room_accuracy_percent']:.2f} | {item['device_selection_accuracy_percent']:.2f} | "
            f"{item['average_correction_round']:.2f} | {item['average_response_time_ms']:.2f} | "
            f"{item['average_energy_saving_rate_percent']:.2f} | {item['average_occupied_comfort_score']:.2f} | "
            f"{item['comfort_retention_rate_percent']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Category Metrics",
            "",
            "| Group | Category | Samples | Completion % | Intent accuracy % | Room accuracy % | Scope accuracy % | Device selection accuracy % |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summary["category_summaries"]:
        lines.append(
            f"| {item['group_name']} | {item['category']} | {item['sample_count']} | "
            f"{item['task_completion_rate_percent']:.2f} | {item['intent_accuracy_percent']:.2f} | "
            f"{item['room_accuracy_percent']:.2f} | {item['scope_accuracy_percent']:.2f} | "
            f"{item['device_selection_accuracy_percent']:.2f} |"
        )

    lines.extend(["", "## Failure Counts", ""])
    for item in summary["group_summaries"]:
        counts = ", ".join(f"{key}: {value}" for key, value in sorted(item["failure_counts"].items()))
        lines.append(f"- {item['group_name']}: {counts or 'none'}")

    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- Records CSV: `{summary['output_paths']['records_csv']}`",
            f"- Summary JSON: `{summary['output_paths']['summary_json']}`",
            f"- Chart data JSON: `{summary['output_paths']['chart_data_json']}`",
            f"- Chart CSV directory: `{summary['output_paths']['chart_csv_dir']}`",
            "",
            "## Metric Notes",
            "",
            "- Completion rate is calculated for groups that execute virtual device actions.",
            "- Device selection accuracy checks whether expected device categories are covered by the plan.",
            "- Occupied comfort is calculated for rooms with active occupancy.",
            "- `--real-mode mock` is intended for local smoke tests without external LLM calls.",
        ]
    )
    return "\n".join(lines)

def group_to_dict(group: ExperimentGroup) -> dict[str, Any]:
    return {
        "group_id": group.group_id,
        "name": group.name,
        "description": group.description,
        "runner_kind": group.runner_kind,
        "llm_mode": group.llm_mode,
        "execute_actions": group.execute_actions,
        "enable_feedback_correction": group.enable_feedback_correction,
        "enable_context_memory": group.enable_context_memory,
        "semantic_applicable": group.semantic_applicable,
        "completion_applicable": group.completion_applicable,
    }


def yes_no(value: bool) -> str:
    return "是" if value else "否"


if __name__ == "__main__":
    raise SystemExit(main())
