from copy import deepcopy

import pytest

from app.experiments.episode_benchmark import (
    METHODS,
    build_episodes,
    check_outcome,
    make_environment,
    run_episode,
    summarize_episodes,
)
from app.simulation.environment import SmartHomeEnvironment


def test_simulated_initial_clock_does_not_break_pairing(monkeypatch):
    import app.simulation.environment as module
    original = module.update_weather_environment
    ticks = iter(('2026-09-07T13:47+08:00', '2026-09-07T13:48+08:00'))
    def clock_changes(state):
        result = original(state)
        result.outdoor_environment.data_updated_at = next(ticks)
        return result
    monkeypatch.setattr(module, 'update_weather_environment', clock_changes)
    task = build_episodes('smoke')[0]
    a = make_environment(task).get_state(refresh_realtime=False)
    b = make_environment(task).get_state(refresh_realtime=False)
    assert a.model_dump() == b.model_dump()


def test_matrix_counts_do_not_confuse_base_scenarios_and_repeats():
    smoke = build_episodes('smoke')
    full = build_episodes('full')
    assert len(smoke) == 24
    assert len(full) == 600
    assert len({row['base_task_id'] for row in full}) == 24
    assert len({row['configuration_fingerprint'] for row in full}) == 600
    assert len({row['stratum'] for row in smoke}) == 8


def test_matched_methods_execute_real_pipeline_and_share_input(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    task = build_episodes('smoke')[0]
    records = [run_episode(task, method, 7, work_dir=tmp_path) for method in METHODS]
    assert len({row['initial_state_fingerprint'] for row in records}) == 1
    assert all(row['runtime_success'] for row in records)
    assert all(row['executed_action_count'] > 0 for row in records)
    assert all(row['request_latency_ms'] >= 0 for row in records)
    assert {row['semantic_mode_effective'] for row in records} == {'mock'}
    assert all(row['trace']['blackboard']['stages'] for row in records)
    assert all(row['post_control_horizon_kwh'] > 0 for row in records)
    assert all(row['final_state_success'] for row in records)
    assert len(summarize_episodes(records)['paired_comparisons']) == 3


def test_outcome_uses_state_predicates_not_runtime_or_self_report():
    state = SmartHomeEnvironment().get_state(refresh_realtime=False)
    checks = [{'entity_id': 'light.living_room_main', 'field': 'is_on', 'op': 'eq', 'value': True}]
    result = check_outcome(state, checks)
    assert result['success'] is False
    assert result['checks'][0]['actual'] is False
    with pytest.raises(ValueError):
        check_outcome(state, [])


def test_pairing_rejects_mismatched_or_duplicate_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    records = [run_episode(build_episodes('smoke')[0], method, 7, work_dir=tmp_path) for method in METHODS]
    changed = deepcopy(records)
    changed[-1]['initial_state_fingerprint'] = 'wrong'
    with pytest.raises(ValueError, match='pair'):
        summarize_episodes(changed)
    with pytest.raises(ValueError, match='duplicate'):
        summarize_episodes(records + [records[0]])


def test_confirmed_history_comes_from_completed_training_episodes(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    task = next(row for row in build_episodes('smoke') if row['stratum'] == 'longitudinal_personalization_transfer')
    full = run_episode(task, 'full', 7, work_dir=tmp_path)
    static = run_episode(task, 'personalized', 7, work_dir=tmp_path)
    assert len(full['trace']['training_episodes']) == 3
    assert full['confirmed_experience_visible'] is True
    assert static['confirmed_experience_visible'] is False
    assert full['initial_state_fingerprint'] == static['initial_state_fingerprint']
def test_explicit_activation_contracts_reject_off_devices():
    from app.experiments.episode_benchmark import build_episodes, check_outcome, make_environment

    for episode in build_episodes('smoke'):
        if episode['base_task_id'] in {'E1-003', 'E1-006', 'E1-009', 'E1-019', 'E1-020', 'E1-021'}:
            assert any(check.get('field') == 'is_on' and check.get('value') is True for check in episode['checks'])
            assert not check_outcome(make_environment(episode).get_state(refresh_realtime=False), episode['checks'])['success']
