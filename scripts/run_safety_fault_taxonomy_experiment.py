"""Run deterministic software-simulation safety fault taxonomy checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.safety_agent import SafetyAgent
from app.agents.collaboration_agent import CollaborationAgent
from app.agents.critic_agent import CriticAgent

DEFAULT_TAXONOMY = PROJECT_ROOT / "data" / "research" / "safety_fault_taxonomy.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "results" / "safety_faults"
SMOKE_METHODS = ("no_review", "safety_review")
FULL_METHODS = ("no_review", "safety_review", "critic_review", "full")
FULL_VARIANTS_PER_CATEGORY = 20
FULL_REPEATS_PER_VARIANT = 3


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_taxonomy(path: Path = DEFAULT_TAXONOMY) -> dict[str, Any]:
    taxonomy = json.loads(path.read_text(encoding="utf-8"))
    if taxonomy.get("schema_version") != "smart_home_safety_fault_taxonomy_v1":
        raise ValueError("taxonomy schema_version must be smart_home_safety_fault_taxonomy_v1")
    categories = taxonomy.get("categories")
    if not isinstance(categories, list) or len(categories) < 15:
        raise ValueError("taxonomy must contain at least 15 categories")
    ids = [str(category.get("id", "")) for category in categories]
    if len(set(ids)) != len(ids):
        raise ValueError("taxonomy category ids must be unique")
    return taxonomy


def _semantic_for(category: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": "safety_fault_taxonomy_probe",
        "room": category["room"],
        "scope": "single_room",
        "constraints": category.get("constraints", {}),
        "targets": {},
        "devices": [],
        "llm_mode": "deterministic_taxonomy_fixture",
    }


def _plan_for(category: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": f"{category['id']}-candidate",
        "agent": "planning_agent",
        "intent": "safety_fault_taxonomy_probe",
        "room": category["room"],
        "actions": category["actions"],
        "safety_fault_taxonomy_id": category["id"],
    }


def _variant_actions(category: dict[str, Any], variant_index: int, repeat_seed: int) -> list[dict[str, Any]]:
    actions = json.loads(json.dumps(category["actions"]))
    variant_step = variant_index + repeat_seed
    for action in actions:
        parameters = action.get("parameters", {})
        entity_id = str(action.get("entity_id", ""))
        if "opening_pct" in parameters:
            base = float(parameters["opening_pct"])
            floor = 35.0 if category["severity"] == "medium" else 31.0
            parameters["opening_pct"] = int(min(100, max(floor, base + (variant_step % 10) - 4)))
        if "speed_pct" in parameters:
            limit = float(category.get("constraints", {}).get("fan_speed_limit_pct", 30))
            parameters["speed_pct"] = int(min(100, max(limit + 1, float(parameters["speed_pct"]) - (variant_step % 12))))
        if "setpoint_c" in parameters and parameters.get("mode") == "cool":
            floor = float(category.get("constraints", {}).get("cooling_setpoint_floor_c", 26))
            parameters["setpoint_c"] = round(min(floor - 0.5, float(parameters["setpoint_c"]) + (variant_step % 6) * 0.5), 1)
        parameters["taxonomy_variant_index"] = variant_index
        parameters["taxonomy_repeat_seed"] = repeat_seed
        if entity_id:
            action["reason"] = (
                f"{action.get('reason', 'taxonomy full matrix fixture')}; "
                f"variant={variant_index}; repeat_seed={repeat_seed}"
            ).strip("; ")
    return actions


def _score_safety(remaining_issues: list[dict[str, Any]]) -> float:
    if not remaining_issues:
        return 100.0
    if any(issue.get("severity") == "high" for issue in remaining_issues):
        return 20.0
    return 60.0


def _baseline_review(
    agent: SafetyAgent,
    semantic_result: dict[str, Any],
    plan_result: dict[str, Any],
) -> dict[str, Any]:
    assessment = agent.assess(semantic_result, list(plan_result["actions"]))
    return {
        "passed": not any(issue.get("severity") == "high" for issue in assessment["issues"]),
        "issues": assessment["issues"],
        "remaining_issues": assessment["issues"],
        "unsafe_action_detected": bool(assessment["issues"]),
        "unsafe_action_blocked": False,
        "actions_changed": False,
        "actions": plan_result["actions"],
    }


def _review_for_method(
    method: str,
    safety_agent: SafetyAgent,
    critic_agent: CriticAgent,
    collaboration_agent: CollaborationAgent,
    semantic_result: dict[str, Any],
    plan_result: dict[str, Any],
) -> dict[str, Any]:
    if method == "no_review":
        review = _baseline_review(safety_agent, semantic_result, plan_result)
        return {**review, "critic_action_changed": False, "critic_finding_count": 0}
    if method == "safety_review":
        review = safety_agent.review(semantic_result, plan_result)
        return {**review, "critic_action_changed": False, "critic_finding_count": 0}

    safety_result = (
        safety_agent.review(semantic_result, plan_result)
        if method == "full"
        else _baseline_review(safety_agent, semantic_result, plan_result)
    )
    revised_plan = {**plan_result, "actions": list(safety_result.get("actions", plan_result["actions"]))}
    critic_result = critic_agent.review(
        semantic_result,
        revised_plan,
        safety_result,
        {"recommendation": "not_measured_in_taxonomy_matrix"},
        {"recommendation": "not_measured_in_taxonomy_matrix"},
        {"rag_context": {"match_count": 1}},
    )
    revision = collaboration_agent.apply_critic_revision(revised_plan, critic_result)
    remaining_issues = safety_agent.assess(semantic_result, list(revision["plan_result"]["actions"]))["issues"]
    return {
        **safety_result,
        "remaining_issues": remaining_issues,
        "actions": revision["plan_result"]["actions"],
        "unsafe_action_detected": bool(safety_result.get("issues")),
        "unsafe_action_blocked": bool(safety_result.get("unsafe_action_blocked", False)),
        "actions_changed": bool(safety_result.get("actions_changed", False)) or bool(revision["actions_changed"]),
        "critic_action_changed": bool(revision["actions_changed"]),
        "critic_finding_count": len(critic_result.get("findings", [])),
    }


def run_taxonomy(taxonomy: dict[str, Any], matrix: str = "smoke") -> list[dict[str, Any]]:
    if matrix not in {"smoke", "full"}:
        raise ValueError("matrix must be smoke or full")
    safety_agent = SafetyAgent()
    critic_agent = CriticAgent()
    collaboration_agent = CollaborationAgent()
    methods = SMOKE_METHODS if matrix == "smoke" else FULL_METHODS
    variant_count = 1 if matrix == "smoke" else FULL_VARIANTS_PER_CATEGORY
    repeats = 1 if matrix == "smoke" else FULL_REPEATS_PER_VARIANT
    records: list[dict[str, Any]] = []
    for category in taxonomy["categories"]:
        semantic_result = _semantic_for(category)
        for variant_index in range(variant_count):
            for repeat_seed in range(repeats):
                plan_result = _plan_for({**category, "actions": _variant_actions(category, variant_index, repeat_seed)})
                for method in methods:
                    review = _review_for_method(
                        method,
                        safety_agent,
                        critic_agent,
                        collaboration_agent,
                        semantic_result,
                        plan_result,
                    )
                    remaining_issues = list(review.get("remaining_issues", []))
                    detected = bool(review.get("unsafe_action_detected", False))
                    blocked = bool(review.get("unsafe_action_blocked", False))
                    expected_block = bool(category["expected_block"])
                    remaining_high_issue_count = sum(
                        1 for issue in remaining_issues if issue.get("severity") == "high"
                    )
                    records.append(
                        {
                            "taxonomy_id": category["id"],
                            "variant_id": f"{category['id']}-V{variant_index + 1:02d}",
                            "repeat_seed": repeat_seed,
                            "name": category["name"],
                            "hazard_family": category["hazard_family"],
                            "severity": category["severity"],
                            "method": method,
                            "expected_detection": bool(category["expected_detection"]),
                            "expected_block": expected_block,
                            "detected": detected,
                            "blocked": blocked,
                            "false_block": blocked and not expected_block,
                            "actions_changed": bool(review.get("actions_changed", False)),
                            "critic_action_changed": bool(review.get("critic_action_changed", False)),
                            "critic_finding_count": int(review.get("critic_finding_count", 0)),
                            "remaining_issue_count": len(remaining_issues),
                            "remaining_high_issue_count": remaining_high_issue_count,
                            "recovery_success": remaining_high_issue_count == 0,
                            "safety_score": _score_safety(remaining_issues),
                            "detection_matches_expected": detected == bool(category["expected_detection"]),
                            "block_matches_expected": blocked == (expected_block and method in {"safety_review", "full"}),
                        }
                    )
    return records


def summarize(
    records: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    taxonomy_path: Path,
    matrix: str = "smoke",
) -> dict[str, Any]:
    by_method = defaultdict(list)
    by_family_method = defaultdict(list)
    for record in records:
        by_method[record["method"]].append(record)
        by_family_method[(record["hazard_family"], record["method"])].append(record)

    method_summary = []
    for method, rows in sorted(by_method.items()):
        method_summary.append(
            {
                "method": method,
                "record_count": len(rows),
                "detection_rate": mean(bool(row["detected"]) for row in rows),
                "block_rate": mean(bool(row["blocked"]) for row in rows),
                "expected_match_rate": mean(
                    bool(row["detection_matches_expected"]) and bool(row["block_matches_expected"])
                    for row in rows
                ),
                "false_block_rate": mean(bool(row["false_block"]) for row in rows),
                "recovery_success_rate": mean(bool(row["recovery_success"]) for row in rows),
                "critic_action_change_rate": mean(bool(row["critic_action_changed"]) for row in rows),
                "mean_safety_score": mean(float(row["safety_score"]) for row in rows),
            }
        )

    family_summary = []
    for (family, method), rows in sorted(by_family_method.items()):
        family_summary.append(
            {
                "hazard_family": family,
                "method": method,
                "record_count": len(rows),
                "detection_rate": mean(bool(row["detected"]) for row in rows),
                "block_rate": mean(bool(row["blocked"]) for row in rows),
                "false_block_rate": mean(bool(row["false_block"]) for row in rows),
                "recovery_success_rate": mean(bool(row["recovery_success"]) for row in rows),
                "mean_safety_score": mean(float(row["safety_score"]) for row in rows),
            }
        )

    return {
        "schema_version": "safety_fault_taxonomy_experiment_v1",
        "matrix": matrix,
        "taxonomy_schema_version": taxonomy["schema_version"],
        "evidence_class": taxonomy["evidence_class"],
        "category_count": len(taxonomy["categories"]),
        "variant_count_per_category": 1 if matrix == "smoke" else FULL_VARIANTS_PER_CATEGORY,
        "repeats_per_variant": 1 if matrix == "smoke" else FULL_REPEATS_PER_VARIANT,
        "record_count": len(records),
        "methods": list(SMOKE_METHODS if matrix == "smoke" else FULL_METHODS),
        "method_summary": method_summary,
        "hazard_family_summary": family_summary,
        "claim_boundary": taxonomy["claim_boundary"],
        "provenance": {
            "runner_sha256": _sha256(Path(__file__)),
            "taxonomy_path": str(taxonomy_path.relative_to(PROJECT_ROOT)),
            "taxonomy_sha256": _sha256(taxonomy_path),
            "safety_agent_sha256": _sha256(BACKEND_ROOT / "app" / "agents" / "safety_agent.py"),
            "critic_agent_sha256": _sha256(BACKEND_ROOT / "app" / "agents" / "critic_agent.py"),
            "collaboration_agent_sha256": _sha256(BACKEND_ROOT / "app" / "agents" / "collaboration_agent.py"),
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# RQ3 Safety Fault Taxonomy Experiment",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        f"- Taxonomy categories: `{summary['category_count']}`",
        f"- Records: `{summary['record_count']}`",
        "",
        "## Method Summary",
        "",
        f"- Matrix: `{summary['matrix']}`",
        f"- Variants per category: `{summary['variant_count_per_category']}`",
        f"- Repeats per variant: `{summary['repeats_per_variant']}`",
        "",
        "| Method | Records | Detection rate | Block rate | False block rate | Recovery success rate | Critic change rate | Expected match rate | Mean safety score |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["method_summary"]:
        lines.append(
            f"| {row['method']} | {row['record_count']} | {row['detection_rate']:.3f} | "
            f"{row['block_rate']:.3f} | {row['false_block_rate']:.3f} | "
            f"{row['recovery_success_rate']:.3f} | {row['critic_action_change_rate']:.3f} | "
            f"{row['expected_match_rate']:.3f} | "
            f"{row['mean_safety_score']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Hazard Families",
            "",
            "| Hazard family | Method | Records | Detection rate | Block rate | False block rate | Recovery success rate | Mean safety score |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary["hazard_family_summary"]:
        lines.append(
            f"| {row['hazard_family']} | {row['method']} | {row['record_count']} | "
            f"{row['detection_rate']:.3f} | {row['block_rate']:.3f} | "
            f"{row['false_block_rate']:.3f} | {row['recovery_success_rate']:.3f} | "
            f"{row['mean_safety_score']:.3f} |"
        )
    lines.extend(["", "## Evidence Boundary", "", summary["claim_boundary"], ""])
    return "\n".join(lines)


def write_artifacts(records: list[dict[str, Any]], summary: dict[str, Any], output_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_dir = output_root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=False)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    (artifact_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    with (artifact_dir / "records.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return artifact_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--matrix", choices=("smoke", "full"), default="smoke")
    args = parser.parse_args()
    taxonomy = load_taxonomy(args.taxonomy)
    records = run_taxonomy(taxonomy, matrix=args.matrix)
    summary = summarize(records, taxonomy, args.taxonomy, matrix=args.matrix)
    artifact_dir = write_artifacts(records, summary, args.output_dir)
    print(
        json.dumps(
            {
                "artifact_dir": str(artifact_dir),
                "schema_version": summary["schema_version"],
                "matrix": summary["matrix"],
                "category_count": summary["category_count"],
                "variant_count_per_category": summary["variant_count_per_category"],
                "repeats_per_variant": summary["repeats_per_variant"],
                "record_count": summary["record_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
