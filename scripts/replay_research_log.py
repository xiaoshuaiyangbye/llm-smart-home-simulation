from argparse import ArgumentParser
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.runtime.replay import ReplayEngine


def main() -> None:
    parser = ArgumentParser(description="Replay a deterministic research JSONL log.")
    parser.add_argument(
        "log_path",
        nargs="?",
        default=str(PROJECT_ROOT / "data" / "logs" / "research_demo.jsonl"),
        help="Path to a JSONL log produced by the research runtime.",
    )
    args = parser.parse_args()

    log_path = Path(args.log_path)
    if not log_path.is_absolute():
        log_path = PROJECT_ROOT / log_path
    result = ReplayEngine().replay(log_path)
    print(f"log_path={log_path}")
    print(f"matched={result.matched}")
    print(f"checked_ticks={result.checked_ticks}")
    if result.mismatches:
        print(f"mismatches={result.mismatches}")


if __name__ == "__main__":
    main()
