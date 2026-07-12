"""Create and verify a SHA-256 manifest for an experiment artifact directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_NAME = "artifact_manifest.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(directory: Path) -> dict[str, object]:
    files = [path for path in sorted(directory.rglob("*")) if path.is_file() and path.name != MANIFEST_NAME]
    return {
        "schema_version": "artifact_manifest_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            {"path": path.relative_to(directory).as_posix(), "sha256": file_sha256(path), "bytes": path.stat().st_size}
            for path in files
        ],
    }


def write_manifest(directory: Path) -> Path:
    manifest_path = directory / MANIFEST_NAME
    manifest_path.write_text(json.dumps(build_manifest(directory), ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def verify_manifest(directory: Path) -> list[str]:
    payload = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in payload.get("files", [])}
    actual = {path.relative_to(directory).as_posix(): path for path in directory.rglob("*") if path.is_file() and path.name != MANIFEST_NAME}
    errors = [f"missing: {path}" for path in expected.keys() - actual.keys()]
    errors += [f"unexpected: {path}" for path in actual.keys() - expected.keys()]
    for path in expected.keys() & actual.keys():
        item = expected[path]
        if item["sha256"] != file_sha256(actual[path]) or item["bytes"] != actual[path].stat().st_size:
            errors.append(f"changed: {path}")
    return sorted(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["create", "verify"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.mode == "create":
        print(write_manifest(args.directory))
        return 0
    errors = verify_manifest(args.directory)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
