"""Run the bounded quality-improvement loop and persist evidence for the next pass.

This script deliberately never edits source, commits, deploys, or deletes data. It
collects evidence, applies deterministic acceptance rules, and leaves the next
change decision to a reviewed engineering task.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "results" / "quality" / "latest.json"


def run(command: list[str], cwd: Path) -> dict[str, object]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": (completed.stdout or "")[-4_000:],
        "stderr": (completed.stderr or "")[-4_000:],
    }


def main() -> int:
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    checks = {
        "backend_lint": run([sys.executable, "-m", "ruff", "check", "app", "tests"], PROJECT_ROOT / "backend"),
        "scripts_lint": run([sys.executable, "-m", "ruff", "check", "scripts"], PROJECT_ROOT),
        "backend_tests": run([sys.executable, "-m", "pytest", "-q"], PROJECT_ROOT / "backend"),
        "thesis_claim_chain": run([sys.executable, "../scripts/validate_thesis_claims.py"], PROJECT_ROOT / "backend"),
        "rag_evaluation": run([sys.executable, "../scripts/evaluate_rag.py", "--min-recall", "1.0"], PROJECT_ROOT / "backend"),
        "frontend_tests": run([npm, "test"], PROJECT_ROOT / "frontend"),
        "frontend_build": run([npm, "run", "build"], PROJECT_ROOT / "frontend"),
    }
    failures = [name for name, result in checks.items() if result["exit_code"] != 0]
    recommendations: list[str] = []
    frontend_output = f"{checks['frontend_build']['stdout']}\n{checks['frontend_build']['stderr']}"
    entry_chunk = re.search(r"dist/assets/index-[^\s]+\.js\s+([\d,.]+) kB", frontend_output)
    if entry_chunk and float(entry_chunk.group(1).replace(",", "")) > 500:
        recommendations.append("Split the first-screen JavaScript entry before adding new first-screen features.")
    if failures:
        recommendations.append("Do not merge or deploy until every failed verification check is green.")
    if not recommendations:
        recommendations.append("No deterministic quality regression detected; review the persisted backlog before selecting new work.")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failures else "failed",
        "failed_checks": failures,
        "checks": checks,
        "recommendations": recommendations,
        "stop_rule": "Stop after collecting evidence. Source changes, deployment, and backlog reprioritization require human-reviewed follow-up.",
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "failed_checks", "recommendations")}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
