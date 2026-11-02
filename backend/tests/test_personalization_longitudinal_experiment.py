from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_personalization_longitudinal_experiment.py"
SPEC = importlib.util.spec_from_file_location("personalization_longitudinal_experiment", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
personalization_longitudinal_experiment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = personalization_longitudinal_experiment
SPEC.loader.exec_module(personalization_longitudinal_experiment)


def test_longitudinal_smoke_covers_four_methods_profiles_and_turns() -> None:
    records = personalization_longitudinal_experiment.run_longitudinal_smoke()

    assert len(records) == 4 * 2 * 5
    assert {record["method"] for record in records} == set(personalization_longitudinal_experiment.METHODS)
    assert {record["profile_id"] for record in records} == {"LP-001", "LP-002"}
    assert {record["turn_index"] for record in records} == {1, 2, 3, 4, 5}


def test_confirmed_experience_is_visible_only_after_explicit_feedback_gate() -> None:
    records = personalization_longitudinal_experiment.run_longitudinal_smoke()
    gated = [record for record in records if record["method"] == "gated_confirmed_memory"]
    ungated = [record for record in records if record["method"] == "ungated_memory"]
    no_memory = [record for record in records if record["method"] == "no_memory"]

    assert all(not record["confirmed_experience_visible"] for record in gated if record["turn_index"] < 3)
    assert all(record["confirmed_experience_visible"] for record in gated if record["turn_index"] >= 3)
    assert all(not record["confirmed_experience_visible"] for record in ungated)
    assert all(not record["confirmed_experience_visible"] for record in no_memory)
    assert sum(record["unauthorized_prior_exposure"] for record in ungated) == 8
    assert sum(record["unauthorized_prior_exposure"] for record in gated) == 0


def test_summary_bounds_longitudinal_smoke_claims() -> None:
    records = personalization_longitudinal_experiment.run_longitudinal_smoke()
    summary = personalization_longitudinal_experiment.summarize(records)
    by_method = {row["method"]: row for row in summary["method_summary"]}

    assert summary["schema_version"] == "personalization_longitudinal_experiment_v1"
    assert summary["record_count"] == 40
    assert by_method["gated_confirmed_memory"]["confirmed_visibility_rate_turns_3_to_5"] == 1.0
    assert by_method["gated_confirmed_memory"]["post_confirmation_visibility_rate"] == 1.0
    assert by_method["gated_confirmed_memory"]["utility_gain_post_minus_pre"] > 0
    assert by_method["static_profile"]["utility_gain_post_minus_pre"] == 0
    assert by_method["ungated_memory"]["unauthorized_prior_exposure_count"] == 8
    assert sum(row["safety_override_count"] for row in by_method.values()) == 0
    assert "not real resident feedback" in summary["claim_boundary"]


def test_longitudinal_full_matrix_expands_profiles_turns_methods_and_seeds() -> None:
    records = personalization_longitudinal_experiment.run_longitudinal(matrix="full")
    summary = personalization_longitudinal_experiment.summarize(records, matrix="full")
    by_method = {row["method"]: row for row in summary["method_summary"]}

    assert len(records) == 30 * 30 * 4 * 3
    assert summary["matrix"] == "full"
    assert summary["profile_count"] == 30
    assert summary["turn_count_per_profile"] == 30
    assert summary["repeat_count_per_profile"] == 3
    assert {record["repeat_seed"] for record in records} == {0, 1, 2}
    assert len({record["profile_id"] for record in records}) == 30

    assert by_method["gated_confirmed_memory"]["post_confirmation_visibility_rate"] == 1.0
    assert by_method["gated_confirmed_memory"]["unauthorized_prior_exposure_count"] == 0
    assert by_method["ungated_memory"]["unauthorized_prior_exposure_count"] == 30 * 3 * 29
    assert by_method["gated_confirmed_memory"]["utility_gain_post_minus_pre"] > 0
    assert by_method["static_profile"]["utility_gain_post_minus_pre"] == 0
    assert sum(row["safety_override_count"] for row in by_method.values()) == 0
