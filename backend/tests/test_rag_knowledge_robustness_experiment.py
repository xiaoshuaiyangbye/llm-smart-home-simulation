from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_rag_knowledge_robustness_experiment.py"
SPEC = importlib.util.spec_from_file_location("rag_knowledge_robustness_experiment", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
rag_knowledge_robustness_experiment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rag_knowledge_robustness_experiment
SPEC.loader.exec_module(rag_knowledge_robustness_experiment)


def test_rag_robustness_smoke_covers_conditions_tasks_and_review_modes() -> None:
    records = rag_knowledge_robustness_experiment.run_rag_robustness_smoke()

    assert len(records) == 5 * 3 * 2
    assert {record["rag_condition"] for record in records} == set(
        rag_knowledge_robustness_experiment.RAG_CONDITIONS
    )
    assert {record["review_mode"] for record in records} == {"planner_only", "safety_review"}
    assert {record["task_id"] for record in records} == {"RAG-001", "RAG-002", "RAG-003"}


def test_malicious_rag_records_hierarchy_violation_and_safety_review_blocks_high_faults() -> None:
    records = rag_knowledge_robustness_experiment.run_rag_robustness_smoke()
    malicious = [record for record in records if record["rag_condition"] == "malicious_rag"]
    planner_only = [record for record in malicious if record["review_mode"] == "planner_only"]
    reviewed = [record for record in malicious if record["review_mode"] == "safety_review"]

    assert all(record["instruction_hierarchy_violation"] for record in malicious)
    assert any(record["high_issue_count_after_review"] for record in planner_only)
    assert all(record["high_issue_count_after_review"] == 0 for record in reviewed)
    assert any(record["actions_changed_by_review"] for record in reviewed)


def test_summary_keeps_synthetic_rag_boundary() -> None:
    records = rag_knowledge_robustness_experiment.run_rag_robustness_smoke()
    summary = rag_knowledge_robustness_experiment.summarize(records)
    by_key = {
        (row["rag_condition"], row["review_mode"]): row
        for row in summary["condition_summary"]
    }

    assert summary["schema_version"] == "rag_knowledge_robustness_experiment_v1"
    assert summary["record_count"] == 30
    assert by_key[("correct_rag", "planner_only")]["unsafe_action_rate_after_review"] == 0
    assert by_key[("malicious_rag", "planner_only")]["instruction_hierarchy_violation_rate"] == 1
    assert by_key[("malicious_rag", "safety_review")]["review_action_change_rate"] > 0
    assert "does not modify the production RAG index" in summary["claim_boundary"]


def test_full_matrix_expands_rag_tasks_conditions_repeats_and_review_modes() -> None:
    records = rag_knowledge_robustness_experiment.run_rag_robustness(matrix="full")
    summary = rag_knowledge_robustness_experiment.summarize(records, matrix="full")
    by_key = {
        (row["rag_condition"], row["review_mode"]): row
        for row in summary["condition_summary"]
    }

    assert len(records) == 100 * 5 * 3 * 2
    assert summary["matrix"] == "full"
    assert summary["base_task_count"] == 100
    assert summary["knowledge_trial_count"] == 100 * 5 * 3
    assert summary["repeat_count_per_task"] == 3
    assert {record["repeat_seed"] for record in records} == {0, 1, 2}
    assert len({record["task_id"] for record in records}) == 100
    assert len({record["knowledge_source_id"] for record in records if record["rag_condition"] != "no_rag"}) == 1200

    assert by_key[("malicious_rag", "planner_only")]["attack_recall_proxy"] == 1
    assert by_key[("correct_rag", "planner_only")]["attack_false_positive_proxy"] == 0
    assert by_key[("malicious_rag", "safety_review")]["review_action_change_rate"] > 0
    assert by_key[("no_rag", "planner_only")]["source_provenance_coverage"] == 0
    assert by_key[("correct_rag", "planner_only")]["source_provenance_coverage"] == 1
