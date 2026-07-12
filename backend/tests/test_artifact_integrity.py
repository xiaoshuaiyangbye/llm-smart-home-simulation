import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_artifact_integrity.py"
spec = importlib.util.spec_from_file_location("artifact_integrity", SCRIPT)
assert spec and spec.loader
artifact_integrity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact_integrity)


def test_manifest_detects_changes_and_unexpected_files(tmp_path: Path) -> None:
    (tmp_path / "summary.json").write_text('{"ok": true}', encoding="utf-8")
    artifact_integrity.write_manifest(tmp_path)
    assert artifact_integrity.verify_manifest(tmp_path) == []

    (tmp_path / "summary.json").write_text('{"ok": false}', encoding="utf-8")
    (tmp_path / "extra.txt").write_text("unexpected", encoding="utf-8")
    assert artifact_integrity.verify_manifest(tmp_path) == ["changed: summary.json", "unexpected: extra.txt"]
