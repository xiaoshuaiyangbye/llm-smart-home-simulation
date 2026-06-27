from pathlib import Path

from app.runtime.logging import read_jsonl


class ReplayLogIndex:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir

    def list_runs(self) -> list[str]:
        return sorted(path.name for path in self.log_dir.glob("*.jsonl"))

    def read_run(self, file_name: str) -> list[dict]:
        return read_jsonl(self.log_dir / file_name)

