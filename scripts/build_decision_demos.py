"""Build source-backed, replay-checked static decision demonstrations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.experiments.decision_demos import build_demo_bundle, verify_demo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'frontend/public/decision-demos/evidence.json')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        bundle = json.loads(args.verify.read_text(encoding='utf-8'))
        results = {example['id']: verify_demo(example) for example in bundle['examples']}
        print(json.dumps(results, ensure_ascii=False))
        return 0 if all(item['passed'] for item in results.values()) else 1
    bundle = build_demo_bundle(ROOT / 'output/decision-demo-build')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(args.output), 'examples': len(bundle['examples']),
                      'replay_checks': {example['id']: len(example['verification']['checks']) for example in bundle['examples']}}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
