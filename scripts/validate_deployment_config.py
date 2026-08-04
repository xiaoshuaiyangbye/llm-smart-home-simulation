"""Fail-closed validation for a public smart-home deployment configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from dotenv import dotenv_values


def validate_deployment_config(env_file: Path) -> dict[str, object]:
    values = {key: str(value or "").strip() for key, value in dotenv_values(env_file).items()}
    checks: list[dict[str, object]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": passed, "detail": detail})

    app_env = values.get("APP_ENV", "")
    record("production_mode", app_env == "production", "APP_ENV must be production.")

    auth_token = values.get("API_AUTH_TOKEN", "")
    record(
        "strong_api_auth_token",
        len(auth_token) >= 32 and auth_token.lower() not in {"change-me", "example", "secret"},
        "API_AUTH_TOKEN must contain at least 32 non-placeholder characters.",
    )

    encryption_key = values.get("PRIVATE_MEMORY_ENCRYPTION_KEY", "")
    valid_encryption_key = False
    if encryption_key:
        try:
            Fernet(encryption_key.encode("ascii"))
            valid_encryption_key = True
        except (ValueError, TypeError):
            valid_encryption_key = False
    record(
        "private_memory_encryption",
        valid_encryption_key,
        "PRIVATE_MEMORY_ENCRYPTION_KEY must be a valid Fernet key.",
    )
    record(
        "separate_auth_and_encryption_keys",
        bool(auth_token and encryption_key and auth_token != encryption_key),
        "Authentication and private-memory encryption must use different secrets.",
    )

    origins = [
        origin.strip()
        for origin in values.get("BACKEND_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    record(
        "explicit_cors_origins",
        bool(origins) and "*" not in origins,
        "BACKEND_CORS_ORIGINS must explicitly list trusted origins and cannot contain '*'.",
    )

    llm_mode = values.get("LLM_MODE", "mock").lower()
    if llm_mode == "real":
        base_url = values.get("REAL_LLM_BASE_URL", "")
        parsed = urlsplit(base_url)
        endpoint_allowed = parsed.scheme == "https" or parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "host.docker.internal",
        }
        record(
            "real_llm_endpoint",
            bool(parsed.netloc and endpoint_allowed),
            "Real LLM endpoints must use HTTPS unless they are explicitly local.",
        )
        record(
            "real_llm_credentials",
            bool(values.get("REAL_LLM_API_KEY")),
            "REAL_LLM_API_KEY is required in real mode.",
        )
        record(
            "real_llm_model",
            bool(values.get("REAL_LLM_MODEL")),
            "REAL_LLM_MODEL is required in real mode.",
        )
        record(
            "real_llm_revision",
            bool(values.get("REAL_LLM_MODEL_REVISION")),
            "REAL_LLM_MODEL_REVISION is required for version-specific evidence.",
        )
    else:
        record(
            "semantic_mode_boundary",
            llm_mode == "mock",
            "LLM_MODE must be mock or real; mock remains simulation-only evidence.",
        )

    failed = [item["check"] for item in checks if not item["passed"]]
    return {
        "schema_version": "deployment_readiness_v1",
        "env_file": str(env_file),
        "ready": not failed,
        "failed_checks": failed,
        "checks": checks,
        "evidence_boundary": (
            "This validates configuration shape only; it does not prove runtime availability, "
            "identity governance, key rotation, privacy compliance, device safety, or field readiness."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error(f"Environment file does not exist: {args.env_file}")
    result = validate_deployment_config(args.env_file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
