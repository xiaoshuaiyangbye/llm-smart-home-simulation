"""Validate the thesis argument chain without upgrading missing evidence into claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = PROJECT_ROOT / "data" / "research" / "thesis_claims.json"

ALLOWED_EVIDENCE_STATUSES = {
    "mechanism_verified_no_comparative_baseline",
    "isolated_guarded_comparison_supported",
    "fixed_simulation_descriptive_mock",
    "named_fixture_effect_insufficient_task_clusters",
    "three_named_fixture_clusters_descriptive",
    "software_evidence_supported",
    "not_evaluated_versioned_real_full_suite",
    "versioned_real_full_suite_descriptive",
}
ALLOWED_NOVELTY_TYPES = {
    "application_specific_system_mechanism",
    "bounded_personalization_system_design",
    "evidence_aware_orchestration_methodology",
    "integration_not_standalone_novelty",
}
REQUIRED_RQ_FIELDS = {
    "id",
    "question",
    "mechanisms",
    "baselines",
    "metrics",
    "repository_evidence",
    "generated_evidence",
    "current_result",
    "evidence_status",
    "supported_claim",
    "prohibited_claim",
    "next_required_evidence",
    "submission_blocker",
}


def _is_nonempty(value: Any) -> bool:
    return bool(value) and (not isinstance(value, str) or bool(value.strip()))


def validate_thesis_claims(
    matrix_path: Path = DEFAULT_MATRIX,
    *,
    require_generated_evidence: bool = False,
) -> dict[str, Any]:
    matrix_path = matrix_path.resolve()
    issues: list[str] = []
    warnings: list[str] = []
    try:
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "thesis_claim_validation_v1",
            "structurally_valid": False,
            "submission_ready": False,
            "issues": [f"matrix_unreadable: {exc}"],
            "warnings": [],
            "blocking_rq_ids": [],
        }

    if matrix.get("schema_version") != "thesis_claim_matrix_v1":
        issues.append("schema_version must be thesis_claim_matrix_v1")
    for field in (
        "working_title",
        "central_problem",
        "recommended_thesis_type",
        "contribution_level",
        "claim_tiers",
        "research_questions",
        "innovation_candidates",
        "submission_blockers",
        "real_home_claim_blockers",
        "primary_related_work",
    ):
        if not _is_nonempty(matrix.get(field)):
            issues.append(f"missing_or_empty: {field}")

    research_questions = matrix.get("research_questions", [])
    rq_ids: list[str] = []
    for index, rq in enumerate(research_questions):
        if not isinstance(rq, dict):
            issues.append(f"research_questions[{index}] must be an object")
            continue
        missing = sorted(REQUIRED_RQ_FIELDS - rq.keys())
        if missing:
            issues.append(f"{rq.get('id', index)} missing fields: {', '.join(missing)}")
            continue
        rq_id = str(rq["id"])
        rq_ids.append(rq_id)
        for field in REQUIRED_RQ_FIELDS - {"submission_blocker"}:
            if not _is_nonempty(rq[field]):
                issues.append(f"{rq_id} has empty field: {field}")
        if not isinstance(rq["submission_blocker"], bool):
            issues.append(f"{rq_id} submission_blocker must be boolean")
        if rq["evidence_status"] not in ALLOWED_EVIDENCE_STATUSES:
            issues.append(f"{rq_id} has unsupported evidence_status: {rq['evidence_status']}")
        for baseline in rq["baselines"]:
            if not isinstance(baseline, dict) or not {"id", "implemented", "purpose"} <= baseline.keys():
                issues.append(f"{rq_id} baseline must contain id, implemented, and purpose")
        for relative_path in rq["repository_evidence"]:
            if not (PROJECT_ROOT / relative_path).exists():
                issues.append(f"{rq_id} repository evidence missing: {relative_path}")
        for relative_path in rq["generated_evidence"]:
            if not (PROJECT_ROOT / relative_path).exists():
                message = f"{rq_id} generated evidence missing: {relative_path}"
                if require_generated_evidence:
                    issues.append(message)
                else:
                    warnings.append(message)
        combined_claim = f"{rq['supported_claim']} {rq['current_result']}".lower()
        if any(term in combined_claim for term in ("真实家庭安全", "真实家庭节能", "真实住户满意度")):
            issues.append(f"{rq_id} supported claim crosses the real-home evidence boundary")

    duplicate_rq_ids = sorted({rq_id for rq_id in rq_ids if rq_ids.count(rq_id) > 1})
    if duplicate_rq_ids:
        issues.append(f"duplicate research question ids: {', '.join(duplicate_rq_ids)}")

    innovation_ids: list[str] = []
    for innovation in matrix.get("innovation_candidates", []):
        if not isinstance(innovation, dict):
            issues.append("innovation candidate must be an object")
            continue
        required = {"id", "name", "novelty_type", "related_rq_ids", "status", "safe_wording", "unsafe_wording"}
        if not required <= innovation.keys():
            issues.append(f"innovation candidate missing fields: {innovation}")
            continue
        innovation_ids.append(str(innovation["id"]))
        if innovation["novelty_type"] not in ALLOWED_NOVELTY_TYPES:
            issues.append(f"{innovation['id']} has unsupported novelty_type")
        unknown = sorted(set(innovation["related_rq_ids"]) - set(rq_ids))
        if unknown:
            issues.append(f"{innovation['id']} references unknown RQs: {', '.join(unknown)}")
    duplicate_innovation_ids = sorted(
        {innovation_id for innovation_id in innovation_ids if innovation_ids.count(innovation_id) > 1}
    )
    if duplicate_innovation_ids:
        issues.append(f"duplicate innovation ids: {', '.join(duplicate_innovation_ids)}")

    blocking_rq_ids = [
        str(rq["id"])
        for rq in research_questions
        if isinstance(rq, dict) and rq.get("submission_blocker") is True
    ]
    structurally_valid = not issues
    return {
        "schema_version": "thesis_claim_validation_v1",
        "matrix_path": str(matrix_path),
        "structurally_valid": structurally_valid,
        "submission_ready": structurally_valid and not blocking_rq_ids,
        "research_question_count": len(rq_ids),
        "innovation_candidate_count": len(innovation_ids),
        "blocking_rq_ids": blocking_rq_ids,
        "issues": issues,
        "warnings": warnings,
        "evidence_boundary": (
            "Structural validity means every claim has a question, mechanism, baseline, metric, evidence, "
            "boundary, and next step. It does not mean the thesis is submission-ready or the claims are true."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", nargs="?", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--require-generated-evidence", action="store_true")
    parser.add_argument("--require-submission-ready", action="store_true")
    args = parser.parse_args()
    result = validate_thesis_claims(
        args.matrix,
        require_generated_evidence=args.require_generated_evidence,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["structurally_valid"]:
        return 1
    if args.require_submission_ready and not result["submission_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
