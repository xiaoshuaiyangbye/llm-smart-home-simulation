import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

from app.experiments.batch_runner import run_batch_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description="Run batch experiments for the smart-home agent workflow.")
    parser.add_argument(
        "--tasks",
        default=str(PROJECT_ROOT / "data" / "tasks" / "batch_tasks.json"),
        help="Path to batch task JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "results"),
        help="Directory for CSV and summary outputs.",
    )
    parser.add_argument(
        "--keep-state",
        action="store_true",
        help="Do not reset the simulated home between tasks.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N tasks for smoke tests.",
    )
    parser.add_argument(
        "--disable-multi-agent",
        action="store_true",
        help="Run the older semantic-planning-execution-feedback path without RAG review agents.",
    )
    args = parser.parse_args()

    load_dotenv(BACKEND_ROOT / ".env")
    result = run_batch_experiment(
        tasks_path=Path(args.tasks),
        output_dir=Path(args.output_dir),
        reset_between_tasks=not args.keep_state,
        limit=args.limit,
        enable_multi_agent_review=not args.disable_multi_agent,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"\nCSV: {result['csv_path']}")
    print(f"Summary: {result['summary_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
