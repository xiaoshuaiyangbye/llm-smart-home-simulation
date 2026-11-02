"""Validate the authorized, bounded E1 protocol and its historical artifact claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = PROJECT_ROOT / "data" / "research" / "e1_episode_benchmark_spec.json"

REQUIRED_METHODS = {"single_agent", "multi_agent_static", "personalized", "full"}
REQUIRED_METRICS = {
    "runtime_success",
    "final_state_success",
    "semantic_accuracy",
    "device_selection_f1",
    "occupied_room_comfort_score",
    "post_control_horizon_kwh",
    "weighted_utility",
    "safety_action_changed",
    "critic_action_changed",
    "feedback_correction_applied",
    "request_latency_ms",
}
REQUIRED_PROVENANCE = {
    "runner_source_sha256",
    "task_suite_sha256",
    "semantic_model_id",
    "semantic_model_revision",
    "semantic_runtime_fingerprint",
    "initial_state_fingerprint",
    "post_control_evaluation_minutes",
    "artifact_schema_version",
}


def validate_spec(spec_path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    spec_path = spec_path.resolve()
    issues: list[str] = []
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"schema_version": "e1_episode_benchmark_spec_validation_v1", "valid": False, "issues": [str(exc)]}

    if spec.get("schema_version") != "e1_episode_benchmark_spec_v1":
        issues.append("schema_version must be e1_episode_benchmark_spec_v1")
    if spec.get("status") != "implemented_bounded_software_protocol":
        issues.append("status must identify the implemented bounded software protocol")
    authorization = spec.get("authorization", {})
    if not authorization.get("user_instruction") or not authorization.get("scope"):
        issues.append("authorization must record the user instruction and implementation scope")
    if spec.get("episode_unit", {}).get("is_independent_population_sample") is not False:
        issues.append("configured episodes must not be claimed as independent population samples")
    design = spec.get("target_design", {})
    methods = set(design.get("methods", [])) if isinstance(design, dict) else set()
    if methods != REQUIRED_METHODS:
        issues.append("target_design.methods must match the four required controls")
    unique_episode_count = int(design.get("unique_episode_count", 0) or 0)
    repeats = int(design.get("repeats_per_episode", 0) or 0)
    target_run_count = int(design.get("target_run_count", 0) or 0)
    if unique_episode_count * len(REQUIRED_METHODS) * repeats != target_run_count:
        issues.append("target_run_count must equal unique episodes x methods x repeats")
    strata = spec.get("task_strata", [])
    if not isinstance(strata, list) or sum(int(item.get("target_unique_episodes", 0)) for item in strata) != unique_episode_count:
        issues.append("task_strata must sum to target_design.unique_episode_count")
    metrics = set(spec.get("primary_metrics", []))
    missing_metrics = sorted(REQUIRED_METRICS - metrics)
    if missing_metrics:
        issues.append(f"missing primary metrics: {', '.join(missing_metrics)}")
    provenance = set(spec.get("provenance_requirements", []))
    missing_provenance = sorted(REQUIRED_PROVENANCE - provenance)
    if missing_provenance:
        issues.append(f"missing provenance fields: {', '.join(missing_provenance)}")
    implemented = spec.get("implemented_protocol", {})
    base_count = implemented.get("base_scenario_count")
    configuration_count = implemented.get("configuration_episode_count")
    if base_count != 24 or configuration_count != unique_episode_count:
        issues.append("implemented protocol must distinguish 24 base scenarios from configured episodes")
    if implemented.get("bootstrap_cluster_unit") != "base_task_id":
        issues.append("bootstrap cluster unit must be base_task_id")
    if implemented.get("original_inferential_plan_executed") is not False:
        issues.append("original inferential plan remains unexecuted; descriptive bootstrap is not mixed-effects/Holm")
    if spec.get("statistical_plan", {}).get("status") != "original_inferential_research_target_not_executed":
        issues.append("original inferential plan must retain its unexecuted status")
    if implemented.get("semantic_mode") != "mock" or implemented.get("post_control_evaluation_minutes") != 30:
        issues.append("implemented protocol must preserve the mock semantic mode and 30-minute horizon")
    artifacts = spec.get("completed_artifacts", [])
    if not artifacts:
        issues.append("completed_artifacts must identify actual generated summaries")
    for artifact in artifacts:
        summary_path = PROJECT_ROOT / artifact.get("summary", "")
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            protocol = json.loads((summary_path.parent / "protocol.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"completed artifact unreadable: {summary_path}: {exc}")
            continue
        for field in ("record_count", "configuration_episode_count", "base_scenario_count", "repeat_count"):
            if artifact.get(field) != summary.get(field):
                issues.append(f"completed artifact {field} mismatch: {summary_path}")
        if artifact.get("semantic_mode") != protocol.get("semantic_mode"):
            issues.append(f"completed artifact semantic_mode mismatch: {summary_path}")
        if not artifact.get("provenance_note"):
            issues.append(f"completed artifact must explain historical source provenance: {summary_path}")
    for relative_path in spec.get("existing_smoke_inputs", []):
        if not (PROJECT_ROOT / relative_path).exists():
            issues.append(f"existing smoke input missing: {relative_path}")
    boundary_text = " ".join(
        str(spec.get(field, ""))
        for field in ("activation_boundary", "supported_thesis_wording", "prohibited_thesis_wording")
    ).lower()
    if "real-home" not in boundary_text or "user approval" not in boundary_text:
        issues.append("spec must preserve real-home and user-approval boundaries")

    return {
        "schema_version": "e1_episode_benchmark_spec_validation_v1",
        "spec_path": str(spec_path),
        "valid": not issues,
        "status": spec.get("status"),
        "base_scenario_count": base_count,
        "configuration_episode_count": configuration_count,
        "completed_artifact_count": len(artifacts),
        "original_inferential_plan_executed": implemented.get("original_inferential_plan_executed"),
        "unique_episode_count": unique_episode_count,
        "method_count": len(methods),
        "repeats_per_episode": repeats,
        "target_run_count": target_run_count,
        "task_stratum_count": len(strata) if isinstance(strata, list) else 0,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", nargs="?", type=Path, default=DEFAULT_SPEC)
    args = parser.parse_args()
    result = validate_spec(args.spec)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
