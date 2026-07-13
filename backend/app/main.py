import os
import secrets
import json
from queue import Empty, Queue
from threading import Thread
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from app.config.simulation import SimulationConfig
from app.runtime.engine import SimulationEngine
from app.runtime.observability import AUTH_COOKIE_NAME, FixedWindowRateLimiter, add_observability_middleware, configure_logging
from app.runtime.replay import ReplayEngine
from app.runtime.sessions import SimulationRuntime, SimulationSessionStore
from app.research import RobustnessConfig, UserFeedbackRequest, UserPreferenceProfile
from app.research.personalization import UserPreferenceUpdate
from app.schemas.action_schema import DeviceActionRequest, DeviceActionResponse
from app.schemas.state_schema import ComfortState, DeviceState, EnergyState, RoomState, SmartHomeState, WeatherType
from app.schemas.task_schema import AgentCommandRequest, AgentCommandResponse, RagQueryRequest, TaskRequest, TaskResponse
from app.simulation.life_simulation import LifeSimulationStartRequest, LifeSimulationStatus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "data" / "logs"

load_dotenv(PROJECT_ROOT / "backend" / ".env.local")
load_dotenv(PROJECT_ROOT / "backend" / ".env")
configure_logging()
app = FastAPI(title="LLM Smart Home Simulation API", version="0.2.0")


def _get_cors_origins() -> list[str]:
    raw_origins = os.getenv("BACKEND_CORS_ORIGINS", "")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


cors_origins = _get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
api_auth_token = os.getenv("API_AUTH_TOKEN") or None
add_observability_middleware(
    app,
    api_token=api_auth_token,
    rate_limiter=FixedWindowRateLimiter(
        max_requests=int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120")),
        max_client_keys=int(os.getenv("API_RATE_LIMIT_MAX_CLIENT_KEYS", "10000")),
    ),
)

session_store = SimulationSessionStore(PROJECT_ROOT, LOG_DIR)


def get_runtime(request: Request) -> SimulationRuntime:
    try:
        return session_store.get(request.headers.get("X-Simulation-Session"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SimulationStepRequest(BaseModel):
    minutes: int = Field(default=1, ge=1, le=1440)


class EnvironmentUpdateRequest(BaseModel):
    weather: WeatherType | None = None
    time_hour: int | None = Field(default=None, ge=0, le=23)


class ResearchRunRequest(BaseModel):
    seed: int = 42
    tick_minutes: int = Field(default=5, ge=1, le=1440)
    run_id: str = Field(default="research-api", min_length=1, max_length=80)
    semantic_result: dict = Field(
        default_factory=lambda: {
            "intent": "study_mode",
            "room": "study_room",
            "scope": "single_room",
            "control_goal": "set_target",
            "targets": {"illuminance_lux_range": [500, 750], "temperature_c_range": [24, 26]},
            "devices": ["light", "ac", "curtain"],
        }
    )


class ResearchReplayRequest(BaseModel):
    log_file: str = Field(default="research_api.jsonl", min_length=1)


class AccessTokenRequest(BaseModel):
    access_token: str = Field(min_length=1, max_length=512)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/api/auth/status")
def auth_status() -> dict[str, bool]:
    return {"requires_auth": api_auth_token is not None}


@app.post("/api/auth/session", status_code=204)
def create_auth_session(request: AccessTokenRequest, response: Response) -> Response:
    if api_auth_token is None:
        return response
    if not secrets.compare_digest(request.access_token, api_auth_token):
        raise HTTPException(status_code=401, detail="Invalid access token.")
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=api_auth_token,
        httponly=True,
        samesite="strict",
        secure=os.getenv("APP_ENV", "local") == "production",
        path="/api",
        max_age=60 * 60 * 12,
    )
    return response


@app.delete("/api/auth/session", status_code=204)
def delete_auth_session(response: Response) -> Response:
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/api")
    return response


@app.get("/api/state", response_model=SmartHomeState)
def get_state(runtime: SimulationRuntime = Depends(get_runtime)) -> SmartHomeState:
    with runtime.lock:
        return runtime.environment.get_state()


@app.get("/api/devices", response_model=list[DeviceState])
def get_devices(runtime: SimulationRuntime = Depends(get_runtime)) -> list[DeviceState]:
    with runtime.lock:
        return runtime.environment.get_state().devices


@app.get("/api/rooms", response_model=list[RoomState])
def get_rooms(runtime: SimulationRuntime = Depends(get_runtime)) -> list[RoomState]:
    with runtime.lock:
        return runtime.environment.get_state().rooms


@app.get("/api/energy", response_model=EnergyState)
def get_energy(runtime: SimulationRuntime = Depends(get_runtime)) -> EnergyState:
    with runtime.lock:
        return runtime.environment.get_energy_metrics()


@app.get("/api/comfort", response_model=ComfortState)
def get_comfort(runtime: SimulationRuntime = Depends(get_runtime)) -> ComfortState:
    with runtime.lock:
        return runtime.environment.get_comfort_metrics()


@app.get("/api/agent/health")
def validate_agent_connection(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    with runtime.lock:
        return runtime.task_runner.validate_llm_connection()


@app.get("/api/context/memory")
def get_context_memory(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    with runtime.lock:
        return runtime.task_runner.get_context_memory()


@app.get("/api/research/profile", response_model=UserPreferenceProfile)
def get_user_preference_profile(runtime: SimulationRuntime = Depends(get_runtime)) -> UserPreferenceProfile:
    with runtime.lock:
        return runtime.preference_service.profile


@app.put("/api/research/profile", response_model=UserPreferenceProfile)
def update_user_preference_profile(
    request: UserPreferenceUpdate,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> UserPreferenceProfile:
    with runtime.lock:
        return runtime.preference_service.update(request)


@app.post("/api/research/profile/feedback", response_model=UserPreferenceProfile)
def record_user_feedback(
    request: UserFeedbackRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> UserPreferenceProfile:
    with runtime.lock:
        return runtime.preference_service.apply_feedback(request)


@app.get("/api/research/robustness", response_model=RobustnessConfig)
def get_robustness_config(runtime: SimulationRuntime = Depends(get_runtime)) -> RobustnessConfig:
    return runtime.robustness_config


@app.put("/api/research/robustness", response_model=RobustnessConfig)
def update_robustness_config(
    request: RobustnessConfig,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> RobustnessConfig:
    with runtime.lock:
        runtime.robustness_config = request
        runtime.life_simulation.robustness_config = request
        return runtime.robustness_config


@app.post("/api/context/memory/reset")
def reset_context_memory(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    with runtime.lock:
        return runtime.task_runner.reset_context_memory()


@app.get("/api/rag/sources")
def get_rag_sources(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    return runtime.task_runner.get_rag_sources()


@app.post("/api/rag/reindex")
def reindex_rag(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    with runtime.lock:
        return runtime.task_runner.reindex_rag()


@app.post("/api/rag/query")
def query_rag(request: RagQueryRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    return runtime.task_runner.query_rag(request.query, request.top_k)


@app.post("/api/state/reset", response_model=SmartHomeState)
def reset_state(runtime: SimulationRuntime = Depends(get_runtime)) -> SmartHomeState:
    with runtime.lock:
        return runtime.environment.reset()


@app.post("/api/environment", response_model=SmartHomeState)
def update_environment(request: EnvironmentUpdateRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> SmartHomeState:
    with runtime.lock:
        return runtime.environment.set_outdoor_environment(weather=request.weather, time_hour=request.time_hour)


@app.post("/api/tasks", response_model=TaskResponse)
def run_task(request: TaskRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> TaskResponse:
    with runtime.lock:
        return runtime.task_runner.run(request)


@app.post("/api/agent/command", response_model=AgentCommandResponse)
def run_agent_command(request: AgentCommandRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> AgentCommandResponse:
    with runtime.lock:
        return runtime.task_runner.run_agent_command(
            request,
            preference_service=runtime.preference_service,
            robustness_config=runtime.robustness_config,
        )


@app.post("/api/agent/command/stream")
def stream_agent_command(request: AgentCommandRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> StreamingResponse:
    """Stream real-time role-stage records for the current center-orchestrated run.

    This is an SSE transport for the local UI.  Events describe actual
    blackboard stages; they do not claim a decentralized A2A protocol.
    """

    events: Queue[tuple[str, dict]] = Queue()

    def run_command() -> None:
        try:
            with runtime.lock:
                response = runtime.task_runner.run_agent_command(
                    request,
                    preference_service=runtime.preference_service,
                    robustness_config=runtime.robustness_config,
                    event_callback=lambda stage: events.put(("stage", stage)),
                )
            events.put(("complete", response.model_dump(mode="json")))
        except Exception as exc:  # Defensive boundary for errors outside TaskRunner's response envelope.
            events.put(("error", {"message": str(exc)}))

    def encode(event: str, payload: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    def event_stream():
        worker = Thread(target=run_command, name="agent-command-stream", daemon=True)
        worker.start()
        yield encode("started", {"transport": "sse", "architecture": "center_orchestrated"})
        while worker.is_alive() or not events.empty():
            try:
                event, payload = events.get(timeout=0.25)
            except Empty:
                continue
            yield encode(event, payload)
        worker.join(timeout=0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/simulation/step", response_model=SmartHomeState)
def step_simulation(request: SimulationStepRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> SmartHomeState:
    with runtime.lock:
        state = runtime.environment.step(minutes=request.minutes)
        runtime.experiment_logger.log_simulation_step(state=state, minutes=request.minutes)
        return state


@app.post("/api/research/run")
def run_research_simulation(request: ResearchRunRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    log_name = _safe_jsonl_name(request.run_id)
    log_path = LOG_DIR / log_name
    with runtime.lock:
        engine = SimulationEngine(config=SimulationConfig(seed=request.seed, tick_minutes=request.tick_minutes, log_run_id=request.run_id), log_path=log_path)
        engine.reset()
        result = engine.run_agent_step(request.semantic_result, minutes=request.tick_minutes)
    return {"success": True, "log_file": log_name, "planner": result["planner"], "executor": result["executor"], "critic": result["critic"], "after_hash": result["tick"]["after_hash"], "diff": result["tick"]["diff"]}


@app.get("/api/research/logs")
def list_research_logs() -> dict[str, list[str]]:
    return {"files": sorted(path.name for path in LOG_DIR.glob("*.jsonl"))}


@app.post("/api/research/replay")
def replay_research_log(request: ResearchReplayRequest) -> dict:
    log_path = (LOG_DIR / request.log_file).resolve()
    if LOG_DIR.resolve() not in log_path.parents or log_path.suffix != ".jsonl":
        raise HTTPException(status_code=400, detail="Invalid research log path.")
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Research log not found.")
    result = ReplayEngine().replay(log_path)
    return {
        "matched": result.matched,
        "checked_ticks": result.checked_ticks,
        "checked_plans": result.checked_plans,
        "mismatches": result.mismatches,
        # A legacy log without semantic inputs can still verify its execution
        # trace, but this field makes that narrower evidence boundary explicit.
        "unverified_plans": result.unverified_plans,
    }


@app.post("/api/life-simulation/start", response_model=LifeSimulationStatus)
def start_life_simulation(request: LifeSimulationStartRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> LifeSimulationStatus:
    with runtime.lock:
        try:
            return runtime.life_simulation.start(request.duration)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/life-simulation/tick", response_model=LifeSimulationStatus)
def tick_life_simulation(runtime: SimulationRuntime = Depends(get_runtime)) -> LifeSimulationStatus:
    with runtime.lock:
        return runtime.life_simulation.tick()


@app.get("/api/life-simulation/status", response_model=LifeSimulationStatus)
def get_life_simulation_status(runtime: SimulationRuntime = Depends(get_runtime)) -> LifeSimulationStatus:
    with runtime.lock:
        return runtime.life_simulation.status()


@app.post("/api/life-simulation/stop", response_model=LifeSimulationStatus)
def stop_life_simulation(runtime: SimulationRuntime = Depends(get_runtime)) -> LifeSimulationStatus:
    with runtime.lock:
        return runtime.life_simulation.stop()


@app.post("/api/life-simulation/today", response_model=SmartHomeState)
def back_to_today(runtime: SimulationRuntime = Depends(get_runtime)) -> SmartHomeState:
    with runtime.lock:
        return runtime.life_simulation.back_to_today()


@app.post("/api/device/action", response_model=DeviceActionResponse)
def run_device_action(request: DeviceActionRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> DeviceActionResponse:
    with runtime.lock:
        success, message, before_state, after_state = runtime.environment.apply_device_action(entity_id=request.entity_id, action=request.action, parameters=request.parameters)
        runtime.experiment_logger.log_device_action(action=request, success=success, message=message, state=after_state)
    return DeviceActionResponse(success=success, message=message, before_state=before_state, after_state=after_state, action=request, timestamp=datetime.now().isoformat(timespec="seconds"))


@app.get("/api/logs")
def list_logs(runtime: SimulationRuntime = Depends(get_runtime)) -> dict[str, list[str]]:
    return {"files": runtime.experiment_logger.list_log_files()}


@app.get("/api/logs/export")
def export_latest_log(runtime: SimulationRuntime = Depends(get_runtime)):
    return FileResponse(path=runtime.experiment_logger.ensure_log_file(), media_type="text/csv", filename=runtime.experiment_logger.log_file.name)


def _safe_jsonl_name(run_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in run_id)
    return f"{safe or 'research-api'}.jsonl"
