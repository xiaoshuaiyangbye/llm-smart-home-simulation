import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "validate_field_validation_evidence.py"
spec = importlib.util.spec_from_file_location("field_validation_evidence", SCRIPT)
assert spec and spec.loader
field_validation_evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(field_validation_evidence)


def _valid_payload(artifact_directory: str) -> dict[str, object]:
    return {
        "schema_version": "field_validation_evidence_v1",
        "claim_scope": "real_device_control",
        "run_id": "field-run-001",
        "recorded_at": "2026-07-12T00:00:00Z",
        "artifact_directory": artifact_directory,
        "device_inventory": [{"entity_id": "light.study", "manufacturer": "example", "model": "L1", "firmware_version": "1.0", "gateway_version": "2.0"}],
        "test_environment": {"isolated": True, "rollback_procedure": "tested", "emergency_stop": "manual", "fault_injection_log": "faults.jsonl"},
        "measurement": {"sensor_readings_manifest": "sensors.csv", "calibration_record": "calibration.pdf", "time_sync_method": "NTP", "missing_data_policy": "record missing"},
        "experiment": {"baseline_policy": "manual", "preregistered_metrics": "metrics.md", "sampling_window": "30m", "load_concurrency_configuration": "one client", "raw_logs_manifest": "logs.csv"},
    }


def test_field_validation_evidence_requires_complete_real_device_evidence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARTIFACT_SIGNING_KEY", "field-evidence-signing-key")
    artifact_directory = tmp_path / "artifact"
    artifact_directory.mkdir()
    (artifact_directory / "raw.csv").write_text("value\n1\n", encoding="utf-8")
    field_validation_evidence.artifact_integrity.write_manifest(
        artifact_directory,
        signing_key="field-evidence-signing-key",
    )

    payload = _valid_payload("artifact")
    assert field_validation_evidence.validate(payload, tmp_path) == []

    payload["test_environment"] = {"isolated": False}
    errors = field_validation_evidence.validate(payload, tmp_path)
    assert "test_environment.isolated must be true" in errors
    assert "test_environment.rollback_procedure must be a non-empty string" in errors


def test_field_validation_evidence_rejects_changed_artifacts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARTIFACT_SIGNING_KEY", "field-evidence-signing-key")
    artifact_directory = tmp_path / "artifact"
    artifact_directory.mkdir()
    (artifact_directory / "raw.csv").write_text("value\n1\n", encoding="utf-8")
    field_validation_evidence.artifact_integrity.write_manifest(
        artifact_directory,
        signing_key="field-evidence-signing-key",
    )
    (artifact_directory / "raw.csv").write_text("value\n2\n", encoding="utf-8")

    errors = field_validation_evidence.validate(_valid_payload("artifact"), tmp_path)
    assert errors == ["artifact changed: raw.csv"]


def test_field_validation_evidence_rejects_unsigned_artifacts(tmp_path: Path) -> None:
    artifact_directory = tmp_path / "artifact"
    artifact_directory.mkdir()
    (artifact_directory / "raw.csv").write_text("value\n1\n", encoding="utf-8")
    field_validation_evidence.artifact_integrity.write_manifest(artifact_directory)

    errors = field_validation_evidence.validate(_valid_payload("artifact"), tmp_path)
    assert errors == ["artifact signature missing"]
