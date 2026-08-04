"""Exercise the deployed API through an isolated QA resident workspace."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "results" / "quality" / "live_api_matrix.json"


@dataclass
class Check:
    name: str
    method: str
    path: str
    status: int
    duration_ms: float


class ApiClient:
    def __init__(self, base_url: str, session_id: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
        )
        self.checks: list[Check] = []

    def json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response, raw = self._request(method, path, body)
        if response.status == 204 or not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def text(self, method: str, path: str, payload: dict[str, Any] | None = None) -> str:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        _, raw = self._request(method, path, body)
        return raw.decode("utf-8")

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
    ) -> tuple[Any, bytes]:
        headers = {"X-Simulation-Session": self.session_id}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        started = time.perf_counter()
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} returned {exc.code}: {detail}") from exc
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        self.checks.append(Check(path.strip("/").replace("/", ".") or "root", method, path, status, duration_ms))
        return response, raw


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def best_effort_cleanup(client: ApiClient) -> None:
    for method, path, payload in [
        ("POST", "/api/autonomy/stop", None),
        ("POST", "/api/life-simulation/stop", None),
        ("POST", "/api/context/memory/reset", None),
        ("DELETE", "/api/research/private-memory", {"confirmation": "RESET_PRIVATE_MEMORY"}),
    ]:
        try:
            client.json(method, path, payload)
        except Exception:
            continue


def run_matrix(client: ApiClient) -> dict[str, Any]:
    health = client.json("GET", "/health")
    require(health["status"] == "ok", "health endpoint did not report ok")

    auth = client.json("GET", "/api/auth/status")
    if auth["requires_auth"]:
        token = os.getenv("API_AUTH_TOKEN")
        require(token, "deployment requires auth; set API_AUTH_TOKEN for the smoke run")
        client.json("POST", "/api/auth/session", {"access_token": token})

    state = client.json("GET", "/api/state")
    readiness = client.json("GET", "/api/system/readiness")
    devices = client.json("GET", "/api/devices")
    rooms = client.json("GET", "/api/rooms")
    energy = client.json("GET", "/api/energy")
    comfort = client.json("GET", "/api/comfort")
    require(len(state["rooms"]) == len(rooms) >= 1, "room/state coverage mismatch")
    require(len(devices) >= 1, "no devices returned")
    require("current_power_w" in energy, "energy payload missing current power")
    require("average_overall_score" in comfort, "comfort payload missing overall score")
    require(
        readiness["runtime"]["autonomous_planning_commit_mode"]
        == "optimistic_snapshot_commit_v1",
        "runtime readiness did not expose the snapshot commit contract",
    )
    require(
        readiness["research_claims"]["ready_for_real_home_claim"] is False,
        "software smoke must not claim real-home readiness",
    )

    llm_health = client.json("GET", "/api/agent/health")
    require(llm_health["success"] is True, f"real LLM health failed: {llm_health.get('error')}")

    client.json("GET", "/api/context/memory")
    profile = client.json("PUT", "/api/research/profile", {"preferred_temperature_c": 25.0})
    require(profile["preferred_temperature_c"] == 25.0, "profile update was not applied")
    feedback = client.json("POST", "/api/research/profile/feedback", {"satisfaction": 4})
    require(feedback["feedback_count"] >= 1, "feedback was not recorded")
    memory = client.json(
        "PUT",
        "/api/research/private-memory/attributes",
        {"attributes": {"health_constraints": "QA 怕风", "sleep_and_routine": "QA 23:00 入睡"}},
    )
    require(memory["private_attributes"]["health_constraints"] == "QA 怕风", "private attribute save failed")
    client.json("GET", "/api/research/private-memory")

    robustness = client.json(
        "PUT",
        "/api/research/robustness",
        {
            "enabled": True,
            "seed": 42,
            "temperature_sensor_noise_c": 0.1,
            "illuminance_sensor_noise_lux": 5,
            "actuator_failure_probability": 0,
        },
    )
    require(robustness["enabled"] is True, "robustness update failed")
    client.json("GET", "/api/research/robustness")

    sources = client.json("GET", "/api/rag/sources")
    require(sources["source_count"] >= 1, "RAG index has no sources")
    query = client.json("POST", "/api/rag/query", {"query": "comfort standards temperature", "top_k": 3})
    require(len(query["matches"]) >= 1, "RAG query returned no matches")
    reindex = client.json("POST", "/api/rag/reindex")
    require(reindex["source_count"] >= 1, "RAG reindex returned no sources")

    client.json("POST", "/api/environment", {"weather": "cloudy", "time_hour": 21})
    presence = client.json("PUT", "/api/presence/current-room", {"current_room_id": "bathroom"})
    require(
        [room["room_id"] for room in presence["state"]["rooms"] if room["occupancy"]] == ["bathroom"],
        "presence event did not update backend occupancy",
    )
    stepped = client.json("POST", "/api/simulation/step", {"minutes": 1})
    require(stepped["current_time_step"] >= 1, "simulation did not advance")
    device = client.json(
        "POST",
        "/api/device/action",
        {"entity_id": "light.living_room_main", "action": "turn_on", "parameters": {}},
    )
    require(device["success"] is True, "manual device action failed")

    task = client.json("POST", "/api/tasks", {"user_command": "打开客厅灯", "experiment_id": "live-api-smoke"})
    require(task["success"] is True, f"task pipeline failed: {task.get('error')}")
    command = client.json(
        "POST",
        "/api/agent/command",
        {"user_command": "把客厅灯调亮一点", "current_room_id": "living_room"},
    )
    require(command["success"] is True, f"agent command failed: {command.get('error')}")
    sse = client.text(
        "POST",
        "/api/agent/command/stream",
        {"user_command": "关闭客厅灯", "current_room_id": "living_room"},
    )
    require("event: started" in sse and "event: complete" in sse, "SSE command did not complete")

    diagnostic = client.json("POST", "/api/autonomy/tick", {"minutes": 1})
    require("decision" in diagnostic and "state" in diagnostic, "autonomy diagnostic tick is incomplete")
    started = client.json(
        "POST",
        "/api/autonomy/start",
        {
            "interval_seconds": 300,
            "simulation_minutes_per_cycle": 1,
            "repeated_trigger_cooldown_seconds": 30,
            "max_consecutive_failures": 3,
        },
    )
    require(started["active"] is True, "autonomy service did not start")
    require(client.json("GET", "/api/autonomy/status")["active"] is True, "autonomy status is not active")
    stopped = client.json("POST", "/api/autonomy/stop")
    require(
        stopped["active"] is False or stopped.get("stopping") is True,
        "autonomy service did not accept the stop request",
    )
    stop_deadline = time.monotonic() + client.timeout
    while stopped["active"] and time.monotonic() < stop_deadline:
        time.sleep(0.25)
        stopped = client.json("GET", "/api/autonomy/status")
    require(stopped["active"] is False, "autonomy worker did not finish before the smoke timeout")

    life = client.json("POST", "/api/life-simulation/start", {"duration": "day"})
    require(life["active"] is True, "life simulation did not start")
    tick = client.json("POST", "/api/life-simulation/tick")
    require(tick["simulated_minute"] >= life["simulated_minute"], "life simulation did not advance")
    client.json("GET", "/api/life-simulation/status")
    require(client.json("POST", "/api/life-simulation/stop")["active"] is False, "life simulation did not stop")
    client.json("POST", "/api/life-simulation/today")

    run_id = f"live-api-{uuid4().hex[:12]}"
    research = client.json("POST", "/api/research/run", {"seed": 42, "tick_minutes": 1, "run_id": run_id})
    require(research["success"] is True, "research run failed")
    client.json("GET", "/api/research/logs")
    replay = client.json("POST", "/api/research/replay", {"log_file": research["log_file"]})
    require(replay["matched"] is True, "research replay did not match")
    client.json("GET", "/api/logs")
    exported = client.text("GET", "/api/logs/export")
    require(bool(exported.strip()), "log export was empty")

    client.json("POST", "/api/context/memory/reset")
    client.json("POST", "/api/state/reset")
    reset_memory = client.json(
        "DELETE",
        "/api/research/private-memory",
        {"confirmation": "RESET_PRIVATE_MEMORY"},
    )
    require(reset_memory["private_attributes"] == {}, "private-memory cleanup failed")

    return {
        "llm_mode": llm_health.get("llm_mode"),
        "model": llm_health.get("model"),
        "checks": [asdict(check) for check in client.checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    session_id = f"live-api-smoke-{uuid4().hex[:16]}"
    client = ApiClient(args.base_url, session_id, args.timeout)
    started = time.perf_counter()
    try:
        result = run_matrix(client)
        status = "passed"
        error = None
    except Exception as exc:  # The persisted report is the diagnostic handoff.
        result = {"checks": [asdict(check) for check in client.checks]}
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        best_effort_cleanup(client)

    report = {
        "schema_version": "live_api_matrix_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "session_id": session_id,
        "status": status,
        "error": error,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        **result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
