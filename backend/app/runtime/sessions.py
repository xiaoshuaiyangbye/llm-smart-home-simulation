from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.agents.reflection_agent import ReflectionAgent
from app.research import RobustnessConfig, UserPreferenceService
from app.runtime.autonomous_service import AutonomousRuntimeService
from app.simulation.environment import SmartHomeEnvironment
from app.simulation.life_simulation import LifeSimulationService

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
DEFAULT_SESSION_ID = "default"


@dataclass
class SimulationRuntime:
    """All mutable simulation resources owned by one browser/session."""

    environment: SmartHomeEnvironment
    experiment_logger: ExperimentLogger
    task_runner: TaskRunner
    life_simulation: LifeSimulationService
    preference_service: UserPreferenceService
    robustness_config: RobustnessConfig
    autonomous_service: AutonomousRuntimeService
    reflection_agent: ReflectionAgent
    lock: RLock


class SimulationSessionStore:
    """Creates isolated runtimes and serializes mutations within each runtime."""

    def __init__(self, project_root: Path, log_dir: Path) -> None:
        self._project_root = project_root
        self._log_dir = log_dir
        self._sessions: dict[str, SimulationRuntime] = {}
        self._lock = RLock()

    def get(self, session_id: str | None) -> SimulationRuntime:
        normalized_id = self.normalize_session_id(session_id)
        with self._lock:
            runtime = self._sessions.get(normalized_id)
            if runtime is None:
                runtime = self._create_runtime(normalized_id)
                self._sessions[normalized_id] = runtime
            return runtime

    @staticmethod
    def normalize_session_id(session_id: str | None) -> str:
        if not session_id:
            return DEFAULT_SESSION_ID
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("Invalid X-Simulation-Session header.")
        return session_id

    def _create_runtime(self, session_id: str) -> SimulationRuntime:
        environment = SmartHomeEnvironment()
        environment.get_state(refresh_realtime=True)
        experiment_logger = ExperimentLogger(self._log_dir, session_id=session_id)
        preference_service = UserPreferenceService(
            storage_path=self._project_root / "data" / "private_memory" / session_id / "user_memory.json",
            encryption_key=os.getenv("PRIVATE_MEMORY_ENCRYPTION_KEY") or None,
        )
        robustness_config = RobustnessConfig()
        runtime_lock = RLock()
        task_runner = TaskRunner(environment=environment, experiment_logger=experiment_logger)
        reflection_agent = ReflectionAgent(preference_service)
        autonomous_service = AutonomousRuntimeService(
            environment=environment,
            task_runner=task_runner,
            preference_service=preference_service,
            reflection_agent=reflection_agent,
            robustness_config=robustness_config,
            runtime_lock=runtime_lock,
            config_path=self._project_root / "data" / "private_memory" / session_id / "autonomy_config.json",
        )
        return SimulationRuntime(
            environment=environment,
            experiment_logger=experiment_logger,
            task_runner=task_runner,
            life_simulation=LifeSimulationService(
                environment=environment,
                experiment_logger=experiment_logger,
                project_root=self._project_root,
                output_dir=self._project_root / "data" / "results" / "life_simulation" / session_id,
                preference_service=preference_service,
                reflection_agent=reflection_agent,
                robustness_config=robustness_config,
            ),
            preference_service=preference_service,
            robustness_config=robustness_config,
            autonomous_service=autonomous_service,
            reflection_agent=reflection_agent,
            lock=runtime_lock,
        )
