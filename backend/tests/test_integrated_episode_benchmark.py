from pathlib import Path

import pytest

from app.experiments.episode_benchmark import build_episodes, run_episode


@pytest.mark.parametrize('method', ['single_agent', 'multi_agent_static', 'personalized', 'full'])
def test_integrated_episode_has_fixed_total_time_and_separate_metrics(tmp_path: Path, method):
    episode = build_episodes('smoke')[0]
    record = run_episode(episode, method, 7, work_dir=tmp_path,
                         accounting_mode='integrated_total_30m_v1')
    assert record['total_episode_minutes'] == 30
    assert record['control_stage_minutes'] + record['post_control_evaluation_minutes'] == 30
    assert record['whole_episode_energy_kwh'] > 0
    assert record['post_control_horizon_kwh'] is None
    assert record['weighted_utility'] is None
    assert record['simulator_accounting']['control_stage_energy_accounted']
    assert record['semantic_mode_effective'] == 'mock'
    before, after = record['trace']['before_state'], record['trace']['after_state']
    assert after['current_time_step'] - before['current_time_step'] == 30
    delta = after['energy_metrics']['cumulative_energy_kwh'] - before['energy_metrics']['cumulative_energy_kwh']
    assert record['whole_episode_energy_kwh'] == pytest.approx(delta)


def test_unknown_accounting_protocol_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='accounting'):
        run_episode(build_episodes('smoke')[0], 'full', 7, work_dir=tmp_path, accounting_mode='unknown')


def test_integrated_summary_rejects_unmatched_horizon_and_duplicate(tmp_path):
    import runpy
    from copy import deepcopy
    root = Path(__file__).resolve().parents[2]
    summarize = runpy.run_path(str(root / 'scripts/run_integrated_e1_benchmark.py'))['summarize']
    episode = build_episodes('smoke')[0]
    rows = [run_episode(episode, method, 7, work_dir=tmp_path,
                        accounting_mode='integrated_total_30m_v1')
            for method in ['single_agent', 'multi_agent_static', 'personalized', 'full']]
    assert summarize(rows)['paired_units'] == 1
    bad = deepcopy(rows)
    bad[-1]['total_episode_minutes'] = 35
    with pytest.raises(ValueError, match='horizon'):
        summarize(bad)
    with pytest.raises(ValueError, match='pairing'):
        summarize(rows + [deepcopy(rows[0])])
    bad = deepcopy(rows)
    bad[-1]['initial_state_fingerprint'] = 'different'
    with pytest.raises(ValueError, match='initial_state'):
        summarize(bad)
