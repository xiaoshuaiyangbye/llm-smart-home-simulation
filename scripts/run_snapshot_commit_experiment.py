"""Run the isolated guarded-versus-unguarded snapshot-commit ablation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.runtime.snapshot_commit import evaluate_snapshot_commit
from app.simulation.environment import SmartHomeEnvironment

POLICIES = {
    "guarded": True,
    "unguarded": False,
}
SCENARIOS = ("no_intervening_change", "state_revision_change")
ACTIONS = [
    {
        "entity_id": "light.living_room_main",
        "action": "turn_on",
        "parameters": {"brightness_pct": 60, "color_temperature_k": 4000},
        "reason": "fixed RQ1 experiment action",
    }
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_trials(repeats: int) -> list[dict[str, Any]]:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    records: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        for trial in range(1, repeats + 1):
            for policy, enforce_freshness in POLICIES.items():
                environment = SmartHomeEnvironment()
                snapshot_revision = environment.revision
                snapshot_preference_fingerprint = "fixed-preference-v1"
                event_to_effect_latency_ms: float | None = None
                if scenario == "state_revision_change":
                    event_started = time.perf_counter_ns()
                    environment.set_current_room("bathroom")
                    event_to_effect_latency_ms = (time.perf_counter_ns() - event_started) / 1_000_000

                commit_id = hashlib.sha256(
                    json.dumps(
                        {"snapshot_revision": snapshot_revision, "actions": ACTIONS},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                decision_started = time.perf_counter_ns()
                evaluation = evaluate_snapshot_commit(
                    snapshot_revision=snapshot_revision,
                    current_revision=environment.revision,
                    snapshot_preference_fingerprint=snapshot_preference_fingerprint,
                    current_preference_fingerprint=snapshot_preference_fingerprint,
                    commit_id=commit_id,
                    committed_action_ids=(),
                    enforce_snapshot_freshness=enforce_freshness,
                )
                decision_latency_us = (time.perf_counter_ns() - decision_started) / 1_000

                commit_started = time.perf_counter_ns()
                execution_success = False
                if evaluation.allowed:
                    execution_results, _ = environment.apply_device_actions_batch(ACTIONS)
                    execution_success = bool(execution_results) and all(
                        bool(item.get("success")) for item in execution_results
                    )
                commit_path_latency_ms = (time.perf_counter_ns() - commit_started) / 1_000_000
                stale_at_commit = evaluation.state_changed or evaluation.preference_changed
                records.append(
                    {
                        "policy": policy,
                        "scenario": scenario,
                        "trial": trial,
                        "snapshot_revision": snapshot_revision,
                        "revision_at_commit": environment.revision,
                        "stale_at_commit": stale_at_commit,
                        "commit_allowed": evaluation.allowed,
                        "commit_status": evaluation.status,
                        "execution_success": execution_success,
                        "stale_committed": stale_at_commit and evaluation.allowed and execution_success,
                        "event_to_effect_latency_ms": event_to_effect_latency_ms,
                        "commit_decision_latency_us": decision_latency_us,
                        "commit_path_latency_ms": commit_path_latency_ms,
                    }
                )
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record["policy"]), str(record["scenario"]))].append(record)

    cells = []
    for (policy, scenario), rows in sorted(grouped.items()):
        decision_latencies = [float(row["commit_decision_latency_us"]) for row in rows]
        commit_latencies = [float(row["commit_path_latency_ms"]) for row in rows]
        event_latencies = [
            float(row["event_to_effect_latency_ms"])
            for row in rows
            if row["event_to_effect_latency_ms"] is not None
        ]
        stale_rows = [row for row in rows if row["stale_at_commit"]]
        cells.append(
            {
                "policy": policy,
                "scenario": scenario,
                "trials": len(rows),
                "commit_rate": mean(bool(row["commit_allowed"]) for row in rows),
                "stale_committed_rate": (
                    mean(bool(row["stale_committed"]) for row in stale_rows) if stale_rows else None
                ),
                "median_commit_decision_latency_us": median(decision_latencies),
                "p95_commit_decision_latency_us": _percentile(decision_latencies, 0.95),
                "median_commit_path_latency_ms": median(commit_latencies),
                "median_event_to_effect_latency_ms": median(event_latencies) if event_latencies else None,
                "p95_event_to_effect_latency_ms": _percentile(event_latencies, 0.95) if event_latencies else None,
            }
        )

    by_key = {(cell["policy"], cell["scenario"]): cell for cell in cells}
    guarded_valid = by_key[("guarded", "no_intervening_change")]
    unguarded_valid = by_key[("unguarded", "no_intervening_change")]
    guarded_stale = by_key[("guarded", "state_revision_change")]
    unguarded_stale = by_key[("unguarded", "state_revision_change")]
    return {
        "schema_version": "snapshot_commit_ablation_v1",
        "design": {
            "schedule": "deterministic snapshot -> optional state mutation -> commit interleaving",
            "independent_variable": "enforce_snapshot_freshness",
            "controlled_components": [
                "initial SmartHomeEnvironment",
                "planned action",
                "duplicate suppression",
                "state mutation",
                "execution path",
            ],
            "evidence_class": "isolated software-simulation mechanism experiment",
        },
        "cells": cells,
        "primary_comparison": {
            "guarded_stale_committed_rate": guarded_stale["stale_committed_rate"],
            "unguarded_stale_committed_rate": unguarded_stale["stale_committed_rate"],
            "absolute_stale_commit_rate_reduction": (
                float(unguarded_stale["stale_committed_rate"])
                - float(guarded_stale["stale_committed_rate"])
            ),
            "guarded_valid_commit_rate": guarded_valid["commit_rate"],
            "unguarded_valid_commit_rate": unguarded_valid["commit_rate"],
            "median_guard_decision_overhead_us": (
                float(guarded_valid["median_commit_decision_latency_us"])
                - float(unguarded_valid["median_commit_decision_latency_us"])
            ),
        },
        "claim_boundary": (
            "The deterministic interleaving isolates snapshot freshness enforcement in the software simulator. "
            "It does not estimate real-home event prevalence, network latency, hard real-time guarantees, or device safety."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    primary = report["primary_comparison"]
    lines = [
        "# RQ1 Snapshot Commit Ablation",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Primary Result",
        "",
        f"- Guarded stale committed rate: `{primary['guarded_stale_committed_rate']:.3f}`",
        f"- Unguarded stale committed rate: `{primary['unguarded_stale_committed_rate']:.3f}`",
        f"- Absolute reduction: `{primary['absolute_stale_commit_rate_reduction']:.3f}`",
        f"- Guarded valid commit rate: `{primary['guarded_valid_commit_rate']:.3f}`",
        f"- Median guard decision overhead: `{primary['median_guard_decision_overhead_us']:+.3f} us`",
        "",
        "## Cells",
        "",
        "| Policy | Scenario | Trials | Commit rate | Stale committed rate | Decision median us | Decision p95 us | Event-to-effect median ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in report["cells"]:
        stale_rate = cell["stale_committed_rate"]
        event_latency = cell["median_event_to_effect_latency_ms"]
        lines.append(
            f"| {cell['policy']} | {cell['scenario']} | {cell['trials']} | "
            f"{cell['commit_rate']:.3f} | "
            f"{stale_rate:.3f} | " if stale_rate is not None else
            f"| {cell['policy']} | {cell['scenario']} | {cell['trials']} | {cell['commit_rate']:.3f} | N/A | "
        )
        lines[-1] += (
            f"{cell['median_commit_decision_latency_us']:.3f} | "
            f"{cell['p95_commit_decision_latency_us']:.3f} | "
            f"{event_latency:.3f} |" if event_latency is not None else
            f"{cell['median_commit_decision_latency_us']:.3f} | "
            f"{cell['p95_commit_decision_latency_us']:.3f} | N/A |"
        )
    lines.extend(["", "## Evidence Boundary", "", report["claim_boundary"], ""])
    return "\n".join(lines)


def write_artifacts(records: list[dict[str, Any]], report: dict[str, Any], output_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_dir = output_root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=False)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["provenance"] = {
        "runner_sha256": _sha256(Path(__file__)),
        "production_gate_sha256": _sha256(BACKEND_ROOT / "app" / "runtime" / "snapshot_commit.py"),
        "record_count": len(records),
    }
    (artifact_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifact_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    with (artifact_dir / "records.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return artifact_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "results" / "snapshot_commit",
    )
    args = parser.parse_args()
    records = run_trials(args.repeats)
    report = summarize(records)
    artifact_dir = write_artifacts(records, report, args.output_dir)
    print(json.dumps({"artifact_dir": str(artifact_dir), **report["primary_comparison"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
