"""Validate auditable evidence before making claims about real smart-home devices."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTEGRITY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_artifact_integrity.py"
_spec = importlib.util.spec_from_file_location("artifact_integrity", INTEGRITY_SCRIPT)
assert _spec and _spec.loader
artifact_integrity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(artifact_integrity)

REAL_CLAIM_SCOPES = {"real_device_control", "real_device_safety", "real_energy_saving"}
REQUIRED_DEVICE_FIELDS = ("entity_id", "manufacturer", "model", "firmware_version", "gateway_version")
REQUIRED_TEXT_FIELDS = {
    "test_environment": ("rollback_procedure", "emergency_stop", "fault_injection_log"),
    "measurement": ("sensor_readings_manifest", "calibration_record", "time_sync_method", "missing_data_policy"),
    "experiment": ("baseline_policy", "preregistered_metrics", "sampling_window", "load_concurrency_configuration", "raw_logs_manifest"),
}


def validate(payload: object, base_directory: Path) -> list[str]:
    if not isinstance(payload, dict):
        return ["evidence must be a JSON object"]
    errors: list[str] = []
    if payload.get("schema_version") != "field_validation_evidence_v1":
        errors.append("schema_version must be field_validation_evidence_v1")
    scope = payload.get("claim_scope")
    if scope not in REAL_CLAIM_SCOPES:
        errors.append(f"claim_scope must be one of {sorted(REAL_CLAIM_SCOPES)}")
    for field in ("run_id", "recorded_at", "artifact_directory"):
        if not _non_empty_text(payload.get(field)):
            errors.append(f"{field} must be a non-empty string")
    inventory = payload.get("device_inventory")
    if not isinstance(inventory, list) or not inventory:
        errors.append("device_inventory must contain at least one device")
    else:
        for index, device in enumerate(inventory):
            if not isinstance(device, dict):
                errors.append(f"device_inventory[{index}] must be an object")
                continue
            for field in REQUIRED_DEVICE_FIELDS:
                if not _non_empty_text(device.get(field)):
                    errors.append(f"device_inventory[{index}].{field} must be a non-empty string")
    environment = payload.get("test_environment")
    if not isinstance(environment, dict) or environment.get("isolated") is not True:
        errors.append("test_environment.isolated must be true")
    for section, fields in REQUIRED_TEXT_FIELDS.items():
        value = payload.get(section)
        if not isinstance(value, dict):
            errors.append(f"{section} must be an object")
            continue
        for field in fields:
            if not _non_empty_text(value.get(field)):
                errors.append(f"{section}.{field} must be a non-empty string")
    artifact_value = payload.get("artifact_directory")
    if _non_empty_text(artifact_value):
        artifact_directory = Path(str(artifact_value))
        if not artifact_directory.is_absolute():
            artifact_directory = base_directory / artifact_directory
        manifest_path = artifact_directory / artifact_integrity.MANIFEST_NAME
        if not manifest_path.is_file():
            errors.append(f"artifact manifest is missing: {manifest_path}")
        else:
            try:
                errors.extend(
                    f"artifact {error}"
                    for error in artifact_integrity.verify_manifest(
                        artifact_directory,
                        signing_key=os.getenv("ARTIFACT_SIGNING_KEY") or None,
                        require_signature=True,
                    )
                )
            except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as error:
                errors.append(f"artifact manifest cannot be verified: {type(error).__name__}")
    return sorted(errors)


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="completed field-validation evidence JSON")
    args = parser.parse_args()
    payload: Any = json.loads(args.evidence.read_text(encoding="utf-8"))
    errors = validate(payload, args.evidence.parent)
    print(json.dumps({"accepted": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
