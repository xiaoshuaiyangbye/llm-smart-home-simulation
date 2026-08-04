import importlib.util
import os
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_personalization_experiments.py"
SPEC = importlib.util.spec_from_file_location("personalization_experiments", SCRIPT_PATH)
assert SPEC and SPEC.loader
personalization_experiments = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = personalization_experiments
SPEC.loader.exec_module(personalization_experiments)


def test_disturbance_is_a_shared_seed_paired_condition() -> None:
    nominal = personalization_experiments.robustness_config_for("nominal", 19)
    disturbed = personalization_experiments.robustness_config_for("disturbed", 19)

    assert nominal.seed == disturbed.seed == 19
    assert nominal.enabled is False
    assert disturbed.enabled is True
    assert disturbed.temperature_sensor_noise_c == 0.5
    assert disturbed.illuminance_sensor_noise_lux == 30
    assert disturbed.actuator_failure_probability == 0.1


def test_protocol_requires_within_condition_and_seed_comparisons() -> None:
    protocol = personalization_experiments.build_experiment_protocol()

    assert protocol["methods"] == {
        "single_agent": "No multi-agent review and no preference adaptation.",
        "multi_agent_static": "Multi-agent review without preference adaptation.",
        "personalized": "Multi-agent review with preference-adapted targets.",
    }
    assert set(protocol["conditions"]) == {"nominal", "disturbed"}
    assert protocol["seeds"] == [7, 19, 31]
    assert protocol["task_ids"] == ["P001", "P002", "P003", "P004", "P005", "P006", "P007"]
    provenance = protocol["artifact_provenance"]
    assert provenance["runner_source_sha256"] == personalization_experiments.runner_source_sha256()
    assert provenance["task_suite_sha256"] == personalization_experiments.task_suite_sha256()
    assert "requires regenerating" in provenance["interpretation_rule"]
    assert "same condition, experiment seed, and task_id" in protocol["comparison_rule"]
    assert "fresh deterministic SmartHomeEnvironment" in protocol["task_initialization"]
    assert "SHA-256" in protocol["disturbance_seed_derivation"]
    assert "Every method is scored" in protocol["outcome_evaluation"]
    assert "post-control cumulative-energy increment" in protocol["outcome_evaluation"]
    assert "30 minutes" in protocol["post_control_evaluation"]
    assert "default mock mode" in protocol["semantic_execution"]
    assert protocol["semantic_runtime_provenance"]["provenance_status"] == "reproducible_mock_baseline"
    assert "task-cluster bootstrap" in protocol["aggregation"]
    assert "insufficient_task_clusters" in protocol["aggregation"]
    assert "only a safety action change" in protocol["multi_agent_intervention_coverage"]
    assert [(fixture["task_id"], fixture["fault_id"]) for fixture in protocol["safety_fault_fixtures"]] == [
        ("P005", "SFI-001"),
        ("P006", "SFI-002"),
        ("P007", "SFI-003"),
    ]
    assert "three deterministic fault-mechanism" in protocol["safety_fixture_claim_boundary"]
    assert "not significance tests" in protocol["inference_limitation"]
    assert "fewer than 3 task clusters" in protocol["inference_limitation"]


def test_task_disturbance_seeds_are_stable_and_task_specific() -> None:
    seeds = [
        personalization_experiments.task_disturbance_seed(19, task_id)
        for task_id, *_ in personalization_experiments.TASKS
    ]

    assert seeds == [
        personalization_experiments.task_disturbance_seed(19, task_id)
        for task_id, *_ in personalization_experiments.TASKS
    ]
    assert len(set(seeds)) == len(personalization_experiments.TASKS)


def test_all_ablation_methods_emit_the_same_outcome_metrics(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")

    records = [
        record
        for method in personalization_experiments.METHODS
        for record in personalization_experiments.run_method(method, "nominal", 7)
    ]

    assert {record["method"] for record in records} == set(personalization_experiments.METHODS)
    assert all(isinstance(record["utility"], float) for record in records)
    assert all(isinstance(record["satisfaction"], float) for record in records)
    assert {record["semantic_mode_configured"] for record in records} == {"mock"}
    assert {record["semantic_mode_effective"] for record in records} == {"mock"}
    assert {record["semantic_model_id"] for record in records} == {"rule-based-mock-v1"}
    assert {record["semantic_model_revision"] for record in records} == {"not_applicable"}
    assert {record["semantic_model_revision_source"] for record in records} == {"not_applicable"}
    assert {record["semantic_provenance_status"] for record in records} == {"reproducible_mock_baseline"}
    assert len({record["semantic_runtime_fingerprint"] for record in records}) == 1
    assert {record["runner_source_sha256"] for record in records} == {
        personalization_experiments.runner_source_sha256()
    }
    assert {record["task_suite_sha256"] for record in records} == {
        personalization_experiments.task_suite_sha256()
    }
    assert all(record["initial_time_step"] == 0 for record in records)
    assert {record["post_control_evaluation_minutes"] for record in records} == {30}
    assert {record["evaluation_time_step"] for record in records} == {30}
    assert {record["comfort_measurement"] for record in records} == {"occupied_room_overall_score"}
    assert all(float(record["energy_kwh"]) > 0 for record in records)
    assert {record["energy_measurement"] for record in records} == {"post_control_horizon_kwh"}
    assert all(float(record["energy_baseline_kwh"]) > 0 for record in records)
    assert all(0 <= float(record["objective_energy_score"]) <= 100 for record in records)
    assert {record["safety_measurement"] for record in records} == {
        "final_executable_plan_severity_penalty_v1"
    }
    assert all(0 <= float(record["safety_score"]) <= 100 for record in records)
    assert len({record["initial_state_fingerprint"] for record in records}) == 1
    for task_id, *_ in personalization_experiments.TASKS:
        matching = [record for record in records if record["task_id"] == task_id]
        assert len(matching) == len(personalization_experiments.METHODS)
        assert {record["disturbance_seed"] for record in matching} == {
            personalization_experiments.task_disturbance_seed(7, task_id)
        }
    fault_records = [record for record in records if record["task_id"] in {"P005", "P006", "P007"}]
    assert {record["evaluation_scenario"] for record in fault_records} == {"safety_fault_injection"}
    assert {record["safety_fault_id"] for record in fault_records} == {"SFI-001", "SFI-002", "SFI-003"}
    assert all(record["safety_fault_injected"] for record in fault_records)
    for fault_id in ("SFI-001", "SFI-002", "SFI-003"):
        fixture_records = [record for record in fault_records if record["safety_fault_id"] == fault_id]
        baseline_fault = next(record for record in fixture_records if record["method"] == "single_agent")
        # The single-agent baseline receives diagnostic assessment but no safety
        # intervention, so the hazard remains in its final executable action.
        assert baseline_fault["safety_fault_detected"] is True
        assert baseline_fault["safety_fault_blocked"] is False
        assert baseline_fault["safety_score"] == 20.0
        assert baseline_fault["safety_high_issue_count"] == 1
        for method in ("multi_agent_static", "personalized"):
            reviewed_fault = next(record for record in fixture_records if record["method"] == method)
            assert reviewed_fault["safety_action_changed"] is True
            assert reviewed_fault["safety_fault_detected"] is True
            assert reviewed_fault["safety_fault_blocked"] is True
            assert reviewed_fault["safety_score"] == 100.0
            assert reviewed_fault["safety_high_issue_count"] == 0


def _record(method: str, task_id: str, utility: float, fingerprint: str = "initial") -> dict[str, object]:
    return {
        "method": method,
        "condition": "nominal",
        "seed": 7,
        "task_id": task_id,
        "disturbance_seed": 100 + int(task_id[-1]),
        "initial_state_fingerprint": fingerprint,
        "post_control_evaluation_minutes": 30,
        "evaluation_time_step": 30,
        "comfort_measurement": "occupied_room_overall_score",
        "completed": True,
        "comfort_score": 80.0,
        "energy_kwh": 2.0,
        "objective_energy_score": 50.0,
        "safety_score": 100.0,
        "safety_measurement": "final_executable_plan_severity_penalty_v1",
        "utility": utility,
        "satisfaction": 70.0,
    }


def test_paired_summary_reports_reproducible_effects_and_intervals() -> None:
    records = [
        _record("single_agent", "P001", 50.0),
        _record("single_agent", "P002", 60.0),
        _record("single_agent", "P003", 70.0),
        _record("multi_agent_static", "P001", 52.0),
        _record("multi_agent_static", "P002", 62.0),
        _record("multi_agent_static", "P003", 72.0),
    ]

    first = personalization_experiments.build_paired_summary(records)
    second = personalization_experiments.build_paired_summary(records)

    assert first == second
    comparison = first["comparisons"][0]
    utility = comparison["metrics"]["weighted_utility"]
    assert comparison["paired_run_count"] == 3
    assert comparison["paired_task_count"] == 3
    assert comparison["seed_replicates_per_task"] == [1]
    assert "post_control_evaluation_minutes" in comparison["pairing_fields"]
    assert "seed" not in comparison["task_cluster_fields"]
    assert utility["mean_difference_candidate_minus_reference"] == 2.0
    assert utility["paired_bootstrap_95_ci"] == [2.0, 2.0]
    assert "not significance tests" in first["claim_guardrail"]
    coverage = first["intervention_coverage"]
    baseline_nominal = next(item for item in coverage if item["method"] == "single_agent")
    assert baseline_nominal["multi_agent_review_coverage"] == "not_applicable_no_multi_agent_review"
    static_nominal = next(item for item in coverage if item["method"] == "multi_agent_static")
    assert static_nominal["multi_agent_review_coverage"] == "not_observed_non_discriminative"
    assert static_nominal["feedback_correction_coverage"] == "not_observed"
    assert static_nominal["review_or_feedback_intervention_count"] == 0
    assert "non-discriminative" in first["multi_agent_mechanism_guardrail"]
    assert "Paired Uncertainty Summary" in personalization_experiments.render_paired_summary_markdown(first)
    assert "Artifact Provenance" in personalization_experiments.render_paired_summary_markdown(first)


def test_paired_summary_clusters_root_seed_replicates_before_bootstrap() -> None:
    records = []
    for task_id, utility in (("P001", 50.0), ("P002", 60.0), ("P003", 70.0)):
        for seed in (7, 19, 31):
            reference = _record("single_agent", task_id, utility)
            candidate = _record(
                "multi_agent_static",
                task_id,
                utility + {"P001": 2.0, "P002": 6.0, "P003": 4.0}[task_id],
            )
            for record in (reference, candidate):
                record["seed"] = seed
                record["disturbance_seed"] = 10_000 + seed + int(task_id[-1])
            records.extend((reference, candidate))

    summary = personalization_experiments.build_paired_summary(records)
    comparison = summary["comparisons"][0]
    utility = comparison["metrics"]["weighted_utility"]

    assert comparison["paired_run_count"] == 9
    assert comparison["paired_task_count"] == 3
    assert comparison["seed_replicates_per_task"] == [3]
    assert utility["mean_difference_candidate_minus_reference"] == 4.0
    assert utility["paired_bootstrap_95_ci"] == personalization_experiments._bootstrap_interval(
        [2.0, 6.0, 4.0],
        analysis_key="nominal:ordinary_control:multi_agent_static:weighted_utility",
    )


def test_paired_summary_with_one_task_cluster_suppresses_bootstrap_interval() -> None:
    summary = personalization_experiments.build_paired_summary(
        [
            _record("single_agent", "P005", 50.0),
            _record("multi_agent_static", "P005", 70.0),
        ]
    )

    comparison = summary["comparisons"][0]
    utility = comparison["metrics"]["weighted_utility"]

    assert comparison["paired_task_count"] == 1
    assert comparison["minimum_task_clusters_for_bootstrap"] == 3
    assert utility["mean_difference_candidate_minus_reference"] == 20.0
    assert utility["paired_bootstrap_95_ci"] is None
    assert utility["uncertainty_status"] == "insufficient_task_clusters"
    assert "N/A (insufficient task clusters)" in personalization_experiments.render_paired_summary_markdown(summary)


def test_paired_summary_marks_observed_review_or_feedback_interventions() -> None:
    reference = _record("single_agent", "P001", 50.0)
    candidate = _record("multi_agent_static", "P001", 52.0)
    candidate.update(
        multi_agent_review_enabled=True,
        safety_issue_count=1,
        safety_action_changed=True,
        feedback_correction_round=1,
        feedback_correction_applied=True,
    )

    summary = personalization_experiments.build_paired_summary([reference, candidate])

    coverage = next(item for item in summary["intervention_coverage"] if item["method"] == "multi_agent_static")
    assert coverage["safety_issue_count"] == 1
    assert coverage["safety_action_changed_count"] == 1
    assert coverage["feedback_correction_applied_count"] == 1
    assert coverage["review_or_feedback_intervention_count"] == 1
    assert coverage["multi_agent_review_coverage"] == "observed"
    assert coverage["feedback_correction_coverage"] == "observed"


def test_paired_summary_rejects_initial_state_mismatch() -> None:
    records = [
        _record("single_agent", "P001", 50.0, "state-a"),
        _record("multi_agent_static", "P001", 52.0, "state-b"),
    ]

    with pytest.raises(ValueError, match="Unpaired records"):
        personalization_experiments.build_paired_summary(records)


def test_paired_summary_rejects_semantic_backend_mismatch() -> None:
    reference = _record("single_agent", "P001", 50.0)
    candidate = _record("multi_agent_static", "P001", 52.0)
    reference.update(semantic_mode_effective="mock", semantic_model_id="rule-based-mock-v1")
    candidate.update(semantic_mode_effective="real", semantic_model_id="qwen3:8b")

    with pytest.raises(ValueError, match="Unpaired records"):
        personalization_experiments.build_paired_summary([reference, candidate])


def test_real_semantic_provenance_requires_an_immutable_revision(monkeypatch) -> None:
    monkeypatch.setenv("REAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("REAL_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("REAL_LLM_MAX_TOKENS", "600")
    monkeypatch.setenv("REAL_LLM_TEMPERATURE", "0.0")
    monkeypatch.setenv("REAL_LLM_SEED", "1729")
    monkeypatch.delenv("REAL_LLM_MODEL_REVISION", raising=False)
    monkeypatch.setattr(personalization_experiments, "ollama_model_digest", lambda *_: None)

    unversioned = personalization_experiments.semantic_runtime_provenance("real")

    assert unversioned["model_id"] == "qwen3:8b"
    assert unversioned["model_revision"] == "unrecorded"
    assert unversioned["provenance_status"] == "unversioned_real_model"
    assert unversioned["model_revision_source"] == "unavailable"
    assert unversioned["decoding"]["temperature"] == 0.0
    assert unversioned["decoding"]["seed"] == 1729
    assert "http://localhost" not in str(unversioned)

    monkeypatch.setenv("REAL_LLM_MODEL_REVISION", "sha256:immutable-ollama-digest")
    versioned = personalization_experiments.semantic_runtime_provenance("real")

    assert versioned["provenance_status"] == "versioned_real_model"
    assert versioned["model_revision_source"] == "configured_environment"
    assert versioned["semantic_runtime_fingerprint"] != unversioned["semantic_runtime_fingerprint"]


def test_real_semantic_provenance_records_matching_ollama_digest(monkeypatch) -> None:
    monkeypatch.setenv("REAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("REAL_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("REAL_LLM_MODEL_REVISION", raising=False)
    monkeypatch.setattr(
        personalization_experiments,
        "ollama_model_digest",
        lambda base_url, model_id: "sha256:immutable-ollama-digest"
        if (base_url, model_id) == ("http://localhost:11434/v1", "qwen3:8b")
        else None,
    )

    provenance = personalization_experiments.semantic_runtime_provenance("real")

    assert provenance["model_revision"] == "sha256:immutable-ollama-digest"
    assert provenance["model_revision_source"] == "ollama_api_tags"
    assert provenance["provenance_status"] == "versioned_real_model"


def test_real_semantic_provenance_bridges_docker_ollama_hostname(monkeypatch) -> None:
    monkeypatch.setenv("REAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("REAL_LLM_BASE_URL", "http://host.docker.internal:11434/v1")
    monkeypatch.delenv("REAL_LLM_MODEL_REVISION", raising=False)
    monkeypatch.setattr(
        personalization_experiments,
        "ollama_model_digest",
        lambda base_url, model_id: "sha256:local-digest"
        if (base_url, model_id) == ("http://localhost:11434/v1", "qwen3:8b")
        else None,
    )

    provenance = personalization_experiments.semantic_runtime_provenance("real")

    assert provenance["model_revision"] == "sha256:local-digest"
    assert provenance["model_revision_source"] == "ollama_api_tags_localhost_fallback"
    assert provenance["provenance_status"] == "versioned_real_model"


def test_ollama_tags_url_requires_an_openai_compatible_v1_endpoint() -> None:
    assert personalization_experiments.ollama_tags_url("http://localhost:11434/v1") == "http://localhost:11434/api/tags"
    assert personalization_experiments.ollama_tags_url("https://api.example.com/v1") is None
    assert personalization_experiments.ollama_tags_url("https://example.invalid/api") is None


def test_selected_environment_file_configures_real_experiment_without_overwriting_shell(tmp_path, monkeypatch) -> None:
    environment_file = tmp_path / "backend.env"
    environment_file.write_text(
        "REAL_LLM_API_KEY=file-key\n"
        "REAL_LLM_BASE_URL=http://localhost:11434/v1\n"
        "REAL_LLM_MODEL=qwen3:8b\n"
        "REAL_LLM_MODEL_REVISION=sha256:ollama-digest\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("REAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("REAL_LLM_MODEL", raising=False)
    monkeypatch.delenv("REAL_LLM_MODEL_REVISION", raising=False)
    monkeypatch.setenv("REAL_LLM_API_KEY", "shell-key")

    assert personalization_experiments.load_experiment_environment(environment_file) is True
    provenance = personalization_experiments.semantic_runtime_provenance("real")

    assert os.environ["REAL_LLM_API_KEY"] == "shell-key"
    assert provenance["model_id"] == "qwen3:8b"
    assert provenance["model_revision"] == "sha256:ollama-digest"
    assert provenance["provenance_status"] == "versioned_real_model"


def test_missing_environment_file_is_reported_without_mutating_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("REAL_LLM_MODEL", raising=False)

    assert personalization_experiments.load_experiment_environment(tmp_path / "missing.env") is False
    assert "REAL_LLM_MODEL" not in os.environ


def test_paired_summary_rejects_semantic_runtime_fingerprint_mismatch() -> None:
    reference = _record("single_agent", "P001", 50.0)
    candidate = _record("multi_agent_static", "P001", 52.0)
    reference.update(
        semantic_mode_effective="real",
        semantic_model_id="qwen3:8b",
        semantic_model_revision="sha256:a",
        semantic_runtime_fingerprint="runtime-a",
    )
    candidate.update(
        semantic_mode_effective="real",
        semantic_model_id="qwen3:8b",
        semantic_model_revision="sha256:a",
        semantic_runtime_fingerprint="runtime-b",
    )

    with pytest.raises(ValueError, match="Unpaired records"):
        personalization_experiments.build_paired_summary([reference, candidate])


def test_paired_summary_rejects_implementation_fingerprint_mismatch() -> None:
    reference = _record("single_agent", "P001", 50.0)
    candidate = _record("multi_agent_static", "P001", 52.0)
    reference.update(runner_source_sha256="runner-a", task_suite_sha256="tasks-a")
    candidate.update(runner_source_sha256="runner-b", task_suite_sha256="tasks-a")

    with pytest.raises(ValueError, match="Unpaired records"):
        personalization_experiments.build_paired_summary([reference, candidate])
