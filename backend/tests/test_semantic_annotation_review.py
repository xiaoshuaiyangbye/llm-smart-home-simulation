import hashlib
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "validate_semantic_annotation_review.py"
spec = importlib.util.spec_from_file_location("semantic_annotation_review", SCRIPT)
assert spec and spec.loader
semantic_annotation_review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(semantic_annotation_review)


def _task_suite(path: Path) -> dict[str, object]:
    return {
        "tasks": [
            {
                "task_id": "P001",
                "expected_control_goal": "turn_on",
                "expected_targets": {"illuminance_lux_range": [100, 500]},
            },
            {
                "task_id": "P003",
                "expected_control_goal": "turn_on",
                "expected_targets": {"illuminance_lux_range": [100, 500]},
            },
        ]
    }


def _label(goal: str = "turn_on") -> dict[str, object]:
    return {"control_goal": goal, "targets": {"illuminance_lux_range": [100, 500]}}


def _review(path: Path) -> dict[str, object]:
    task_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "schema_version": "semantic_annotation_review_v1",
        "task_suite_sha256": task_hash,
        "reviewed_at": "2026-07-13T00:00:00Z",
        "reviewers": [
            {"reviewer_id": "A", "independent_of_reference_author": True},
            {"reviewer_id": "B", "independent_of_reference_author": True},
        ],
        "task_reviews": [
            {"task_id": "P001", "reviewer_labels": {"A": _label(), "B": _label()}},
            {
                "task_id": "P003",
                "reviewer_labels": {"A": _label("turn_on"), "B": _label("set_target")},
                "adjudication": {
                    "adjudicator_id": "chair",
                    "rationale": "Task wording is treated as a binary open action in this simulator.",
                    "label": _label("turn_on"),
                },
            },
        ],
    }


def test_completed_independent_review_requires_coverage_and_adjudication(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps(_task_suite(tasks)), encoding="utf-8")

    errors, metadata = semantic_annotation_review.validate(_review(tasks), tasks)

    assert errors == []
    assert metadata["accepted"] is True
    assert metadata["unanimous_task_count"] == 1
    assert metadata["adjudicated_task_count"] == 1


def test_disagreement_without_an_adjudication_is_rejected(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps(_task_suite(tasks)), encoding="utf-8")
    review = _review(tasks)
    del review["task_reviews"][1]["adjudication"]  # type: ignore[index]

    errors, metadata = semantic_annotation_review.validate(review, tasks)

    assert metadata["accepted"] is False
    assert "task_reviews[1].adjudication is required when reviewers disagree" in errors
