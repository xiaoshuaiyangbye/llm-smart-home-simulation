from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.config.simulation import SimulationConfig
from app.runtime.engine import SimulationEngine, stable_state_hash
from app.runtime.replay import ReplayEngine


def main() -> None:
    log_path = PROJECT_ROOT / "data" / "logs" / "research_demo.jsonl"
    engine = SimulationEngine(
        config=SimulationConfig(seed=20260627, tick_minutes=5, log_run_id="research-demo"),
        log_path=log_path,
    )
    engine.reset()
    decision = engine.plan(
        {
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
    executor, critic = engine.execute_plan(decision)
    final_state = engine.world.snapshot().model_dump(mode="json")
    replay = ReplayEngine().replay(log_path)
    print(f"log_path={log_path}")
    print(f"planned_tool_calls={len(decision.tool_calls)}")
    print(f"executed_count={executor.executed_count}")
    print(f"critic_approved={critic.approved}")
    print(f"final_state_hash={stable_state_hash(final_state)}")
    print(f"replay_matched={replay.matched}")
    print(f"replay_checked_ticks={replay.checked_ticks}")


if __name__ == "__main__":
    main()
