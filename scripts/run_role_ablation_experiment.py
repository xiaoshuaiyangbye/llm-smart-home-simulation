"""Run component-level role ablations for the center-orchestrated agents."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.collaboration_agent import CollaborationAgent
from app.agents.critic_agent import CriticAgent
from app.agents.execution_agent import ExecutionAgent
from app.agents.feedback_agent import FeedbackAgent
from app.agents.safety_agent import SafetyAgent
from app.simulation.environment import SmartHomeEnvironment

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "results" / "role_ablation"
FULL_UNIQUE_TASKS = 200
FULL_REPEATS_PER_TASK = 3
ROLE_GROUPS = {
    "single": {
        "safety": False,
        "critic": False,
        "execution": True,
        "feedback": False,
    },
    "planner_only": {
        "safety": False,
        "critic": False,
        "execution": False,
        "feedback": False,
    },
    "plus_safety": {
        "safety": True,
        "critic": False,
        "execution": True,
        "feedback": False,
    },
    "plus_critic": {
        "safety": False,
        "critic": True,
        "execution": True,
        "feedback": False,
    },
    "plus_feedback": {
        "safety": False,
        "critic": False,
        "execution": True,
        "feedback": True,
    },
    "full": {
        "safety": True,
        "critic": True,
        "execution": True,
        "feedback": True,
    },
}
TASKS = [
    {
        "task_id": "RA-001",
        "scenario": "ordinary_lighting",
        "room": "study_room",
        "semantic": {
            "intent": "lighting_comfort_control",
            "room": "study_room",
            "scope": "single_room",
            "targets": {"illuminance_lux_range": [500, 800], "temperature_c_range": [18, 30]},
            "constraints": {"comfort_first": True, "energy_saving": False},
        },
        "actions": [
            {
                "entity_id": "light.study_room_main",
                "action": "turn_on",
                "parameters": {"brightness_pct": 80, "color_temperature_k": 4000},
                "reason": "frozen planner output for role ablation",
            }
        ],
    },
    {
        "task_id": "RA-002",
        "scenario": "high_safety_fault",
        "room": "bedroom",
        "semantic": {
            "intent": "thermal_comfort_control",
            "room": "bedroom",
            "scope": "single_room",
            "targets": {"illuminance_lux_range": [0, 1200], "temperature_c_range": [24, 28]},
            "constraints": {"avoid_overcooling": True, "cooling_setpoint_floor_c": 26},
        },
        "actions": [
            {
                "entity_id": "ac.bedroom_main",
                "action": "set_temperature",
                "parameters": {"mode": "cool", "setpoint_c": 16},
                "reason": "frozen unsafe planner output for role ablation",
            }
        ],
    },
    {
        "task_id": "RA-003",
        "scenario": "medium_energy_conflict",
        "room": "living_room",
        "semantic": {
            "intent": "thermal_comfort_control",
            "room": "living_room",
            "scope": "single_room",
            "targets": {"illuminance_lux_range": [0, 1200], "temperature_c_range": [22, 26]},
            "constraints": {"comfort_first": True, "energy_saving": True},
        },
        "actions": [
            {
                "entity_id": "ac.living_room_main",
                "action": "turn_on",
                "parameters": {"mode": "cool", "setpoint_c": 24},
                "reason": "frozen cooling action for role ablation",
            },
            {
                "entity_id": "window.living_room_main",
                "action": "set_opening",
                "parameters": {"opening_pct": 60},
                "reason": "frozen ventilation conflict for role ablation",
            },
        ],
    },
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _variant_task(task: dict[str, Any], variant_index: int, repeat_seed: int) -> dict[str, Any]:
    variant = json.loads(json.dumps(task))
    variant["task_id"] = f"{task['task_id']}-V{variant_index + 1:03d}"
    variant["variant_index"] = variant_index
    variant["repeat_seed"] = repeat_seed
    step = variant_index + repeat_seed
    for action in variant["actions"]:
        parameters = action.setdefault("parameters", {})
        if "brightness_pct" in parameters:
            parameters["brightness_pct"] = int(max(35, min(100, float(parameters["brightness_pct"]) + (step % 9) - 4)))
        if "color_temperature_k" in parameters:
            parameters["color_temperature_k"] = int(float(parameters["color_temperature_k"]) + ((step % 5) - 2) * 100)
        if "opening_pct" in parameters:
            parameters["opening_pct"] = int(max(35, min(100, float(parameters["opening_pct"]) + (step % 10) - 4)))
        if "setpoint_c" in parameters and parameters.get("mode") == "cool":
            floor = float(variant["semantic"].get("constraints", {}).get("cooling_setpoint_floor_c", 26))
            parameters["setpoint_c"] = round(min(floor - 0.5, float(parameters["setpoint_c"]) + (step % 6) * 0.5), 1)
        parameters["role_ablation_variant_index"] = variant_index
        parameters["role_ablation_repeat_seed"] = repeat_seed
        action["reason"] = (
            f"{action.get('reason', 'role ablation full fixture')}; "
            f"variant={variant_index}; repeat_seed={repeat_seed}"
        ).strip("; ")
    return variant


def _tasks_for_matrix(matrix: str) -> list[dict[str, Any]]:
    if matrix == "smoke":
        return [json.loads(json.dumps(task)) for task in TASKS]
    if matrix != "full":
        raise ValueError("matrix must be smoke or full")
    tasks: list[dict[str, Any]] = []
    for variant_index in range(FULL_UNIQUE_TASKS):
        template = TASKS[variant_index % len(TASKS)]
        tasks.append(_variant_task(template, variant_index, repeat_seed=0))
    return tasks


def _plan_for(task: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "plan_id": f"{task['task_id']}-role-ablation",
        "agent": "planning_agent",
        "intent": task["semantic"]["intent"],
        "room": task["room"],
        "actions": actions,
    }


def _safety_score(remaining_issues: list[dict[str, Any]]) -> float:
    if not remaining_issues:
        return 100.0
    if any(issue.get("severity") == "high" for issue in remaining_issues):
        return 20.0
    return 60.0


def run_role_ablation(matrix: str = "smoke") -> list[dict[str, Any]]:
    safety_agent = SafetyAgent()
    critic_agent = CriticAgent()
    collaboration_agent = CollaborationAgent()
    execution_agent = ExecutionAgent()
    feedback_agent = FeedbackAgent()
    records: list[dict[str, Any]] = []

    tasks = _tasks_for_matrix(matrix)
    repeat_count = 1 if matrix == "smoke" else FULL_REPEATS_PER_TASK
    for task in tasks:
        for repeat_seed in range(repeat_count):
            task_variant = task if matrix == "smoke" else _variant_task(TASKS[task["variant_index"] % len(TASKS)], task["variant_index"], repeat_seed)
            for group_id, config in ROLE_GROUPS.items():
                record = _run_one_role_group(
                    task_variant,
                    group_id,
                    config,
                    safety_agent,
                    critic_agent,
                    collaboration_agent,
                    execution_agent,
                    feedback_agent,
                    matrix,
                    repeat_seed,
                )
                records.append(record)
    return records


def _run_one_role_group(
    task: dict[str, Any],
    group_id: str,
    config: dict[str, bool],
    safety_agent: SafetyAgent,
    critic_agent: CriticAgent,
    collaboration_agent: CollaborationAgent,
    execution_agent: ExecutionAgent,
    feedback_agent: FeedbackAgent,
    matrix: str,
    repeat_seed: int,
) -> dict[str, Any]:
            environment = SmartHomeEnvironment()
            semantic = dict(task["semantic"])
            original_actions = list(task["actions"])
            plan = _plan_for(task, original_actions)

            if config["safety"]:
                safety_result = safety_agent.review(semantic, plan)
                plan["actions"] = safety_result["actions"]
            else:
                assessment = safety_agent.assess(semantic, original_actions)
                safety_result = {
                    "passed": not any(issue.get("severity") == "high" for issue in assessment["issues"]),
                    "issues": assessment["issues"],
                    "remaining_issues": assessment["issues"],
                    "unsafe_action_detected": bool(assessment["issues"]),
                    "unsafe_action_blocked": False,
                    "actions_changed": False,
                    "actions": original_actions,
                }
            safety_action_changed = bool(safety_result.get("actions_changed", False))

            critic_changed = False
            if config["critic"]:
                critic_result = critic_agent.review(
                    semantic,
                    plan,
                    safety_result,
                    {"recommendation": "not_measured_in_component_ablation"},
                    {"recommendation": "not_measured_in_component_ablation"},
                    {"rag_context": {"match_count": 1}},
                )
                revision = collaboration_agent.apply_critic_revision(plan, critic_result)
                critic_changed = bool(revision["actions_changed"])
                plan = revision["plan_result"]
                safety_result = safety_agent.review(semantic, plan) if config["safety"] else safety_result
            else:
                critic_result = {
                    "approved": True,
                    "needs_revision": False,
                    "findings": [],
                    "revision_requests": [],
                }

            execution_success = False
            feedback_completed: bool | str = "not_applicable"
            feedback_correction_count = 0
            if config["execution"]:
                execution_result = execution_agent.execute(plan, environment)
                execution_success = all(bool(item.get("success")) for item in execution_result["results"])
                if config["feedback"]:
                    feedback = feedback_agent.evaluate(
                        semantic,
                        environment.get_state(refresh_realtime=False),
                    )
                    feedback_completed = bool(feedback["completed"])
                    feedback_correction_count = len(feedback.get("correction_actions", []))
                else:
                    feedback = {"completed": "not_run", "correction_actions": []}
            else:
                execution_result = {"executed_count": 0, "results": []}
                feedback = {"completed": "not_applicable", "correction_actions": []}

            remaining_issues = (
                safety_agent.assess(semantic, list(plan["actions"]))["issues"]
                if config["safety"] or config["critic"]
                else safety_result["remaining_issues"]
            )
            remaining_high_issue_count = sum(
                1 for issue in remaining_issues if isinstance(issue, dict) and issue.get("severity") == "high"
            )
            any_action_changed = list(plan["actions"]) != original_actions
            final_state_success = bool(config["execution"]) and remaining_high_issue_count == 0 and bool(execution_success)
            ordinary_task_side_effect = task["scenario"] == "ordinary_lighting" and any_action_changed
            role_stage_count = int(config["safety"]) + int(config["critic"]) + int(config["execution"]) + int(config["feedback"])
            return {
                "matrix": matrix,
                "group_id": group_id,
                "task_id": task["task_id"],
                "base_task_id": task["task_id"].split("-V", 1)[0],
                "variant_index": int(task.get("variant_index", 0)),
                "repeat_seed": repeat_seed,
                "scenario": task["scenario"],
                "safety_enabled": bool(config["safety"]),
                "critic_enabled": bool(config["critic"]),
                "execution_enabled": bool(config["execution"]),
                "feedback_enabled": bool(config["feedback"]),
                "original_action_count": len(original_actions),
                "final_action_count": len(plan["actions"]),
                "safety_issue_count": len(safety_result["issues"]),
                "remaining_issue_count": len(remaining_issues),
                "remaining_high_issue_count": remaining_high_issue_count,
                "recovery_success": remaining_high_issue_count == 0,
                "safety_action_changed": safety_action_changed,
                "critic_finding_count": len(critic_result.get("findings", [])),
                "critic_needs_revision": bool(critic_result.get("needs_revision", False)),
                "critic_action_changed": critic_changed,
                "execution_success": execution_success,
                "final_state_success": final_state_success,
                "feedback_completed": feedback_completed,
                "feedback_correction_count": feedback_correction_count,
                "any_action_changed": any_action_changed,
                "ordinary_task_side_effect": ordinary_task_side_effect,
                "request_latency_proxy_us": 100 + role_stage_count * 25 + len(plan["actions"]) * 10,
                "safety_score": _safety_score(remaining_issues),
                "evidence_class": "component_level_software_role_ablation",
            }


def summarize(records: list[dict[str, Any]], matrix: str = "smoke") -> dict[str, Any]:
    by_group = defaultdict(list)
    by_scenario = defaultdict(list)
    for record in records:
        by_group[record["group_id"]].append(record)
        by_scenario[(record["scenario"], record["group_id"])].append(record)

    group_summary = []
    for group_id, rows in sorted(by_group.items()):
        group_summary.append(
            {
                "group_id": group_id,
                "record_count": len(rows),
                "action_change_rate": mean(bool(row["any_action_changed"]) for row in rows),
                "safety_action_change_rate": mean(bool(row["safety_action_changed"]) for row in rows),
                "critic_action_change_rate": mean(bool(row["critic_action_changed"]) for row in rows),
                "mean_safety_score": mean(float(row["safety_score"]) for row in rows),
                "recovery_success_rate": mean(bool(row["recovery_success"]) for row in rows),
                "final_state_success_rate": mean(bool(row["final_state_success"]) for row in rows),
                "ordinary_task_side_effect_rate": mean(bool(row["ordinary_task_side_effect"]) for row in rows),
                "mean_request_latency_proxy_us": mean(float(row["request_latency_proxy_us"]) for row in rows),
                "feedback_correction_rate": mean(
                    float(row["feedback_correction_count"] > 0)
                    for row in rows
                    if row["feedback_enabled"]
                )
                if any(row["feedback_enabled"] for row in rows)
                else None,
            }
        )

    scenario_summary = []
    for (scenario, group_id), rows in sorted(by_scenario.items()):
        scenario_summary.append(
            {
                "scenario": scenario,
                "group_id": group_id,
                "record_count": len(rows),
                "action_changed": any(bool(row["any_action_changed"]) for row in rows),
                "remaining_issue_count": sum(int(row["remaining_issue_count"]) for row in rows),
                "recovery_success_rate": mean(bool(row["recovery_success"]) for row in rows),
                "final_state_success_rate": mean(bool(row["final_state_success"]) for row in rows),
                "mean_safety_score": mean(float(row["safety_score"]) for row in rows),
            }
        )

    return {
        "schema_version": "role_ablation_experiment_v1",
        "matrix": matrix,
        "evidence_class": "component_level_software_role_ablation",
        "task_count": len({record["task_id"] for record in records}),
        "repeat_count_per_task": 1 if matrix == "smoke" else FULL_REPEATS_PER_TASK,
        "group_count": len(ROLE_GROUPS),
        "record_count": len(records),
        "groups": ROLE_GROUPS,
        "group_summary": group_summary,
        "scenario_summary": scenario_summary,
        "claim_boundary": (
            "This component run isolates observable role contributions on frozen candidate plans. "
            "It is not a full end-to-end multi-agent benchmark, not decentralized agent negotiation, "
            "and not evidence of real-home safety or resident outcomes."
        ),
        "provenance": {
            "runner_sha256": _sha256(Path(__file__)),
            "safety_agent_sha256": _sha256(BACKEND_ROOT / "app" / "agents" / "safety_agent.py"),
            "critic_agent_sha256": _sha256(BACKEND_ROOT / "app" / "agents" / "critic_agent.py"),
            "collaboration_agent_sha256": _sha256(BACKEND_ROOT / "app" / "agents" / "collaboration_agent.py"),
            "feedback_agent_sha256": _sha256(BACKEND_ROOT / "app" / "agents" / "feedback_agent.py"),
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Multi-Agent Role Ablation Experiment",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        f"- Matrix: `{summary['matrix']}`",
        f"- Groups: `{summary['group_count']}`",
        f"- Tasks: `{summary['task_count']}`",
        f"- Repeats per task: `{summary['repeat_count_per_task']}`",
        f"- Records: `{summary['record_count']}`",
        "",
        "## Group Summary",
        "",
        "| Group | Records | Action change rate | Safety change rate | Critic change rate | Recovery success rate | Final-state success rate | Ordinary side-effect rate | Mean latency proxy us | Mean safety score | Feedback correction rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["group_summary"]:
        feedback_rate = row["feedback_correction_rate"]
        lines.append(
            f"| {row['group_id']} | {row['record_count']} | {row['action_change_rate']:.3f} | "
            f"{row['safety_action_change_rate']:.3f} | {row['critic_action_change_rate']:.3f} | "
            f"{row['recovery_success_rate']:.3f} | {row['final_state_success_rate']:.3f} | "
            f"{row['ordinary_task_side_effect_rate']:.3f} | {row['mean_request_latency_proxy_us']:.3f} | "
            f"{row['mean_safety_score']:.3f} | "
            f"{feedback_rate:.3f} |" if feedback_rate is not None else
            f"| {row['group_id']} | {row['record_count']} | {row['action_change_rate']:.3f} | "
            f"{row['safety_action_change_rate']:.3f} | {row['critic_action_change_rate']:.3f} | "
            f"{row['recovery_success_rate']:.3f} | {row['final_state_success_rate']:.3f} | "
            f"{row['ordinary_task_side_effect_rate']:.3f} | {row['mean_request_latency_proxy_us']:.3f} | "
            f"{row['mean_safety_score']:.3f} | N/A |"
        )
    lines.extend(
        [
            "",
            "## Scenario Summary",
            "",
            "| Scenario | Group | Records | Action changed | Remaining issues | Recovery success rate | Final-state success rate | Mean safety score |",
            "|---|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in summary["scenario_summary"]:
        lines.append(
            f"| {row['scenario']} | {row['group_id']} | {row['record_count']} | "
            f"{row['action_changed']} | {row['remaining_issue_count']} | "
            f"{row['recovery_success_rate']:.3f} | {row['final_state_success_rate']:.3f} | "
            f"{row['mean_safety_score']:.3f} |"
        )
    lines.extend(["", "## Evidence Boundary", "", summary["claim_boundary"], ""])
    return "\n".join(lines)


def write_artifacts(records: list[dict[str, Any]], summary: dict[str, Any], output_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_dir = output_root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=False)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    (artifact_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    with (artifact_dir / "records.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return artifact_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--matrix", choices=("smoke", "full"), default="smoke")
    args = parser.parse_args()
    records = run_role_ablation(matrix=args.matrix)
    summary = summarize(records, matrix=args.matrix)
    artifact_dir = write_artifacts(records, summary, args.output_dir)
    print(
        json.dumps(
            {
                "artifact_dir": str(artifact_dir),
                "schema_version": summary["schema_version"],
                "matrix": summary["matrix"],
                "group_count": summary["group_count"],
                "task_count": summary["task_count"],
                "repeat_count_per_task": summary["repeat_count_per_task"],
                "record_count": summary["record_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
