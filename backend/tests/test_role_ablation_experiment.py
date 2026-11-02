from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_role_ablation_experiment.py"
SPEC = importlib.util.spec_from_file_location("role_ablation_experiment", SCRIPT_PATH)
assert SPEC and SPEC.loader
role_ablation_experiment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = role_ablation_experiment
SPEC.loader.exec_module(role_ablation_experiment)


def test_role_ablation_smoke_runs_six_groups_over_three_tasks() -> None:
    records = role_ablation_experiment.run_role_ablation()

    assert len(records) == 18
    assert {record["group_id"] for record in records} == set(role_ablation_experiment.ROLE_GROUPS)
    assert {record["scenario"] for record in records} == {
        "ordinary_lighting",
        "high_safety_fault",
        "medium_energy_conflict",
    }


def test_role_ablation_isolates_safety_and_critic_action_changes() -> None:
    records = role_ablation_experiment.run_role_ablation()

    high_fault = [
        record for record in records
        if record["scenario"] == "high_safety_fault"
    ]
    energy_conflict = [
        record for record in records
        if record["scenario"] == "medium_energy_conflict"
    ]

    assert next(record for record in high_fault if record["group_id"] == "single")["safety_score"] == 20.0
    assert next(record for record in high_fault if record["group_id"] == "plus_safety")["safety_score"] == 100.0
    assert next(record for record in high_fault if record["group_id"] == "plus_safety")["safety_action_changed"]
    assert next(record for record in high_fault if record["group_id"] == "full")["safety_score"] == 100.0
    assert next(record for record in high_fault if record["group_id"] == "full")["safety_action_changed"]
    assert not next(record for record in energy_conflict if record["group_id"] == "plus_safety")["any_action_changed"]
    assert next(record for record in energy_conflict if record["group_id"] == "plus_critic")["critic_action_changed"]
    assert next(record for record in energy_conflict if record["group_id"] == "full")["critic_action_changed"]


def test_role_ablation_full_matrix_expands_tasks_groups_and_repeats() -> None:
    records = role_ablation_experiment.run_role_ablation(matrix="full")
    summary = role_ablation_experiment.summarize(records, matrix="full")

    assert len(records) == 3600
    assert summary["matrix"] == "full"
    assert summary["task_count"] == 200
    assert summary["repeat_count_per_task"] == 3
    assert summary["group_count"] == 6
    assert {record["repeat_seed"] for record in records} == {0, 1, 2}

    high_fault_records = [
        record
        for record in records
        if record["scenario"] == "high_safety_fault"
    ]
    energy_conflict_records = [
        record
        for record in records
        if record["scenario"] == "medium_energy_conflict"
    ]
    ordinary_records = [
        record
        for record in records
        if record["scenario"] == "ordinary_lighting"
    ]

    assert all(
        record["recovery_success"]
        for record in high_fault_records
        if record["group_id"] in {"plus_safety", "full"}
    )
    assert not any(
        record["recovery_success"]
        for record in high_fault_records
        if record["group_id"] in {"single", "planner_only", "plus_critic", "plus_feedback"}
    )
    assert all(
        record["critic_action_changed"]
        for record in energy_conflict_records
        if record["group_id"] in {"plus_critic", "full"}
    )
    assert not any(record["ordinary_task_side_effect"] for record in ordinary_records)


def test_role_ablation_summary_keeps_component_boundary() -> None:
    records = role_ablation_experiment.run_role_ablation()
    summary = role_ablation_experiment.summarize(records)
    report = role_ablation_experiment.render_markdown(
        {**summary, "generated_at": "2026-09-01T00:00:00+00:00"}
    )

    assert summary["schema_version"] == "role_ablation_experiment_v1"
    assert summary["group_count"] == 6
    assert summary["task_count"] == 3
    assert summary["record_count"] == 18
    assert "not a full end-to-end multi-agent benchmark" in summary["claim_boundary"]
    assert "Role Ablation Experiment" in report
