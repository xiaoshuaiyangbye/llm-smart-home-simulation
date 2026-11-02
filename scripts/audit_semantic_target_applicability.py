"""Read-only rescoring of saved semantic predictions; never calls a model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.experiments.semantic_targets import REFERENCE_STATUS, evaluate_applicable_targets, summarize_applicable_targets

DEFAULT_RECORDS = PROJECT_ROOT / "output/rq5-real-model-fixed/20260716_111455/task_records.csv"
DEFAULT_TASKS = PROJECT_ROOT / "data/tasks/reproduction_tasks.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output/semantic-target-audit"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decode(value: str | None) -> object:
    try:
        return json.loads(value) if value else None
    except (TypeError, ValueError):
        return None


def audit_records(records_path: Path, tasks_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use saved predictions, checking commands/labels against the source suite.

    An absent prediction column is unavailable evidence, not a model failure.
    A present but missing/malformed prediction remains a scored failure whenever
    a requested field has a usable reference. No prediction is reconstructed.
    """
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    task_list = payload["tasks"] if isinstance(payload, dict) else payload
    tasks = {str(task["task_id"]): task for task in task_list}
    if len(tasks) != len(task_list):
        raise ValueError("Source task IDs must be unique.")
    annotations = payload.get("target_annotations", {}) if isinstance(payload, dict) else {}
    with records_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        source_records = list(reader)
    results = []
    for row in source_records:
        task = tasks.get(row.get("task_id", ""))
        status = "rescored_saved_prediction"
        measurement = None
        expected = _decode(row.get("expected_targets"))
        semantic_applicable = row.get("semantic_applicable", "").lower() == "true"
        if not semantic_applicable:
            status = "semantic_not_applicable"
        elif task is None:
            status = "task_not_in_source_suite"
        elif row.get("user_command") != task.get("user_command"):
            status = "command_mismatch_with_source_suite"
        elif "expected_targets" not in columns:
            status = "historical_reference_not_recorded"
        elif expected != annotations.get(task["task_id"], task.get("expected_targets")):
            status = "reference_mismatch_with_source_suite"
        elif "predicted_targets" not in columns:
            status = "prediction_not_recorded"
        else:
            measurement = evaluate_applicable_targets(
                row["user_command"], expected, _decode(row.get("predicted_targets")),
            )
        results.append({
            **row,
            "audit_status": status,
            "audit_reference_status": REFERENCE_STATUS,
            "audit_applicable": measurement["applicable"] if measurement else None,
            "audit_exact_match": measurement["exact_match"] if measurement else None,
            "audit_field_denominator": measurement["denominator"] if measurement else None,
            "audit_review_required": measurement["review_required"] if measurement else None,
            "audit_metrics_json": json.dumps(measurement, ensure_ascii=False, sort_keys=True),
        })
    # Repeats remain in the audit CSV. Only the original primary repeat counts
    # toward descriptive accuracy, so a task is not counted three times.
    primary = [row for row in results if row.get("repeat_index", "1") == "1"]
    seen: set[tuple[str, str]] = set()
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in primary:
        key = (row["group_id"], row["task_id"])
        if key in seen:
            raise ValueError(f"Duplicate primary record: {key}")
        seen.add(key)
        by_group[row["group_id"]].append(row)
    group_summaries = []
    for group_id, rows in sorted(by_group.items()):
        measurements = [json.loads(row["audit_metrics_json"]) for row in rows if row["audit_status"] == "rescored_saved_prediction"]
        legacy = [row for row in rows if row.get("target_applicable", "").lower() == "true"]
        group_summaries.append({
            "group_id": group_id,
            "primary_record_count": len(rows),
            "effective_llm_modes": sorted({row.get("effective_llm_mode", "") for row in rows}),
            "legacy_target_task_denominator": len(legacy),
            "legacy_target_exact_match_percent": round(sum(row.get("target_exact_match", "").lower() == "true" for row in legacy) / len(legacy) * 100, 2) if legacy else None,
            "audit_status_counts": dict(Counter(row["audit_status"] for row in rows)),
            "explicit_target_metrics": summarize_applicable_targets(measurements),
        })
    return results, {
        "schema_version": "semantic_target_audit_v1",
        "reference_status": REFERENCE_STATUS,
        "historical_record_count": len(results),
        "primary_record_count": len(primary),
        "primary_repeat_index": 1,
        "unique_task_count": len({row["task_id"] for row in primary}),
        "audit_status_counts": dict(Counter(row["audit_status"] for row in results)),
        "group_summaries": group_summaries,
        "rq5_blocker_resolved": False,
        "model_calls_made": 0,
        "interpretation": "Additive lexical applicability audit of saved predictions against existing project-curated labels; no independent adjudication or new model evaluation.",
        "limitations": [
            "The conservative lexical rule covers explicit Arabic-numeral temperature, illuminance and humidity targets only; other forms require manual review.",
            "Zero applicable-field denominators mean N/A, not perfect or failed accuracy; no model improvement can be inferred.",
            "Historical full-target metrics, failure classifications, task commands and labels are preserved. Their default target fields can remain useful policy diagnostics, but are not all explicitly requested parameters.",
            "Task-suite alignment is checked against saved row commands and reference targets; the current file hash alone does not establish the historical suite's byte identity.",
            "Only primary isolated repeats contribute to accuracy denominators. Saved real-model provenance is inherited, not freshly verified.",
            "Missing prediction columns and mismatched historical references are reported as unavailable evidence; predictions and labels are never reconstructed.",
            "This software audit neither adjudicates semantic labels nor validates real devices or homes; RQ5 still requires independent human review.",
        ],
    }


def _metric(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# 语义目标适用性审计",
        "",
        "本报告只重评分保存的预测，不调用模型、不修改历史产物。保留原 target exact match 与 range IoU；新增指标只统计主命令明确指定的数值温度、照度、湿度。",
        "",
        f"历史记录 {summary['historical_record_count']} 条；主重复记录 {summary['primary_record_count']} 条；独立 task ID {summary['unique_task_count']} 个。",
        "",
        "| Group | 原指标任务分母 | 原目标精确匹配 % | 新指标适用任务 | 新指标字段分母 | 新目标精确匹配 % | 需审查任务 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group in summary["group_summaries"]:
        metric = group["explicit_target_metrics"]
        lines.append(
            f"| {group['group_id']} | {group['legacy_target_task_denominator']} | "
            f"{_metric(group['legacy_target_exact_match_percent'])} | {metric['applicable_task_count']} | "
            f"{metric['field_denominator']} | {_metric(metric['exact_match_percent'])} | {metric['review_required_count']} |"
        )
    lines.extend([
        "",
        "分母为 0 时为 N/A，不表示模型变好或变差。默认参数不应直接算作用户要求的参数错误；模糊、否定、条件和相对调整需要单独裁决。",
        "",
        f"标签状态：`{REFERENCE_STATUS}`。现有标签尚未独立裁决；本审计不会解除 RQ5。",
        "",
        "审计 CSV 保留原行全部字段，新增 audit 字段；summary.json 保存输入和审计代码 SHA-256、分母与排除原因。",
        "",
        *[f"- {limitation}" for limitation in summary["limitations"]],
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    inputs = {"records": args.records.resolve(), "tasks": args.tasks.resolve()}
    hashes = {key: _sha256(path) for key, path in inputs.items()}
    records, summary = audit_records(inputs["records"], inputs["tasks"])
    now = datetime.now(timezone.utc)
    output = args.output_root.resolve() / now.strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    summary.update({
        "generated_at": now.isoformat(),
        "input_provenance": {key: {"path": str(path), "sha256": hashes[key]} for key, path in inputs.items()},
        "audit_script_sha256": _sha256(Path(__file__)),
        "applicability_module_sha256": _sha256(PROJECT_ROOT / "backend/app/experiments/semantic_targets.py"),
        "output_directory": str(output),
    })
    if hashes != {key: _sha256(path) for key, path in inputs.items()}:
        raise RuntimeError("Audit input changed during evaluation; result must not be published.")
    summary["input_hashes_unchanged"] = True
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "report.md").write_text(render_report(summary), encoding="utf-8")
    with (output / "task_records_audit.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]) if records else [])
        writer.writeheader()
        writer.writerows(records)
    print(json.dumps({"output_directory": str(output), "group_summaries": summary["group_summaries"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
