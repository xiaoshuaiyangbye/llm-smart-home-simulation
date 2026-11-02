"""Run matched, isolated end-to-end smart-home simulation episodes."""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.experiments.episode_benchmark import METHODS, SPEC_PATH, TASKS_PATH, build_episodes, run_episode, source_provenance, summarize_episodes


def run_benchmark(matrix: str, output_dir: Path, mode: str = 'mock') -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    episodes = build_episodes(matrix)
    seeds = (7,) if matrix == 'smoke' else (7, 19, 31)
    records = []
    protocol = {'schema_version': 'e1_episode_protocol_v1', 'generated_at': datetime.now(UTC).isoformat(),
                'matrix': matrix, 'semantic_mode': mode, 'methods': METHODS, 'seeds': seeds,
                'configuration_episode_count': len(episodes), 'target_record_count': len(episodes) * len(seeds) * len(METHODS),
                'base_scenario_count': len({episode['base_task_id'] for episode in episodes}),
                'statistical_analysis': 'Descriptive base-scenario cluster bootstrap; no significance claim.',
                **source_provenance()}
    (output_dir / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'episodes.json').write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'frozen_spec.json').write_bytes(SPEC_PATH.read_bytes())
    (output_dir / 'frozen_tasks.json').write_bytes(TASKS_PATH.read_bytes())
    with (output_dir / 'records.jsonl').open('x', encoding='utf-8') as record_file, gzip.open(output_dir / 'traces.jsonl.gz', 'xt', encoding='utf-8') as trace_file:
        for index, episode in enumerate(episodes):
            for seed in seeds:
                for method in METHODS:
                    record = run_episode(episode, method, seed, work_dir=output_dir / 'isolated', mode=mode)
                    trace = record.pop('trace')
                    trace_file.write(json.dumps({'task_id': record['task_id'], 'method': method, 'repeat_seed': seed, **trace}, ensure_ascii=False) + '\n')
                    record_file.write(json.dumps(record, ensure_ascii=False) + '\n')
                    records.append(record)
            if (index + 1) % 25 == 0:
                print(json.dumps({'completed_configurations': index + 1, 'records': len(records)}), flush=True)
    summary = summarize_episodes(records)
    summary['matrix'] = matrix
    (output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# E1 端到端软件仿真实验', '', summary['evidence_boundary'], '',
             f"基础场景 {summary['base_scenario_count']}；配置 episode {summary['configuration_episode_count']}；记录 {len(records)}。", '',
             '| 方法 | 开发者状态契约通过率 | 平均请求毫秒 | 后置 30 分钟估计 kWh |', '| --- | --- | --- | --- |']
    for method, metrics in summary['methods'].items():
        lines.append(f"| {method} | {metrics['final_state_success']:.3f} | {metrics['request_latency_ms']:.3f} | {metrics['post_control_horizon_kwh']:.5f} |")
    lines.extend(['', '语义参考为开发者编写的未独立审查标签；重复与配置变体不是新增独立基础任务。',
                  '置信区间仅描述这批基础场景的变异；未主张 mixed-effects 显著性、真实住户或现场结论。'])
    (output_dir / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', choices=('smoke', 'full'), default='smoke')
    parser.add_argument('--semantic-mode', choices=('mock', 'real'), default='mock')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    out = args.output_dir or ROOT / 'data/results/e1_task_benchmark' / datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
    summary = run_benchmark(args.matrix, out, args.semantic_mode)
    print(json.dumps({'output_dir': str(out), 'record_count': summary['record_count'], 'methods': summary['methods']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
