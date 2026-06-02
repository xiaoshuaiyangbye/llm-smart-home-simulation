import csv
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _latest_batch_csv(results_dir: Path) -> Path:
    files = sorted(results_dir.glob("batch_results_*.csv"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No batch_results_*.csv found in {results_dir}")
    return files[-1]


def _float(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except ValueError:
        return 0.0


def main() -> int:
    results_dir = PROJECT_ROOT / "data" / "results"
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_batch_csv(results_dir)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("category") or "uncategorized"].append(row)

    lines = [
        "# 对照实验统计报告",
        "",
        f"数据文件：`{csv_path}`",
        "",
        "本报告以固定策略基线功率作为对照组，将大语言模型智能体执行后的实时功率作为实验组，用于分析任务控制后的能耗变化与舒适度表现。",
        "",
        "| 任务类型 | 样本数 | 实验组平均功率 W | 对照组平均功率 W | 平均节能率 % | 平均舒适度 |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for category, items in sorted(grouped.items()):
        count = len(items)
        current_power = sum(_float(row, "current_power_w") for row in items) / count
        baseline_power = sum(_float(row, "baseline_power_w") for row in items) / count
        saving_rate = sum(_float(row, "energy_saving_rate_percent") for row in items) / count
        comfort = sum(_float(row, "average_comfort_score") for row in items) / count
        lines.append(
            f"| {category} | {count} | {current_power:.2f} | {baseline_power:.2f} | {saving_rate:.2f} | {comfort:.2f} |"
        )

    output_path = csv_path.with_name(csv_path.stem.replace("batch_results", "control_report") + ".md")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
