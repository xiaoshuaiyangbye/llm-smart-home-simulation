from dataclasses import dataclass, field
from pathlib import Path

from app.config.simulation import SimulationConfig
from app.runtime.engine import SimulationEngine, stable_state_hash
from app.runtime.logging import read_jsonl
from app.tools.schemas import ToolCall
from app.world.smart_home_world import SmartHomeWorld


@dataclass
class ReplayResult:
    matched: bool
    checked_ticks: int
    mismatches: list[dict] = field(default_factory=list)


class ReplayEngine:
    def replay(self, log_path: Path) -> ReplayResult:
        records = read_jsonl(log_path)
        start_record = next((item for item in records if item["event_type"] == "run_started"), None)
        if start_record is None:
            return ReplayResult(
                matched=False,
                checked_ticks=0,
                mismatches=[{"reason": "missing run_started record"}],
            )

        config = SimulationConfig(
            seed=int(start_record["payload"]["seed"]),
            tick_minutes=int(start_record["payload"]["tick_minutes"]),
            log_run_id="replay",
        )
        engine = SimulationEngine(
            world=SmartHomeWorld(),
            config=config,
            log_path=log_path.with_suffix(".replay.tmp.jsonl"),
        )
        initial = engine.reset()
        mismatches: list[dict] = []
        if initial["state_hash"] != start_record["payload"]["state_hash"]:
            mismatches.append(
                {
                    "tick": 0,
                    "reason": "initial state hash mismatch",
                    "expected": start_record["payload"]["state_hash"],
                    "actual": initial["state_hash"],
                }
            )

        checked = 0
        for record in records:
            if record["event_type"] != "tick_completed":
                continue
            payload = record["payload"]
            calls = [ToolCall.model_validate(item) for item in payload.get("actions", [])]
            result = engine.tick(calls, minutes=int(payload["minutes"]))
            actual_hash = stable_state_hash(result["state"])
            expected_hash = payload["after_hash"]
            checked += 1
            if actual_hash != expected_hash:
                mismatches.append(
                    {
                        "tick": record["tick"],
                        "reason": "state hash mismatch",
                        "expected": expected_hash,
                        "actual": actual_hash,
                    }
                )
        tmp_path = log_path.with_suffix(".replay.tmp.jsonl")
        if tmp_path.exists():
            tmp_path.unlink()
        return ReplayResult(matched=not mismatches, checked_ticks=checked, mismatches=mismatches)

