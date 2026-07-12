from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
SEMANTIC_ADAPTER_PATH = BACKEND_ROOT / "app" / "agents" / "llm_client.py"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

from app.agents.feedback_agent import FeedbackAgent
from app.agents.llm_client import TARGETS_BY_INTENT
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.schemas.task_schema import AgentCommandRequest
from app.simulation.baseline_policy import plan_conventional_baseline_actions
from app.simulation.environment import SmartHomeEnvironment


@dataclass(frozen=True)
class ExperimentGroup:
    group_id: str
    name: str
    description: str
    runner_kind: str
    llm_mode: str
    execute_actions: bool
    enable_feedback_correction: bool
    enable_context_memory: bool
    semantic_applicable: bool = True
    completion_applicable: bool = True


EXPERIMENT_GROUPS = [
    ExperimentGroup(
        group_id="fixed_policy_baseline",
        name="Fixed policy baseline",
        description="Uses deterministic household control rules without natural-language parsing.",
        runner_kind="baseline",
        llm_mode="none",
        execute_actions=True,
        enable_feedback_correction=False,
        enable_context_memory=False,
        semantic_applicable=False,
        completion_applicable=True,
    ),
    ExperimentGroup(
        group_id="rule_semantic_full",
        name="Rule semantic baseline",
        description="Uses mock semantic parsing with rule-based planning, execution, and feedback correction.",
        runner_kind="task_runner",
        llm_mode="mock",
        execute_actions=True,
        enable_feedback_correction=True,
        enable_context_memory=True,
    ),
    ExperimentGroup(
        group_id="real_semantic_planning",
        name="Real semantic parsing + planning",
        description="Uses a real LLM for semantic parsing and generates plans without executing device actions.",
        runner_kind="task_runner",
        llm_mode="real",
        execute_actions=False,
        enable_feedback_correction=False,
        enable_context_memory=True,
        completion_applicable=False,
    ),
    ExperimentGroup(
        group_id="real_no_feedback",
        name="Real parsing without feedback correction",
        description="Uses real semantic parsing, planning, and execution while disabling correction rounds.",
        runner_kind="task_runner",
        llm_mode="real",
        execute_actions=True,
        enable_feedback_correction=False,
        enable_context_memory=True,
    ),
    ExperimentGroup(
        group_id="real_no_context",
        name="Real parsing without context memory",
        description="Uses real semantic parsing, planning, execution, and feedback while disabling context memory.",
        runner_kind="task_runner",
        llm_mode="real",
        execute_actions=True,
        enable_feedback_correction=True,
        enable_context_memory=False,
    ),
    ExperimentGroup(
        group_id="full_system",
        name="Full workflow",
        description="Uses semantic parsing, rule-based planning, execution, feedback correction, and context memory.",
        runner_kind="task_runner",
        llm_mode="real",
        execute_actions=True,
        enable_feedback_correction=True,
        enable_context_memory=True,
    ),
]
GROUPS_BY_ID = {group.group_id: group for group in EXPERIMENT_GROUPS}
MINIMUM_TASKS_FOR_PERFORMANCE_CLAIM = 6
MINIMUM_CATEGORIES_FOR_PERFORMANCE_CLAIM = 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reproducible smart-home agent experiments.")
    parser.add_argument(
        "--tasks",
        default=str(PROJECT_ROOT / "data" / "tasks" / "reproduction_tasks.json"),
        help="Path to the fixed reproduction task JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "results" / "reproduction_experiments"),
        help="Directory where a timestamped reproduction result folder will be created.",
    )
    parser.add_argument(
        "--groups",
        default="all",
        help="Comma-separated group ids, or 'all'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N tasks for smoke tests.",
    )
    parser.add_argument(
        "--real-mode",
        choices=["real", "mock"],
        default="real",
        help="Use mock here only for local smoke tests without spending real LLM quota.",
    )
    parser.add_argument(
        "--env-file",
        default=str(BACKEND_ROOT / ".env"),
        help=(
            "Optional dotenv file loaded before real-mode validation. Use deploy/backend.env "
            "to align a host-run benchmark with the Docker backend configuration."
        ),
    )
    parser.add_argument(
        "--repeat-count",
        type=int,
        default=1,
        help=(
            "Number of isolated repetitions for every task/group. Values above one measure "
            "within-task semantic and plan-output stability; they do not add independent task coverage."
        ),
    )
    args = parser.parse_args()
    if args.repeat_count < 1:
        parser.error("--repeat-count must be at least 1")

    env_file = Path(args.env_file)
    env_file_loaded = load_experiment_environment(env_file)
    tasks_path = Path(args.tasks)
    source_tasks = load_tasks(tasks_path)
    tasks = source_tasks
    if args.limit is not None:
        tasks = tasks[: max(0, args.limit)]
    evaluation_scope = build_evaluation_scope(source_tasks, tasks, requested_limit=args.limit)
    task_suite_provenance = build_task_suite_provenance(tasks_path, source_tasks)

    groups = resolve_groups(args.groups)
    if args.real_mode == "real":
        require_real_llm_if_needed(groups)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []
    for group in groups:
        group_records: list[dict[str, Any]] = []
        for repeat_index in range(1, args.repeat_count + 1):
            group_records.extend(
                run_group(
                    group,
                    tasks,
                    output_dir,
                    real_mode=args.real_mode,
                    repeat_index=repeat_index,
                )
            )
        records.extend(group_records)
        group_summaries.append(summarize_records(primary_performance_records(group_records), group))

    performance_records = primary_performance_records(records)

    records_csv = output_dir / "task_records.csv"
    summary_json = output_dir / "summary.json"
    chart_data_json = output_dir / "chart_data.json"
    report_md = output_dir / "reproduction_report.md"
    chart_csv_dir = output_dir / "chart_csv"
    chart_csv_dir.mkdir(parents=True, exist_ok=True)

    write_csv(records_csv, records)
    category_summaries = summarize_by_group_and_category(performance_records)
    chart_data = build_chart_data(group_summaries, category_summaries, performance_records)
    write_chart_csvs(chart_csv_dir, chart_data)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tasks_path": str(tasks_path),
        "task_count": len(tasks),
        "repeat_count": args.repeat_count,
        "performance_metrics_repeat_index": 1,
        "performance_metric_record_count": len(performance_records),
        "stability_record_count": len(records),
        "evaluation_scope": evaluation_scope,
        "task_suite_provenance": task_suite_provenance,
        "real_mode": args.real_mode,
        "environment_file": str(env_file),
        "environment_file_loaded": env_file_loaded,
        "semantic_runtime_provenance": {
            effective_llm_mode_for_group(group, args.real_mode): semantic_runtime_provenance(
                effective_llm_mode_for_group(group, args.real_mode)
            )
            for group in groups
        },
        "groups": [group_to_dict(group, args.real_mode) for group in groups],
        "group_summaries": group_summaries,
        "category_summaries": category_summaries,
        "repeat_stability": summarize_repeat_stability(records, repeat_count=args.repeat_count),
        "output_paths": {
            "records_csv": str(records_csv),
            "summary_json": str(summary_json),
            "chart_data_json": str(chart_data_json),
            "chart_csv_dir": str(chart_csv_dir),
            "report_md": str(report_md),
        },
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    chart_data_json.write_text(json.dumps(chart_data, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(render_report(summary), encoding="utf-8")

    print(json.dumps({"output_dir": str(output_dir), **summary["output_paths"]}, ensure_ascii=False, indent=2))
    return 0


def load_experiment_environment(env_file: Path) -> bool:
    """Load an explicit, non-secret benchmark configuration when it exists.

    Reproduction runs are commonly launched on the host while the running
    dashboard reads Docker's ``deploy/backend.env``. Shell variables retain
    precedence so CI and users can provide credentials without writing them.
    """
    if not env_file.is_file():
        bridge_docker_ollama_endpoint_for_host_runner()
        return False
    load_dotenv(env_file, override=False)
    bridge_docker_ollama_endpoint_for_host_runner()
    return True


def bridge_docker_ollama_endpoint_for_host_runner() -> None:
    """Make Docker's host-only Ollama alias usable from this host-side script.

    The deployment backend can reach ``host.docker.internal`` while a Windows
    process running this benchmark cannot. Only that exact local endpoint is
    rewritten to localhost; the configured and effective endpoints are kept as
    non-secret hashes in the generated provenance.
    """
    configured_base_url = os.getenv("REAL_LLM_BASE_URL", "")
    os.environ["REAL_LLM_CONFIGURED_BASE_URL"] = configured_base_url
    parsed = urlsplit(configured_base_url)
    if parsed.hostname != "host.docker.internal":
        os.environ["REAL_LLM_ENDPOINT_RESOLUTION"] = "configured"
        return
    local_base_url = urlunsplit(
        (
            parsed.scheme,
            f"localhost:{parsed.port}" if parsed.port else "localhost",
            parsed.path,
            "",
            "",
        )
    )
    os.environ["REAL_LLM_BASE_URL"] = local_base_url
    os.environ["REAL_LLM_ENDPOINT_RESOLUTION"] = "host_docker_internal_to_localhost"


def _sha256_text(value: str) -> str:
    """Return a stable non-secret runtime identifier."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_canonical_sha256_fingerprint(value: object) -> bool:
    """Return whether an experiment fingerprint is a generated SHA-256 digest.

    Repeat-stability evidence relies on these fields being generated by the
    experiment runner. A non-empty placeholder (for example, ``unrecorded``)
    must not be treated as a matching measurement merely because it repeats.
    """
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value.strip()) is not None


def semantic_adapter_sha256() -> str:
    """Fingerprint the semantic adapter whose prompt/decoding produced records."""
    return hashlib.sha256(SEMANTIC_ADAPTER_PATH.read_bytes()).hexdigest()


def ollama_tags_url(base_url: str) -> str | None:
    """Return the local Ollama tags endpoint for a compatible OpenAI URL."""
    parsed = urlsplit(base_url)
    normalized_path = parsed.path.rstrip("/")
    local_ollama_hosts = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname not in local_ollama_hosts
        or not normalized_path.endswith("/v1")
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, f"{normalized_path[:-3]}/api/tags", "", ""))


def ollama_model_digest(base_url: str, model_id: str) -> str | None:
    """Probe a local Ollama manifest without making a benchmark unavailable."""
    tags_url = ollama_tags_url(base_url)
    if not tags_url or not model_id:
        return None
    try:
        request = Request(tags_url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    for candidate in payload.get("models", []) if isinstance(payload, dict) else []:
        if not isinstance(candidate, dict) or candidate.get("name") != model_id:
            continue
        digest = str(candidate.get("digest", "")).strip()
        if digest:
            return digest if digest.startswith("sha256:") else f"sha256:{digest}"
    return None


def real_model_revision() -> tuple[str, str]:
    """Prefer a supplied revision, with a narrowly scoped local-Ollama fallback."""
    configured_revision = os.getenv("REAL_LLM_MODEL_REVISION", "").strip()
    if configured_revision:
        return configured_revision, "configured_environment"

    base_url = os.getenv("REAL_LLM_BASE_URL", "")
    model_id = os.getenv("REAL_LLM_MODEL", "")
    digest = ollama_model_digest(base_url, model_id)
    if digest:
        return digest, "ollama_api_tags"

    parsed = urlsplit(base_url)
    if parsed.hostname == "host.docker.internal":
        local_base_url = urlunsplit(
            (
                parsed.scheme,
                f"localhost:{parsed.port}" if parsed.port else "localhost",
                parsed.path,
                "",
                "",
            )
        )
        digest = ollama_model_digest(local_base_url, model_id)
        if digest:
            return digest, "ollama_api_tags_localhost_fallback"
    return "unrecorded", "unavailable"


def semantic_runtime_provenance(semantic_mode: str) -> dict[str, object]:
    """Persist non-secret model/configuration identifiers for benchmark claims."""
    if semantic_mode == "mock":
        payload: dict[str, object] = {
            "semantic_mode": "mock",
            "model_id": "rule-based-mock-v1",
            "model_revision": "not_applicable",
            "model_revision_source": "not_applicable",
            "provenance_status": "reproducible_mock_baseline",
            "semantic_adapter_sha256": semantic_adapter_sha256(),
        }
    elif semantic_mode == "real":
        model_revision, revision_source = real_model_revision()
        payload = {
            "semantic_mode": "real",
            "model_id": os.getenv("REAL_LLM_MODEL", "unconfigured-real-model"),
            "model_revision": model_revision,
            "model_revision_source": revision_source,
            "provenance_status": (
                "versioned_real_model" if model_revision != "unrecorded" else "unversioned_real_model"
            ),
            "semantic_adapter_sha256": semantic_adapter_sha256(),
            "endpoint_sha256": _sha256_text(os.getenv("REAL_LLM_BASE_URL", "")),
            "configured_endpoint_sha256": _sha256_text(
                os.getenv("REAL_LLM_CONFIGURED_BASE_URL", os.getenv("REAL_LLM_BASE_URL", ""))
            ),
            "endpoint_resolution": os.getenv("REAL_LLM_ENDPOINT_RESOLUTION", "configured"),
            "resource_id_sha256": _sha256_text(os.getenv("REAL_LLM_RESOURCE_ID", "")),
            "decoding": {
                "temperature": float(os.getenv("REAL_LLM_TEMPERATURE", "0.0")),
                "seed": int(os.getenv("REAL_LLM_SEED", "42")),
                "max_tokens": int(os.getenv("REAL_LLM_MAX_TOKENS", "320")),
                "stream": os.getenv("REAL_LLM_STREAM", "true").lower() in {"1", "true", "yes", "on"},
                "max_retries": int(os.getenv("REAL_LLM_MAX_RETRIES", "2")),
            },
        }
    else:
        payload = {
            "semantic_mode": "none",
            "model_id": "not_applicable",
            "model_revision": "not_applicable",
            "model_revision_source": "not_applicable",
            "provenance_status": "not_applicable",
            "semantic_adapter_sha256": "not_applicable",
        }
    payload["semantic_runtime_fingerprint"] = _sha256_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return payload


def load_tasks(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)
    tasks = payload["tasks"] if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("Task file must contain a list or a {'tasks': [...]} object.")
    if not tasks:
        raise ValueError("Task file must contain at least one reproduction task.")
    control_goal_annotations = payload.get("control_goal_annotations", {}) if isinstance(payload, dict) else {}
    target_annotations = payload.get("target_annotations", {}) if isinstance(payload, dict) else {}
    if not isinstance(control_goal_annotations, dict):
        raise ValueError("control_goal_annotations must be an object when provided.")
    if not isinstance(target_annotations, dict):
        raise ValueError("target_annotations must be an object when provided.")
    if isinstance(payload, dict) and "semantic_ground_truth_schema_version" in payload:
        validate_semantic_annotation_provenance(payload.get("semantic_annotation_provenance"))
    annotated_tasks: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Every reproduction task must be an object.")
        task_copy = dict(task)
        raw_task_id = task_copy.get("task_id")
        if not isinstance(raw_task_id, str) or not raw_task_id.strip():
            raise ValueError("Task IDs must be unique, non-empty task_id strings.")
        task_id = raw_task_id.strip()
        if task_id in seen_task_ids:
            raise ValueError(f"Task IDs must be unique, non-empty task_id strings (duplicate: {task_id}).")
        seen_task_ids.add(task_id)
        # The task ID is the join key for manual annotations, primary metrics,
        # and repeat-stability units. Store the validated canonical value so
        # whitespace cannot split what is logically one experimental task.
        task_copy["task_id"] = task_id
        task_copy.update(validate_main_command(task_id, task_copy))
        if "pre_context_commands" in task_copy:
            task_copy["pre_context_commands"] = validate_pre_context_commands(
                task_id,
                task_copy["pre_context_commands"],
            )
        annotated_goal = control_goal_annotations.get(task_id, task_copy.get("expected_control_goal"))
        if annotated_goal is not None:
            if annotated_goal not in {"turn_on", "turn_off", "set_target"}:
                raise ValueError(f"Task {task_id or '<unknown>'} has an invalid expected control goal: {annotated_goal}")
            task_copy["expected_control_goal"] = annotated_goal
        annotated_targets = target_annotations.get(task_id, task_copy.get("expected_targets"))
        if annotated_targets is not None:
            task_copy["expected_targets"] = validate_target_annotation(task_id, annotated_targets)
        annotated_tasks.append(task_copy)

    # The versioned default suite has a manual action-direction annotation for
    # every task. Do not silently score direction-less tasks as semantic wins.
    if isinstance(payload, dict) and "semantic_ground_truth_schema_version" in payload:
        missing_goal_annotations = [str(task.get("task_id", "<unknown>")) for task in annotated_tasks if "expected_control_goal" not in task]
        if missing_goal_annotations:
            raise ValueError("Missing expected control-goal annotations for: " + ", ".join(missing_goal_annotations))
        missing_target_annotations = [str(task.get("task_id", "<unknown>")) for task in annotated_tasks if "expected_targets" not in task]
        if missing_target_annotations:
            raise ValueError("Missing expected target annotations for: " + ", ".join(missing_target_annotations))
    return annotated_tasks


def validate_main_command(task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate the measured command before an experiment begins.

    ``run_group`` must not coerce an arbitrary JSON value with ``str(...)``:
    doing so would turn (for example) ``null`` into the measured prompt
    ``"None"``.  Validate the two request fields with the same schema used at
    runtime while leaving task-level labels and setup metadata untouched.
    """
    user_command = task.get("user_command")
    if not isinstance(user_command, str) or not user_command.strip():
        raise ValueError(f"Task {task_id}.user_command must be a non-empty string.")

    normalized_command: dict[str, Any] = {"user_command": user_command.strip()}
    if "current_room_id" in task:
        current_room_id = task["current_room_id"]
        if current_room_id is not None and (
            not isinstance(current_room_id, str) or not current_room_id.strip()
        ):
            raise ValueError(f"Task {task_id}.current_room_id must be a non-empty string or null.")
        normalized_command["current_room_id"] = (
            current_room_id.strip() if isinstance(current_room_id, str) else None
        )

    try:
        AgentCommandRequest(**normalized_command)
    except ValueError as error:
        raise ValueError(f"Task {task_id} has an invalid command request: {error}") from error
    return normalized_command


def validate_pre_context_commands(task_id: str, commands: object) -> list[dict[str, Any]]:
    """Reject malformed setup commands before a reproduction run begins.

    Context commands establish the history/state for the measured command, so
    silently skipping a malformed item would change the experimental condition
    without leaving an auditable failure. Keep the accepted shape aligned with
    ``AgentCommandRequest`` and normalize only the two meaningful strings.
    """
    if not isinstance(commands, list):
        raise ValueError(f"Task {task_id} pre_context_commands must be a list.")

    normalized_commands: list[dict[str, Any]] = []
    allowed_keys = {"user_command", "current_room_id"}
    for index, command in enumerate(commands, start=1):
        prefix = f"Task {task_id} pre_context_commands[{index}]"
        if not isinstance(command, dict):
            raise ValueError(f"{prefix} must be an object.")
        unknown_keys = sorted(set(command) - allowed_keys)
        if unknown_keys:
            raise ValueError(f"{prefix} has unsupported keys: {', '.join(unknown_keys)}")

        user_command = command.get("user_command")
        if not isinstance(user_command, str) or not user_command.strip():
            raise ValueError(f"{prefix}.user_command must be a non-empty string.")
        normalized_command: dict[str, Any] = {"user_command": user_command.strip()}

        if "current_room_id" in command:
            current_room_id = command["current_room_id"]
            if current_room_id is not None and (
                not isinstance(current_room_id, str) or not current_room_id.strip()
            ):
                raise ValueError(f"{prefix}.current_room_id must be a non-empty string or null.")
            normalized_command["current_room_id"] = (
                current_room_id.strip() if isinstance(current_room_id, str) else None
            )

        try:
            AgentCommandRequest(**normalized_command)
        except ValueError as error:
            raise ValueError(f"{prefix} has an invalid command request: {error}") from error
        normalized_commands.append(normalized_command)
    return normalized_commands


def validate_target_annotation(task_id: str, targets: object) -> dict[str, list[float]]:
    """Validate manually curated semantic target ranges before scoring them.

    The fixed suite treats these ranges as task labels, not values inferred from
    the current semantic adapter. This keeps parameter correctness auditable if
    the parser's defaults later change.
    """
    if not isinstance(targets, dict) or not targets:
        raise ValueError(f"Task {task_id or '<unknown>'} must have a non-empty target annotation object.")
    allowed_keys = {"illuminance_lux_range", "temperature_c_range", "humidity_percent_range"}
    unknown_keys = sorted(set(targets) - allowed_keys)
    if unknown_keys:
        raise ValueError(f"Task {task_id or '<unknown>'} has unsupported target keys: {', '.join(unknown_keys)}")
    normalized: dict[str, list[float]] = {}
    for key, value in targets.items():
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"Task {task_id or '<unknown>'} target {key} must be a two-value range.")
        try:
            lower, upper = (float(value[0]), float(value[1]))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Task {task_id or '<unknown>'} target {key} must be numeric.") from error
        if not (math.isfinite(lower) and math.isfinite(upper) and lower <= upper):
            raise ValueError(f"Task {task_id or '<unknown>'} target {key} must be a finite ordered range.")
        normalized[key] = [lower, upper]
    return normalized


def validate_semantic_annotation_provenance(provenance: object) -> dict[str, str]:
    """Require auditable label-quality boundaries for versioned task suites.

    Coverage alone establishes that every task has a label, not that labels
    were independently reviewed or ambiguities adjudicated. The artifact
    therefore records the evidence status rather than inferring quality from
    its own completeness.
    """
    if not isinstance(provenance, dict):
        raise ValueError("Versioned task suites require semantic_annotation_provenance.")
    required_fields = {
        "protocol_version",
        "reference_type",
        "annotation_unit",
        "independent_review_evidence_status",
        "inter_annotator_agreement_evidence_status",
        "ambiguity_adjudication_evidence_status",
    }
    missing_fields = sorted(required_fields - set(provenance))
    if missing_fields:
        raise ValueError(
            "semantic_annotation_provenance is missing required fields: "
            + ", ".join(missing_fields)
        )
    normalized = {field: str(provenance[field]).strip() for field in required_fields}
    if any(not value for value in normalized.values()):
        raise ValueError("semantic_annotation_provenance fields must be non-empty strings.")
    return normalized


def build_evaluation_scope(
    source_tasks: list[dict[str, Any]],
    executed_tasks: list[dict[str, Any]],
    *,
    requested_limit: int | None,
) -> dict[str, Any]:
    """Describe whether aggregate percentages are adequate performance evidence.

    A limited invocation is useful for health and integration smoke checks, but
    its percentages are individual-case diagnostics. The explicit metadata
    keeps machine-readable artifacts and their Markdown report from silently
    promoting a small subset into a benchmark-wide result.
    """
    source_categories = sorted({str(task.get("category", "uncategorized")) for task in source_tasks})
    executed_categories = sorted({str(task.get("category", "uncategorized")) for task in executed_tasks})
    source_task_count = len(source_tasks)
    executed_task_count = len(executed_tasks)
    is_limited_subset = executed_task_count < source_task_count
    has_minimum_coverage = (
        executed_task_count >= MINIMUM_TASKS_FOR_PERFORMANCE_CLAIM
        and len(executed_categories) >= MINIMUM_CATEGORIES_FOR_PERFORMANCE_CLAIM
    )
    performance_claim_allowed = not is_limited_subset and has_minimum_coverage
    if is_limited_subset:
        claim_status = "smoke_test_insufficient_task_coverage"
    elif not has_minimum_coverage:
        claim_status = "insufficient_task_coverage"
    else:
        claim_status = "fixed_task_suite_descriptive"
    return {
        "claim_status": claim_status,
        "performance_claim_allowed": performance_claim_allowed,
        "source_task_count": source_task_count,
        "executed_task_count": executed_task_count,
        "requested_limit": requested_limit,
        "source_category_count": len(source_categories),
        "executed_category_count": len(executed_categories),
        "source_categories": source_categories,
        "executed_categories": executed_categories,
        "minimum_tasks_for_performance_claim": MINIMUM_TASKS_FOR_PERFORMANCE_CLAIM,
        "minimum_categories_for_performance_claim": MINIMUM_CATEGORIES_FOR_PERFORMANCE_CLAIM,
        "interpretation": (
            "Aggregate percentages are descriptive results for the fixed simulated task suite, not "
            "population estimates or real-home performance claims."
            if performance_claim_allowed
            else "Aggregate percentages are smoke-test diagnostics only and must not be used as "
            "benchmark-wide performance estimates."
        ),
    }


def build_task_suite_provenance(tasks_path: Path, tasks: list[dict[str, Any]]) -> dict[str, object]:
    """Record the version and coverage of the manually curated semantic reference."""
    payload = json.loads(tasks_path.read_text(encoding="utf-8-sig"))
    schema_version = (
        str(payload.get("semantic_ground_truth_schema_version", "unversioned"))
        if isinstance(payload, dict)
        else "unversioned"
    )
    annotated_task_count = sum("expected_control_goal" in task for task in tasks)
    target_annotated_task_count = sum("expected_targets" in task for task in tasks)
    annotation_provenance = (
        validate_semantic_annotation_provenance(payload.get("semantic_annotation_provenance"))
        if isinstance(payload, dict) and "semantic_ground_truth_schema_version" in payload
        else None
    )
    label_quality_status = (
        "incomplete_annotation_provenance"
        if annotation_provenance
        and any(
            annotation_provenance[field] != "recorded"
            for field in (
                "independent_review_evidence_status",
                "inter_annotator_agreement_evidence_status",
                "ambiguity_adjudication_evidence_status",
            )
        )
        else "annotation_provenance_recorded"
    )
    return {
        "task_suite_sha256": hashlib.sha256(tasks_path.read_bytes()).hexdigest(),
        "semantic_ground_truth_schema_version": schema_version,
        "control_goal_annotated_task_count": annotated_task_count,
        "task_count": len(tasks),
        "control_goal_annotation_complete": annotated_task_count == len(tasks),
        "target_annotated_task_count": target_annotated_task_count,
        "target_annotation_complete": target_annotated_task_count == len(tasks),
        "semantic_annotation_provenance": annotation_provenance,
        "label_quality_status": label_quality_status,
    }


def resolve_groups(raw_groups: str) -> list[ExperimentGroup]:
    if raw_groups == "all":
        return EXPERIMENT_GROUPS
    group_ids = [item.strip() for item in raw_groups.split(",") if item.strip()]
    unknown = [group_id for group_id in group_ids if group_id not in GROUPS_BY_ID]
    if unknown:
        raise ValueError(f"Unknown experiment groups: {', '.join(unknown)}")
    return [GROUPS_BY_ID[group_id] for group_id in group_ids]


def require_real_llm_if_needed(groups: list[ExperimentGroup]) -> None:
    if not any(group.llm_mode == "real" for group in groups):
        return
    if not os.getenv("REAL_LLM_API_KEY"):
        raise RuntimeError(
            "Real LLM groups require REAL_LLM_API_KEY in the selected environment or shell. "
            "For a quick local smoke test, pass --real-mode mock."
        )


def run_group(
    group: ExperimentGroup,
    tasks: list[dict[str, Any]],
    output_dir: Path,
    *,
    real_mode: str,
    repeat_index: int = 1,
) -> list[dict[str, Any]]:
    environment = SmartHomeEnvironment()
    logger = ExperimentLogger(output_dir / "logs" / group.group_id / f"repeat_{repeat_index:03d}")
    effective_llm_mode = effective_llm_mode_for_group(group, real_mode)
    semantic_provenance = semantic_runtime_provenance(effective_llm_mode)
    records: list[dict[str, Any]] = []

    with temporary_llm_mode(effective_llm_mode):
        runner = None
        if group.runner_kind == "task_runner":
            runner = TaskRunner(
                environment=environment,
                experiment_logger=logger,
                refresh_realtime=False,
                enable_feedback_correction=group.enable_feedback_correction,
                enable_context_memory=group.enable_context_memory,
                execute_actions=group.execute_actions,
            )

        for task_index, task in enumerate(tasks, start=1):
            environment.reset(refresh_realtime=False)
            if runner is not None:
                runner.reset_context_memory()
            apply_task_setup(environment, task)
            state_fingerprint = initial_state_fingerprint(environment)

            started_at = time.perf_counter()
            pre_context_success = True
            if runner is not None:
                pre_context_success = run_pre_context_commands(runner, task)

            if group.runner_kind == "baseline":
                response = run_fixed_policy_baseline(environment, task)
            elif runner is not None:
                response = runner.run_agent_command(
                    AgentCommandRequest(
                        user_command=str(task["user_command"]),
                        current_room_id=task.get("current_room_id"),
                    )
                )
            else:
                raise RuntimeError(f"Unsupported runner_kind: {group.runner_kind}")

            response_time_ms = round((time.perf_counter() - started_at) * 1000, 2)
            record = build_record(
                group=group,
                task=task,
                task_index=task_index,
                repeat_index=repeat_index,
                response=response,
                environment=environment,
                response_time_ms=response_time_ms,
                pre_context_success=pre_context_success,
                initial_state_fingerprint=state_fingerprint,
                effective_llm_mode=effective_llm_mode,
                real_mode=real_mode,
                semantic_provenance=semantic_provenance,
            )
            records.append(record)

    return records


def effective_llm_mode_for_group(group: ExperimentGroup, real_mode: str) -> str:
    """Resolve the semantic engine actually used for an experiment group."""
    return "mock" if group.llm_mode == "real" and real_mode == "mock" else group.llm_mode


def display_group_name(group: ExperimentGroup, effective_llm_mode: str) -> str:
    """Prevent mock smoke-test outputs from being presented as real-LLM results."""
    if group.llm_mode == "real" and effective_llm_mode != "real":
        return f"{group.name} [semantic={effective_llm_mode}]"
    return group.name


@contextmanager
def temporary_llm_mode(mode: str):
    previous = os.environ.get("LLM_MODE")
    if mode != "none":
        os.environ["LLM_MODE"] = mode
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LLM_MODE", None)
        else:
            os.environ["LLM_MODE"] = previous


def apply_task_setup(environment: SmartHomeEnvironment, task: dict[str, Any]) -> None:
    env_updates = task.get("environment")
    if isinstance(env_updates, dict):
        environment.set_outdoor_environment(
            weather=env_updates.get("weather"),
            time_hour=env_updates.get("time_hour"),
        )

    expected_intent = str(task.get("expected_intent", ""))
    expected_room = str(task.get("expected_room", ""))
    current_room_id = task.get("current_room_id")
    if expected_intent == "away_mode":
        environment.set_away()
        return

    room_id = current_room_id if isinstance(current_room_id, str) else expected_room
    if room_id and room_id != "all_rooms":
        environment.set_current_room(room_id, activity_for_intent(expected_intent))


def activity_for_intent(intent: str) -> str:
    if intent == "study_mode":
        return "study"
    if intent == "movie_mode":
        return "movie"
    if intent == "sleep_mode":
        return "sleep"
    return "idle"


def initial_state_fingerprint(environment: SmartHomeEnvironment) -> str:
    """Bind every repeated semantic request to its fully initialized simulator input."""
    payload = environment.get_state(refresh_realtime=False).model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_pre_context_commands(runner: TaskRunner, task: dict[str, Any]) -> bool:
    commands = task.get("pre_context_commands", [])
    if not isinstance(commands, list):
        return True
    success = True
    for command in commands:
        if not isinstance(command, dict):
            continue
        response = runner.run_agent_command(
            AgentCommandRequest(
                user_command=str(command.get("user_command", "")),
                current_room_id=command.get("current_room_id"),
            )
        )
        success = success and response.success
    return success


def run_fixed_policy_baseline(environment: SmartHomeEnvironment, task: dict[str, Any]):
    state_before = environment.get_state(refresh_realtime=False)
    actions = plan_conventional_baseline_actions(state_before)
    results, final_state = environment.apply_device_actions_batch(actions, dt_minutes=5)
    semantic_result = expected_semantic_from_task(task)
    feedback_result = FeedbackAgent().evaluate(semantic_result, final_state, revision_round=0)

    success = all(item["success"] for item in results) if results else True
    return SimpleNamespace(
        success=success,
        semantic_result=semantic_result,
        plan_result={
            "plan_id": "fixed-policy-baseline",
            "agent": "fixed_policy_baseline",
            "intent": semantic_result["intent"],
            "room": semantic_result["room"],
            "scope": semantic_result["scope"],
            "control_goal": semantic_result["control_goal"],
            "actions": actions,
        },
        execution_result={
            "agent": "fixed_policy_baseline",
            "executed_count": sum(1 for item in results if item["success"]),
            "results": results,
            "final_state": final_state.model_dump(),
        },
        feedback_result=feedback_result,
        final_state=final_state,
        error="" if success else "fixed policy action failed",
    )


def expected_semantic_from_task(task: dict[str, Any]) -> dict[str, Any]:
    intent = str(task.get("expected_intent") or "basic_light_control")
    targets = dict(TARGETS_BY_INTENT.get(intent, TARGETS_BY_INTENT["basic_light_control"]))
    command = str(task.get("user_command", ""))
    if any(keyword in command for keyword in ["湿度", "潮", "洗澡"]):
        targets["humidity_percent_range"] = [40, 70]
    return {
        "intent": intent,
        "room": str(task.get("expected_room") or task.get("current_room_id") or "living_room"),
        "scope": str(task.get("expected_scope") or "single_room"),
        "control_goal": detect_control_goal(command, intent),
        "task_type": "device_control" if intent.startswith("basic_") else "scene_control",
        "targets": targets,
        "devices": list(task.get("expected_devices", [])),
        "constraints": {
            "comfort_first": intent not in {"away_mode", "energy_saving_mode"},
            "energy_saving": intent in {"away_mode", "energy_saving_mode"},
        },
        "llm_mode": "none",
    }


def detect_control_goal(command: str, intent: str) -> str:
    if any(keyword in command for keyword in ["关闭", "关掉", "关上", "全关", "不要"]):
        return "turn_off"
    if any(keyword in command for keyword in ["打开", "开启", "开到", "亮"]):
        return "turn_on"
    if intent.startswith("basic_"):
        return "turn_on"
    return "set_target"


def build_record(
    *,
    group: ExperimentGroup,
    task: dict[str, Any],
    task_index: int,
    repeat_index: int,
    response,
    environment: SmartHomeEnvironment,
    response_time_ms: float,
    pre_context_success: bool,
    effective_llm_mode: str,
    real_mode: str,
    semantic_provenance: dict[str, object],
    initial_state_fingerprint: str = "",
) -> dict[str, Any]:
    semantic = response.semantic_result or {}
    plan = response.plan_result or {}
    feedback = response.feedback_result or {}
    final_state = response.final_state or environment.get_state(refresh_realtime=False)
    expected_devices = [str(device) for device in task.get("expected_devices", [])]
    raw_actions = plan.get("actions", []) if isinstance(plan, dict) else None
    planned_actions = raw_actions if isinstance(raw_actions, list) else []
    planned_device_types = sorted(device_types_from_actions(planned_actions))
    device_selection = device_selection_metrics(expected_devices, planned_device_types)
    target_measurement = (
        target_range_metrics(task.get("expected_targets"), semantic.get("targets"))
        if group.semantic_applicable
        else target_range_metrics(None, None)
    )
    # The fixed-policy baseline builds an oracle semantic object only to drive
    # its shared feedback helper. It does not parse the user command, so its
    # target ranges must not appear as a semantic-parameter score.
    target_measurement["applicable"] = bool(
        group.semantic_applicable and target_measurement["applicable"]
    )
    llm_metrics = semantic.get("llm_metrics", {}) if isinstance(semantic.get("llm_metrics"), dict) else {}

    intent_correct = bool(semantic.get("intent") == task.get("expected_intent")) if group.semantic_applicable else ""
    room_correct = bool(semantic.get("room") == task.get("expected_room")) if group.semantic_applicable else ""
    scope_correct = bool(semantic.get("scope") == task.get("expected_scope")) if group.semantic_applicable else ""
    control_goal_applicable = group.semantic_applicable and "expected_control_goal" in task
    control_goal_correct = (
        bool(semantic.get("control_goal") == task.get("expected_control_goal")) if control_goal_applicable else ""
    )
    completed = bool(feedback.get("completed", False)) if group.completion_applicable else ""
    main_command_success = bool(response.success)
    runtime_success = bool(pre_context_success and main_command_success)
    response_error = str(response.error or "")
    error = response_error
    if not pre_context_success:
        error = "pre-context command failed" if not response_error else f"pre-context command failed; {response_error}"
    occupied_comfort = occupied_comfort_score(final_state)
    failure_type = classify_failure(
        success=runtime_success,
        semantic_applicable=group.semantic_applicable,
        completion_applicable=group.completion_applicable,
        intent_correct=intent_correct,
        room_correct=room_correct,
        scope_correct=scope_correct,
        control_goal_correct=control_goal_correct,
        target_exact_match=target_measurement["exact_match"],
        device_selection_exact_match=device_selection["exact_match"],
        completed=completed,
        error=error,
    )

    return {
        "group_id": group.group_id,
        "group_name": display_group_name(group, effective_llm_mode),
        "task_index": task_index,
        "repeat_index": repeat_index,
        "task_id": task.get("task_id", f"P{task_index:03d}"),
        "category": task.get("category", "uncategorized"),
        "user_command": task.get("user_command", ""),
        "pre_context_count": len(task.get("pre_context_commands", []) or []),
        "pre_context_success": pre_context_success,
        "effective_llm_mode": effective_llm_mode,
        "real_mode": real_mode,
        "semantic_model_id": semantic_provenance["model_id"],
        "semantic_model_revision": semantic_provenance["model_revision"],
        "semantic_model_revision_source": semantic_provenance["model_revision_source"],
        "semantic_provenance_status": semantic_provenance["provenance_status"],
        "semantic_adapter_sha256": semantic_provenance["semantic_adapter_sha256"],
        "semantic_runtime_fingerprint": semantic_provenance["semantic_runtime_fingerprint"],
        "initial_state_fingerprint": initial_state_fingerprint,
        "execute_actions": group.execute_actions,
        "feedback_correction_enabled": group.enable_feedback_correction,
        "context_memory_enabled": group.enable_context_memory,
        # A task with setup/context commands is only runnable when the whole
        # command chain succeeds. Keep the main-command result separately so
        # a context failure remains diagnosable without inflating the report.
        "success": runtime_success,
        "main_command_success": main_command_success,
        "completion_applicable": group.completion_applicable,
        "outcome_metrics_applicable": group.execute_actions,
        "completed": completed,
        "semantic_applicable": group.semantic_applicable,
        "expected_intent": task.get("expected_intent", ""),
        "predicted_intent": semantic.get("intent", ""),
        "intent_correct": intent_correct,
        "expected_room": task.get("expected_room", ""),
        "predicted_room": semantic.get("room", ""),
        "room_correct": room_correct,
        "expected_scope": task.get("expected_scope", ""),
        "predicted_scope": semantic.get("scope", ""),
        "scope_correct": scope_correct,
        "control_goal_applicable": control_goal_applicable,
        "expected_control_goal": task.get("expected_control_goal", ""),
        "predicted_control_goal": semantic.get("control_goal", ""),
        "control_goal_correct": control_goal_correct,
        "target_applicable": target_measurement["applicable"],
        "expected_targets": json.dumps(
            task.get("expected_targets", {}) if group.semantic_applicable else {},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "predicted_targets": json.dumps(
            semantic.get("targets", {}) if group.semantic_applicable else {},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "semantic_output_fingerprint": semantic_output_fingerprint(
            semantic,
            applicable=group.semantic_applicable,
        ),
        "target_expected_key_count": target_measurement["expected_key_count"],
        "target_predicted_key_count": target_measurement["predicted_key_count"],
        "target_range_iou_percent": target_measurement["range_iou_percent"],
        "target_exact_match": target_measurement["exact_match"],
        "expected_devices": "|".join(expected_devices),
        "planned_device_types": "|".join(planned_device_types),
        "device_selection_expected_count": device_selection["expected_count"],
        "device_selection_planned_count": device_selection["planned_count"],
        "device_selection_true_positive_count": device_selection["true_positive_count"],
        "device_selection_false_positive_count": device_selection["false_positive_count"],
        "device_selection_false_negative_count": device_selection["false_negative_count"],
        "device_selection_precision_percent": device_selection["precision_percent"],
        "device_selection_recall_percent": device_selection["recall_percent"],
        "device_selection_f1_percent": device_selection["f1_percent"],
        # Accuracy is exact set match at the task level: a plan must include
        # every expected device category and no unrequested category.  The
        # component counts and precision/recall/F1 remain in each record so
        # the metric is reconstructable rather than a black-box percentage.
        "device_selection_accuracy_percent": 100.0 if device_selection["exact_match"] else 0.0,
        "device_selection_exact_match": device_selection["exact_match"],
        "action_count": len(planned_actions),
        "plan_action_fingerprint": plan_action_fingerprint(raw_actions),
        "executed_count": int((response.execution_result or {}).get("executed_count", 0)),
        "correction_round": int(feedback.get("correction_round", 0) or 0),
        "response_time_ms": response_time_ms,
        "llm_request_ms": float(llm_metrics.get("request_ms", 0) or 0),
        "llm_prompt_bytes": int(llm_metrics.get("prompt_bytes", 0) or 0),
        "llm_cache_hit": bool(llm_metrics.get("cache_hit", False)),
        "current_power_w": final_state.energy_metrics.current_power_w if group.execute_actions else "",
        "baseline_power_w": final_state.energy_metrics.baseline_power_w if group.execute_actions else "",
        "energy_saving_rate_percent": final_state.energy_metrics.energy_saving_rate_percent if group.execute_actions else "",
        "average_comfort_score": final_state.comfort_metrics.average_overall_score if group.execute_actions else "",
        "occupied_comfort_score": occupied_comfort if occupied_comfort is not None and group.execute_actions else "",
        "comfort_retained": occupied_comfort >= 80 if occupied_comfort is not None and group.execute_actions else "",
        "failure_type": failure_type,
        "error": error,
    }


def semantic_output_fingerprint(semantic: dict[str, Any], *, applicable: bool) -> str:
    """Fingerprint only parser output that can change semantic interpretation.

    Request durations, cache flags, plan identifiers and feedback diagnostics are
    deliberately excluded: they are useful runtime observations but must not
    make otherwise identical semantic predictions look unstable.
    """
    if not applicable:
        # Keep the inapplicability boundary explicit in persisted records.  An
        # empty string is too easy to confuse with a missing/failed fingerprint
        # during downstream CSV analysis.
        return "not_applicable"
    payload = {
        "predicted_intent": semantic.get("intent", ""),
        "predicted_room": semantic.get("room", ""),
        "predicted_scope": semantic.get("scope", ""),
        "predicted_control_goal": semantic.get("control_goal", ""),
        "predicted_targets": semantic.get("targets", {}),
    }
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def plan_action_fingerprint(actions: object) -> str:
    """Fingerprint the ordered executable action payload from a fresh task run.

    A malformed action payload is measurement failure, not an empty plan. The
    empty string lets repeat-stability aggregation fail closed instead of
    silently filtering invalid entries into a valid-looking hash.
    """
    if not isinstance(actions, list) or any(not isinstance(action, dict) for action in actions):
        return ""
    normalized_actions = actions
    return _sha256_text(
        json.dumps(normalized_actions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def device_types_from_actions(actions: list[dict[str, Any]]) -> set[str]:
    device_types: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        entity_id = str(action.get("entity_id", ""))
        if "." in entity_id:
            device_types.add(entity_id.split(".", 1)[0])
    return device_types


def device_selection_metrics(expected_devices: list[str], planned_device_types: list[str]) -> dict[str, int | float | bool]:
    """Calculate exact-set device selection and traceable set-overlap metrics.

    The former "accuracy" was recall only, which awarded 100% to a plan that
    covered every requested device while also controlling extra categories.
    For smart-home execution those false positives matter: they can consume
    energy or create a safety-relevant side effect. Exact set match is the
    task-level accuracy; precision, recall and F1 explain the error shape.
    """
    planned = set(planned_device_types)
    expected = set(expected_devices)
    true_positive_count = len(expected & planned)
    false_positive_count = len(planned - expected)
    false_negative_count = len(expected - planned)
    precision = true_positive_count / len(planned) if planned else 0.0
    recall = true_positive_count / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "expected_count": len(expected),
        "planned_count": len(planned),
        "true_positive_count": true_positive_count,
        "false_positive_count": false_positive_count,
        "false_negative_count": false_negative_count,
        "precision_percent": round(precision * 100, 2),
        "recall_percent": round(recall * 100, 2),
        "f1_percent": round(f1 * 100, 2),
        "exact_match": planned == expected,
    }


def target_range_metrics(expected_targets: object, predicted_targets: object) -> dict[str, int | float | bool]:
    """Score semantic control parameters using independently versioned ranges.

    Exact match remains the task-level correctness decision. Mean interval IoU
    gives an error-sensitive secondary measure: a partially overlapping range
    is visible without being promoted to a correct executable interpretation.
    """
    if not isinstance(expected_targets, dict) or not expected_targets:
        return {
            "applicable": False,
            "expected_key_count": 0,
            "predicted_key_count": 0,
            "range_iou_percent": 0.0,
            "exact_match": False,
        }
    expected = validate_target_annotation("expected", expected_targets)
    predicted = (
        validate_target_annotation("predicted", predicted_targets)
        if isinstance(predicted_targets, dict) and predicted_targets
        else {}
    )
    keys = sorted(set(expected) | set(predicted))
    ious: list[float] = []
    for key in keys:
        expected_range = expected.get(key)
        predicted_range = predicted.get(key)
        if expected_range is None or predicted_range is None:
            ious.append(0.0)
            continue
        intersection = max(0.0, min(expected_range[1], predicted_range[1]) - max(expected_range[0], predicted_range[0]))
        union = max(expected_range[1], predicted_range[1]) - min(expected_range[0], predicted_range[0])
        ious.append(1.0 if union == 0 and expected_range == predicted_range else (intersection / union if union else 0.0))
    return {
        "applicable": True,
        "expected_key_count": len(expected),
        "predicted_key_count": len(predicted),
        "range_iou_percent": round(mean(ious) * 100, 2) if ious else 0.0,
        "exact_match": expected == predicted,
    }


def occupied_comfort_score(state) -> float | None:
    occupied_room = next((room for room in state.rooms if room.occupancy and room.activity != "away"), None)
    if occupied_room is None:
        return None
    comfort = next((item for item in state.comfort_metrics.rooms if item.room_id == occupied_room.room_id), None)
    return comfort.overall_comfort_score if comfort else None


def classify_failure(
    *,
    success: bool,
    semantic_applicable: bool,
    completion_applicable: bool,
    intent_correct: bool | str,
    room_correct: bool | str,
    scope_correct: bool | str,
    control_goal_correct: bool | str,
    target_exact_match: bool,
    device_selection_exact_match: bool,
    completed: bool | str,
    error: str,
) -> str:
    if not success:
        return "runtime_error" if error else "execution_error"
    if semantic_applicable:
        if intent_correct is False:
            return "semantic_intent_error"
        if room_correct is False:
            return "semantic_room_error"
        if scope_correct is False:
            return "semantic_scope_error"
        if control_goal_correct is False:
            return "semantic_control_goal_error"
        if target_exact_match is False:
            return "semantic_target_error"
    if not device_selection_exact_match:
        return "device_selection_mismatch"
    if completion_applicable and completed is False:
        return "feedback_not_completed"
    return "none"


def summarize_records(records: list[dict[str, Any]], group: ExperimentGroup) -> dict[str, Any]:
    effective_llm_modes = sorted({str(record["effective_llm_mode"]) for record in records})
    return {
        "group_id": group.group_id,
        "group_name": records[0]["group_name"] if records else group.name,
        "description": group.description,
        "configured_llm_mode": group.llm_mode,
        "effective_llm_modes": effective_llm_modes,
        "sample_count": len(records),
        "success_rate_percent": rate(records, "success"),
        "task_completion_rate_percent": applicable_rate(records, "completed", "completion_applicable"),
        "intent_accuracy_percent": applicable_rate(records, "intent_correct", "semantic_applicable"),
        "room_accuracy_percent": applicable_rate(records, "room_correct", "semantic_applicable"),
        "scope_accuracy_percent": applicable_rate(records, "scope_correct", "semantic_applicable"),
        "control_goal_accuracy_percent": applicable_rate(records, "control_goal_correct", "control_goal_applicable"),
        "target_exact_match_percent": applicable_rate(records, "target_exact_match", "target_applicable"),
        "target_range_iou_percent": applicable_average(records, "target_range_iou_percent", "target_applicable"),
        "device_selection_accuracy_percent": average(records, "device_selection_accuracy_percent"),
        "device_selection_precision_percent": average(records, "device_selection_precision_percent"),
        "device_selection_recall_percent": average(records, "device_selection_recall_percent"),
        "device_selection_f1_percent": average(records, "device_selection_f1_percent"),
        "average_correction_round": average(records, "correction_round"),
        "average_response_time_ms": average(records, "response_time_ms"),
        "average_llm_request_ms": average(records, "llm_request_ms"),
        "llm_cache_hit_rate_percent": rate(records, "llm_cache_hit"),
        "average_current_power_w": applicable_average(records, "current_power_w", "outcome_metrics_applicable"),
        "average_baseline_power_w": applicable_average(records, "baseline_power_w", "outcome_metrics_applicable"),
        "average_energy_saving_rate_percent": applicable_average(records, "energy_saving_rate_percent", "outcome_metrics_applicable"),
        "average_comfort_score": applicable_average(records, "average_comfort_score", "outcome_metrics_applicable"),
        "average_occupied_comfort_score": applicable_average(records, "occupied_comfort_score", "outcome_metrics_applicable"),
        "comfort_retention_rate_percent": applicable_rate(records, "comfort_retained", "outcome_metrics_applicable"),
        "failure_counts": dict(Counter(record["failure_type"] for record in records)),
    }


def primary_performance_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select the preregistered first isolated run for coverage-based metrics.

    Additional repetitions are retained in the CSV and used only by
    ``summarize_repeat_stability``. Counting them in accuracy, outcome, or
    category summaries would inflate the apparent task sample size despite
    reusing the same task fixture.
    """
    primary: list[dict[str, Any]] = []
    seen_task_units: set[tuple[str, str]] = set()
    for record in records:
        repeat_index = record.get("repeat_index", 1)
        if repeat_index != 1:
            continue
        task_unit = (str(record["group_id"]), str(record["task_id"]))
        if task_unit in seen_task_units:
            raise ValueError(
                "Duplicate primary performance record for "
                f"group {task_unit[0]!r} and task {task_unit[1]!r}."
            )
        seen_task_units.add(task_unit)
        primary.append(record)
    return primary


def summarize_by_group_and_category(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    group_names = {record["group_id"]: record["group_name"] for record in records}
    for record in records:
        grouped[(record["group_id"], record["category"])].append(record)

    summaries = []
    for (group_id, category), items in sorted(grouped.items()):
        summaries.append(
            {
                "group_id": group_id,
                "group_name": group_names.get(group_id, group_id),
                "category": category,
                "sample_count": len(items),
                "success_rate_percent": rate(items, "success"),
                "task_completion_rate_percent": applicable_rate(items, "completed", "completion_applicable"),
                "intent_accuracy_percent": applicable_rate(items, "intent_correct", "semantic_applicable"),
                "room_accuracy_percent": applicable_rate(items, "room_correct", "semantic_applicable"),
                "scope_accuracy_percent": applicable_rate(items, "scope_correct", "semantic_applicable"),
                "control_goal_accuracy_percent": applicable_rate(items, "control_goal_correct", "control_goal_applicable"),
                "target_exact_match_percent": applicable_rate(items, "target_exact_match", "target_applicable"),
                "target_range_iou_percent": applicable_average(items, "target_range_iou_percent", "target_applicable"),
                "device_selection_accuracy_percent": average(items, "device_selection_accuracy_percent"),
                "device_selection_precision_percent": average(items, "device_selection_precision_percent"),
                "device_selection_recall_percent": average(items, "device_selection_recall_percent"),
                "device_selection_f1_percent": average(items, "device_selection_f1_percent"),
                "average_energy_saving_rate_percent": applicable_average(items, "energy_saving_rate_percent", "outcome_metrics_applicable"),
                "average_occupied_comfort_score": applicable_average(items, "occupied_comfort_score", "outcome_metrics_applicable"),
            }
        )
    return summaries


def summarize_repeat_stability(records: list[dict[str, Any]], *, repeat_count: int) -> list[dict[str, Any]]:
    """Report within-task agreement across isolated repetitions, never as task coverage.

    Repeated calls to a local model answer a reproducibility question: whether
    a fixed task/configuration emitted the same semantic interpretation and
    executable plan. They are not independent task examples, so this summary
    is intentionally separate from benchmark accuracy and category coverage.
    """
    by_group_task: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    group_names: dict[str, str] = {}
    for record in records:
        if record.get("semantic_applicable") is not True:
            continue
        group_id = str(record["group_id"])
        by_group_task[(group_id, str(record["task_id"]))].append(record)
        group_names[group_id] = str(record["group_name"])

    summaries: list[dict[str, Any]] = []
    by_group: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for (group_id, _task_id), task_records in by_group_task.items():
        by_group[group_id].append(task_records)

    for group_id, task_runs in sorted(by_group.items()):
        observed_repeat_counts = sorted({len(items) for items in task_runs})
        complete_repeat_units = [items for items in task_runs if len(items) == repeat_count]
        expected_repeat_indices = list(range(1, repeat_count + 1))
        invalid_repeat_index_task_ids = sorted(
            str(items[0]["task_id"])
            for items in complete_repeat_units
            if (
                any(
                    not isinstance(record.get("repeat_index"), int)
                    or isinstance(record.get("repeat_index"), bool)
                    for record in items
                )
                or sorted(record["repeat_index"] for record in items) != expected_repeat_indices
            )
        )
        semantic_runtime_fingerprints = {
            str(record.get("semantic_runtime_fingerprint", "")).strip()
            for task_records in task_runs
            for record in task_records
        }
        semantic_runtime_fingerprint_count = len(semantic_runtime_fingerprints)
        invalid_semantic_runtime_fingerprint_task_ids = sorted(
            {
                str(record["task_id"])
                for task_records in task_runs
                for record in task_records
                if str(record.get("semantic_runtime_fingerprint", "")).strip()
                and not is_canonical_sha256_fingerprint(record.get("semantic_runtime_fingerprint"))
            }
        )
        missing_semantic_output_fingerprint_task_ids = sorted(
            {
                str(record["task_id"])
                for task_records in task_runs
                for record in task_records
                if not str(record.get("semantic_output_fingerprint", "")).strip()
            }
        )
        invalid_semantic_output_fingerprint_task_ids = sorted(
            {
                str(record["task_id"])
                for task_records in task_runs
                for record in task_records
                if str(record.get("semantic_output_fingerprint", "")).strip()
                and not is_canonical_sha256_fingerprint(record.get("semantic_output_fingerprint"))
            }
        )
        missing_plan_action_fingerprint_task_ids = sorted(
            {
                str(record["task_id"])
                for task_records in task_runs
                for record in task_records
                if not str(record.get("plan_action_fingerprint", "")).strip()
            }
        )
        invalid_plan_action_fingerprint_task_ids = sorted(
            {
                str(record["task_id"])
                for task_records in task_runs
                for record in task_records
                if str(record.get("plan_action_fingerprint", "")).strip()
                and not is_canonical_sha256_fingerprint(record.get("plan_action_fingerprint"))
            }
        )
        failed_run_task_ids = sorted(
            {
                str(record["task_id"])
                for task_records in task_runs
                for record in task_records
                # An identical empty/error response may produce identical
                # canonical hashes. That proves a repeatable failure, not
                # semantic or executable-plan reproducibility.
                if record.get("success") is False
            }
        )
        if repeat_count < 2:
            status = "single_run_no_stability_measurement"
            semantic_stability_percent: float | None = None
            plan_stability_percent: float | None = None
            unstable_task_ids: list[str] = []
        elif len(complete_repeat_units) != len(task_runs):
            status = "incomplete_repeat_units"
            semantic_stability_percent = None
            plan_stability_percent = None
            unstable_task_ids = []
        elif invalid_repeat_index_task_ids:
            # A matching number of records is not sufficient evidence of
            # independent repetitions: every task must cover each requested
            # repeat index exactly once.  Otherwise duplicated primary runs
            # can be mistaken for a repeated-run measurement.
            status = "invalid_repeat_indices"
            semantic_stability_percent = None
            plan_stability_percent = None
            unstable_task_ids = []
        elif failed_run_task_ids:
            status = "failed_runs_no_stability_measurement"
            semantic_stability_percent = None
            plan_stability_percent = None
            unstable_task_ids = []
        elif semantic_runtime_fingerprint_count != 1 or "" in semantic_runtime_fingerprints:
            # A matching output cannot be interpreted as repeatable semantic
            # behavior when the model, decoding configuration, endpoint, or
            # semantic adapter provenance changed between runs.
            status = "inconsistent_semantic_runtime_fingerprint"
            semantic_stability_percent = None
            plan_stability_percent = None
            unstable_task_ids = []
        elif (
            invalid_semantic_runtime_fingerprint_task_ids
            or invalid_semantic_output_fingerprint_task_ids
            or invalid_plan_action_fingerprint_task_ids
        ):
            # A repeated non-empty placeholder (such as ``unrecorded``) is not
            # evidence that the underlying runtime, semantic output, or plan
            # was measured identically. All three fields are generated as
            # canonical SHA-256 digests by this runner.
            status = "invalid_fingerprint_format"
            semantic_stability_percent = None
            plan_stability_percent = None
            unstable_task_ids = []
        elif missing_semantic_output_fingerprint_task_ids or missing_plan_action_fingerprint_task_ids:
            # Missing hashes are an instrumentation failure, not matching
            # outputs. Treat them as unavailable evidence rather than a
            # single identical empty value that would otherwise score 100%.
            status = "missing_semantic_or_plan_fingerprint"
            semantic_stability_percent = None
            plan_stability_percent = None
            unstable_task_ids = []
        else:
            status = "measured"
            semantic_stable = [
                len({str(record.get("semantic_output_fingerprint", "")) for record in items}) == 1
                for items in complete_repeat_units
            ]
            plan_stable = [
                len({str(record.get("plan_action_fingerprint", "")) for record in items}) == 1
                for items in complete_repeat_units
            ]
            semantic_stability_percent = round(sum(semantic_stable) / len(semantic_stable) * 100, 2)
            plan_stability_percent = round(sum(plan_stable) / len(plan_stable) * 100, 2)
            unstable_task_ids = sorted(
                str(items[0]["task_id"])
                for items, semantic_is_stable, plan_is_stable in zip(
                    complete_repeat_units, semantic_stable, plan_stable
                )
                if not semantic_is_stable or not plan_is_stable
            )

        summaries.append(
            {
                "group_id": group_id,
                "group_name": group_names[group_id],
                "requested_repeat_count": repeat_count,
                "task_repeat_unit_count": len(task_runs),
                "observed_repeat_counts": observed_repeat_counts,
                "invalid_repeat_index_task_ids": invalid_repeat_index_task_ids,
                "semantic_runtime_fingerprint_count": semantic_runtime_fingerprint_count,
                "invalid_semantic_runtime_fingerprint_task_ids": invalid_semantic_runtime_fingerprint_task_ids,
                "missing_semantic_output_fingerprint_task_ids": missing_semantic_output_fingerprint_task_ids,
                "invalid_semantic_output_fingerprint_task_ids": invalid_semantic_output_fingerprint_task_ids,
                "missing_plan_action_fingerprint_task_ids": missing_plan_action_fingerprint_task_ids,
                "invalid_plan_action_fingerprint_task_ids": invalid_plan_action_fingerprint_task_ids,
                "failed_run_task_ids": failed_run_task_ids,
                "stability_status": status,
                "semantic_output_exact_stability_percent": semantic_stability_percent,
                "plan_action_exact_stability_percent": plan_stability_percent,
                "unstable_task_ids": unstable_task_ids,
            }
        )
    return summaries


def rate(records: list[dict[str, Any]], field: str, applicability_field: str | None = None) -> float:
    applicable = [
        record
        for record in records
        if record.get(field) != ""
        and (applicability_field is None or record.get(applicability_field) is True)
    ]
    if not applicable:
        return 0.0
    return round(sum(1 for record in applicable if record.get(field) is True) / len(applicable) * 100, 2)


def applicable_rate(records: list[dict[str, Any]], field: str, applicability_field: str) -> float | None:
    """Return None, rather than a misleading zero, when a metric is not applicable."""
    if not any(record.get(applicability_field) is True for record in records):
        return None
    return rate(records, field, applicability_field)


def average(records: list[dict[str, Any]], field: str) -> float:
    values = [
        float(record[field])
        for record in records
        if record.get(field) not in {"", None}
    ]
    return round(mean(values), 2) if values else 0.0


def applicable_average(records: list[dict[str, Any]], field: str, applicability_field: str) -> float | None:
    """Keep non-executed ablation outcomes out of aggregate comparisons."""
    applicable_records = [record for record in records if record.get(applicability_field) is True]
    if not applicable_records:
        return None
    return average(applicable_records, field)


def build_chart_data(
    group_summaries: list[dict[str, Any]],
    category_summaries: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    correction_distribution = []
    grouped_rounds: dict[tuple[str, int], int] = Counter(
        (record["group_id"], int(record["correction_round"]))
        for record in records
        if record.get("completion_applicable") is True
    )
    group_names = {record["group_id"]: record["group_name"] for record in records}
    for (group_id, correction_round), count in sorted(grouped_rounds.items()):
        correction_distribution.append(
            {
                "group_id": group_id,
                "group_name": group_names.get(group_id, group_id),
                "correction_round": correction_round,
                "count": count,
            }
        )

    return {
        "method_completion_rate": [
            {
                "group_id": item["group_id"],
                "group_name": item["group_name"],
                "task_completion_rate_percent": item["task_completion_rate_percent"],
            }
            for item in group_summaries
            if item["task_completion_rate_percent"] is not None
        ],
        "method_energy_saving_rate": [
            {
                "group_id": item["group_id"],
                "group_name": item["group_name"],
                "average_energy_saving_rate_percent": item["average_energy_saving_rate_percent"],
            }
            for item in group_summaries
            if item["average_energy_saving_rate_percent"] is not None
        ],
        "power_by_task": [
            {
                "task_index": record["task_index"],
                "task_id": record["task_id"],
                "group_id": record["group_id"],
                "group_name": record["group_name"],
                "current_power_w": record["current_power_w"],
                "baseline_power_w": record["baseline_power_w"],
            }
            for record in records
            if record.get("execute_actions") is True
        ],
        "comfort_by_task": [
            {
                "task_index": record["task_index"],
                "task_id": record["task_id"],
                "group_id": record["group_id"],
                "group_name": record["group_name"],
                "average_comfort_score": record["average_comfort_score"],
                "occupied_comfort_score": record["occupied_comfort_score"],
            }
            for record in records
            if record.get("execute_actions") is True
        ],
        "correction_round_distribution": correction_distribution,
        "semantic_accuracy_by_category": [
            {
                "group_id": item["group_id"],
                "group_name": item["group_name"],
                "category": item["category"],
                "intent_accuracy_percent": item["intent_accuracy_percent"],
                "room_accuracy_percent": item["room_accuracy_percent"],
                "scope_accuracy_percent": item["scope_accuracy_percent"],
                "control_goal_accuracy_percent": item["control_goal_accuracy_percent"],
                "target_exact_match_percent": item["target_exact_match_percent"],
                "target_range_iou_percent": item["target_range_iou_percent"],
            }
            for item in category_summaries
            if item["intent_accuracy_percent"] is not None
        ],
    }


def write_chart_csvs(chart_csv_dir: Path, chart_data: dict[str, list[dict[str, Any]]]) -> None:
    for name, rows in chart_data.items():
        write_csv(chart_csv_dir / f"{name}.csv", rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render_report(summary: dict[str, Any]) -> str:
    evaluation_scope = summary["evaluation_scope"]
    performance_metrics_repeat_index = summary.get("performance_metrics_repeat_index", 1)
    performance_metric_record_count = summary.get(
        "performance_metric_record_count",
        sum(int(item.get("sample_count", 0)) for item in summary["group_summaries"]),
    )
    stability_record_count = summary.get("stability_record_count", performance_metric_record_count)
    lines = [
        "# Reproduction Experiment Report",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Task file: `{summary['tasks_path']}`",
        f"- Task count: {summary['task_count']}",
        f"- Isolated task repetitions: {summary['repeat_count']}",
        (
            "- Coverage-based performance metrics and charts use isolated repeat "
            f"{performance_metrics_repeat_index} "
            f"({performance_metric_record_count} records); all "
            f"{stability_record_count} records are retained for repeated-run stability."
        ),
        f"- LLM mode: `{summary['real_mode']}`",
        f"- Environment file: `{summary['environment_file']}` (loaded: `{summary['environment_file_loaded']}`)",
        "",
        "## Experiment Groups",
        "",
        "| Group | Configured semantic mode | Effective semantic mode | Description | Executes actions | Feedback correction | Context memory |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    if not evaluation_scope["performance_claim_allowed"]:
        lines[8:8] = [
            "## Evaluation Scope Warning",
            "",
            (
                f"> This run executed {evaluation_scope['executed_task_count']}/"
                f"{evaluation_scope['source_task_count']} source tasks across "
                f"{evaluation_scope['executed_category_count']}/"
                f"{evaluation_scope['source_category_count']} categories "
                f"(`{evaluation_scope['claim_status']}`). The percentages below are case-level "
                "smoke-test diagnostics, not benchmark-wide performance estimates."
            ),
            "",
        ]
    provenance_lines = [
        (
            f"- `{mode}`: model `{provenance['model_id']}`, revision `{provenance['model_revision']}` "
            f"({provenance['model_revision_source']}), status `{provenance['provenance_status']}`, "
            f"runtime fingerprint `{provenance['semantic_runtime_fingerprint']}`."
        )
        for mode, provenance in summary["semantic_runtime_provenance"].items()
    ]
    lines[8:8] = [
        "## Semantic Runtime Provenance",
        "",
        *provenance_lines,
        "",
        "A result supports a version-specific local-Ollama semantic claim only when its effective mode is "
        "`real` and its provenance status is `versioned_real_model`. Mock results and unversioned real "
        "results remain reproducibility artifacts, not model-version performance evidence.",
        "",
    ]
    task_provenance = summary["task_suite_provenance"]
    lines[8:8] = [
        "## Task-suite Ground Truth",
        "",
        f"- Suite SHA-256: `{task_provenance['task_suite_sha256']}`",
        f"- Semantic-reference schema: `{task_provenance['semantic_ground_truth_schema_version']}`",
        (
            "- Control-goal labels: "
            f"{task_provenance['control_goal_annotated_task_count']}/{task_provenance['task_count']} "
            f"(complete: `{task_provenance['control_goal_annotation_complete']}`)."
        ),
        (
            "- Target-range labels: "
            f"{task_provenance['target_annotated_task_count']}/{task_provenance['task_count']} "
            f"(complete: `{task_provenance['target_annotation_complete']}`)."
        ),
        f"- Label-quality evidence status: `{task_provenance['label_quality_status']}`.",
        (
            "- Annotation protocol: "
            f"`{task_provenance['semantic_annotation_provenance']['protocol_version']}`; "
            f"reference type: `{task_provenance['semantic_annotation_provenance']['reference_type']}`."
            if task_provenance["semantic_annotation_provenance"]
            else "- Annotation protocol: `not_recorded`."
        ),
        (
            "- Independent review / inter-annotator agreement / ambiguity adjudication evidence: "
            f"`{task_provenance['semantic_annotation_provenance']['independent_review_evidence_status']}` / "
            f"`{task_provenance['semantic_annotation_provenance']['inter_annotator_agreement_evidence_status']}` / "
            f"`{task_provenance['semantic_annotation_provenance']['ambiguity_adjudication_evidence_status']}`."
            if task_provenance["semantic_annotation_provenance"]
            else "- Independent review / inter-annotator agreement / ambiguity adjudication evidence: `not_recorded`."
        ),
        "- A complete label count is not evidence of independent label validity; these statuses require auditable review material before label-quality claims.",
        "",
    ]
    for group in summary["groups"]:
        lines.append(
            f"| {group['display_name']} | `{group['llm_mode']}` | `{group['effective_llm_mode']}` | {group['description']} | "
            f"{yes_no(group['execute_actions'])} | {yes_no(group['enable_feedback_correction'])} | "
            f"{yes_no(group['enable_context_memory'])} |"
        )

    lines.extend(
        [
            "",
            "## Overall Metrics (primary isolated repeat)",
            "",
            "| Group | Runtime success % | Completion % | Intent accuracy % | Room accuracy % | Scope accuracy % | Control-goal accuracy % | Target exact match % | Target range IoU % | Device exact match % | Device F1 % | Avg corrections | Avg response ms | Energy saving % | Occupied comfort | Comfort retention % |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summary["group_summaries"]:
        lines.append(
            f"| {item['group_name']} | {item['success_rate_percent']:.2f} | "
            f"{format_metric(item['task_completion_rate_percent'])} | {format_metric(item['intent_accuracy_percent'])} | "
            f"{format_metric(item['room_accuracy_percent'])} | {format_metric(item['scope_accuracy_percent'])} | "
            f"{format_metric(item['control_goal_accuracy_percent'])} | {format_metric(item['target_exact_match_percent'])} | "
            f"{format_metric(item['target_range_iou_percent'])} | {item['device_selection_accuracy_percent']:.2f} | "
            f"{item['device_selection_f1_percent']:.2f} | "
            f"{item['average_correction_round']:.2f} | {item['average_response_time_ms']:.2f} | "
            f"{format_metric(item['average_energy_saving_rate_percent'])} | {format_metric(item['average_occupied_comfort_score'])} | "
            f"{format_metric(item['comfort_retention_rate_percent'])} |"
        )

    lines.extend(
        [
            "",
            "## Category Metrics (primary isolated repeat)",
            "",
            "| Group | Category | Samples | Runtime success % | Completion % | Intent accuracy % | Room accuracy % | Scope accuracy % | Control-goal accuracy % | Target exact match % | Target range IoU % | Device exact match % | Device F1 % |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summary["category_summaries"]:
        lines.append(
            f"| {item['group_name']} | {item['category']} | {item['sample_count']} | "
            f"{format_metric(item['task_completion_rate_percent'])} | {format_metric(item['intent_accuracy_percent'])} | "
            f"{format_metric(item['room_accuracy_percent'])} | {format_metric(item['scope_accuracy_percent'])} | "
            f"{format_metric(item['control_goal_accuracy_percent'])} | "
            f"{format_metric(item['target_exact_match_percent'])} | {format_metric(item['target_range_iou_percent'])} | "
            f"{item['device_selection_accuracy_percent']:.2f} | {item['device_selection_f1_percent']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Repeated-run Stability",
            "",
            "| Group | Repeat count | Task units | Invalid repeat-index task IDs | Runtime fingerprints | Semantic output exact stability % | Executable plan exact stability % | Invalid runtime fingerprint task IDs | Missing semantic fingerprint task IDs | Invalid semantic fingerprint task IDs | Missing plan fingerprint task IDs | Invalid plan fingerprint task IDs | Failed run task IDs | Status | Unstable task IDs |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|---|---|",
        ]
    )
    for item in summary["repeat_stability"]:
        lines.append(
            f"| {item['group_name']} | {item['requested_repeat_count']} | "
            f"{item['task_repeat_unit_count']} | {', '.join(item['invalid_repeat_index_task_ids']) or 'none'} | "
            f"{item['semantic_runtime_fingerprint_count']} | "
            f"{format_metric(item['semantic_output_exact_stability_percent'])} | "
            f"{format_metric(item['plan_action_exact_stability_percent'])} | "
            f"{', '.join(item['invalid_semantic_runtime_fingerprint_task_ids']) or 'none'} | "
            f"{', '.join(item['missing_semantic_output_fingerprint_task_ids']) or 'none'} | "
            f"{', '.join(item['invalid_semantic_output_fingerprint_task_ids']) or 'none'} | "
            f"{', '.join(item['missing_plan_action_fingerprint_task_ids']) or 'none'} | "
            f"{', '.join(item['invalid_plan_action_fingerprint_task_ids']) or 'none'} | "
            f"{', '.join(item['failed_run_task_ids']) or 'none'} | "
            f"`{item['stability_status']}` | "
            f"{', '.join(item['unstable_task_ids']) or 'none'} |"
        )

    lines.extend(["", "## Failure Counts", ""])
    for item in summary["group_summaries"]:
        counts = ", ".join(f"{key}: {value}" for key, value in sorted(item["failure_counts"].items()))
        lines.append(f"- {item['group_name']}: {counts or 'none'}")

    output_paths = summary.get("output_paths")
    if output_paths:
        lines.extend(
            [
                "",
                "## Output Files",
                "",
                f"- Records CSV: `{output_paths['records_csv']}`",
                f"- Summary JSON: `{output_paths['summary_json']}`",
                f"- Chart data JSON: `{output_paths['chart_data_json']}`",
                f"- Chart CSV directory: `{output_paths['chart_csv_dir']}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Metric Notes",
            "",
            "- Runtime success means every required pre-context command and the main runner command returned without a runtime or execution error. It is not semantic correctness or task completion; inspect the separate semantic and completion metrics before making task-success claims.",
            "- Completion rate is calculated for groups that execute virtual device actions.",
            "- Device exact match requires planned and expected device-category sets to be identical. Per-record true/false-positive and false-negative counts plus precision, recall and F1 make every mismatch traceable; extra planned devices are failures rather than free additions.",
            "- Control-goal accuracy compares the manually annotated `turn_on`, `turn_off`, or `set_target` intent direction for each task. It is reported separately because matching an intent/device while reversing its action direction is not semantically correct for safe execution.",
            "- Target exact match compares the full annotated target-key set and numeric range endpoints. Target range IoU is the mean interval intersection-over-union across the union of target keys; it describes partial overlap but does not count as a correct semantic interpretation.",
            "- Occupied comfort is calculated for rooms with active occupancy.",
            "- Metrics shown as `N/A` are not applicable to that ablation. In particular, planning-only groups do not execute actions and must not be compared on completion, energy, or comfort outcomes.",
            "- `--real-mode mock` is intended for local smoke tests without external LLM calls; groups marked `semantic=mock` are not evidence for real or local-Ollama semantic performance.",
            "- A real benchmark should use the same explicit `--env-file` as the target deployment; mismatched runtime fingerprints are non-comparable semantic runs.",
            "- Repeated-run stability compares isolated repetitions of the same fixed task only when every task covers each requested repeat index exactly once, every included record succeeded, and semantic-runtime, semantic-output, and executable-plan fingerprints are canonical SHA-256 digests with one shared runtime value. Duplicate/missing repeat indices, failed runs, missing or invalid fingerprints, or a changed model, decoding configuration, endpoint, or semantic adapter causes the stability result to be withheld. Repetitions after the preregistered primary run are excluded from coverage-based performance metrics, category sample counts, and charts; they are not independent task coverage, accuracy estimates, or evidence of concurrent-service stability.",
            "- Evaluation scope metadata states whether aggregate percentages are limited smoke-test diagnostics; even a complete fixed suite remains descriptive simulated evidence, not a population or real-home estimate.",
        ]
    )
    return "\n".join(lines)

def group_to_dict(group: ExperimentGroup, real_mode: str) -> dict[str, Any]:
    effective_llm_mode = effective_llm_mode_for_group(group, real_mode)
    return {
        "group_id": group.group_id,
        "name": group.name,
        "display_name": display_group_name(group, effective_llm_mode),
        "description": group.description,
        "runner_kind": group.runner_kind,
        "llm_mode": group.llm_mode,
        "effective_llm_mode": effective_llm_mode,
        "execute_actions": group.execute_actions,
        "enable_feedback_correction": group.enable_feedback_correction,
        "enable_context_memory": group.enable_context_memory,
        "semantic_applicable": group.semantic_applicable,
        "completion_applicable": group.completion_applicable,
    }


def yes_no(value: bool) -> str:
    return "是" if value else "否"


def format_metric(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
