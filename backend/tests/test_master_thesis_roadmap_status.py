from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "summarize_master_thesis_experiment_roadmap.py"
SPEC = importlib.util.spec_from_file_location("master_thesis_roadmap_status", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
master_thesis_roadmap_status = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = master_thesis_roadmap_status
SPEC.loader.exec_module(master_thesis_roadmap_status)


def test_master_thesis_roadmap_status_identifies_completed_and_blocked_work() -> None:
    result = master_thesis_roadmap_status.summarize_roadmap()

    assert result["valid"] is True
    assert result["row_count"] == 17
    assert result["table_counts"] == {"issues": 9, "experiment_packages": 8}
    assert result["blockers"]["needs_user_research_design_confirmation"] == ["D1"]
    assert result["blockers"]["requires_external_human_evidence"] == ["D8", "E6"]
    assert result["blockers"]["requires_full_benchmark_or_real_bridge"] == []
    assert result["blockers"]["requires_physical_calibration_or_validation"] == [
        "D7",
        "E5",
    ]
    assert result["software_verified_complete_ids"] == [
        "D0",
        "D2",
        "D3",
        "D4",
        "D5",
        "D6",
        "E0",
        "E1",
        "E2",
        "E3",
        "E4",
        "E7",
    ]
    assert result["bounded_software_complete_ids"] == ["E1"]


def test_connected_but_uncalibrated_bridge_is_never_complete() -> None:
    row = master_thesis_roadmap_status.RoadmapRow(table="issues", row_id="D7",
        status="EnergyPlus 已接入，实测校准待做", priority="P1", description="软件运行已完成；设备未校准")
    assert master_thesis_roadmap_status._classification(row) == "physical_bridge_verified_calibration_pending"


def test_roadmap_preserves_e1_statistical_and_population_boundaries() -> None:
    markdown = master_thesis_roadmap_status.DEFAULT_ROADMAP.read_text(encoding="utf-8")
    e1 = next(line for line in markdown.splitlines() if line.startswith("| E1 "))

    assert "24" in e1 and "600" in e1 and "配置" in e1
    assert "mixed-effects/Holm 未执行" in e1
    assert "mock" in e1
    assert "20260907_055214_523861" in e1
    assert "20260907_092614_310836" in e1
