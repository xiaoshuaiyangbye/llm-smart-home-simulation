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
