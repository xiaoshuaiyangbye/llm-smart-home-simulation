"""Versioned E1 evaluation with control included in a fixed 30-minute horizon."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.experiments.episode_benchmark import (  # noqa: E402
    METHODS, SPEC_PATH, TASKS_PATH, build_episodes, run_episode, source_provenance,
)

MODE = 'integrated_total_30m_v1'


def summarize(records):
    if not records:
        raise ValueError('No records')
    groups = defaultdict(list)
    for row in records:
        if row['accounting_mode'] != MODE or row['total_episode_minutes'] != 30:
            raise ValueError('Invalid accounting mode or total horizon')
        groups[(row['task_id'], row['repeat_seed'])].append(row)
    invariant = ('configuration_fingerprint', 'initial_state_fingerprint', 'disturbance_seed',
                 'condition', 'semantic_mode_effective', 'semantic_runtime_fingerprint',
                 'task_suite_sha256', 'runner_source_sha256', 'dependency_source_sha256',
                 'spec_sha256', 'accounting_mode', 'total_episode_minutes')
    for key, group in groups.items():
        if len(group) != len(METHODS) or {r['method'] for r in group} != set(METHODS):
            raise ValueError(f'Duplicate or incomplete method pairing: {key}')
        for field in invariant:
            if len({json.dumps(r[field], sort_keys=True) for r in group}) != 1:
                raise ValueError(f'Unmatched {field} for {key}')
    metrics = ('runtime_success', 'final_state_success', 'whole_episode_energy_kwh',
               'occupied_room_comfort_score', 'request_latency_ms', 'control_stage_minutes')
    return {'schema_version': 'integrated_e1_summary_v1', 'accounting_mode': MODE,
            'record_count': len(records), 'paired_units': len(groups),
            'base_scenario_count': len({r['base_task_id'] for r in records}),
            'configuration_count': len({r['task_id'] for r in records}),
            'effective_semantic_modes': sorted({r['semantic_mode_effective'] for r in records}),
            'methods': {m: {f: mean(r[f] for r in records if r['method'] == m) for f in metrics} for m in METHODS},
            'base_scenario_results': {
                base: {m: {f: mean(r[f] for r in records if r['base_task_id'] == base and r['method'] == m)
                           for f in metrics} for m in METHODS} for base in sorted({r['base_task_id'] for r in records})},
            'inference': 'Descriptive fixed-development-scenario results only; no population significance claim.',
            'evidence_boundary': records[0]['evidence_boundary']}


def run(matrix, output):
    output.mkdir(parents=True, exist_ok=False)
    episodes = build_episodes(matrix)
    seeds = [7] if matrix == 'smoke' else [7, 19, 31]
    provenance = source_provenance()
    provenance['source_manifest'][str(Path(__file__).relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    protocol = {'schema_version': 'integrated_e1_protocol_v1', 'accounting_mode': MODE,
                'matrix': matrix, 'methods': METHODS, 'repeat_seeds': seeds,
                'semantic_mode': 'mock', 'total_episode_minutes': 30,
                'training_accounting': 'legacy isolated scripted setup; outside evaluation horizon',
                'initial_preparation': 'legacy frozen fixture; physical evaluation begins at before_state',
                'integration_step_minutes': 1, 'refresh_realtime': False,
                'legacy_weighted_utility': 'not_applicable', 'post_control_horizon_kwh': 'not_applicable',
                'independent_units': '24 developer base scenarios; configurations/seeds are repeated conditions',
                **provenance}
    (output / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'episodes.json').write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'frozen_spec.json').write_bytes(SPEC_PATH.read_bytes())
    (output / 'frozen_tasks.json').write_bytes(TASKS_PATH.read_bytes())
    with zipfile.ZipFile(output / 'frozen_sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in protocol['source_manifest']:
            archive.write(ROOT / name, arcname=name)
    records = []
    with (output / 'records.jsonl').open('x', encoding='utf-8') as raw, gzip.open(output / 'traces.jsonl.gz', 'xt', encoding='utf-8') as traces:
        for i, episode in enumerate(episodes):
            for seed in seeds:
                for method in METHODS:
                    row = run_episode(episode, method, seed, work_dir=output / 'isolated', accounting_mode=MODE)
                    trace = row.pop('trace')
                    traces.write(json.dumps({'task_id': row['task_id'], 'method': method, 'repeat_seed': seed, **trace}, ensure_ascii=False) + '\n')
                    raw.write(json.dumps(row, ensure_ascii=False) + '\n')
                    records.append(row)
            if (i + 1) % 25 == 0:
                print(json.dumps({'configurations': i + 1, 'records': len(records)}), flush=True)
    summary = summarize(records)
    summary['matrix'] = matrix
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 固定总30分钟积分核算E1', '', summary['evidence_boundary'], '',
             '| 方法 | 状态契约通过率 | 全程积分能耗 kWh | 舒适分 | 控制分钟 |',
             '| --- | ---: | ---: | ---: | ---: |']
    for m, v in summary['methods'].items():
        lines.append(f"| {m} | {v['final_state_success']:.3f} | {v['whole_episode_energy_kwh']:.6f} | {v['occupied_room_comfort_score']:.3f} | {v['control_stage_minutes']:.3f} |")
    lines += ['', '本表仅比较同一冻结积分协议下的方法；不得与旧协议结果相减后解释为修复带来的因果收益。']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', choices=['smoke', 'full'], default='smoke')
    args = parser.parse_args()
    output = ROOT / 'data/results/integrated_e1' / datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
    result = run(args.matrix, output)
    print(json.dumps({'output_dir': str(output), 'record_count': result['record_count'], 'methods': result['methods']}))
