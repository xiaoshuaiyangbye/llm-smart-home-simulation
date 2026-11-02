"""Run a bounded longitudinal personalization experiment.

This runner is intentionally component-level: it tests explicit feedback
promotion, confirmed-experience visibility, and a deterministic preference
alignment proxy. It does not claim real resident satisfaction or full
TaskRunner end-to-end control quality.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "results" / "personalization_longitudinal"
os.environ.setdefault("LLM_MODE", "mock")

import sys

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research import UserFeedbackRequest, UserPreferenceService
from app.research.personalization import UserPreferenceUpdate

METHODS = ("no_memory", "static_profile", "ungated_memory", "gated_confirmed_memory")
SMOKE_TURN_COUNT = 5
FULL_PROFILE_COUNT = 30
FULL_TURN_COUNT = 30
FULL_REPEAT_SEEDS = 3
PROFILE_CASES = (
    {
        "profile_id": "LP-001",
        "room": "study_room",
        "intent": "study_mode",
        "desired_temperature_c": 26.5,
        "desired_illuminance_lux": 650.0,
    },
    {
        "profile_id": "LP-002",
        "room": "bedroom",
        "intent": "sleep_mode",
        "desired_temperature_c": 27.0,
        "desired_illuminance_lux": 120.0,
    },
)


def runner_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _profile_cases_for_matrix(matrix: str) -> list[dict[str, Any]]:
    if matrix == "smoke":
        return [json.loads(json.dumps(case)) for case in PROFILE_CASES]
    if matrix != "full":
        raise ValueError("matrix must be smoke or full")
    profiles: list[dict[str, Any]] = []
    rooms = ("study_room", "bedroom", "living_room")
    intents = ("study_mode", "sleep_mode", "energy_saving_mode")
    for index in range(FULL_PROFILE_COUNT):
        base = json.loads(json.dumps(PROFILE_CASES[index % len(PROFILE_CASES)]))
        intent = intents[index % len(intents)]
        room = rooms[index % len(rooms)]
        if intent == "sleep_mode":
            illuminance = 80.0 + (index % 5) * 20.0
            temperature = 26.0 + (index % 4) * 0.4
        elif intent == "energy_saving_mode":
            illuminance = 350.0 + (index % 6) * 35.0
            temperature = 25.5 + (index % 5) * 0.3
        else:
            illuminance = 550.0 + (index % 7) * 30.0
            temperature = 25.0 + (index % 6) * 0.35
        profiles.append(
            {
                **base,
                "profile_id": f"LP-FULL-{index + 1:02d}",
                "room": room,
                "intent": intent,
                "desired_temperature_c": round(temperature, 2),
                "desired_illuminance_lux": round(illuminance, 2),
            }
        )
    return profiles


def task_suite_sha256(matrix: str = "smoke") -> str:
    encoded = json.dumps(
        _profile_cases_for_matrix(matrix),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _base_semantic(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": case["intent"],
        "room": case["room"],
        "targets": {},
        "constraints": {"safety_boundary": "default_smart_home_limits"},
    }


def _target_centers(personalized_semantic: dict[str, Any], case: dict[str, Any]) -> dict[str, float]:
    targets = personalized_semantic.get("targets", {})
    temperature_range = targets.get("temperature_c_range", [25.0, 25.0])
    illuminance_range = targets.get("illuminance_lux_range", [500.0, 500.0])
    if case["intent"] == "sleep_mode" and "illuminance_lux_range" not in targets:
        illuminance_range = [50.0, 50.0]
    return {
        "temperature_c": round((float(temperature_range[0]) + float(temperature_range[1])) / 2, 3),
        "illuminance_lux": round((float(illuminance_range[0]) + float(illuminance_range[1])) / 2, 3),
    }


def _ungated_proxy_targets(case: dict[str, Any], turn_index: int) -> dict[str, float]:
    if turn_index == 1:
        return {"temperature_c": 25.0, "illuminance_lux": 500.0 if case["intent"] != "sleep_mode" else 50.0}
    # This deliberately models an unsafe ablation: unconfirmed experience is
    # allowed to influence downstream planning before explicit user promotion.
    return {
        "temperature_c": round(25.0 + (float(case["desired_temperature_c"]) - 25.0) * 0.45, 3),
        "illuminance_lux": round(500.0 + (float(case["desired_illuminance_lux"]) - 500.0) * 0.45, 3)
        if case["intent"] != "sleep_mode"
        else round(50.0 + (float(case["desired_illuminance_lux"]) - 50.0) * 0.45, 3),
    }


def _alignment_utility(targets: dict[str, float], case: dict[str, Any]) -> float:
    temperature_error = abs(targets["temperature_c"] - float(case["desired_temperature_c"]))
    illuminance_error = abs(targets["illuminance_lux"] - float(case["desired_illuminance_lux"]))
    temperature_score = max(0.0, 100.0 - temperature_error * 30.0)
    illuminance_score = max(0.0, 100.0 - illuminance_error / 5.0)
    return round(temperature_score * 0.55 + illuminance_score * 0.45, 3)


def _safety_override_count(targets: dict[str, float]) -> int:
    violations = 0
    if not 16.0 <= targets["temperature_c"] <= 30.0:
        violations += 1
    if not 50.0 <= targets["illuminance_lux"] <= 1200.0:
        violations += 1
    return violations


def _comfort_proxy(targets: dict[str, float], case: dict[str, Any]) -> float:
    return round(100.0 - abs(targets["temperature_c"] - float(case["desired_temperature_c"])) * 20.0, 3)


def _energy_proxy(targets: dict[str, float], case: dict[str, Any]) -> float:
    cooling_setpoint_score = max(0.0, min(100.0, (targets["temperature_c"] - 22.0) * 14.0))
    illuminance_score = max(0.0, min(100.0, 100.0 - targets["illuminance_lux"] / 12.0))
    if case["intent"] == "sleep_mode":
        return round(cooling_setpoint_score * 0.7 + illuminance_score * 0.3, 3)
    return round(cooling_setpoint_score * 0.55 + illuminance_score * 0.45, 3)


def _record_positive_outcome(service: UserPreferenceService, case: dict[str, Any]) -> None:
    service.record_reflection(
        trigger="longitudinal_personalization_smoke",
        user_command=f"{case['room']} repeated preference trial",
        semantic_result={"intent": case["intent"], "room": case["room"]},
        plan_result={"actions": [{"entity_id": f"simulated.{case['room']}"}]},
        execution_result={"executed_count": 1},
        feedback_result={"completed": True, "correction_round": 0},
    )


def run_longitudinal_smoke() -> list[dict[str, Any]]:
    return run_longitudinal(matrix="smoke")


def run_longitudinal(matrix: str = "smoke") -> list[dict[str, Any]]:
    profiles = _profile_cases_for_matrix(matrix)
    turn_count = SMOKE_TURN_COUNT if matrix == "smoke" else FULL_TURN_COUNT
    repeat_count = 1 if matrix == "smoke" else FULL_REPEAT_SEEDS
    records: list[dict[str, Any]] = []
    for method in METHODS:
        for repeat_seed in range(repeat_count):
            for case in profiles:
                service = UserPreferenceService()
                if method == "static_profile":
                    service.update(
                        UserPreferenceUpdate(
                            preferred_temperature_c=float(case["desired_temperature_c"]),
                            preferred_illuminance_lux=float(case["desired_illuminance_lux"]),
                        )
                    )
                for turn_index in range(1, turn_count + 1):
                    if method == "gated_confirmed_memory":
                        _record_positive_outcome(service, case)
                        service.apply_feedback(
                            UserFeedbackRequest(
                                satisfaction=5,
                                desired_temperature_c=float(case["desired_temperature_c"]),
                                desired_illuminance_lux=float(case["desired_illuminance_lux"]),
                            )
                        )
                    elif method == "ungated_memory":
                        _record_positive_outcome(service, case)

                    personalized = service.personalize_semantic_result(_base_semantic(case))
                    confirmed_experience = personalized["user_preference_context"]["confirmed_experience"]
                    targets = (
                        _ungated_proxy_targets(case, turn_index)
                        if method == "ungated_memory"
                        else _target_centers(personalized, case)
                    )
                    unauthorized_prior = method == "ungated_memory" and confirmed_experience is None and turn_index >= 2
                    records.append(
                        {
                            "schema_version": "personalization_longitudinal_record_v1",
                            "matrix": matrix,
                            "method": method,
                            "profile_id": case["profile_id"],
                            "repeat_seed": repeat_seed,
                            "intent": case["intent"],
                            "room": case["room"],
                            "turn_index": turn_index,
                            "phase": "pre_confirmation_window" if turn_index < 3 else "post_confirmation_window",
                            "explicit_feedback_count": int(
                                service.learned_patterns.get(f"{case['intent']}:{case['room']}", {}).get(
                                    "explicit_feedback_count",
                                    0,
                                )
                            ),
                            "confirmed_experience_visible": confirmed_experience is not None,
                            "unauthorized_prior_exposure": unauthorized_prior,
                            "target_temperature_c": targets["temperature_c"],
                            "target_illuminance_lux": targets["illuminance_lux"],
                            "preference_alignment_utility": _alignment_utility(targets, case),
                            "comfort_proxy": _comfort_proxy(targets, case),
                            "energy_proxy": _energy_proxy(targets, case),
                            "safety_override_count": _safety_override_count(targets),
                            "runner_source_sha256": runner_source_sha256(),
                            "task_suite_sha256": task_suite_sha256(matrix),
                            "evidence_class": "component_level_software_longitudinal_personalization_matrix",
                        }
                    )
    return records


def summarize(records: list[dict[str, Any]], matrix: str = "smoke") -> dict[str, Any]:
    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_method[str(record["method"])].append(record)

    method_summary = []
    for method in METHODS:
        method_records = by_method[method]
        pre = [float(record["preference_alignment_utility"]) for record in method_records if record["turn_index"] < 3]
        post = [float(record["preference_alignment_utility"]) for record in method_records if record["turn_index"] >= 3]
        post_records = [record for record in method_records if record["turn_index"] >= 3]
        post_visibility_rate = round(
            sum(bool(record["confirmed_experience_visible"]) for record in post_records) / len(post_records),
            4,
        )
        method_summary.append(
            {
                "method": method,
                "record_count": len(method_records),
                "mean_pre_confirmation_utility": round(mean(pre), 3),
                "mean_post_confirmation_utility": round(mean(post), 3),
                "utility_gain_post_minus_pre": round(mean(post) - mean(pre), 3),
                "post_confirmation_visibility_rate": post_visibility_rate,
                "confirmed_visibility_rate_turns_3_to_5": post_visibility_rate,
                "unauthorized_prior_exposure_count": sum(
                    bool(record["unauthorized_prior_exposure"]) for record in method_records
                ),
                "safety_override_count": sum(int(record["safety_override_count"]) for record in method_records),
                "mean_comfort_proxy": round(mean(float(record["comfort_proxy"]) for record in method_records), 3),
                "mean_energy_proxy": round(mean(float(record["energy_proxy"]) for record in method_records), 3),
            }
        )

    return {
        "schema_version": "personalization_longitudinal_experiment_v1",
        "matrix": matrix,
        "evidence_class": "component_level_software_longitudinal_personalization_matrix",
        "method_count": len(METHODS),
        "profile_count": len({record["profile_id"] for record in records}),
        "turn_count_per_profile": max(int(record["turn_index"]) for record in records),
        "repeat_count_per_profile": len({int(record["repeat_seed"]) for record in records}),
        "record_count": len(records),
        "method_summary": method_summary,
        "claim_boundary": (
            "This component run validates explicit-feedback promotion and deterministic preference-alignment proxies. "
            "It is not a full TaskRunner benchmark, not real resident feedback, and not evidence of real-home "
            "satisfaction, safety, or energy savings."
        ),
        "provenance": {
            "runner_source_sha256": runner_source_sha256(),
            "task_suite_sha256": task_suite_sha256(matrix),
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Personalization Longitudinal Experiment",
        "",
        f"Schema: `{summary['schema_version']}`",
        f"Matrix: `{summary['matrix']}`",
        f"Evidence class: `{summary['evidence_class']}`",
        "",
        f"> Boundary: {summary['claim_boundary']}",
        "",
        "| Method | Records | Pre utility | Post utility | Gain | Post-confirmation visibility | Unauthorized prior exposures | Safety overrides |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["method_summary"]:
        lines.append(
            f"| {row['method']} | {row['record_count']} | {row['mean_pre_confirmation_utility']:.3f} | "
            f"{row['mean_post_confirmation_utility']:.3f} | {row['utility_gain_post_minus_pre']:+.3f} | "
            f"{row['confirmed_visibility_rate_turns_3_to_5']:.4f} | "
            f"{row['unauthorized_prior_exposure_count']} | {row['safety_override_count']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `gated_confirmed_memory` is the only method that exposes `confirmed_experience` after the third explicit positive feedback.",
            "- `ungated_memory` is an unsafe ablation: it can improve the proxy before confirmation, but records unauthorized prior exposure.",
            "- `static_profile` is a fixed-profile baseline, not a feedback-learning mechanism.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_artifacts(records: list[dict[str, Any]], output_root: Path = DEFAULT_OUTPUT_ROOT, matrix: str = "smoke") -> Path:
    output_dir = output_root / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "records.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    summary = summarize(records, matrix=matrix)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--matrix", choices=("smoke", "full"), default="smoke")
    args = parser.parse_args()
    records = run_longitudinal(matrix=args.matrix)
    output_dir = write_artifacts(records, args.output_root, matrix=args.matrix)
    summary = summarize(records, matrix=args.matrix)
    print(json.dumps({"output_dir": str(output_dir), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
