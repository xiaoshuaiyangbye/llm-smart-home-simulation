"""Summarize completion and blockers in the master thesis experiment roadmap."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROADMAP = PROJECT_ROOT / "docs" / "master_thesis_experiment_roadmap.md"


@dataclass(frozen=True)
class RoadmapRow:
    table: str
    row_id: str
    status: str
    priority: str | None
    description: str

    @property
    def searchable_text(self) -> str:
        return " ".join(part for part in (self.status, self.priority or "", self.description) if part)


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(set(cell.replace(" ", "")) <= {"-", ":"} for cell in cells)


def _section_lines(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        raise ValueError(f"missing section heading: {heading}")
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start:end]


def _parse_table(markdown: str, heading: str, table_name: str) -> list[RoadmapRow]:
    rows: list[RoadmapRow] = []
    header: list[str] | None = None
    for line in _section_lines(markdown, heading):
        cells = _split_markdown_row(line)
        if not cells:
            if rows:
                break
            continue
        if _is_separator_row(cells):
            continue
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells, strict=False))
        if table_name == "issues":
            row_id = row.get("编号", "").split()[0]
            status = row.get("状态", "")
            priority = row.get("优先级", "")
        else:
            first_cell = row.get("实验包", "")
            row_id = first_cell.split()[0]
            status = row.get("状态", "")
            priority = None
        description = " ".join(value for value in row.values() if value)
        rows.append(RoadmapRow(table=table_name, row_id=row_id, status=status, priority=priority, description=description))
    if header is None or not rows:
        raise ValueError(f"no markdown table rows found under: {heading}")
    return rows


def _classification(row: RoadmapRow) -> str:
    text = row.searchable_text
    if "待用户确认" in text or "待用户研究设计确认" in text:
        return "needs_user_research_design_confirmation"
    if "待外部人员" in text or "需外部授权" in text or "真实外部人员" in text:
        return "requires_external_human_evidence"
    if "真实桥接待做" in text or "full 待" in text or "待扩展" in text:
        return "requires_full_benchmark_or_real_bridge"
    if "energyplus" in text.lower() and ("未校准" in text or "实测校准待做" in text):
        return "physical_bridge_verified_calibration_pending"
    if "已完成" in text or "本轮完成" in text or "已建立" in text:
        return "software_verified_complete"
    return "uncategorized"


def summarize_roadmap(roadmap_path: Path = DEFAULT_ROADMAP) -> dict[str, Any]:
    roadmap_path = roadmap_path.resolve()
    markdown = roadmap_path.read_text(encoding="utf-8")
    rows = [
        *_parse_table(markdown, "## 现有问题与深入方案", "issues"),
        *_parse_table(markdown, "## 推荐的硕士论文实验包", "experiment_packages"),
    ]
    entries: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    by_table: dict[str, dict[str, int]] = {}
    for row in rows:
        classification = _classification(row)
        counts[classification] = counts.get(classification, 0) + 1
        by_table.setdefault(row.table, {})
        by_table[row.table][classification] = by_table[row.table].get(classification, 0) + 1
        entries.append(
            {
                "table": row.table,
                "id": row.row_id,
                "status": row.status,
                "priority": row.priority,
                "classification": classification,
            }
        )

    blockers = {
        "needs_user_research_design_confirmation": [
            entry["id"] for entry in entries if entry["classification"] == "needs_user_research_design_confirmation"
        ],
        "requires_external_human_evidence": [
            entry["id"] for entry in entries if entry["classification"] == "requires_external_human_evidence"
        ],
        "requires_full_benchmark_or_real_bridge": [
            entry["id"] for entry in entries if entry["classification"] == "requires_full_benchmark_or_real_bridge"
        ],
        "requires_physical_calibration_or_validation": [
            entry["id"] for entry in entries if entry["classification"] == "physical_bridge_verified_calibration_pending"
        ],
    }
    safe_software_complete = [entry["id"] for entry in entries if entry["classification"] == "software_verified_complete"]
    return {
        "schema_version": "master_thesis_roadmap_status_v1",
        "roadmap_path": str(roadmap_path),
        "valid": True,
        "row_count": len(entries),
        "table_counts": {
            "issues": sum(1 for row in rows if row.table == "issues"),
            "experiment_packages": sum(1 for row in rows if row.table == "experiment_packages"),
        },
        "classification_counts": counts,
        "classification_counts_by_table": by_table,
        "software_verified_complete_ids": safe_software_complete,
        "bounded_software_complete_ids": [
            entry["id"] for entry in entries
            if entry["classification"] == "software_verified_complete" and "限定软件矩阵已完成" in entry["status"]
        ],
        "blockers": blockers,
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roadmap", nargs="?", type=Path, default=DEFAULT_ROADMAP)
    args = parser.parse_args()
    result = summarize_roadmap(args.roadmap)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
