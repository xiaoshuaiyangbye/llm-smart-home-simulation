import json

from app.agents import llm_client


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_real_client_sends_explicit_reproducible_decoding_controls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(b'{"choices":[{"message":{"content":"{}"}}]}')

    monkeypatch.setenv("REAL_LLM_API_KEY", "test-key")
    monkeypatch.setenv("REAL_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("REAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("REAL_LLM_MODEL_REVISION", "sha256:immutable-local-model")
    monkeypatch.setenv("REAL_LLM_STREAM", "false")
    monkeypatch.setenv("REAL_LLM_TEMPERATURE", "0.0")
    monkeypatch.setenv("REAL_LLM_SEED", "1729")
    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)

    client = llm_client.RealLLMClient()
    assert client._chat_completion("return JSON") == "{}"

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["temperature"] == 0.0
    assert payload["seed"] == 1729
    assert client.model_revision == "sha256:immutable-local-model"


def test_real_connection_reports_configured_model_revision(monkeypatch) -> None:
    monkeypatch.setenv("REAL_LLM_API_KEY", "test-key")
    monkeypatch.setenv("REAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("REAL_LLM_MODEL_REVISION", "sha256:immutable-local-model")
    client = llm_client.RealLLMClient()
    monkeypatch.setattr(client, "parse_command", lambda *_args, **_kwargs: {})

    status = client.validate_connection(None)

    assert status["success"] is True
    assert status["model_revision"] == "sha256:immutable-local-model"


def test_local_ollama_empty_openai_response_uses_explicit_native_fallback(monkeypatch) -> None:
    requests: list[object] = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/chat/completions"):
            return _FakeResponse(b'{"choices":[{"message":{"content":""}}]}')
        return _FakeResponse(b'{"message":{"content":"{}"}}')

    monkeypatch.setenv("REAL_LLM_API_KEY", "ollama")
    monkeypatch.setenv("REAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("REAL_LLM_STREAM", "false")
    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    client = llm_client.RealLLMClient()

    assert client._chat_completion("return JSON") == "{}"
    assert client._last_transport == "ollama_native_fallback"
    assert len(requests) == 2
    native_payload = json.loads(requests[1].data.decode("utf-8"))
    assert native_payload["stream"] is False
    assert native_payload["options"]["seed"] == 42
