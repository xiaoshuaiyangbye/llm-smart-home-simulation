"""Evaluate retrieval against a small, versioned regression set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.rag import RagDocumentStore
DEFAULT_CASES_PATH = PROJECT_ROOT / "data" / "evaluation" / "rag_evaluation.json"


def evaluate(cases_path: Path = DEFAULT_CASES_PATH) -> dict[str, object]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    store = RagDocumentStore(project_root=PROJECT_ROOT)
    results: list[dict[str, object]] = []
    for case in cases:
        result = store.query(str(case["query"]), top_k=3)
        expected = str(case["expected_source_contains"])
        sources = [str(match["source"]) for match in result["matches"]]
        results.append({"query": case["query"], "passed": any(expected in source for source in sources), "sources": sources})
    passed = sum(1 for item in results if item["passed"])
    return {"passed": passed, "total": len(results), "recall_at_3": passed / len(results) if results else 0.0, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-recall", type=float, default=1.0)
    args = parser.parse_args()
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["recall_at_3"] >= args.min_recall else 1


if __name__ == "__main__":
    raise SystemExit(main())
