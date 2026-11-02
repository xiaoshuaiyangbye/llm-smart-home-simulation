from app.agents.decision_trace import DecisionTrace
from app.experiments.episode_benchmark import build_episodes, run_episode


def test_trace_compares_executable_actions_and_keeps_snapshots():
    trace = DecisionTrace('mock')
    before = [{'entity_id': 'window.bedroom_main', 'action': 'set_opening', 'parameters': {'opening_pct': 100}, 'reason': 'candidate'}]
    after = [{'entity_id': 'window.bedroom_main', 'action': 'set_opening', 'parameters': {'opening_pct': 10}, 'reason': 'review'}]
    trace.record('safety_agent', before_actions=before, after_actions=after, duration_ms=.2)
    before[0]['parameters']['opening_pct'] = 0
    event = trace.snapshot()['events'][0]
    assert event['actions_changed'] is True
    assert event['before_actions'][0]['parameters']['opening_pct'] == 100
    trace.record('critic_agent', before_actions=after, after_actions=[{**after[0], 'reason': 'new wording'}])
    assert trace.snapshot()['events'][1]['actions_changed'] is False


def test_real_pipeline_records_safety_intervention_and_execution(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    task = next(row for row in build_episodes('smoke') if row['stratum'] == 'safety_fault_injection')
    row = run_episode(task, 'full', 7, work_dir=tmp_path)
    trace = row['trace']['response']['plan_result']['decision_trace']
    assert trace['schema_version'] == 'decision_trace_v1'
    safety = [event for event in trace['events'] if event['stage'] == 'safety_agent']
    assert any(event['actions_changed'] for event in safety)
    assert any(event['stage'] == 'execution_agent' and event['after_state'] for event in trace['events'])
    assert all(event['duration_ms'] >= 0 for event in trace['events'])


def test_ordinary_review_presence_is_not_an_intervention(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    row = run_episode(build_episodes('smoke')[0], 'full', 7, work_dir=tmp_path)
    events = row['trace']['response']['plan_result']['decision_trace']['events']
    assert all(not event['actions_changed'] for event in events if event['stage'] in {'safety_agent', 'critic_agent'})


def test_role_ablation_can_disable_safety_without_disabling_other_roles(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    task = next(row for row in build_episodes('smoke') if row['stratum'] == 'safety_fault_injection')
    row = run_episode(task, 'full', 7, work_dir=tmp_path, role_options={'enable_safety_review': False})
    assert row['safety_action_changed'] is False
    assert row['trace']['blackboard']['agent_outputs']['critic_agent']['enabled'] is True


def test_named_critic_probe_changes_executed_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    task = build_episodes('smoke')[0]
    task.update(command='客厅节能模式', fault={'id': 'test-critic', 'type': 'cooling_window_conflict'},
                checks=[{'entity_id': 'window.living_room_main', 'field': 'opening_pct', 'op': 'lte', 'value': 10}])
    full = run_episode(task, 'full', 7, work_dir=tmp_path)
    without = run_episode(task, 'full', 7, work_dir=tmp_path, role_options={'enable_critic_review': False})
    assert full['critic_action_changed'] is True
    assert without['critic_action_changed'] is False
    assert full['final_state_success'] is True
    assert without['final_state_success'] is False


def test_feedback_iterations_have_separate_action_state_events(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    task = next(row for row in build_episodes('smoke') if row['stratum'] == 'longitudinal_personalization_transfer')
    row = run_episode(task, 'single_agent', 7, work_dir=tmp_path)
    events = row['trace']['response']['plan_result']['decision_trace']['events']
    corrections = [event for event in events if event['stage'] == 'feedback_correction']
    assert row['feedback_correction_applied'] is True
    assert corrections and all(event['before_state'] and event['after_state'] for event in corrections)
