from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from collections import deque
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger("smart_home.api")
AUTH_COOKIE_NAME = "smart_home_access"


class FixedWindowRateLimiter:
    """Small in-process limiter; deployments can replace it with a shared gateway."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: int = 60,
        max_client_keys: int = 10_000,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")
        if max_client_keys < 1:
            raise ValueError("max_client_keys must be at least 1")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_client_keys = max_client_keys
        self._requests: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, client_key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            timestamps = self._requests.get(client_key)
            if timestamps is None:
                self._evict_expired_clients(now)
                if len(self._requests) >= self.max_client_keys:
                    # Failing closed avoids turning an unbounded set of client
                    # identifiers into an in-process memory exhaustion vector.
                    return False
                timestamps = deque()
                self._requests[client_key] = timestamps
            while timestamps and timestamps[0] <= now - self.window_seconds:
                timestamps.popleft()
            if len(timestamps) >= self.max_requests:
                return False
            timestamps.append(now)
            return True

    def _evict_expired_clients(self, now: float) -> None:
        """Drop idle client buckets before admitting a new client identifier."""
        expiry = now - self.window_seconds
        expired_client_keys = [
            client_key
            for client_key, timestamps in self._requests.items()
            if not timestamps or timestamps[-1] <= expiry
        ]
        for client_key in expired_client_keys:
            del self._requests[client_key]


def configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def add_observability_middleware(app, *, api_token: str | None, rate_limiter: FixedWindowRateLimiter) -> None:
    @app.middleware("http")
    async def trace_request(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        path = request.url.path

        if path.startswith("/api/"):
            client = request.client.host if request.client else "unknown"
            is_auth_endpoint = path.startswith("/api/auth/")
            supplied_token = request.headers.get("X-API-Key") or request.cookies.get(AUTH_COOKIE_NAME)
            if api_token and not is_auth_endpoint and not (supplied_token and secrets.compare_digest(supplied_token, api_token)):
                return _error_response(401, "Missing or invalid API key.", request_id)
            if not rate_limiter.allow(client):
                return _error_response(429, "Rate limit exceeded.", request_id)

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed request_id=%s method=%s path=%s", request_id, request.method, path)
            return _error_response(500, "Internal server error.", request_id)

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            path,
            response.status_code,
            elapsed_ms,
        )
        return response


def _error_response(status_code: int, detail: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )
