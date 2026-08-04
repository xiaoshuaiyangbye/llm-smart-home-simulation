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
from app.runtime.autonomous_service import AutonomousRuntimeConfig
from app.runtime.observability import AUTH_COOKIE_NAME, FixedWindowRateLimiter, add_observability_middleware, configure_logging
from app.runtime.replay import ReplayEngine
from app.runtime.sessions import SimulationRuntime, SimulationSessionStore
from app.research import (
    PrivateAttributeUpdate,
    PrivateMemoryResetRequest,
    RobustnessConfig,
    UserFeedbackRequest,
    UserPreferenceProfile,
)
from app.research.personalization import UserPreferenceUpdate
from app.schemas.action_schema import DeviceActionRequest, DeviceActionResponse
from app.schemas.state_schema import ComfortState, DeviceState, EnergyState, RoomId, RoomState, SmartHomeState, WeatherType
from app.schemas.task_schema import AgentCommandRequest, AgentCommandResponse, RagQueryRequest, TaskRequest, TaskResponse
from app.simulation.life_simulation import LifeSimulationStartRequest, LifeSimulationStatus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "data" / "logs"

load_dotenv(PROJECT_ROOT / "backend" / ".env.local")
load_dotenv(PROJECT_ROOT / "backend" / ".env")
configure_logging()
app = FastAPI(title="LLM Smart Home Simulation API", version="0.3.0")


def _get_cors_origins() -> list[str]:
    raw_origins = os.getenv("BACKEND_CORS_ORIGINS", "")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


cors_origins = _get_cors_origins()
api_auth_token = os.getenv("API_AUTH_TOKEN") or None
add_observability_middleware(
    app,
    api_token=api_auth_token,
    rate_limiter=FixedWindowRateLimiter(
        max_requests=int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120")),
        max_client_keys=int(os.getenv("API_RATE_LIMIT_MAX_CLIENT_KEYS", "10000")),
    ),
)
# Register CORS last so it remains the outermost user middleware and also
# decorates authentication/rate-limit failures with browser-readable headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

session_store = SimulationSessionStore(PROJECT_ROOT, LOG_DIR)


def get_runtime(request: Request) -> SimulationRuntime:
    try:
        return session_store.get(request.headers.get("X-Simulation-Session"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SimulationStepRequest(BaseModel):
    minutes: int = Field(default=1, ge=1, le=1440)


class CurrentRoomUpdateRequest(BaseModel):
    current_room_id: RoomId


class PresenceUpdateResponse(BaseModel):
    state: SmartHomeState
    reflex_action: dict | None = None
    autonomy_woken: bool


class AutonomousTickRequest(BaseModel):
    minutes: int = Field(default=5, ge=1, le=60)


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


@app.get("/api/system/readiness")
def system_readiness(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    memory = runtime.preference_service.private_memory_snapshot()
    autonomy = runtime.autonomous_service.status()
    task_suite = json.loads(
        (PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json").read_text(encoding="utf-8")
    )
    annotation = task_suite.get("semantic_annotation_provenance", {})
    independent_review_complete = all(
        annotation.get(field) == "recorded"
        for field in (
            "independent_review_evidence_status",
            "inter_annotator_agreement_evidence_status",
            "ambiguity_adjudication_evidence_status",
        )
    )
    app_env = os.getenv("APP_ENV", "local")
    auth_configured = bool(api_auth_token and len(api_auth_token) >= 32)
    encryption_configured = bool(memory["storage_security"]["encrypted_at_rest"])
    cors_configured = bool(os.getenv("BACKEND_CORS_ORIGINS", "").strip()) and "*" not in cors_origins
    return {
        "schema_version": "system_readiness_v1",
        "runtime": {
            "app_env": app_env,
            "auth_configured": auth_configured,
            "private_memory_encryption_configured": encryption_configured,
            "explicit_cors_configured": cors_configured,
            "storage_health": memory["storage_health"],
            "autonomous_planning_commit_mode": autonomy["planning_commit_mode"],
            "stale_plan_count": autonomy["stale_plan_count"],
        },
        "deployment": {
            "ready_for_public_deployment": (
                app_env == "production"
                and auth_configured
                and encryption_configured
                and cors_configured
            ),
            "config_validator": "scripts/validate_deployment_config.py",
        },
        "research_claims": {
            "independent_semantic_review_complete": independent_review_complete,
            "real_device_field_evidence_complete": False,
            "ready_for_real_home_claim": False,
            "required_external_work": [
                "two independent semantic reviewers plus adjudication",
                "validated real-device field evidence",
            ],
        },
        "evidence_boundary": (
            "Runtime readiness is software observability, not privacy compliance, "
            "real-resident effectiveness, real-device safety, or field validation."
        ),
    }


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
        return runtime.environment.get_state(refresh_realtime=False)


@app.get("/api/devices", response_model=list[DeviceState])
def get_devices(runtime: SimulationRuntime = Depends(get_runtime)) -> list[DeviceState]:
    with runtime.lock:
        return runtime.environment.get_state(refresh_realtime=False).devices


@app.get("/api/rooms", response_model=list[RoomState])
def get_rooms(runtime: SimulationRuntime = Depends(get_runtime)) -> list[RoomState]:
    with runtime.lock:
        return runtime.environment.get_state(refresh_realtime=False).rooms


@app.get("/api/energy", response_model=EnergyState)
def get_energy(runtime: SimulationRuntime = Depends(get_runtime)) -> EnergyState:
    with runtime.lock:
        return runtime.environment.get_state(refresh_realtime=False).energy_metrics


@app.get("/api/comfort", response_model=ComfortState)
def get_comfort(runtime: SimulationRuntime = Depends(get_runtime)) -> ComfortState:
    with runtime.lock:
        return runtime.environment.get_state(refresh_realtime=False).comfort_metrics


@app.put("/api/presence/current-room", response_model=PresenceUpdateResponse)
def update_current_room(
    request: CurrentRoomUpdateRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> PresenceUpdateResponse:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "更新人员位置")
        result = runtime.autonomous_service.update_presence(request.current_room_id)
        return PresenceUpdateResponse.model_validate(result)


@app.get("/api/agent/health")
def validate_agent_connection(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    # Snapshot mutable simulator state under the runtime lock, then release it
    # before the potentially slow network probe. A real-model health check must
    # not block unrelated memory saves, device controls, or state reads.
    with runtime.lock:
        current_state = runtime.environment.get_state(refresh_realtime=False)
    return runtime.task_runner.validate_llm_connection(current_state=current_state)


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
        _reject_during_life_simulation(runtime, "修改用户偏好")
        profile = runtime.preference_service.update(request)
    runtime.autonomous_service.request_immediate_cycle()
    return profile


@app.post("/api/research/profile/feedback", response_model=UserPreferenceProfile)
def record_user_feedback(
    request: UserFeedbackRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> UserPreferenceProfile:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "提交偏好反馈")
        profile = runtime.preference_service.apply_feedback(request)
    runtime.autonomous_service.request_immediate_cycle()
    return profile


@app.get("/api/research/private-memory")
def get_private_user_memory(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    with runtime.lock:
        return runtime.preference_service.private_memory_snapshot()


@app.put("/api/research/private-memory/attributes")
def update_private_user_attributes(
    request: PrivateAttributeUpdate,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> dict:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "修改私有知识")
        memory = runtime.preference_service.update_private_attributes(request)
    runtime.autonomous_service.request_immediate_cycle()
    return memory


@app.delete("/api/research/private-memory")
def reset_private_user_memory(
    request: PrivateMemoryResetRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> dict:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "清除私有知识")
        if runtime.autonomous_service.status()["active"]:
            raise HTTPException(status_code=409, detail="请先停止自治服务，再清除用户私有记忆。")
        return runtime.preference_service.reset_private_memory(request)


@app.get("/api/research/robustness", response_model=RobustnessConfig)
def get_robustness_config(runtime: SimulationRuntime = Depends(get_runtime)) -> RobustnessConfig:
    return runtime.robustness_config


@app.put("/api/research/robustness", response_model=RobustnessConfig)
def update_robustness_config(
    request: RobustnessConfig,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> RobustnessConfig:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "修改鲁棒性配置")
        runtime.robustness_config = request
        runtime.life_simulation.robustness_config = request
        runtime.autonomous_service.robustness_config = request
        config = runtime.robustness_config
    runtime.autonomous_service.request_immediate_cycle()
    return config


@app.post("/api/context/memory/reset")
def reset_context_memory(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "重置上下文记忆")
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
        _reject_during_life_simulation(runtime, "重置环境")
        if runtime.autonomous_service.status()["active"]:
            raise HTTPException(status_code=409, detail="请先停止自治服务，再重置环境状态。")
        return runtime.environment.reset()


@app.post("/api/environment", response_model=SmartHomeState)
def update_environment(request: EnvironmentUpdateRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> SmartHomeState:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "修改室外环境")
        state = runtime.environment.set_outdoor_environment(weather=request.weather, time_hour=request.time_hour)
    runtime.autonomous_service.request_immediate_cycle()
    return state


@app.post("/api/tasks", response_model=TaskResponse)
def run_task(request: TaskRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> TaskResponse:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "执行交互任务")
        response = runtime.task_runner.run(request)
        if response.success:
            _register_manual_overrides(runtime, response.agent_output.actions)
        return response


@app.post("/api/agent/command", response_model=AgentCommandResponse)
def run_agent_command(request: AgentCommandRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> AgentCommandResponse:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "执行自然语言控制")
        response = runtime.task_runner.run_agent_command(
            request,
            preference_service=runtime.preference_service,
            robustness_config=runtime.robustness_config,
        )
        response = _attach_post_decision_reflection(runtime, request, response, trigger="interactive_command")
        if response.success:
            _register_manual_overrides(runtime, response.plan_result.get("actions", []))
        return response


@app.post("/api/agent/command/stream")
def stream_agent_command(request: AgentCommandRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> StreamingResponse:
    """Stream real-time role-stage records for the current center-orchestrated run.

    This is an SSE transport for the local UI.  Events describe actual
    blackboard stages; they do not claim a decentralized A2A protocol.
    """

    events: Queue[tuple[str, dict]] = Queue()

    with runtime.lock:
        _reject_during_life_simulation(runtime, "执行自然语言控制")

    def run_command() -> None:
        try:
            with runtime.lock:
                _reject_during_life_simulation(runtime, "执行自然语言控制")
                response = runtime.task_runner.run_agent_command(
                    request,
                    preference_service=runtime.preference_service,
                    robustness_config=runtime.robustness_config,
                    event_callback=lambda stage: events.put(("stage", stage)),
                )
                response = _attach_post_decision_reflection(
                    runtime,
                    request,
                    response,
                    trigger="interactive_command_stream",
                    event_callback=lambda stage: events.put(("stage", stage)),
                )
                if response.success:
                    _register_manual_overrides(runtime, response.plan_result.get("actions", []))
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
        _reject_during_life_simulation(runtime, "推进普通仿真")
        state = runtime.environment.step(minutes=request.minutes, refresh_realtime=False)
        runtime.experiment_logger.log_simulation_step(state=state, minutes=request.minutes)
        return state


@app.post("/api/autonomy/tick")
def run_autonomous_sensor_tick(
    request: AutonomousTickRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> dict:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "执行自治诊断周期")
        if runtime.autonomous_service.status()["active"]:
            raise HTTPException(status_code=409, detail="自治服务运行中，请通过状态接口观察后台周期。")
        return runtime.autonomous_service.run_once(
            trigger="autonomous_diagnostic_tick",
            simulation_minutes=request.minutes,
        )


@app.post("/api/autonomy/start")
def start_autonomous_runtime(
    request: AutonomousRuntimeConfig,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> dict:
    with runtime.lock:
        if runtime.life_simulation.active:
            raise HTTPException(status_code=409, detail="生活快速仿真运行中，不能同时启动常驻自治服务。")
        try:
            return runtime.autonomous_service.start(request)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/autonomy/stop")
def stop_autonomous_runtime(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    return runtime.autonomous_service.stop()


@app.get("/api/autonomy/status")
def get_autonomous_runtime_status(runtime: SimulationRuntime = Depends(get_runtime)) -> dict:
    return runtime.autonomous_service.status()


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
            if runtime.autonomous_service.status()["active"]:
                raise RuntimeError("常驻自治服务运行中，请先停止自治服务再启动生活快速仿真。")
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
        if runtime.autonomous_service.status()["active"]:
            raise HTTPException(status_code=409, detail="请先停止自治服务，再回到今天。")
        return runtime.life_simulation.back_to_today()


@app.post("/api/device/action", response_model=DeviceActionResponse)
def run_device_action(request: DeviceActionRequest, runtime: SimulationRuntime = Depends(get_runtime)) -> DeviceActionResponse:
    with runtime.lock:
        _reject_during_life_simulation(runtime, "手动控制设备")
        success, message, before_state, after_state = runtime.environment.apply_device_action(entity_id=request.entity_id, action=request.action, parameters=request.parameters)
        runtime.experiment_logger.log_device_action(action=request, success=success, message=message, state=after_state)
        if success:
            _register_manual_overrides(runtime, [request.model_dump(mode="json")])
    return DeviceActionResponse(success=success, message=message, before_state=before_state, after_state=after_state, action=request, timestamp=datetime.now().isoformat(timespec="seconds"))


@app.get("/api/logs")
def list_logs(runtime: SimulationRuntime = Depends(get_runtime)) -> dict[str, list[str]]:
    return {"files": runtime.experiment_logger.list_log_files()}


@app.get("/api/logs/export")
def export_latest_log(runtime: SimulationRuntime = Depends(get_runtime)):
    return FileResponse(path=runtime.experiment_logger.ensure_log_file(), media_type="text/csv", filename=runtime.experiment_logger.log_file.name)


def _attach_post_decision_reflection(
    runtime: SimulationRuntime,
    request: AgentCommandRequest,
    response: AgentCommandResponse,
    *,
    trigger: str,
    event_callback=None,
) -> AgentCommandResponse:
    return runtime.reflection_agent.reflect(
        response,
        user_command=request.user_command,
        trigger=trigger,
        event_callback=event_callback,
    )


def _reject_during_life_simulation(runtime: SimulationRuntime, operation: str) -> None:
    if runtime.life_simulation.active:
        raise HTTPException(
            status_code=409,
            detail=f"生活快速仿真运行中，不能{operation}；请先停止生活仿真。",
        )


def _register_manual_overrides(
    runtime: SimulationRuntime,
    actions: list[object],
) -> None:
    devices = {
        device.entity_id: device
        for device in runtime.environment.get_state(refresh_realtime=False).devices
    }
    for action in actions:
        if hasattr(action, "model_dump"):
            action = action.model_dump(mode="json")
        if not isinstance(action, dict):
            continue
        device = devices.get(str(action.get("entity_id", "")))
        if device is None:
            continue
        runtime.autonomous_service.register_manual_override(
            room_id=device.room,
            device_type=device.device_type,
        )


def _safe_jsonl_name(run_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in run_id)
    return f"{safe or 'research-api'}.jsonl"
