"""Remove one review role at a time from actual TaskRunner episodes."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.experiments.episode_benchmark import BOUNDARY, SIMULATOR_ACCOUNTING, build_episodes, fingerprint, run_episode, source_provenance

VARIANTS = {'full': {}, 'without_safety': {'enable_safety_review': False},
            'without_critic': {'enable_critic_review': False}, 'without_feedback': {'enable_feedback_correction': False}}


def role_probe() -> dict:
    task = build_episodes('smoke')[0]
    task.update(base_task_id='ROLE-CRITIC-001', task_id='ROLE-CRITIC-001', stratum='named_critic_conflict_probe',
                command='客厅节能模式', expected_intent='energy_saving_mode',
                checks=[{'entity_id': 'window.living_room_main', 'field': 'opening_pct', 'op': 'lte', 'value': 10}],
                fault={'id': 'ROLE-CRITIC-001', 'type': 'cooling_window_conflict', 'room': 'living_room'})
    task['configuration_fingerprint'] = fingerprint({key: value for key, value in task.items() if key != 'configuration_fingerprint'})
    return task


def run_contributions(output: Path, seeds: tuple[int, ...] = (7, 19, 31)) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    tasks = [*build_episodes('smoke'), role_probe()]
    records, pairs = [], defaultdict(dict)
    with (output / 'records.jsonl').open('x', encoding='utf-8') as handle:
        for task in tasks:
            for seed in seeds:
                for variant, options in VARIANTS.items():
                    row = run_episode(task, 'full', seed, work_dir=output / 'isolated', role_options=options)
                    trace = row.pop('trace')
                    row.update(role_variant=variant, role_options=options,
                               decision_trace=trace['response']['plan_result'].get('decision_trace'))
                    handle.write(json.dumps(row, ensure_ascii=False) + '\n')
                    records.append(row)
                    pairs[(task['task_id'], seed)][variant] = row
    for pair in pairs.values():
        if len({row['initial_state_fingerprint'] for row in pair.values()}) != 1:
            raise ValueError('Role-ablation initial-state pairing mismatch')
    metrics = ('final_state_success', 'post_control_horizon_kwh', 'occupied_room_comfort_score', 'request_latency_ms')
    effects = {}
    for variant in VARIANTS.keys() - {'full'}:
        effects[variant] = {}
        for scope in ('base_suite', 'named_critic_conflict_probe'):
            subset = [pair for pair in pairs.values() if (pair['full']['stratum'] == 'named_critic_conflict_probe') == (scope == 'named_critic_conflict_probe')]
            effects[variant][scope] = {'paired_runs': len(subset), 'full_minus_removed':
                {metric: mean(float(pair['full'][metric]) - float(pair[variant][metric]) for pair in subset) for metric in metrics}}
    summary = {'schema_version': 'e1_role_contribution_v1', 'record_count': len(records), 'base_scenario_count': 24,
               'additional_named_probe_count': 1, 'repeat_count': len(seeds), 'effects': effects,
               'role_intervention_counts': {role: sum(row['role_variant'] == 'full' and bool(row[field]) for row in records)
                    for role, field in [('safety', 'safety_action_changed'), ('critic', 'critic_action_changed'), ('feedback', 'feedback_correction_applied')]},
               'provenance': source_provenance(),
               'simulator_accounting': SIMULATOR_ACCOUNTING,
               'outcome_metric_definition': 'developer_state_contract_pass_not_complete_intent',
               'boundary': BOUNDARY + ' Named critic fault is reported separately. Removal effects do not imply natural error prevalence or universal role benefit.'}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    out = args.output_dir or ROOT / 'data/results/e1_role_contribution' / datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
    result = run_contributions(out)
    print(json.dumps({'output_dir': str(out), 'record_count': result['record_count'], 'effects': result['effects']}, ensure_ascii=False))
