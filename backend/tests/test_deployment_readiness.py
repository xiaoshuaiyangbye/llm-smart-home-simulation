import importlib.util
from pathlib import Path

from cryptography.fernet import Fernet

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_deployment_config.py"
spec = importlib.util.spec_from_file_location("deployment_readiness", SCRIPT)
assert spec and spec.loader
deployment_readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment_readiness)
validate_deployment_config = deployment_readiness.validate_deployment_config


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_public_deployment_config_requires_auth_encryption_and_explicit_cors(tmp_path) -> None:
    result = validate_deployment_config(
        _write(
            tmp_path / "backend.env",
            [
                "APP_ENV=production",
                "LLM_MODE=mock",
                "API_AUTH_TOKEN=short",
                "PRIVATE_MEMORY_ENCRYPTION_KEY=",
                "BACKEND_CORS_ORIGINS=*",
            ],
        )
    )

    assert result["ready"] is False
    assert set(result["failed_checks"]) >= {
        "strong_api_auth_token",
        "private_memory_encryption",
        "explicit_cors_origins",
    }


def test_valid_mock_deployment_config_passes_without_exposing_secrets(tmp_path) -> None:
    auth_token = "a" * 48
    encryption_key = Fernet.generate_key().decode("ascii")
    result = validate_deployment_config(
        _write(
            tmp_path / "backend.env",
            [
                "APP_ENV=production",
                "LLM_MODE=mock",
                f"API_AUTH_TOKEN={auth_token}",
                f"PRIVATE_MEMORY_ENCRYPTION_KEY={encryption_key}",
                "BACKEND_CORS_ORIGINS=https://smart-home.example",
            ],
        )
    )

    assert result["ready"] is True
    assert auth_token not in str(result)
    assert encryption_key not in str(result)


def test_real_model_deployment_requires_immutable_revision(tmp_path) -> None:
    result = validate_deployment_config(
        _write(
            tmp_path / "backend.env",
            [
                "APP_ENV=production",
                "LLM_MODE=real",
                f"API_AUTH_TOKEN={'a' * 48}",
                f"PRIVATE_MEMORY_ENCRYPTION_KEY={Fernet.generate_key().decode('ascii')}",
                "BACKEND_CORS_ORIGINS=https://smart-home.example",
                "REAL_LLM_BASE_URL=https://models.example/v1",
                "REAL_LLM_API_KEY=configured",
                "REAL_LLM_MODEL=qwen",
                "REAL_LLM_MODEL_REVISION=",
            ],
        )
    )

    assert result["ready"] is False
    assert "real_llm_revision" in result["failed_checks"]
