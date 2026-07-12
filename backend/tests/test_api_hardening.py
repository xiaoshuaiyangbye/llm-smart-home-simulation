from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app
from app.runtime.observability import AUTH_COOKIE_NAME, FixedWindowRateLimiter, add_observability_middleware


def test_sessions_keep_device_state_isolated() -> None:
    client = TestClient(app)
    session_a = {"X-Simulation-Session": "session-a"}
    session_b = {"X-Simulation-Session": "session-b"}

    action = client.post(
        "/api/device/action",
        headers=session_a,
        json={"entity_id": "light.living_room_main", "action": "turn_on", "parameters": {"brightness_pct": 80}},
    )
    assert action.status_code == 200
    assert action.json()["success"] is True

    state_a = client.get("/api/state", headers=session_a).json()
    state_b = client.get("/api/state", headers=session_b).json()
    light_a = next(device for device in state_a["devices"] if device["entity_id"] == "light.living_room_main")
    light_b = next(device for device in state_b["devices"] if device["entity_id"] == "light.living_room_main")
    assert light_a["is_on"] is True
    assert light_b["is_on"] is False


def test_invalid_session_id_is_rejected() -> None:
    response = TestClient(app).get("/api/state", headers={"X-Simulation-Session": "bad/session"})
    assert response.status_code == 400


def test_api_key_and_rate_limit_middleware() -> None:
    protected_app = FastAPI()
    add_observability_middleware(
        protected_app,
        api_token="test-token",
        rate_limiter=FixedWindowRateLimiter(max_requests=1),
    )

    @protected_app.get("/api/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(protected_app)
    unauthorized = client.get("/api/ping")
    assert unauthorized.status_code == 401
    assert unauthorized.headers["X-Request-ID"]

    allowed = client.get("/api/ping", headers={"X-API-Key": "test-token"})
    assert allowed.status_code == 200
    assert allowed.headers["X-Request-ID"]

    limited = client.get("/api/ping", headers={"X-API-Key": "test-token"})
    assert limited.status_code == 429


def test_rate_limiter_bounds_client_key_storage_and_recovers_expired_clients(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr("app.runtime.observability.time.monotonic", lambda: now[0])
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=60, max_client_keys=2)

    assert limiter.allow("client-a") is True
    assert limiter.allow("client-b") is True
    assert limiter.allow("client-c") is False
    assert set(limiter._requests) == {"client-a", "client-b"}

    now[0] += 61
    assert limiter.allow("client-c") is True
    assert set(limiter._requests) == {"client-c"}


def test_http_only_auth_cookie_can_authorize_browser_requests() -> None:
    protected_app = FastAPI()
    add_observability_middleware(
        protected_app,
        api_token="test-token",
        rate_limiter=FixedWindowRateLimiter(max_requests=2),
    )

    @protected_app.get("/api/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(protected_app)
    client.cookies.set(AUTH_COOKIE_NAME, "test-token")
    assert client.get("/api/ping").status_code == 200
