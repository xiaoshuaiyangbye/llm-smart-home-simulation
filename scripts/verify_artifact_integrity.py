"""Create and verify a SHA-256 manifest for an experiment artifact directory."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
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


def _canonical_manifest(payload: dict[str, object]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _signature(payload: dict[str, object], signing_key: str) -> str:
    return hmac.new(
        signing_key.encode("utf-8"),
        _canonical_manifest(payload),
        hashlib.sha256,
    ).hexdigest()


def write_manifest(directory: Path, signing_key: str | None = None) -> Path:
    manifest_path = directory / MANIFEST_NAME
    payload = build_manifest(directory)
    if signing_key:
        payload["schema_version"] = "artifact_manifest_v2_signed"
        payload["signature"] = {
            "algorithm": "hmac-sha256",
            "value": _signature(payload, signing_key),
        }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def verify_manifest(
    directory: Path,
    signing_key: str | None = None,
    *,
    require_signature: bool = False,
) -> list[str]:
    payload = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    errors: list[str] = []
    signature = payload.get("signature")
    if signature is None:
        if require_signature:
            errors.append("signature missing")
    elif not isinstance(signature, dict) or signature.get("algorithm") != "hmac-sha256":
        errors.append("signature format invalid")
    elif not signing_key:
        errors.append("signature key unavailable")
    else:
        expected_signature = _signature(payload, signing_key)
        supplied_signature = signature.get("value")
        if not isinstance(supplied_signature, str) or not hmac.compare_digest(
            supplied_signature,
            expected_signature,
        ):
            errors.append("signature mismatch")
    expected = {item["path"]: item for item in payload.get("files", [])}
    actual = {path.relative_to(directory).as_posix(): path for path in directory.rglob("*") if path.is_file() and path.name != MANIFEST_NAME}
    errors += [f"missing: {path}" for path in expected.keys() - actual.keys()]
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
    parser.add_argument(
        "--signing-key-env",
        default="ARTIFACT_SIGNING_KEY",
        help="Environment variable containing the HMAC key; the key is never written to output.",
    )
    parser.add_argument("--require-signature", action="store_true")
    args = parser.parse_args()
    signing_key = os.getenv(args.signing_key_env) or None
    if args.mode == "create":
        if args.require_signature and not signing_key:
            parser.error(f"Required signing key environment variable is unset: {args.signing_key_env}")
        print(write_manifest(args.directory, signing_key=signing_key))
        return 0
    errors = verify_manifest(
        args.directory,
        signing_key=signing_key,
        require_signature=args.require_signature,
    )
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
