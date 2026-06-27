import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.experiments.evaluation import summarize_batch_records
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.schemas.task_schema import AgentCommandRequest
from app.simulation.environment import SmartHomeEnvironment


def load_batch_tasks(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)
    tasks = payload["tasks"] if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("Batch task file must contain a list or a {'tasks': [...]} object.")
    return tasks


def run_batch_experiment(
    tasks_path: Path,
    output_dir: Path,
    reset_between_tasks: bool = True,
    limit: int | None = None,
    enable_multi_agent_review: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = SmartHomeEnvironment()
    logger = ExperimentLogger(output_dir)
    runner = TaskRunner(
        environment=environment,
        experiment_logger=logger,
        enable_multi_agent_review=enable_multi_agent_review,
    )
    tasks = load_batch_tasks(tasks_path)
    if limit is not None:
        tasks = tasks[: max(0, limit)]

    records: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        if reset_between_tasks:
            environment.reset()

        user_command = str(task["user_command"])
        started_at = time.perf_counter()
        response = runner.run_agent_command(AgentCommandRequest(user_command=user_command))
        response_time_ms = (time.perf_counter() - started_at) * 1000

        semantic = response.semantic_result or {}
        plan = response.plan_result or {}
        multi_agent_context = plan.get("multi_agent_context", {}) if isinstance(plan.get("multi_agent_context"), dict) else {}
        knowledge_result = multi_agent_context.get("knowledge_result", {}) if isinstance(multi_agent_context.get("knowledge_result"), dict) else {}
        safety_result = multi_agent_context.get("safety_result", {}) if isinstance(multi_agent_context.get("safety_result"), dict) else {}
        critic_result = multi_agent_context.get("critic_result", {}) if isinstance(multi_agent_context.get("critic_result"), dict) else {}
        rag_context = knowledge_result.get("rag_context", {}) if isinstance(knowledge_result.get("rag_context"), dict) else {}
        feedback = response.feedback_result or {}
        final_state = response.final_state or environment.get_state(refresh_realtime=False)
        expected_intent = task.get("expected_intent")
        expected_room = task.get("expected_room")
        expected_scope = task.get("expected_scope")
        predicted_intent = semantic.get("intent")
        predicted_room = semantic.get("room")
        predicted_scope = semantic.get("scope")

        record = {
            "task_index": index,
            "task_id": task.get("task_id", f"task_{index:03d}"),
            "category": task.get("category", "uncategorized"),
            "user_command": user_command,
            "success": bool(response.success),
            "completed": bool(feedback.get("completed", False)),
            "llm_mode": semantic.get("llm_mode", ""),
            "expected_intent": expected_intent,
            "predicted_intent": predicted_intent,
            "intent_correct": predicted_intent == expected_intent if expected_intent else "",
            "expected_room": expected_room,
            "predicted_room": predicted_room,
            "room_correct": predicted_room == expected_room if expected_room else "",
            "expected_scope": expected_scope,
            "predicted_scope": predicted_scope,
            "scope_correct": predicted_scope == expected_scope if expected_scope else "",
            "action_count": len(plan.get("actions", [])) if plan else 0,
            "multi_agent_enabled": enable_multi_agent_review,
            "rag_match_count": rag_context.get("match_count", 0),
            "safety_issue_count": len(safety_result.get("issues", [])) if isinstance(safety_result.get("issues"), list) else 0,
            "critic_approved": critic_result.get("approved", ""),
            "critic_needs_revision": critic_result.get("needs_revision", ""),
            "response_time_ms": round(response_time_ms, 2),
            "current_power_w": final_state.energy_metrics.current_power_w,
            "baseline_power_w": final_state.energy_metrics.baseline_power_w,
            "energy_saving_rate_percent": final_state.energy_metrics.energy_saving_rate_percent,
            "average_comfort_score": final_state.comfort_metrics.average_overall_score,
            "average_humidity_score": final_state.comfort_metrics.average_humidity_score,
            "error": response.error or "",
        }
        records.append(record)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"batch_results_{timestamp}.csv"
    summary_path = output_dir / f"batch_summary_{timestamp}.json"
    _write_csv(csv_path, records)
    summary = summarize_batch_records(records)
    summary.update(
        {
            "tasks_path": str(tasks_path),
            "csv_path": str(csv_path),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "reset_between_tasks": reset_between_tasks,
            "task_limit": limit,
            "multi_agent_enabled": enable_multi_agent_review,
        }
    )
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    return {
        "records": records,
        "summary": summary,
        "csv_path": csv_path,
        "summary_path": summary_path,
    }


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
