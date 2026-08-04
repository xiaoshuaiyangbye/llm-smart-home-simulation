from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "prepare_semantic_review_packets.py"
SPEC = importlib.util.spec_from_file_location("semantic_review_packets", SCRIPT_PATH)
assert SPEC and SPEC.loader
semantic_review_packets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = semantic_review_packets
SPEC.loader.exec_module(semantic_review_packets)


def test_review_packets_are_complete_blinded_and_differently_ordered() -> None:
    packets, manifest = semantic_review_packets.build_packets(
        PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
    )

    assert manifest["task_count"] == 36
    assert manifest["reference_labels_in_packets"] is False
    assert manifest["review_status"] == "not_started_external"
    first_ids = [task["task_id"] for task in packets["reviewer-a"]["tasks"]]
    second_ids = [task["task_id"] for task in packets["reviewer-b"]["tasks"]]
    assert set(first_ids) == set(second_ids)
    assert first_ids != second_ids
    for packet in packets.values():
        assert len(packet["tasks"]) == 36
        assert packet["independent_of_reference_author"] is None
        for task in packet["tasks"]:
            assert "expected_intent" not in task
            assert "expected_control_goal" not in task
            assert "expected_targets" not in task
            assert task["annotation"] == {
                "control_goal": None,
                "targets": {},
                "rationale": "",
                "ambiguity_flag": None,
            }
