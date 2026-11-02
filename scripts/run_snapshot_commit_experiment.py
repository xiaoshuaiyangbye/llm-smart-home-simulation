"""Run the isolated guarded-versus-unguarded snapshot-commit ablation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
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
PRESSURE_POLICIES = ("unguarded", "global_lock", "optimistic", "optimistic_replan")
SMOKE_PRESSURE_POLICIES = ("unguarded", "optimistic")
PRESSURE_MATRIX = {
    "smoke": {
        "policies": SMOKE_PRESSURE_POLICIES,
        "planner_delay_ms": (0, 250),
        "event_rates": (0.0, 1.0),
        "fault_rates": (0.0,),
        "traces": 3,
    },
    "full": {
        "policies": PRESSURE_POLICIES,
        "planner_delay_ms": (0, 100, 500, 1000, 3000),
        "event_rates": (0.0, 0.25, 0.5, 1.0),
        "fault_rates": (0.0, 0.05, 0.2),
        "traces": 20,
    },
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


def _commit_id(snapshot_revision: int, actions: list[dict[str, Any]], suffix: str = "") -> str:
    return hashlib.sha256(
        json.dumps(
            {"snapshot_revision": snapshot_revision, "actions": actions, "suffix": suffix},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _should_trigger(rate: float, seed: str) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    return random.Random(seed).random() < rate


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


def run_pressure_matrix(matrix: str) -> list[dict[str, Any]]:
    if matrix not in PRESSURE_MATRIX:
        raise ValueError(f"unknown pressure matrix: {matrix}")

    config = PRESSURE_MATRIX[matrix]
    records: list[dict[str, Any]] = []
    for policy in config["policies"]:
        for planner_delay_ms in config["planner_delay_ms"]:
            for event_rate in config["event_rates"]:
                for fault_rate in config["fault_rates"]:
                    for trace_id in range(1, int(config["traces"]) + 1):
                        seed = (
                            f"{matrix}:{policy}:{planner_delay_ms}:"
                            f"{event_rate}:{fault_rate}:{trace_id}"
                        )
                        environment = SmartHomeEnvironment()
                        snapshot_revision = environment.revision
                        first_snapshot_revision = snapshot_revision
                        snapshot_preference_fingerprint = "fixed-preference-v1"
                        event_requested = _should_trigger(float(event_rate), f"event:{seed}")
                        fault_triggered = _should_trigger(float(fault_rate), f"fault:{seed}")
                        event_applied = False
                        event_to_effect_latency_ms: float | None = None

                        if event_requested and policy != "global_lock":
                            event_started = time.perf_counter_ns()
                            environment.set_current_room("bathroom")
                            event_to_effect_latency_ms = (time.perf_counter_ns() - event_started) / 1_000_000
                            event_applied = True

                        if policy == "unguarded":
                            enforce_freshness = False
                        else:
                            enforce_freshness = True

                        commit_id = _commit_id(snapshot_revision, ACTIONS)
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

                        replan_count = 0
                        replan_success = False
                        if policy == "optimistic_replan" and not evaluation.allowed:
                            replan_count = 1
                            snapshot_revision = environment.revision
                            commit_id = _commit_id(snapshot_revision, ACTIONS, suffix="replan")
                            replan_evaluation = evaluate_snapshot_commit(
                                snapshot_revision=snapshot_revision,
                                current_revision=environment.revision,
                                snapshot_preference_fingerprint=snapshot_preference_fingerprint,
                                current_preference_fingerprint=snapshot_preference_fingerprint,
                                commit_id=commit_id,
                                committed_action_ids=(),
                                enforce_snapshot_freshness=True,
                            )
                            replan_success = replan_evaluation.allowed
                            evaluation = replan_evaluation

                        commit_started = time.perf_counter_ns()
                        execution_success = False
                        if evaluation.allowed and not fault_triggered:
                            execution_results, _ = environment.apply_device_actions_batch(ACTIONS)
                            execution_success = bool(execution_results) and all(
                                bool(item.get("success")) for item in execution_results
                            )
                        commit_path_latency_ms = (time.perf_counter_ns() - commit_started) / 1_000_000
                        stale_at_first_commit = event_applied
                        records.append(
                            {
                                "matrix": matrix,
                                "policy": policy,
                                "trace_id": trace_id,
                                "seed": seed,
                                "planner_delay_ms": planner_delay_ms,
                                "event_rate": event_rate,
                                "fault_rate": fault_rate,
                                "event_requested": event_requested,
                                "event_applied": event_applied,
                                "fault_triggered": fault_triggered,
                                "first_snapshot_revision": first_snapshot_revision,
                                "revision_at_commit": environment.revision,
                                "stale_at_first_commit": stale_at_first_commit,
                                "commit_allowed": evaluation.allowed,
                                "commit_status": evaluation.status,
                                "execution_success": execution_success,
                                "stale_committed": (
                                    stale_at_first_commit
                                    and policy == "unguarded"
                                    and evaluation.allowed
                                    and execution_success
                                ),
                                "replan_count": replan_count,
                                "replan_success": replan_success,
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


def summarize_pressure_matrix(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, int, float, float], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[
            (
                str(record["policy"]),
                int(record["planner_delay_ms"]),
                float(record["event_rate"]),
                float(record["fault_rate"]),
            )
        ].append(record)

    cells = []
    for (policy, planner_delay_ms, event_rate, fault_rate), rows in sorted(grouped.items()):
        decision_latencies = [float(row["commit_decision_latency_us"]) for row in rows]
        stale_rows = [row for row in rows if row["stale_at_first_commit"]]
        valid_rows = [row for row in rows if not row["stale_at_first_commit"]]
        replan_rows = [row for row in rows if int(row["replan_count"]) > 0]
        cells.append(
            {
                "policy": policy,
                "planner_delay_ms": planner_delay_ms,
                "event_rate": event_rate,
                "fault_rate": fault_rate,
                "traces": len(rows),
                "stale_committed_rate": (
                    mean(bool(row["stale_committed"]) for row in stale_rows) if stale_rows else None
                ),
                "valid_commit_rate": (
                    mean(bool(row["commit_allowed"]) and bool(row["execution_success"]) for row in valid_rows)
                    if valid_rows
                    else None
                ),
                "execution_success_rate": mean(bool(row["execution_success"]) for row in rows),
                "replan_success_rate": (
                    mean(bool(row["replan_success"]) for row in replan_rows) if replan_rows else None
                ),
                "median_commit_decision_latency_us": median(decision_latencies),
                "p95_commit_decision_latency_us": _percentile(decision_latencies, 0.95),
            }
        )

    return {
        "schema_version": "snapshot_commit_pressure_matrix_v1",
        "design": {
            "schedule": "virtual planner delay -> optional state mutation -> commit or replan",
            "evidence_class": "isolated software-simulation pressure matrix",
            "virtual_delay_note": (
                "planner_delay_ms is a deterministic virtual variable recorded in the matrix; "
                "the runner does not sleep and does not measure real LLM latency."
            ),
        },
        "matrix": records[0]["matrix"] if records else None,
        "record_count": len(records),
        "cells": cells,
        "claim_boundary": (
            "The pressure matrix exercises deterministic software interleavings and simulated tool faults. "
            "It does not prove hard real-time behavior, real presence-event latency, real network reliability, "
            "or real-device safety."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    if report["schema_version"] == "snapshot_commit_pressure_matrix_v1":
        lines = [
            "# RQ1 Snapshot Commit Pressure Matrix",
            "",
            f"Generated at: `{report['generated_at']}`",
            "",
            "## Design",
            "",
            report["design"]["virtual_delay_note"],
            "",
            "## Cells",
            "",
            "| Policy | Delay ms | Event rate | Fault rate | Traces | Stale committed rate | Valid commit rate | Replan success rate | Decision median us | Decision p95 us |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for cell in report["cells"]:
            stale_rate = cell["stale_committed_rate"]
            valid_rate = cell["valid_commit_rate"]
            replan_rate = cell["replan_success_rate"]
            lines.append(
                f"| {cell['policy']} | {cell['planner_delay_ms']} | {cell['event_rate']:.2f} | "
                f"{cell['fault_rate']:.2f} | {cell['traces']} | "
                f"{stale_rate:.3f} | " if stale_rate is not None else
                f"| {cell['policy']} | {cell['planner_delay_ms']} | {cell['event_rate']:.2f} | "
                f"{cell['fault_rate']:.2f} | {cell['traces']} | N/A | "
            )
            lines[-1] += f"{valid_rate:.3f} | " if valid_rate is not None else "N/A | "
            lines[-1] += f"{replan_rate:.3f} | " if replan_rate is not None else "N/A | "
            lines[-1] += (
                f"{cell['median_commit_decision_latency_us']:.3f} | "
                f"{cell['p95_commit_decision_latency_us']:.3f} |"
            )
        lines.extend(["", "## Evidence Boundary", "", report["claim_boundary"], ""])
        return "\n".join(lines)

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
    parser.add_argument("--matrix", choices=sorted(PRESSURE_MATRIX))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "results" / "snapshot_commit",
    )
    args = parser.parse_args()
    if args.matrix:
        records = run_pressure_matrix(args.matrix)
        report = summarize_pressure_matrix(records)
    else:
        records = run_trials(args.repeats)
        report = summarize(records)
    artifact_dir = write_artifacts(records, report, args.output_dir)
    result = {"artifact_dir": str(artifact_dir), "schema_version": report["schema_version"]}
    if "primary_comparison" in report:
        result.update(report["primary_comparison"])
    else:
        result["record_count"] = report["record_count"]
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
