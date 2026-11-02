"""Matched, local EnergyPlus controller comparison with explicit claim boundaries."""
import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.energyplus.contracts import RunRequest  # noqa: E402
from app.energyplus.model import runtime_directory  # noqa: E402
from app.energyplus.service import model_status  # noqa: E402


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def trace_diagnostics(directory):
    traces = [json.loads(line) for line in (directory / "control_trace.jsonl").read_text(encoding="utf-8").splitlines() if line]
    model_calls = [row["real_model_result"] for row in traces if row.get("real_model_result")]
    proposals = [action for row in traces for action in row.get("proposed_actions", [])]
    mapped = [action for row in traces for action in row.get("mapped_actions", [])]
    rejected = [item for row in traces for item in row.get("rejected_actions", [])]
    latencies = [row["latency_seconds"] for row in model_calls]
    return {"trace_records": len(traces), "semantic_modes": sorted({row.get("semantic_mode_effective", "unknown") for row in traces}),
        "real_model_call_count": len(model_calls),
        "model_revision": sorted({row.get("revision") for row in model_calls if row.get("revision")}),
        "adapter_sha256": sorted({row.get("adapter_sha256") for row in model_calls if row.get("adapter_sha256")}),
        "mean_model_latency_ms": sum(latencies) * 1000 / len(latencies) if latencies else None,
        "max_model_latency_ms": max(latencies) * 1000 if latencies else None,
        "proposed_action_count": len(proposals), "mapped_action_count": len(mapped),
        "rejected_action_count": len(rejected),
        "rejected_action_reasons": sorted({item["reason"] for item in rejected}),
        "co2_guard_intervention_count": sum(bool(row.get("co2_guard_intervention")) +
            sum(g.get("guard") == "co2_ventilation" for g in row.get("guard_interventions", [])) for row in traces),
        "window_hvac_guard_intervention_count": sum(bool(row.get("window_hvac_guard_intervention")) +
            sum(g.get("guard") == "window_hvac" for g in row.get("guard_interventions", [])) for row in traces),
        "guard_count_unit": "room interventions; legacy single-room flags count as one"}


def run_comparison(base, controllers, destination):
    runtime_directory()
    if "harness_real" in controllers and not model_status().get("ready"):
        raise RuntimeError("Real DeepSeek planner is not ready; refusing a mock substitute")
    destination.mkdir(parents=True, exist_ok=False)
    entries = []
    for controller in controllers:
        directory = destination / controller
        directory.mkdir()
        request = base.model_copy(update={"controller": controller})
        (directory / "config.json").write_text(json.dumps({"request": request.model_dump(), "calibration": None,
            "owner": "matched-experiment"}, ensure_ascii=False, indent=2), encoding="utf-8")
        with (directory / "worker.log").open("w", encoding="utf-8") as log:
            process = subprocess.run([sys.executable, "-u", "-m", "app.energyplus.runner", "--config", str(directory / "config.json")],
                cwd=ROOT / "backend", stdout=log, stderr=subprocess.STDOUT, timeout=3600, check=False)
        status_path = directory / "status.json"
        if not status_path.is_file():
            log_path = directory / "worker.log"
            raise RuntimeError(f"{controller} worker produced no status file; exit={process.returncode}; "
                               f"see {log_path if log_path.exists() else directory}")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if process.returncode or status["status"] != "completed":
            raise RuntimeError(f"{controller} failed (exit={process.returncode}): {status.get('error')}; see {directory / 'worker.log'}")
        summary = status["summary"]
        entries.append({"controller": controller, "directory": str(directory), "summary": summary,
            "trace_diagnostics": trace_diagnostics(directory),
            "input_model_sha256": summary["provenance"]["model_sha256"],
            "weather_sha256": summary["provenance"]["weather_sha256"],
            "initial_state_fingerprint": summary["initial_state_fingerprint"],
            "raw_trace_sha256": digest(directory / "control_trace.jsonl"),
            "observations_sha256": digest(directory / "observations.jsonl")})
    comparable = all(len({row[key] for row in entries}) == 1 for key in
        ("input_model_sha256", "weather_sha256", "initial_state_fingerprint"))
    if not comparable:
        raise ValueError("Run inputs or initial physical state differ; no paired comparison is valid")
    baseline = entries[0]["summary"]
    comparisons = []
    for row in entries[1:]:
        candidate = row["summary"]
        comfort_gap = candidate["occupied_target_satisfaction_rate"] - baseline["occupied_target_satisfaction_rate"]
        energy_delta = candidate["modeled_electricity_kwh"] - baseline["modeled_electricity_kwh"]
        comparisons.append({"baseline": entries[0]["controller"], "candidate": row["controller"],
            "modeled_electricity_delta_kwh": energy_delta,
            "occupied_target_satisfaction_delta": comfort_gap,
            "co2_excess_delta_ppm_minutes": candidate["co2_excess_ppm_minutes"] - baseline["co2_excess_ppm_minutes"],
            "comfort_matched_within_one_percentage_point": abs(comfort_gap) <= 0.01,
            "energy_saving_claim_allowed": False,
            "interpretation": "descriptive difference in one uncalibrated software simulation; no field savings or statistical effect"})
    report = {"schema": "energyplus_matched_comparison_v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs_matched": comparable, "request_without_controller": base.model_dump(exclude={"controller"}),
        "runs": entries, "comparisons": comparisons,
        "evidence_boundary": "EnergyPlus software model with example TMY weather and uncalibrated geometry/equipment."
                             " No physical-house performance, energy-saving, independent semantic or statistical claim."}
    (destination / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controllers", nargs="+", default=["rule", "harness_mock"],
        choices=["rule", "manual", "harness_mock", "harness_real"])
    parser.add_argument("--season", choices=["summer", "winter"], default="summer")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--spatial-scope", choices=["whole_home", "single_room"], default="whole_home")
    parser.add_argument("--command", default="客厅看书，保持舒适，注意通风并节约能源")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if len(set(arguments.controllers)) != len(arguments.controllers):
        parser.error("Controller names must be unique")
    base = RunRequest(spatial_scope=arguments.spatial_scope, season=arguments.season, days=arguments.days, user_command=arguments.command)
    destination = (arguments.output or ROOT / "data/results/energyplus/comparisons" / uuid.uuid4().hex).resolve()
    report = run_comparison(base, arguments.controllers, destination)
    print(json.dumps({"report": str(destination / "comparison.json"), "inputs_matched": report["inputs_matched"],
        "comparisons": report["comparisons"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
