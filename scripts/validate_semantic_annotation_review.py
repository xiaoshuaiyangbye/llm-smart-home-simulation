"""Validate independently reviewed semantic labels for a reproduction task suite.

The validator is intentionally evidence-gated: it can verify a completed
review artifact, but it cannot turn a template or a single-author decision
into independent label evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "semantic_annotation_review_v1"
LABEL_KEYS = {"control_goal", "targets"}
VALID_CONTROL_GOALS = {"turn_on", "turn_off", "set_target"}


def validate(review: object, task_suite_path: Path) -> tuple[list[str], dict[str, object]]:
    """Return validation errors and non-claiming review coverage metadata."""
    if not isinstance(review, dict):
        return ["review must be a JSON object"], {}

    errors: list[str] = []
    task_payload = json.loads(task_suite_path.read_text(encoding="utf-8-sig"))
    if not isinstance(task_payload, dict) or not isinstance(task_payload.get("tasks"), list):
        return ["task suite must be an object containing tasks"], {}
    tasks = {str(task.get("task_id")): task for task in task_payload["tasks"] if isinstance(task, dict)}
    if len(tasks) != len(task_payload["tasks"]) or not tasks:
        return ["task suite contains invalid or duplicate task IDs"], {}
    suite_goals = task_payload.get("control_goal_annotations", {})
    suite_targets = task_payload.get("target_annotations", {})
    if not isinstance(suite_goals, dict) or not isinstance(suite_targets, dict):
        return ["task suite annotations must be objects"], {}

    if review.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    expected_hash = hashlib.sha256(task_suite_path.read_bytes()).hexdigest()
    if review.get("task_suite_sha256") != expected_hash:
        errors.append("task_suite_sha256 does not match the supplied task suite")
    if not _non_empty_text(review.get("reviewed_at")):
        errors.append("reviewed_at must be a non-empty string")

    reviewers = _reviewers(review.get("reviewers"), errors)
    review_entries = review.get("task_reviews")
    if not isinstance(review_entries, list):
        return sorted(errors + ["task_reviews must be a list"]), {}

    seen_ids: set[str] = set()
    agreement_count = 0
    disagreement_count = 0
    for index, entry in enumerate(review_entries):
        prefix = f"task_reviews[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        task_id = entry.get("task_id")
        if not isinstance(task_id, str) or task_id not in tasks:
            errors.append(f"{prefix}.task_id must identify a task in the suite")
            continue
        if task_id in seen_ids:
            errors.append(f"{prefix}.task_id is duplicated: {task_id}")
            continue
        seen_ids.add(task_id)
        labels = entry.get("reviewer_labels")
        if not isinstance(labels, dict):
            errors.append(f"{prefix}.reviewer_labels must be an object")
            continue
        if set(labels) != set(reviewers):
            errors.append(f"{prefix}.reviewer_labels must contain exactly the declared reviewers")
            continue
        normalized_labels = {reviewer_id: _validate_label(value, f"{prefix}.reviewer_labels.{reviewer_id}", errors) for reviewer_id, value in labels.items()}
        if any(value is None for value in normalized_labels.values()):
            continue

        final_label = _suite_label(tasks[task_id], task_id, suite_goals, suite_targets, errors)
        if final_label is None:
            continue
        reviewer_values = list(normalized_labels.values())
        unanimous = all(value == reviewer_values[0] for value in reviewer_values[1:])
        if unanimous:
            agreement_count += 1
            if reviewer_values[0] != final_label:
                errors.append(f"{prefix} unanimous label does not match the versioned task-suite label")
            if "adjudication" in entry:
                errors.append(f"{prefix} must not include adjudication when reviewers agree")
        else:
            disagreement_count += 1
            adjudication = _validate_adjudication(entry.get("adjudication"), prefix, reviewers, errors)
            if adjudication is not None and adjudication != final_label:
                errors.append(f"{prefix}.adjudication does not match the versioned task-suite label")

    missing = sorted(set(tasks) - seen_ids)
    if missing:
        errors.append("task_reviews is missing task IDs: " + ", ".join(missing))
    metadata = {
        "task_suite_sha256": expected_hash,
        "task_count": len(tasks),
        "reviewed_task_count": len(seen_ids),
        "unanimous_task_count": agreement_count,
        "adjudicated_task_count": disagreement_count,
        "inter_annotator_exact_agreement": agreement_count / len(tasks) if tasks else 0.0,
        "accepted": not errors,
    }
    return sorted(errors), metadata


def _reviewers(value: object, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or len(value) < 2:
        errors.append("reviewers must contain at least two independent reviewers")
        return []
    reviewer_ids: list[str] = []
    for index, reviewer in enumerate(value):
        prefix = f"reviewers[{index}]"
        if not isinstance(reviewer, dict):
            errors.append(f"{prefix} must be an object")
            continue
        reviewer_id = reviewer.get("reviewer_id")
        if not _non_empty_text(reviewer_id):
            errors.append(f"{prefix}.reviewer_id must be a non-empty string")
            continue
        if reviewer.get("independent_of_reference_author") is not True:
            errors.append(f"{prefix}.independent_of_reference_author must be true")
        reviewer_ids.append(str(reviewer_id))
    if len(set(reviewer_ids)) != len(reviewer_ids):
        errors.append("reviewer_id values must be unique")
    return reviewer_ids


def _validate_label(value: object, prefix: str, errors: list[str]) -> dict[str, object] | None:
    if not isinstance(value, dict) or set(value) != LABEL_KEYS:
        errors.append(f"{prefix} must contain exactly control_goal and targets")
        return None
    goal = value.get("control_goal")
    if goal not in VALID_CONTROL_GOALS:
        errors.append(f"{prefix}.control_goal is invalid")
    targets = _normalized_targets(value.get("targets"), prefix, errors)
    if goal not in VALID_CONTROL_GOALS or targets is None:
        return None
    return {"control_goal": goal, "targets": targets}


def _suite_label(
    task: dict[str, Any],
    task_id: str,
    suite_goals: dict[str, object],
    suite_targets: dict[str, object],
    errors: list[str],
) -> dict[str, object] | None:
    goal = suite_goals.get(task_id, task.get("expected_control_goal"))
    targets = suite_targets.get(task_id, task.get("expected_targets"))
    if goal is None or targets is None:
        errors.append(f"task suite task {task_id} must expose expected_control_goal and expected_targets")
        return None
    return _validate_label({"control_goal": goal, "targets": targets}, f"task suite task {task_id}", errors)


def _normalized_targets(value: object, prefix: str, errors: list[str]) -> dict[str, list[float]] | None:
    if not isinstance(value, dict) or not value:
        errors.append(f"{prefix}.targets must be a non-empty object")
        return None
    normalized: dict[str, list[float]] = {}
    for key, range_value in value.items():
        if key not in {"illuminance_lux_range", "temperature_c_range", "humidity_percent_range"}:
            errors.append(f"{prefix}.targets contains unsupported key {key}")
            continue
        if not isinstance(range_value, list) or len(range_value) != 2:
            errors.append(f"{prefix}.targets.{key} must be a two-value range")
            continue
        try:
            lower, upper = float(range_value[0]), float(range_value[1])
        except (TypeError, ValueError):
            errors.append(f"{prefix}.targets.{key} must be numeric")
            continue
        if lower > upper:
            errors.append(f"{prefix}.targets.{key} must be ordered")
            continue
        normalized[key] = [lower, upper]
    return normalized if normalized else None


def _validate_adjudication(value: object, prefix: str, reviewer_ids: list[str], errors: list[str]) -> dict[str, object] | None:
    if not isinstance(value, dict):
        errors.append(f"{prefix}.adjudication is required when reviewers disagree")
        return None
    if not _non_empty_text(value.get("adjudicator_id")) or value.get("adjudicator_id") in reviewer_ids:
        errors.append(f"{prefix}.adjudication.adjudicator_id must name a non-reviewer adjudicator")
    if not _non_empty_text(value.get("rationale")):
        errors.append(f"{prefix}.adjudication.rationale must be a non-empty string")
    return _validate_label(value.get("label"), f"{prefix}.adjudication.label", errors)


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path, help="completed independent annotation-review JSON")
    parser.add_argument("--tasks", required=True, type=Path, help="versioned reproduction task suite JSON")
    args = parser.parse_args()
    review: Any = json.loads(args.review.read_text(encoding="utf-8"))
    errors, metadata = validate(review, args.tasks)
    print(json.dumps({**metadata, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
