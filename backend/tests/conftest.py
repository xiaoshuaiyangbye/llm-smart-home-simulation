from pathlib import Path
import os
import sys
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# Unit tests must not depend on a locally running embedding service. Production
# and local development can still opt into RAG_RETRIEVAL_MODE=local_embedding.
os.environ["RAG_RETRIEVAL_MODE"] = "lexical"


@pytest.fixture
def isolated_api_runtime(monkeypatch, tmp_path):
    """Inject offline test runtimes without weakening the online real-only gate."""
    from fastapi import Request
    from app.main import app, get_runtime
    from app.runtime.sessions import SimulationSessionStore

    monkeypatch.setenv("LLM_MODE", "mock")
    store = SimulationSessionStore(tmp_path, tmp_path / "logs")

    def runtime_for_request(request: Request):
        return store.get(request.headers.get("X-Simulation-Session"))

    monkeypatch.setitem(app.dependency_overrides, get_runtime, runtime_for_request)
    yield store
    for runtime in store._sessions.values():
        runtime.autonomous_service.stop()
