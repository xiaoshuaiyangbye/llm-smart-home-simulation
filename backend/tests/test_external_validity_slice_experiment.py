from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_external_validity_slice_experiment.py"
SPEC = importlib.util.spec_from_file_location("external_validity_slice_experiment", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
external_validity_slice_experiment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = external_validity_slice_experiment
SPEC.loader.exec_module(external_validity_slice_experiment)


def test_external_validity_fixture_covers_building_climate_and_season_axes() -> None:
    fixture = external_validity_slice_experiment.load_fixture()

    assert len(fixture["buildings"]) == 2
    assert len(fixture["climates"]) == 2
    assert len(fixture["seasons"]) == 2
    assert fixture["days_per_slice"] == 2


def test_external_validity_slice_smoke_generates_expected_records() -> None:
    records = external_validity_slice_experiment.run_external_validity_slice()

    assert len(records) == 2 * 2 * 2 * 4 * 2
    assert {record["control_policy"] for record in records} == set(
        external_validity_slice_experiment.CONTROL_POLICIES
    )
    assert {record["source_externality"] for record in records} == {
        "synthetic_public_standard_inspired_slice"
    }
    assert all(float(record["daily_energy_kwh"]) >= 0 for record in records)


def test_external_validity_summary_keeps_adapter_boundary() -> None:
    fixture = external_validity_slice_experiment.load_fixture()
    records = external_validity_slice_experiment.run_external_validity_slice()
    summary = external_validity_slice_experiment.summarize(records, fixture)
    by_policy = {row["control_policy"]: row for row in summary["policy_summary"]}

    assert summary["schema_version"] == "external_validity_slice_smoke_v1"
    assert summary["record_count"] == 64
    assert summary["slice_count"] == 8
    assert by_policy["energy_saving"]["mean_daily_energy_kwh"] < by_policy["comfort_first"]["mean_daily_energy_kwh"]
    assert (
        by_policy["energy_saving"]["mean_comfort_violation_minutes"]
        > by_policy["rule_baseline"]["mean_comfort_violation_minutes"]
    )
    assert "not calibrated field data" in summary["claim_boundary"]
