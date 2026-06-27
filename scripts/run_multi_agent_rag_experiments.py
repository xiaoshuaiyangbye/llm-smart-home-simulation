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
    parser = argparse.ArgumentParser(description="Run baseline vs multi-agent RAG ablation experiments.")
    parser.add_argument(
        "--tasks",
        default=str(PROJECT_ROOT / "data" / "tasks" / "batch_tasks.json"),
        help="Path to batch task JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "results" / "multi_agent_rag"),
        help="Directory for CSV and summary outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N tasks for smoke tests.",
    )
    args = parser.parse_args()

    load_dotenv(BACKEND_ROOT / ".env")
    output_dir = Path(args.output_dir)
    baseline = run_batch_experiment(
        tasks_path=Path(args.tasks),
        output_dir=output_dir / "baseline",
        reset_between_tasks=True,
        limit=args.limit,
        enable_multi_agent_review=False,
    )
    upgraded = run_batch_experiment(
        tasks_path=Path(args.tasks),
        output_dir=output_dir / "multi_agent_rag",
        reset_between_tasks=True,
        limit=args.limit,
        enable_multi_agent_review=True,
    )
    comparison = {
        "tasks_path": str(args.tasks),
        "task_limit": args.limit,
        "baseline": baseline["summary"],
        "multi_agent_rag": upgraded["summary"],
        "delta": _summary_delta(baseline["summary"], upgraded["summary"]),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = output_dir / "comparison_summary.json"
    with comparison_path.open("w", encoding="utf-8") as file:
        json.dump(comparison, file, ensure_ascii=False, indent=2)

    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    print(f"\nComparison: {comparison_path}")
    return 0


def _summary_delta(baseline: dict, upgraded: dict) -> dict:
    keys = [
        "task_count",
        "success_rate",
        "completion_rate",
        "intent_accuracy",
        "room_accuracy",
        "scope_accuracy",
        "average_action_count",
        "average_response_time_ms",
        "average_energy_saving_rate_percent",
        "average_comfort_score",
    ]
    delta = {}
    for key in keys:
        left = baseline.get(key)
        right = upgraded.get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            delta[key] = round(right - left, 4)
    return delta


if __name__ == "__main__":
    raise SystemExit(main())
