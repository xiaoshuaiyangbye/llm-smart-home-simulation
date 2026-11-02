from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "validate_e1_episode_benchmark_spec.py"
SPEC = importlib.util.spec_from_file_location("e1_episode_benchmark_spec", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
e1_episode_benchmark_spec = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e1_episode_benchmark_spec
SPEC.loader.exec_module(e1_episode_benchmark_spec)


def test_e1_episode_benchmark_spec_records_authorized_bounded_execution() -> None:
    result = e1_episode_benchmark_spec.validate_spec()

    assert result["valid"] is True
    assert result["unique_episode_count"] == 600
    assert result["method_count"] == 4
    assert result["repeats_per_episode"] == 3
    assert result["target_run_count"] == 7200
    assert result["status"] == "implemented_bounded_software_protocol"
    assert result["base_scenario_count"] == 24
    assert result["configuration_episode_count"] == 600
    assert result["completed_artifact_count"] >= 2
    assert result["original_inferential_plan_executed"] is False
    assert result["issues"] == []


@pytest.mark.parametrize("mutation, expected_issue", [
    ("population", "independent population"),
    ("inference", "original inferential plan"),
    ("artifact_count", "record_count"),
    ("authorization", "authorization"),
])
def test_e1_spec_rejects_unsupported_execution_claims(tmp_path: Path, mutation: str, expected_issue: str) -> None:
    spec = json.loads(e1_episode_benchmark_spec.DEFAULT_SPEC.read_text(encoding="utf-8"))
    if mutation == "population":
        spec["episode_unit"]["is_independent_population_sample"] = True
    elif mutation == "inference":
        spec["implemented_protocol"]["original_inferential_plan_executed"] = True
    elif mutation == "artifact_count":
        spec["completed_artifacts"][0]["record_count"] = 9999
    else:
        spec["authorization"] = {}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")

    result = e1_episode_benchmark_spec.validate_spec(path)

    assert result["valid"] is False
    assert any(expected_issue in issue for issue in result["issues"])
