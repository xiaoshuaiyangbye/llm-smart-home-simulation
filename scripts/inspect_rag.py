import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.rag import RagDocumentStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the local RAG index.")
    parser.add_argument("query", nargs="?", default="comfort energy safety standards")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--reindex", action="store_true")
    args = parser.parse_args()

    store = RagDocumentStore(PROJECT_ROOT)
    if args.reindex:
        print(json.dumps(store.reindex(), ensure_ascii=False, indent=2))
    result = store.query(args.query, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
