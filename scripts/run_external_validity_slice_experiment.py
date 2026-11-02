"""Run a small external-validity slice smoke for building energy claims.

This validates the experiment adapter shape for building/climate/season slices
without depending on external services. The fixture is synthetic and public
standard-inspired; it is not calibrated BOPTEST, CASAS, or field evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = PROJECT_ROOT / "data" / "research" / "external_validity_slices.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "results" / "external_validity"

CONTROL_POLICIES = {
    "rule_baseline": {"summer_setpoint_c": 24.0, "winter_setpoint_c": 22.0, "switches_per_day": 4},
    "comfort_first": {"summer_setpoint_c": 24.5, "winter_setpoint_c": 22.0, "switches_per_day": 5},
    "energy_saving": {"summer_setpoint_c": 27.0, "winter_setpoint_c": 19.5, "switches_per_day": 2},
    "safety_aware": {"summer_setpoint_c": 26.0, "winter_setpoint_c": 20.5, "switches_per_day": 3},
}
OCCUPIED_HOURS_PER_DAY = 14


def runner_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def fixture_sha256(path: Path = DEFAULT_FIXTURE) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != "external_validity_slice_fixture_v1":
        raise ValueError("Unsupported external-validity fixture schema.")
    for field in ("buildings", "climates", "seasons", "days_per_slice", "claim_boundary"):
        if not fixture.get(field):
            raise ValueError(f"Missing fixture field: {field}")
    return fixture


def _policy_setpoint(policy: dict[str, float], season: str) -> float:
    return float(policy["summer_setpoint_c"] if season == "summer" else policy["winter_setpoint_c"])


def _outdoor_temperature(climate: dict[str, Any], season: str) -> float:
    return float(climate["summer_outdoor_c"] if season == "summer" else climate["winter_outdoor_c"])


def _daily_energy_kwh(
    building: dict[str, Any],
    climate: dict[str, Any],
    season: dict[str, Any],
    policy: dict[str, float],
) -> float:
    season_name = str(season["season"])
    setpoint = _policy_setpoint(policy, season_name)
    outdoor = _outdoor_temperature(climate, season_name)
    thermal_delta = max(0.0, outdoor - setpoint) if season_name == "summer" else max(0.0, setpoint - outdoor)
    hvac_cop = max(1.0, float(building["hvac_cop"]))
    return round(float(building["thermal_loss_kw_per_c"]) * thermal_delta * 24 / hvac_cop, 5)


def _comfort_violation_minutes(season: dict[str, Any], policy: dict[str, float]) -> int:
    season_name = str(season["season"])
    setpoint = _policy_setpoint(policy, season_name)
    comfort_target = float(season["comfort_temperature_c"])
    allowed = float(season["allowed_deviation_c"])
    excess = max(0.0, abs(setpoint - comfort_target) - allowed)
    return round(excess * OCCUPIED_HOURS_PER_DAY * 60 / max(allowed, 0.1))


def run_external_validity_slice(fixture_path: Path = DEFAULT_FIXTURE) -> list[dict[str, Any]]:
    fixture = load_fixture(fixture_path)
    records: list[dict[str, Any]] = []
    for building in fixture["buildings"]:
        for climate in fixture["climates"]:
            for season in fixture["seasons"]:
                for control_policy, policy in CONTROL_POLICIES.items():
                    for day_index in range(1, int(fixture["days_per_slice"]) + 1):
                        energy_kwh = _daily_energy_kwh(building, climate, season, policy)
                        comfort_violations = _comfort_violation_minutes(season, policy)
                        records.append(
                            {
                                "schema_version": "external_validity_slice_smoke_record_v1",
                                "building_id": building["building_id"],
                                "building_type": building["building_type"],
                                "floor_area_m2": building["floor_area_m2"],
                                "climate_id": climate["climate_id"],
                                "season": season["season"],
                                "control_policy": control_policy,
                                "day_index": day_index,
                                "daily_energy_kwh": energy_kwh,
                                "energy_kwh_per_m2": round(energy_kwh / float(building["floor_area_m2"]), 6),
                                "comfort_violation_minutes": comfort_violations,
                                "control_switch_count": int(policy["switches_per_day"]),
                                "source_externality": "synthetic_public_standard_inspired_slice",
                                "runner_source_sha256": runner_source_sha256(),
                                "fixture_sha256": fixture_sha256(fixture_path),
                                "evidence_class": "synthetic_external_validity_adapter_smoke",
                            }
                        )
    return records


def summarize(records: list[dict[str, Any]], fixture: dict[str, Any]) -> dict[str, Any]:
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_slice: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_policy[str(record["control_policy"])].append(record)
        by_slice[(str(record["building_id"]), str(record["climate_id"]), str(record["season"]))].append(record)

    policy_summary = []
    for policy in CONTROL_POLICIES:
        group = by_policy[policy]
        policy_summary.append(
            {
                "control_policy": policy,
                "record_count": len(group),
                "mean_daily_energy_kwh": round(mean(float(record["daily_energy_kwh"]) for record in group), 5),
                "mean_energy_kwh_per_m2": round(mean(float(record["energy_kwh_per_m2"]) for record in group), 6),
                "mean_comfort_violation_minutes": round(
                    mean(float(record["comfort_violation_minutes"]) for record in group),
                    3,
                ),
                "mean_control_switch_count": round(mean(float(record["control_switch_count"]) for record in group), 3),
            }
        )

    return {
        "schema_version": "external_validity_slice_smoke_v1",
        "evidence_class": "synthetic_external_validity_adapter_smoke",
        "building_count": len({record["building_id"] for record in records}),
        "climate_count": len({record["climate_id"] for record in records}),
        "season_count": len({record["season"] for record in records}),
        "control_policy_count": len(CONTROL_POLICIES),
        "days_per_slice": int(fixture["days_per_slice"]),
        "record_count": len(records),
        "slice_count": len(by_slice),
        "policy_summary": policy_summary,
        "claim_boundary": fixture["claim_boundary"],
        "provenance": {
            "runner_source_sha256": runner_source_sha256(),
            "fixture_sha256": fixture_sha256(),
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# External Validity Slice Smoke Report",
        "",
        f"Schema: `{summary['schema_version']}`",
        f"Evidence class: `{summary['evidence_class']}`",
        "",
        f"> Boundary: {summary['claim_boundary']}",
        "",
        "| Policy | Records | Mean daily kWh | Mean kWh/m2 | Mean comfort violation min | Mean switches |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["policy_summary"]:
        lines.append(
            f"| {row['control_policy']} | {row['record_count']} | {row['mean_daily_energy_kwh']:.5f} | "
            f"{row['mean_energy_kwh_per_m2']:.6f} | {row['mean_comfort_violation_minutes']:.3f} | "
            f"{row['mean_control_switch_count']:.3f} |"
        )
    return "\n".join(lines) + "\n"


def write_artifacts(records: list[dict[str, Any]], fixture: dict[str, Any], output_root: Path) -> Path:
    output_dir = output_root / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "records.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    summary = summarize(records, fixture)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    fixture = load_fixture(args.fixture)
    records = run_external_validity_slice(args.fixture)
    output_dir = write_artifacts(records, fixture, args.output_root)
    summary = summarize(records, fixture)
    print(json.dumps({"output_dir": str(output_dir), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
