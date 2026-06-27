from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config.simulation import SimulationConfig
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.memory.replay_log import ReplayLogIndex
from app.runtime.engine import SimulationEngine
from app.runtime.replay import ReplayEngine
from app.schemas.action_schema import DeviceActionRequest, DeviceActionResponse
from app.schemas.state_schema import ComfortState, DeviceState, EnergyState, RoomState, SmartHomeState, WeatherType
from app.schemas.task_schema import AgentCommandRequest, AgentCommandResponse, RagQueryRequest, TaskRequest, TaskResponse
from app.simulation.environment import SmartHomeEnvironment
from app.simulation.life_simulation import (
    LifeSimulationService,
    LifeSimulationStartRequest,
    LifeSimulationStatus,
)
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "data" / "logs"

app = FastAPI(title="LLM Smart Home Simulation API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

environment = SmartHomeEnvironment()
experiment_logger = ExperimentLogger(LOG_DIR)
replay_log_index = ReplayLogIndex(LOG_DIR)
task_runner = TaskRunner(environment=environment, experiment_logger=experiment_logger)
life_simulation = LifeSimulationService(
    environment=environment,
    experiment_logger=experiment_logger,
    project_root=PROJECT_ROOT,
)


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
            "targets": {
                "illuminance_lux_range": [500, 750],
                "temperature_c_range": [24, 26],
            },
            "devices": ["light", "ac", "curtain"],
        }
    )


class ResearchReplayRequest(BaseModel):
    log_file: str = Field(default="research_api.jsonl", min_length=1)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state", response_model=SmartHomeState)
def get_state() -> SmartHomeState:
    return environment.get_state()


@app.get("/api/devices", response_model=list[DeviceState])
def get_devices() -> list[DeviceState]:
    return environment.get_state().devices


@app.get("/api/rooms", response_model=list[RoomState])
def get_rooms() -> list[RoomState]:
    return environment.get_state().rooms


@app.get("/api/energy", response_model=EnergyState)
def get_energy() -> EnergyState:
    return environment.get_energy_metrics()


@app.get("/api/comfort", response_model=ComfortState)
def get_comfort() -> ComfortState:
    return environment.get_comfort_metrics()


@app.get("/api/agent/health")
def validate_agent_connection() -> dict:
    return task_runner.validate_llm_connection()


@app.get("/api/context/memory")
def get_context_memory() -> dict:
    return task_runner.get_context_memory()


@app.post("/api/context/memory/reset")
def reset_context_memory() -> dict:
    return task_runner.reset_context_memory()


@app.get("/api/rag/sources")
def get_rag_sources() -> dict:
    return task_runner.get_rag_sources()


@app.post("/api/rag/reindex")
def reindex_rag() -> dict:
    return task_runner.reindex_rag()


@app.post("/api/rag/query")
def query_rag(request: RagQueryRequest) -> dict:
    return task_runner.query_rag(request.query, request.top_k)


@app.post("/api/state/reset", response_model=SmartHomeState)
def reset_state() -> SmartHomeState:
    return environment.reset()


@app.post("/api/environment", response_model=SmartHomeState)
def update_environment(request: EnvironmentUpdateRequest) -> SmartHomeState:
    return environment.set_outdoor_environment(
        weather=request.weather,
        time_hour=request.time_hour,
    )


@app.post("/api/tasks", response_model=TaskResponse)
def run_task(request: TaskRequest) -> TaskResponse:
    return task_runner.run(request)


@app.post("/api/agent/command", response_model=AgentCommandResponse)
def run_agent_command(request: AgentCommandRequest) -> AgentCommandResponse:
    return task_runner.run_agent_command(request)


@app.post("/api/simulation/step", response_model=SmartHomeState)
def step_simulation(request: SimulationStepRequest) -> SmartHomeState:
    state = environment.step(minutes=request.minutes)
    experiment_logger.log_simulation_step(state=state, minutes=request.minutes)
    return state


@app.post("/api/research/run")
def run_research_simulation(request: ResearchRunRequest) -> dict:
    log_name = _safe_jsonl_name(request.run_id)
    log_path = LOG_DIR / log_name
    engine = SimulationEngine(
        config=SimulationConfig(
            seed=request.seed,
            tick_minutes=request.tick_minutes,
            log_run_id=request.run_id,
        ),
        log_path=log_path,
    )
    engine.reset()
    result = engine.run_agent_step(request.semantic_result, minutes=request.tick_minutes)
    return {
        "success": True,
        "log_file": log_name,
        "log_path": str(log_path),
        "planner": result["planner"],
        "executor": result["executor"],
        "critic": result["critic"],
        "after_hash": result["tick"]["after_hash"],
        "diff": result["tick"]["diff"],
    }


@app.get("/api/research/logs")
def list_research_logs() -> dict[str, list[str]]:
    return {"files": replay_log_index.list_runs()}


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
        "mismatches": result.mismatches,
    }


@app.post("/api/life-simulation/start", response_model=LifeSimulationStatus)
def start_life_simulation(request: LifeSimulationStartRequest) -> LifeSimulationStatus:
    try:
        return life_simulation.start(request.duration)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/life-simulation/tick", response_model=LifeSimulationStatus)
def tick_life_simulation() -> LifeSimulationStatus:
    return life_simulation.tick()


@app.get("/api/life-simulation/status", response_model=LifeSimulationStatus)
def get_life_simulation_status() -> LifeSimulationStatus:
    return life_simulation.status()


@app.post("/api/life-simulation/stop", response_model=LifeSimulationStatus)
def stop_life_simulation() -> LifeSimulationStatus:
    return life_simulation.stop()


@app.post("/api/life-simulation/today", response_model=SmartHomeState)
def back_to_today() -> SmartHomeState:
    return life_simulation.back_to_today()


@app.post("/api/device/action", response_model=DeviceActionResponse)
def run_device_action(request: DeviceActionRequest) -> DeviceActionResponse:
    success, message, before_state, after_state = environment.apply_device_action(
        entity_id=request.entity_id,
        action=request.action,
        parameters=request.parameters,
    )
    experiment_logger.log_device_action(
        action=request,
        success=success,
        message=message,
        state=after_state,
    )
    return DeviceActionResponse(
        success=success,
        message=message,
        before_state=before_state,
        after_state=after_state,
        action=request,
        timestamp=datetime.now().isoformat(timespec="seconds"),
    )


@app.get("/api/logs")
def list_logs() -> dict[str, list[str]]:
    return {"files": experiment_logger.list_log_files()}


@app.get("/api/logs/export")
def export_latest_log():
    log_path = experiment_logger.ensure_log_file()
    return FileResponse(
        path=log_path,
        media_type="text/csv",
        filename=log_path.name,
    )


def _safe_jsonl_name(run_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in run_id)
    return f"{safe or 'research-api'}.jsonl"
