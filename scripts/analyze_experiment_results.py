import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.experiments.evaluation import summarize_batch_records


def _latest_batch_csv(results_dir: Path) -> Path:
    files = sorted(results_dir.glob("batch_results_*.csv"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No batch_results_*.csv found in {results_dir}")
    return files[-1]


def _coerce_record(row: dict[str, str]) -> dict:
    result = dict(row)
    for key in ["success", "completed", "intent_correct", "room_correct", "scope_correct"]:
        if result.get(key) in {"True", "False"}:
            result[key] = result[key] == "True"
    for key in ["response_time_ms", "action_count", "current_power_w", "average_comfort_score"]:
        if result.get(key) not in {"", None}:
            result[key] = float(result[key])
    return result


def main() -> int:
    results_dir = PROJECT_ROOT / "data" / "results"
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_batch_csv(results_dir)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        records = [_coerce_record(row) for row in csv.DictReader(file)]

    summary = summarize_batch_records(records)
    summary["csv_path"] = str(csv_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    output_path = csv_path.with_name(csv_path.stem.replace("batch_results", "analysis") + ".json")
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    print(f"\nSaved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
