from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_safety_fault_taxonomy_experiment.py"
SPEC = importlib.util.spec_from_file_location("safety_fault_taxonomy_experiment", SCRIPT_PATH)
assert SPEC and SPEC.loader
safety_fault_taxonomy_experiment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = safety_fault_taxonomy_experiment
SPEC.loader.exec_module(safety_fault_taxonomy_experiment)


def test_taxonomy_has_fifteen_unique_software_fault_categories() -> None:
    taxonomy = safety_fault_taxonomy_experiment.load_taxonomy()
    categories = taxonomy["categories"]

    assert taxonomy["schema_version"] == "smart_home_safety_fault_taxonomy_v1"
    assert len(categories) == 15
    assert len({category["id"] for category in categories}) == 15
    assert {category["hazard_family"] for category in categories} == {
        "airflow_health_constraint",
        "energy_conflict",
        "thermal_health_constraint",
    }
    assert "not a calibrated distribution" in taxonomy["claim_boundary"]


def test_safety_review_blocks_high_faults_and_preserves_medium_warnings() -> None:
    taxonomy = safety_fault_taxonomy_experiment.load_taxonomy()
    records = safety_fault_taxonomy_experiment.run_taxonomy(taxonomy)

    assert len(records) == 30
    assert {record["method"] for record in records} == {"no_review", "safety_review"}

    high_reviewed = [
        record
        for record in records
        if record["method"] == "safety_review" and record["severity"] == "high"
    ]
    medium_reviewed = [
        record
        for record in records
        if record["method"] == "safety_review" and record["severity"] == "medium"
    ]
    baseline_high = [
        record
        for record in records
        if record["method"] == "no_review" and record["severity"] == "high"
    ]

    assert all(record["detected"] for record in high_reviewed)
    assert all(record["blocked"] for record in high_reviewed)
    assert all(record["safety_score"] == 100.0 for record in high_reviewed)
    assert all(record["detected"] for record in medium_reviewed)
    assert not any(record["blocked"] for record in medium_reviewed)
    assert all(record["safety_score"] == 60.0 for record in medium_reviewed)
    assert all(record["detected"] for record in baseline_high)
    assert not any(record["blocked"] for record in baseline_high)
    assert all(record["safety_score"] == 20.0 for record in baseline_high)


def test_full_matrix_expands_taxonomy_variants_methods_and_repeats() -> None:
    taxonomy = safety_fault_taxonomy_experiment.load_taxonomy()
    records = safety_fault_taxonomy_experiment.run_taxonomy(taxonomy, matrix="full")
    summary = safety_fault_taxonomy_experiment.summarize(
        records,
        taxonomy,
        safety_fault_taxonomy_experiment.DEFAULT_TAXONOMY,
        matrix="full",
    )

    assert len(records) == 3600
    assert summary["matrix"] == "full"
    assert summary["variant_count_per_category"] == 20
    assert summary["repeats_per_variant"] == 3
    assert set(summary["methods"]) == {"no_review", "safety_review", "critic_review", "full"}
    assert {record["repeat_seed"] for record in records} == {0, 1, 2}
    assert len({record["variant_id"] for record in records}) == 300

    full_high_faults = [
        record
        for record in records
        if record["method"] == "full" and record["severity"] == "high"
    ]
    critic_medium_conflicts = [
        record
        for record in records
        if record["method"] == "critic_review" and record["severity"] == "medium"
    ]

    assert all(record["recovery_success"] for record in full_high_faults)
    assert all(record["critic_action_changed"] for record in critic_medium_conflicts)
    assert not any(record["false_block"] for record in records)


def test_summary_reports_method_and_family_level_boundaries() -> None:
    taxonomy = safety_fault_taxonomy_experiment.load_taxonomy()
    records = safety_fault_taxonomy_experiment.run_taxonomy(taxonomy)
    summary = safety_fault_taxonomy_experiment.summarize(
        records,
        taxonomy,
        safety_fault_taxonomy_experiment.DEFAULT_TAXONOMY,
    )
    report = safety_fault_taxonomy_experiment.render_markdown(
        {**summary, "generated_at": "2026-09-01T00:00:00+00:00"}
    )

    assert summary["schema_version"] == "safety_fault_taxonomy_experiment_v1"
    assert summary["category_count"] == 15
    assert summary["record_count"] == 30
    assert summary["provenance"]["taxonomy_sha256"]
    assert summary["provenance"]["critic_agent_sha256"]
    assert summary["provenance"]["collaboration_agent_sha256"]
    assert "real-home faults" in summary["claim_boundary"]
    assert "Hazard Families" in report
