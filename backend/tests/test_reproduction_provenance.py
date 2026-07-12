import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_A = "a" * 64
SEMANTIC_B = "b" * 64
SEMANTIC_C = "c" * 64
PLAN_A = "d" * 64
PLAN_B = "e" * 64
RUNTIME_A = "f" * 64
RUNTIME_BEFORE = "0" * 64
RUNTIME_AFTER = "1" * 64
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_reproduction_experiments.py"
SPEC = importlib.util.spec_from_file_location("reproduction_experiments", SCRIPT_PATH)
assert SPEC and SPEC.loader
reproduction_experiments = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reproduction_experiments
SPEC.loader.exec_module(reproduction_experiments)


def test_mock_override_is_visible_in_real_group_display_name() -> None:
    group = reproduction_experiments.GROUPS_BY_ID["real_no_feedback"]

    effective_mode = reproduction_experiments.effective_llm_mode_for_group(group, "mock")

    assert effective_mode == "mock"
    assert reproduction_experiments.display_group_name(group, effective_mode).endswith("[semantic=mock]")
    assert reproduction_experiments.group_to_dict(group, "mock")["effective_llm_mode"] == "mock"


def test_real_execution_preserves_real_group_name() -> None:
    group = reproduction_experiments.GROUPS_BY_ID["real_no_feedback"]

    effective_mode = reproduction_experiments.effective_llm_mode_for_group(group, "real")

    assert effective_mode == "real"
    assert reproduction_experiments.display_group_name(group, effective_mode) == group.name


def test_reproduction_runtime_provenance_uses_selected_environment(
    monkeypatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "docker-backend.env"
    env_file.write_text(
        "REAL_LLM_API_KEY=ollama\n"
        "REAL_LLM_BASE_URL=http://host.docker.internal:11434/v1\n"
        "REAL_LLM_MODEL=qwen3:8b\n"
        "REAL_LLM_MODEL_REVISION=sha256:fixed-model-digest\n"
        "REAL_LLM_MAX_TOKENS=600\n",
        encoding="utf-8",
    )
    for variable in (
        "REAL_LLM_API_KEY",
        "REAL_LLM_BASE_URL",
        "REAL_LLM_CONFIGURED_BASE_URL",
        "REAL_LLM_ENDPOINT_RESOLUTION",
        "REAL_LLM_MODEL",
        "REAL_LLM_MODEL_REVISION",
        "REAL_LLM_MAX_TOKENS",
    ):
        monkeypatch.delenv(variable, raising=False)

    assert reproduction_experiments.load_experiment_environment(env_file) is True
    provenance = reproduction_experiments.semantic_runtime_provenance("real")

    assert reproduction_experiments.os.environ["REAL_LLM_BASE_URL"] == "http://localhost:11434/v1"
    assert provenance["model_id"] == "qwen3:8b"
    assert provenance["model_revision"] == "sha256:fixed-model-digest"
    assert provenance["model_revision_source"] == "configured_environment"
    assert provenance["provenance_status"] == "versioned_real_model"
    assert provenance["endpoint_resolution"] == "host_docker_internal_to_localhost"
    assert provenance["semantic_adapter_sha256"] == reproduction_experiments.semantic_adapter_sha256()
    assert provenance["semantic_runtime_fingerprint"]


def test_task_loader_rejects_empty_missing_and_duplicate_task_ids(tmp_path: Path) -> None:
    """Task IDs are experiment-unit keys, never optional display labels."""
    cases = [
        ([], "at least one reproduction task"),
        ([{"user_command": "打开客厅灯"}], "unique, non-empty task_id"),
        (
            [
                {"task_id": "P001", "user_command": "打开客厅灯"},
                {"task_id": "P001", "user_command": "关闭客厅灯"},
            ],
            "unique, non-empty task_id",
        ),
    ]

    for index, (tasks, expected_error) in enumerate(cases):
        path = tmp_path / f"invalid-tasks-{index}.json"
        path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")

        try:
            reproduction_experiments.load_tasks(path)
        except ValueError as error:
            assert expected_error in str(error)
        else:
            raise AssertionError("Expected invalid task-suite IDs to fail before execution.")


def test_task_loader_rejects_malformed_pre_context_commands(tmp_path: Path) -> None:
    """Context setup is part of the measured task chain, never skippable input."""
    cases = [
        ("not-a-list", "must be a list"),
        ([None], "must be an object"),
        ([{"user_command": "   "}], "user_command must be a non-empty string"),
        ([{"user_command": "打开灯", "current_room_id": "unknown_room"}], "invalid command request"),
        ([{"user_command": "打开灯", "room": "living_room"}], "unsupported keys"),
    ]

    for index, (commands, expected_error) in enumerate(cases):
        path = tmp_path / f"invalid-pre-context-{index}.json"
        path.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": f"X{index:03d}",
                            "user_command": "打开客厅灯",
                            "pre_context_commands": commands,
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        try:
            reproduction_experiments.load_tasks(path)
        except ValueError as error:
            assert expected_error in str(error)
        else:
            raise AssertionError("Expected malformed pre-context commands to fail before execution.")


def test_task_loader_rejects_malformed_main_command(tmp_path: Path) -> None:
    """The measured command is input data, never a value to coerce with str()."""
    cases = [
        ({"user_command": None}, "user_command must be a non-empty string"),
        ({"user_command": "   "}, "user_command must be a non-empty string"),
        ({"user_command": "打开灯", "current_room_id": False}, "current_room_id must be a non-empty string or null"),
        ({"user_command": "打开灯", "current_room_id": "unknown_room"}, "invalid command request"),
    ]

    for index, (command, expected_error) in enumerate(cases):
        path = tmp_path / f"invalid-main-command-{index}.json"
        path.write_text(
            json.dumps({"tasks": [{"task_id": f"M{index:03d}", **command}]}, ensure_ascii=False),
            encoding="utf-8",
        )

        try:
            reproduction_experiments.load_tasks(path)
        except ValueError as error:
            assert expected_error in str(error)
        else:
            raise AssertionError("Expected malformed main command to fail before execution.")


def test_planning_only_group_does_not_report_execution_outcomes(tmp_path: Path) -> None:
    group = reproduction_experiments.GROUPS_BY_ID["real_semantic_planning"]
    task = reproduction_experiments.load_tasks(PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json")[0]

    records = reproduction_experiments.run_group(group, [task], tmp_path, real_mode="mock")
    summary = reproduction_experiments.summarize_records(records, group)
    chart_data = reproduction_experiments.build_chart_data([summary], [], records)

    assert records[0]["outcome_metrics_applicable"] is False
    assert records[0]["semantic_provenance_status"] == "reproducible_mock_baseline"
    assert records[0]["energy_saving_rate_percent"] == ""
    assert summary["task_completion_rate_percent"] is None
    assert summary["average_energy_saving_rate_percent"] is None
    assert summary["average_occupied_comfort_score"] is None
    assert chart_data["method_completion_rate"] == []
    assert chart_data["method_energy_saving_rate"] == []


def test_fixed_policy_baseline_does_not_report_oracle_target_accuracy(tmp_path: Path) -> None:
    """A baseline's feedback-only reference must not be scored as parsing."""
    group = reproduction_experiments.GROUPS_BY_ID["fixed_policy_baseline"]
    task = reproduction_experiments.load_tasks(
        PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
    )[0]

    records = reproduction_experiments.run_group(group, [task], tmp_path, real_mode="mock")
    summary = reproduction_experiments.summarize_records(records, group)
    category_summary = reproduction_experiments.summarize_by_group_and_category(records)[0]

    assert records[0]["semantic_applicable"] is False
    assert records[0]["semantic_output_fingerprint"] == "not_applicable"
    assert records[0]["target_applicable"] is False
    assert summary["target_exact_match_percent"] is None
    assert summary["target_range_iou_percent"] is None
    assert category_summary["target_exact_match_percent"] is None
    assert category_summary["target_range_iou_percent"] is None


def test_repeat_output_fingerprints_are_canonical_and_respect_semantic_boundary() -> None:
    semantic = {
        "intent": "basic_light_control",
        "room": "living_room",
        "scope": "single_room",
        "control_goal": "turn_on",
        "targets": {"illuminance_lux_range": [300, 700]},
        "llm_metrics": {"request_ms": 10, "cache_hit": False},
    }
    same_interpretation = {
        **semantic,
        "targets": {"illuminance_lux_range": [300, 700]},
        "llm_metrics": {"request_ms": 999, "cache_hit": True},
    }

    assert reproduction_experiments.semantic_output_fingerprint(
        semantic, applicable=True
    ) == reproduction_experiments.semantic_output_fingerprint(same_interpretation, applicable=True)
    assert reproduction_experiments.semantic_output_fingerprint(semantic, applicable=False) == "not_applicable"
    assert reproduction_experiments.plan_action_fingerprint(
        [{"entity_id": "light.living_room", "action": "set_power", "parameters": {"power": True}}]
    ) == reproduction_experiments.plan_action_fingerprint(
        [{"parameters": {"power": True}, "action": "set_power", "entity_id": "light.living_room"}]
    )


def test_plan_fingerprint_refuses_malformed_action_payloads() -> None:
    valid_empty_plan = reproduction_experiments.plan_action_fingerprint([])

    assert reproduction_experiments.plan_action_fingerprint("not-a-list") == ""
    assert reproduction_experiments.plan_action_fingerprint(["not-an-action"]) == ""
    assert reproduction_experiments.plan_action_fingerprint([{}])
    assert reproduction_experiments.plan_action_fingerprint(["not-an-action"]) != valid_empty_plan


def test_limited_task_run_is_explicitly_not_a_performance_estimate() -> None:
    source_tasks = reproduction_experiments.load_tasks(
        PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
    )
    scope = reproduction_experiments.build_evaluation_scope(
        source_tasks,
        source_tasks[:1],
        requested_limit=1,
    )

    assert scope["claim_status"] == "smoke_test_insufficient_task_coverage"
    assert scope["performance_claim_allowed"] is False
    assert scope["executed_task_count"] == 1
    assert scope["source_task_count"] > scope["executed_task_count"]


def test_small_complete_custom_suite_is_not_promoted_to_performance_evidence() -> None:
    task = {"task_id": "T001", "category": "single_device_control"}
    scope = reproduction_experiments.build_evaluation_scope([task], [task], requested_limit=None)

    assert scope["claim_status"] == "insufficient_task_coverage"
    assert scope["performance_claim_allowed"] is False


def test_device_selection_exact_match_penalizes_unrequested_actuation() -> None:
    metrics = reproduction_experiments.device_selection_metrics(
        ["light"], ["light", "window"]
    )

    assert metrics == {
        "expected_count": 1,
        "planned_count": 2,
        "true_positive_count": 1,
        "false_positive_count": 1,
        "false_negative_count": 0,
        "precision_percent": 50.0,
        "recall_percent": 100.0,
        "f1_percent": 66.67,
        "exact_match": False,
    }
    assert reproduction_experiments.classify_failure(
        success=True,
        semantic_applicable=False,
        completion_applicable=False,
        intent_correct="",
        room_correct="",
        scope_correct="",
        control_goal_correct="",
        target_exact_match=True,
        device_selection_exact_match=False,
        completed="",
        error="",
    ) == "device_selection_mismatch"


def test_versioned_task_suite_has_complete_control_goal_annotations() -> None:
    path = PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
    tasks = reproduction_experiments.load_tasks(path)
    provenance = reproduction_experiments.build_task_suite_provenance(path, tasks)

    assert len(tasks) == 36
    assert {task["expected_control_goal"] for task in tasks} == {"turn_on", "turn_off", "set_target"}
    assert provenance["semantic_ground_truth_schema_version"] == "semantic_reference_v4"
    assert provenance["control_goal_annotation_complete"] is True
    assert provenance["target_annotation_complete"] is True
    assert provenance["label_quality_status"] == "incomplete_annotation_provenance"
    assert provenance["semantic_annotation_provenance"] == {
        "protocol_version": "semantic_annotation_provenance_v1",
        "reference_type": "project_curated_simulated",
        "annotation_unit": "task_level_semantic_reference",
        "independent_review_evidence_status": "not_recorded",
        "inter_annotator_agreement_evidence_status": "not_recorded",
        "ambiguity_adjudication_evidence_status": "not_recorded",
    }
    assert tasks[20]["expected_targets"]["humidity_percent_range"] == [40.0, 70.0]


def test_versioned_task_suite_rejects_missing_annotation_provenance(tmp_path: Path) -> None:
    source_path = PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
    payload = source_path.read_text(encoding="utf-8")
    invalid_path = tmp_path / "missing-provenance.json"
    invalid_path.write_text(
        payload.replace('  "semantic_annotation_provenance": {', '  "missing_annotation_provenance": {', 1),
        encoding="utf-8",
    )

    try:
        reproduction_experiments.load_tasks(invalid_path)
    except ValueError as error:
        assert "semantic_annotation_provenance" in str(error)
    else:
        raise AssertionError("Versioned suites must declare annotation provenance.")


def test_control_goal_mismatch_is_a_traceable_semantic_failure() -> None:
    failure = reproduction_experiments.classify_failure(
        success=True,
        semantic_applicable=True,
        completion_applicable=False,
        intent_correct=True,
        room_correct=True,
        scope_correct=True,
        control_goal_correct=False,
        target_exact_match=True,
        device_selection_exact_match=True,
        completed="",
        error="",
    )

    assert failure == "semantic_control_goal_error"


def test_target_range_metric_exposes_wrong_control_parameters() -> None:
    metrics = reproduction_experiments.target_range_metrics(
        {"temperature_c_range": [24, 26.7]},
        {"temperature_c_range": [18, 20]},
    )

    assert metrics == {
        "applicable": True,
        "expected_key_count": 1,
        "predicted_key_count": 1,
        "range_iou_percent": 0.0,
        "exact_match": False,
    }
    assert reproduction_experiments.classify_failure(
        success=True,
        semantic_applicable=True,
        completion_applicable=False,
        intent_correct=True,
        room_correct=True,
        scope_correct=True,
        control_goal_correct=True,
        target_exact_match=False,
        device_selection_exact_match=True,
        completed="",
        error="",
    ) == "semantic_target_error"


def test_fixed_policy_baseline_does_not_report_semantic_target_accuracy(tmp_path: Path) -> None:
    group = reproduction_experiments.GROUPS_BY_ID["fixed_policy_baseline"]
    task = reproduction_experiments.load_tasks(PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json")[0]

    records = reproduction_experiments.run_group(group, [task], tmp_path, real_mode="mock")
    summary = reproduction_experiments.summarize_records(records, group)

    assert records[0]["target_applicable"] is False
    assert records[0]["expected_targets"] == "{}"
    assert records[0]["predicted_targets"] == "{}"
    assert summary["target_exact_match_percent"] is None
    assert summary["target_range_iou_percent"] is None


def test_repeat_stability_reports_semantic_and_plan_variation_by_task() -> None:
    records = [
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "task_id": "P001",
            "repeat_index": 1,
            "semantic_applicable": True,
            "semantic_output_fingerprint": "a" * 64,
            "plan_action_fingerprint": "b" * 64,
            "semantic_runtime_fingerprint": "c" * 64,
        },
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "task_id": "P001",
            "repeat_index": 2,
            "semantic_applicable": True,
            "semantic_output_fingerprint": "a" * 64,
            "plan_action_fingerprint": "b" * 64,
            "semantic_runtime_fingerprint": "c" * 64,
        },
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "task_id": "P002",
            "repeat_index": 1,
            "semantic_applicable": True,
            "semantic_output_fingerprint": "d" * 64,
            "plan_action_fingerprint": "e" * 64,
            "semantic_runtime_fingerprint": "c" * 64,
        },
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "task_id": "P002",
            "repeat_index": 2,
            "semantic_applicable": True,
            "semantic_output_fingerprint": "f" * 64,
            "plan_action_fingerprint": "e" * 64,
            "semantic_runtime_fingerprint": "c" * 64,
        },
    ]

    summary = reproduction_experiments.summarize_repeat_stability(records, repeat_count=2)

    assert summary == [
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "requested_repeat_count": 2,
            "task_repeat_unit_count": 2,
            "observed_repeat_counts": [2],
            "invalid_repeat_index_task_ids": [],
            "semantic_runtime_fingerprint_count": 1,
            "invalid_semantic_runtime_fingerprint_task_ids": [],
            "missing_semantic_output_fingerprint_task_ids": [],
            "invalid_semantic_output_fingerprint_task_ids": [],
            "missing_plan_action_fingerprint_task_ids": [],
            "invalid_plan_action_fingerprint_task_ids": [],
            "failed_run_task_ids": [],
            "stability_status": "measured",
            "semantic_output_exact_stability_percent": 50.0,
            "plan_action_exact_stability_percent": 100.0,
            "unstable_task_ids": ["P002"],
        }
    ]


def test_repeat_stability_refuses_to_compare_different_semantic_runtime_fingerprints() -> None:
    records = [
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "task_id": "P001",
            "repeat_index": 1,
            "semantic_applicable": True,
            "semantic_output_fingerprint": "a" * 64,
            "plan_action_fingerprint": "b" * 64,
            "semantic_runtime_fingerprint": "d" * 64,
        },
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "task_id": "P001",
            "repeat_index": 2,
            "semantic_applicable": True,
            "semantic_output_fingerprint": "a" * 64,
            "plan_action_fingerprint": "b" * 64,
            "semantic_runtime_fingerprint": "e" * 64,
        },
    ]

    summary = reproduction_experiments.summarize_repeat_stability(records, repeat_count=2)

    assert summary[0]["semantic_runtime_fingerprint_count"] == 2
    assert summary[0]["stability_status"] == "inconsistent_semantic_runtime_fingerprint"
    assert summary[0]["semantic_output_exact_stability_percent"] is None
    assert summary[0]["plan_action_exact_stability_percent"] is None


def test_repeat_stability_refuses_to_label_missing_output_fingerprints_as_stable() -> None:
    summary = reproduction_experiments.summarize_repeat_stability(
        [
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "repeat_index": 1,
                "semantic_applicable": True,
                "semantic_output_fingerprint": "",
                "plan_action_fingerprint": "",
                "semantic_runtime_fingerprint": "c" * 64,
            },
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "repeat_index": 2,
                "semantic_applicable": True,
                "semantic_output_fingerprint": "",
                "plan_action_fingerprint": "",
                "semantic_runtime_fingerprint": "c" * 64,
            },
        ],
        repeat_count=2,
    )

    assert summary[0]["stability_status"] == "missing_semantic_or_plan_fingerprint"
    assert summary[0]["missing_semantic_output_fingerprint_task_ids"] == ["P001"]
    assert summary[0]["missing_plan_action_fingerprint_task_ids"] == ["P001"]
    assert summary[0]["semantic_output_exact_stability_percent"] is None
    assert summary[0]["plan_action_exact_stability_percent"] is None


def test_repeat_stability_refuses_nonempty_placeholder_fingerprints() -> None:
    summary = reproduction_experiments.summarize_repeat_stability(
        [
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "repeat_index": 1,
                "semantic_applicable": True,
                "semantic_output_fingerprint": "not_recorded",
                "plan_action_fingerprint": "not_recorded",
                "semantic_runtime_fingerprint": "not_recorded",
            },
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "repeat_index": 2,
                "semantic_applicable": True,
                "semantic_output_fingerprint": "not_recorded",
                "plan_action_fingerprint": "not_recorded",
                "semantic_runtime_fingerprint": "not_recorded",
            },
        ],
        repeat_count=2,
    )

    assert summary[0]["stability_status"] == "invalid_fingerprint_format"
    assert summary[0]["invalid_semantic_runtime_fingerprint_task_ids"] == ["P001"]
    assert summary[0]["invalid_semantic_output_fingerprint_task_ids"] == ["P001"]
    assert summary[0]["invalid_plan_action_fingerprint_task_ids"] == ["P001"]
    assert summary[0]["semantic_output_exact_stability_percent"] is None
    assert summary[0]["plan_action_exact_stability_percent"] is None


def test_repeat_stability_refuses_duplicate_repeat_indices() -> None:
    summary = reproduction_experiments.summarize_repeat_stability(
        [
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "repeat_index": 1,
                "semantic_applicable": True,
                "semantic_output_fingerprint": "a" * 64,
                "plan_action_fingerprint": "b" * 64,
                "semantic_runtime_fingerprint": "c" * 64,
            },
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "repeat_index": 1,
                "semantic_applicable": True,
                "semantic_output_fingerprint": "a" * 64,
                "plan_action_fingerprint": "b" * 64,
                "semantic_runtime_fingerprint": "c" * 64,
            },
        ],
        repeat_count=2,
    )

    assert summary[0]["stability_status"] == "invalid_repeat_indices"
    assert summary[0]["invalid_repeat_index_task_ids"] == ["P001"]
    assert summary[0]["semantic_output_exact_stability_percent"] is None
    assert summary[0]["plan_action_exact_stability_percent"] is None


def test_repeat_stability_refuses_missing_repeat_index() -> None:
    summary = reproduction_experiments.summarize_repeat_stability(
        [
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "repeat_index": 1,
                "semantic_applicable": True,
                "semantic_output_fingerprint": "a" * 64,
                "plan_action_fingerprint": "b" * 64,
                "semantic_runtime_fingerprint": "c" * 64,
            },
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "semantic_applicable": True,
                "semantic_output_fingerprint": "a" * 64,
                "plan_action_fingerprint": "b" * 64,
                "semantic_runtime_fingerprint": "c" * 64,
            },
        ],
        repeat_count=2,
    )

    assert summary[0]["stability_status"] == "invalid_repeat_indices"
    assert summary[0]["invalid_repeat_index_task_ids"] == ["P001"]


def test_repeat_stability_refuses_to_label_one_run_as_a_measurement() -> None:
    summary = reproduction_experiments.summarize_repeat_stability(
        [
            {
                "group_id": "full_system",
                "group_name": "Full workflow",
                "task_id": "P001",
                "repeat_index": 1,
                "semantic_applicable": True,
                "semantic_output_fingerprint": "a" * 64,
                "plan_action_fingerprint": "b" * 64,
                "semantic_runtime_fingerprint": "c" * 64,
            }
        ],
        repeat_count=1,
    )

    assert summary[0]["stability_status"] == "single_run_no_stability_measurement"
    assert summary[0]["semantic_output_exact_stability_percent"] is None
    assert summary[0]["plan_action_exact_stability_percent"] is None


def test_repeat_stability_refuses_to_label_repeatable_failures_as_stable() -> None:
    empty_semantic_fingerprint = reproduction_experiments.semantic_output_fingerprint({}, applicable=True)
    empty_plan_fingerprint = reproduction_experiments.plan_action_fingerprint([])
    records = [
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "task_id": "P001",
            "repeat_index": 1,
            "semantic_applicable": True,
            "success": False,
            "semantic_output_fingerprint": empty_semantic_fingerprint,
            "plan_action_fingerprint": empty_plan_fingerprint,
            "semantic_runtime_fingerprint": "a" * 64,
        },
        {
            "group_id": "full_system",
            "group_name": "Full workflow",
            "task_id": "P001",
            "repeat_index": 2,
            "semantic_applicable": True,
            "success": False,
            "semantic_output_fingerprint": empty_semantic_fingerprint,
            "plan_action_fingerprint": empty_plan_fingerprint,
            "semantic_runtime_fingerprint": "a" * 64,
        },
    ]

    summary = reproduction_experiments.summarize_repeat_stability(records, repeat_count=2)

    assert summary[0]["failed_run_task_ids"] == ["P001"]
    assert summary[0]["stability_status"] == "failed_runs_no_stability_measurement"
    assert summary[0]["semantic_output_exact_stability_percent"] is None
    assert summary[0]["plan_action_exact_stability_percent"] is None


def test_report_labels_runtime_success_separately_from_semantic_correctness(tmp_path: Path) -> None:
    """A successful runner response must not be presented as semantic task success."""
    group = reproduction_experiments.GROUPS_BY_ID["rule_semantic_full"]
    task = reproduction_experiments.load_tasks(
        PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
    )[0]
    record = reproduction_experiments.run_group(group, [task], tmp_path, real_mode="mock")[0]
    summary = {
        "generated_at": "test",
        "tasks_path": "test.json",
        "task_count": 1,
        "repeat_count": 1,
        "real_mode": "mock",
        "environment_file": "test.env",
        "environment_file_loaded": False,
        "evaluation_scope": reproduction_experiments.build_evaluation_scope([task], [task], requested_limit=1),
        "semantic_runtime_provenance": {"mock": reproduction_experiments.semantic_runtime_provenance("mock")},
        "task_suite_provenance": reproduction_experiments.build_task_suite_provenance(
            PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json",
            reproduction_experiments.load_tasks(PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"),
        ),
        "groups": [reproduction_experiments.group_to_dict(group, "mock")],
        "group_summaries": [reproduction_experiments.summarize_records([record], group)],
        "category_summaries": reproduction_experiments.summarize_by_group_and_category([record]),
        "repeat_stability": reproduction_experiments.summarize_repeat_stability([record], repeat_count=1),
        "output_paths": {
            "records_csv": "records.csv",
            "summary_json": "summary.json",
            "chart_data_json": "chart_data.json",
            "chart_csv_dir": "chart_csv",
        },
    }

    report = reproduction_experiments.render_report(summary)

    assert record["success"] is True
    assert record["intent_correct"] is False
    assert "Runtime success %" in report
    assert "It is not semantic correctness or task completion" in report


def test_failed_pre_context_command_is_not_reported_as_task_runtime_success() -> None:
    """A failed context setup invalidates the task chain, even if the final command runs."""
    group = reproduction_experiments.GROUPS_BY_ID["rule_semantic_full"]
    task = reproduction_experiments.load_tasks(
        PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
    )[0]
    environment = reproduction_experiments.SmartHomeEnvironment()
    reproduction_experiments.apply_task_setup(environment, task)
    final_state = environment.get_state(refresh_realtime=False)
    semantic = reproduction_experiments.expected_semantic_from_task(task)
    response = SimpleNamespace(
        success=True,
        semantic_result=semantic,
        plan_result={"actions": []},
        execution_result={"executed_count": 0},
        feedback_result={"completed": True, "correction_round": 0},
        final_state=final_state,
        error="",
    )

    record = reproduction_experiments.build_record(
        group=group,
        task=task,
        task_index=1,
        repeat_index=1,
        response=response,
        environment=environment,
        response_time_ms=1.0,
        pre_context_success=False,
        effective_llm_mode="rule",
        real_mode="mock",
        semantic_provenance=reproduction_experiments.semantic_runtime_provenance("rule"),
    )

    assert record["main_command_success"] is True
    assert record["pre_context_success"] is False
    assert record["success"] is False
    assert record["failure_type"] == "runtime_error"
    assert record["error"] == "pre-context command failed"
    assert reproduction_experiments.summarize_records([record], group)["success_rate_percent"] == 0.0


def test_repeated_runs_do_not_expand_coverage_based_performance_samples(tmp_path: Path) -> None:
    """Later repetitions belong only to the within-task stability analysis."""
    group = reproduction_experiments.GROUPS_BY_ID["rule_semantic_full"]
    task = reproduction_experiments.load_tasks(
        PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
    )[0]
    records = reproduction_experiments.run_group(
        group, [task], tmp_path, real_mode="mock", repeat_index=1
    ) + reproduction_experiments.run_group(
        group, [task], tmp_path, real_mode="mock", repeat_index=2
    )

    performance_records = reproduction_experiments.primary_performance_records(records)
    summary = reproduction_experiments.summarize_records(performance_records, group)
    category_summary = reproduction_experiments.summarize_by_group_and_category(performance_records)
    chart_data = reproduction_experiments.build_chart_data(
        [summary], category_summary, performance_records
    )

    assert len(records) == 2
    assert [record["repeat_index"] for record in performance_records] == [1]
    assert summary["sample_count"] == 1
    assert category_summary[0]["sample_count"] == 1
    assert len(chart_data["power_by_task"]) == 1
