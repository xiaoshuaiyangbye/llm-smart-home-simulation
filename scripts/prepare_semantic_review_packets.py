"""Prepare two blinded annotation packets without fabricating reviewer evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "research" / "semantic_review_packets"
REVIEWER_SLOTS = ("reviewer-a", "reviewer-b")


def _task_order_key(task_id: str, reviewer_slot: str, suite_sha256: str) -> str:
    return hashlib.sha256(f"{suite_sha256}:{reviewer_slot}:{task_id}".encode("utf-8")).hexdigest()


def build_packets(task_suite_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    raw_bytes = task_suite_path.read_bytes()
    suite_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    payload = json.loads(raw_bytes.decode("utf-8-sig"))
    tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("task suite must contain a non-empty tasks list")

    packets: dict[str, dict[str, Any]] = {}
    for reviewer_slot in REVIEWER_SLOTS:
        ordered_tasks = sorted(
            tasks,
            key=lambda task: _task_order_key(str(task.get("task_id", "")), reviewer_slot, suite_sha256),
        )
        annotations = []
        for task in ordered_tasks:
            task_id = str(task.get("task_id", "")).strip()
            if not task_id:
                raise ValueError("every review task must have a task_id")
            annotations.append(
                {
                    "task_id": task_id,
                    "category": task.get("category"),
                    "user_command": task.get("user_command"),
                    "current_room_id": task.get("current_room_id"),
                    "annotation": {
                        "control_goal": None,
                        "targets": {},
                        "rationale": "",
                        "ambiguity_flag": None,
                    },
                }
            )
        packets[reviewer_slot] = {
            "schema_version": "semantic_annotation_packet_v1",
            "task_suite_sha256": suite_sha256,
            "reviewer_slot": reviewer_slot,
            "reviewer_identity": "replace-with-real-reviewer-id",
            "independent_of_reference_author": None,
            "instructions": [
                "Complete this packet independently without viewing the versioned reference labels or the other packet.",
                "Choose control_goal from turn_on, turn_off, or set_target.",
                "Record all applicable numeric target ranges and a short rationale.",
                "Set ambiguity_flag=true whenever more than one defensible label remains.",
            ],
            "tasks": annotations,
        }

    manifest = {
        "schema_version": "semantic_annotation_handoff_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_suite_path": str(task_suite_path.resolve()),
        "task_suite_sha256": suite_sha256,
        "task_count": len(tasks),
        "reviewer_slots": list(REVIEWER_SLOTS),
        "reference_labels_in_packets": False,
        "review_status": "not_started_external",
        "acceptance_command": (
            "backend\\.venv\\Scripts\\python.exe scripts\\validate_semantic_annotation_review.py "
            "<completed-review.json> --tasks data\\tasks\\reproduction_tasks.json"
        ),
        "evidence_boundary": (
            "Packet generation proves only blinded task preparation. It does not prove reviewer identity, "
            "independence, completed review, agreement, or adjudication."
        ),
    }
    return packets, manifest


def write_packets(
    packets: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    output_root: Path,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / timestamp
    output_dir.mkdir(parents=True, exist_ok=False)
    for reviewer_slot, packet in packets.items():
        (output_dir / f"{reviewer_slot}.json").write_text(
            json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    packets, manifest = build_packets(args.tasks)
    output_dir = write_packets(packets, manifest, args.output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "task_count": manifest["task_count"],
                "task_suite_sha256": manifest["task_suite_sha256"],
                "review_status": manifest["review_status"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
