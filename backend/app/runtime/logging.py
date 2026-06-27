import json
from pathlib import Path
from typing import Any


class JsonlSimulationLogger:
    """Append-only deterministic JSONL logger."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.sequence = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.path.unlink()

    def write(self, event_type: str, tick: int, payload: dict[str, Any]) -> None:
        record = {
            "sequence": self.sequence,
            "run_id": self.run_id,
            "tick": tick,
            "event_type": event_type,
            "payload": payload,
        }
        self.sequence += 1
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

