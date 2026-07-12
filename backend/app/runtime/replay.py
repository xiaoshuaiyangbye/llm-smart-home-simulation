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
    checked_plans: int = 0
    mismatches: list[dict] = field(default_factory=list)
    unverified_plans: list[dict] = field(default_factory=list)


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
        checked_plans = 0
        semantic_inputs: dict[int, dict] = {}
        unverified_plans: list[dict] = []
        for record in records:
            event_type = record["event_type"]
            payload = record["payload"]
            if event_type == "agent_semantic_input":
                semantic_inputs[int(record["tick"])] = payload
                continue
            if event_type == "agent_planned":
                tick = int(record["tick"])
                semantic_payload = semantic_inputs.get(tick)
                if semantic_payload is None:
                    # Logs created before semantic-input provenance was added
                    # remain replayable, but cannot support a planning claim.
                    unverified_plans.append(
                        {"tick": tick, "reason": "missing semantic input provenance"}
                    )
                    continue
                semantic_result = semantic_payload.get("semantic_result")
                expected_input_hash = semantic_payload.get("semantic_input_sha256")
                if not isinstance(semantic_result, dict) or expected_input_hash != stable_state_hash(semantic_result):
                    mismatches.append(
                        {
                            "tick": tick,
                            "reason": "semantic input hash mismatch",
                            "expected": expected_input_hash,
                            "actual": stable_state_hash(semantic_result) if isinstance(semantic_result, dict) else None,
                        }
                    )
                    continue
                actual_plan = engine.plan(semantic_result).model_dump(mode="json")
                checked_plans += 1
                expected_plan_hash = stable_state_hash(payload)
                actual_plan_hash = stable_state_hash(actual_plan)
                if actual_plan_hash != expected_plan_hash:
                    mismatches.append(
                        {
                            "tick": tick,
                            "reason": "planner output mismatch",
                            "expected": expected_plan_hash,
                            "actual": actual_plan_hash,
                        }
                    )
                continue
            if event_type != "tick_completed":
                continue
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
        return ReplayResult(
            matched=not mismatches,
            checked_ticks=checked,
            checked_plans=checked_plans,
            mismatches=mismatches,
            unverified_plans=unverified_plans,
        )
