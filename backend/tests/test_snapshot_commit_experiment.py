from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from app.runtime.snapshot_commit import evaluate_snapshot_commit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_snapshot_commit_experiment.py"
SPEC = importlib.util.spec_from_file_location("snapshot_commit_experiment", SCRIPT_PATH)
assert SPEC and SPEC.loader
snapshot_commit_experiment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = snapshot_commit_experiment
SPEC.loader.exec_module(snapshot_commit_experiment)


def test_production_default_rejects_stale_snapshot_and_duplicates() -> None:
    stale = evaluate_snapshot_commit(
        snapshot_revision=1,
        current_revision=2,
        snapshot_preference_fingerprint="a",
        current_preference_fingerprint="a",
        commit_id="commit-a",
        committed_action_ids=(),
    )
    duplicate = evaluate_snapshot_commit(
        snapshot_revision=1,
        current_revision=1,
        snapshot_preference_fingerprint="a",
        current_preference_fingerprint="a",
        commit_id="commit-a",
        committed_action_ids=("commit-a",),
    )

    assert stale.allowed is False
    assert stale.status == "stale_snapshot_replan_required"
    assert duplicate.allowed is False
    assert duplicate.status == "duplicate_commit_suppressed"


def test_isolated_ablation_changes_only_freshness_enforcement() -> None:
    records = snapshot_commit_experiment.run_trials(3)
    report = snapshot_commit_experiment.summarize(records)
    primary = report["primary_comparison"]

    assert len(records) == 12
    assert primary["guarded_stale_committed_rate"] == 0.0
    assert primary["unguarded_stale_committed_rate"] == 1.0
    assert primary["absolute_stale_commit_rate_reduction"] == 1.0
    assert primary["guarded_valid_commit_rate"] == 1.0
    assert primary["unguarded_valid_commit_rate"] == 1.0


def test_pressure_matrix_smoke_preserves_default_ablation_contract() -> None:
    records = snapshot_commit_experiment.run_pressure_matrix("smoke")
    report = snapshot_commit_experiment.summarize_pressure_matrix(records)

    assert len(records) == 24
    assert report["schema_version"] == "snapshot_commit_pressure_matrix_v1"
    assert {record["policy"] for record in records} == {"unguarded", "optimistic"}
    assert {record["planner_delay_ms"] for record in records} == {0, 250}
    assert {record["event_rate"] for record in records} == {0.0, 1.0}
    assert {record["fault_rate"] for record in records} == {0.0}

    stale_unguarded = [
        record for record in records
        if record["policy"] == "unguarded" and record["event_rate"] == 1.0
    ]
    stale_optimistic = [
        record for record in records
        if record["policy"] == "optimistic" and record["event_rate"] == 1.0
    ]

    assert all(record["stale_committed"] for record in stale_unguarded)
    assert not any(record["stale_committed"] for record in stale_optimistic)
    assert all(record["commit_status"] == "stale_snapshot_replan_required" for record in stale_optimistic)
