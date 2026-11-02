from copy import deepcopy

from app.experiments.decision_demos import build_demo_bundle, verify_demo
from app.experiments.episode_benchmark import fingerprint


def test_three_saved_demos_are_replayable_observed_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    bundle = build_demo_bundle(tmp_path)
    assert {example['id'] for example in bundle['examples']} == {'stale-snapshot', 'confirmed-feedback', 'conflicting-knowledge'}
    assert all(example['verification']['passed'] for example in bundle['examples'])
    memory = next(example for example in bundle['examples'] if example['id'] == 'confirmed-feedback')
    assert [event['details']['confirmed_after'] for event in memory['trace']['events'] if event['stage'] == 'user_feedback'] == [False, False, True]
    stale = next(example for example in bundle['examples'] if example['id'] == 'stale-snapshot')
    assert any(event['details'].get('status') == 'stale_snapshot_replan_required' for event in stale['trace']['events'])


def test_replay_detects_tampered_device_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    example = deepcopy(build_demo_bundle(tmp_path)['examples'][-1])
    event = next(event for event in example['trace']['events'] if event['stage'] == 'execution_agent')
    event['after_state']['devices'][0]['is_on'] = not event['after_state']['devices'][0]['is_on']
    assert verify_demo(example)['passed'] is False


def test_replay_rejects_changed_hash_and_truncated_event_chain(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    original = build_demo_bundle(tmp_path)['examples'][-1]
    invalid_hash = deepcopy(original)
    invalid_hash['trace_sha256'] = 'bogus'
    assert verify_demo(invalid_hash)['passed'] is False
    truncated = deepcopy(original)
    truncated['trace']['events'] = [event for event in truncated['trace']['events'] if event['stage'] == 'execution_agent']
    truncated['trace_sha256'] = fingerprint(truncated['trace'])
    assert verify_demo(truncated)['passed'] is False
