"""Generate and independently replay three saved simulation demonstrations."""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.agents.decision_trace import DecisionTrace
from app.agents.execution_agent import ExecutionAgent
from app.experiments.episode_benchmark import (
    build_episodes, evaluation_profile, fingerprint, isolated_rag, make_environment,
    run_episode, semantic_mode, source_provenance,
)
from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.research import UserFeedbackRequest
from app.runtime.snapshot_commit import evaluate_snapshot_commit
from app.schemas.state_schema import SmartHomeState
from app.schemas.task_schema import AgentCommandRequest
from app.simulation.environment import SmartHomeEnvironment


def _state_value(state: dict) -> dict:
    # Wall-clock observation metadata is not a device/physics replay outcome.
    return {key: state[key] for key in ('devices', 'rooms', 'energy_metrics', 'comfort_metrics', 'current_time_step')}


def verify_demo(example: dict) -> dict:
    checks = []
    try:
        if example['trace']['schema_version'] != 'decision_trace_v1':
            raise ValueError('Unsupported trace schema')
        if example.get('trace_sha256') != fingerprint(example['trace']):
            raise ValueError('Saved trace digest mismatch')
        events = example['trace']['events']
        stages = [event['stage'] for event in events]
        required = {
            'stale-snapshot': ['planning_agent', 'state_changed', 'commit_guard'],
            'confirmed-feedback': ['user_feedback'] * 3 + ['planning_agent', 'collaboration_agent', 'safety_agent', 'critic_agent', 'execution_agent', 'outcome'],
            'conflicting-knowledge': ['knowledge_agent', 'planning_agent', 'collaboration_agent', 'safety_agent', 'critic_agent', 'execution_agent', 'outcome'],
        }[example['id']]
        cursor = iter(stages)
        if not all(stage in cursor for stage in required):
            raise ValueError('Required demonstration stages missing or reordered')
        if len({event['event_id'] for event in events}) != len(events):
            raise ValueError('Duplicate event ids')
        if example['id'] != 'stale-snapshot':
            outcome = events[-1]
            if outcome['stage'] != 'outcome' or outcome['details']['correction_rounds'] != stages.count('feedback_correction'):
                raise ValueError('Incomplete correction chain')
        checks.append({'type': 'digest_and_required_event_integrity', 'passed': True})
        service = evaluation_profile()
        previous_execution_state = None
        for event in events:
            if event['stage'] in {'execution_agent', 'feedback_correction'}:
                if previous_execution_state is not None and _state_value(event['before_state']) != _state_value(previous_execution_state):
                    raise ValueError('Discontinuous execution state chain')
                environment = SmartHomeEnvironment(SmartHomeState.model_validate(event['before_state']))
                ExecutionAgent().execute({'plan_id': 'saved-replay', 'actions': event['after_actions']}, environment)
                actual = environment.get_state(refresh_realtime=False).model_dump(mode='json')
                checks.append({'event_id': event['event_id'], 'type': 'device_and_physics_replay',
                               'passed': _state_value(actual) == _state_value(event['after_state'])})
                previous_execution_state = event['after_state']
            elif event['stage'] == 'commit_guard':
                result = asdict(evaluate_snapshot_commit(**event['details']['guard_inputs']))
                checks.append({'event_id': event['event_id'], 'type': 'snapshot_guard_replay',
                               'passed': result == event['details']['guard_result'] and not result['allowed'] and not event['after_actions']})
            elif event['stage'] == 'user_feedback':
                details = event['details']
                service.record_reflection(**details['reflection_input'])
                service.apply_feedback(UserFeedbackRequest(**details['feedback_input']))
                observed = service.personalize_semantic_result(details['semantic_input'])['user_preference_context']['confirmed_experience']
                checks.append({'event_id': event['event_id'], 'type': 'explicit_feedback_gate_replay',
                               'passed': bool(observed) == details['confirmed_after']})
    except (KeyError, TypeError, ValueError) as exc:
        checks.append({'type': 'invalid_saved_trace', 'passed': False, 'error': str(exc)})
    return {'passed': bool(checks) and all(check['passed'] for check in checks), 'checks': checks,
            'boundary': 'Digest consistency, required event structure and software replay of saved inputs; self-consistency is not authenticated provenance, independent labels or real-device validation.'}


def _stale_demo(work_dir: Path) -> dict:
    episode = build_episodes('smoke')[0]
    environment = make_environment(episode)
    before = environment.get_state(refresh_realtime=False).model_copy(deep=True)
    revision = environment.revision
    planning = TaskRunner(SmartHomeEnvironment(before), ExperimentLogger(work_dir / 'logs'), execute_actions=False,
                          log_task_results=False, rag_store=isolated_rag(work_dir, 'correct_rag'))
    response = planning.run_agent_command(AgentCommandRequest(user_command=episode['command'], current_room_id=episode['room']))
    if not response.success:
        raise RuntimeError(response.error)
    actions = response.plan_result['actions']
    environment.set_away()
    after = environment.get_state(refresh_realtime=False)
    inputs = {'snapshot_revision': revision, 'current_revision': environment.revision,
              'snapshot_preference_fingerprint': 'fixed-profile', 'current_preference_fingerprint': 'fixed-profile',
              'commit_id': 'saved-stale-demo', 'committed_action_ids': []}
    guard = asdict(evaluate_snapshot_commit(**inputs))
    trace = DecisionTrace('mock')
    trace.record('planning_agent', after_actions=actions, details={'command': episode['command']})
    trace.record('state_changed', before_state=before, after_state=after,
                 details={'message': '隔离仿真在计划生成后调用 set_away；环境版本已变化。'})
    trace.record('commit_guard', before_actions=actions, after_actions=[], before_state=after, after_state=after,
                 details={'guard_inputs': inputs, 'guard_result': guard, 'status': guard['status'],
                          'message': '提交门禁拒绝过期计划；本记录在拒绝处结束，未伪造重新规划或执行。'})
    return {'id': 'stale-snapshot', 'title': '计划生成后，住户离开了房间',
            'description': '真实隔离仿真状态变化与提交门禁。旧计划被拒绝，此保存记录未执行重规划。', 'trace': trace.snapshot()}


def _feedback_demo(work_dir: Path) -> dict:
    episode = next(task for task in build_episodes('smoke') if task['stratum'] == 'longitudinal_personalization_transfer')
    preferences = evaluation_profile()
    trace = DecisionTrace('mock')
    for index in range(3):
        runner = TaskRunner(make_environment(episode), ExperimentLogger(work_dir / 'logs'),
                            rag_store=isolated_rag(work_dir, 'correct_rag'), log_task_results=False)
        response = runner.run_agent_command(AgentCommandRequest(user_command=episode['command'], current_room_id=episode['room']), preference_service=preferences)
        if not response.success:
            raise RuntimeError(response.error)
        raw = response.semantic_result
        semantic = {key: raw[key] for key in ('intent', 'room', 'targets', 'control_goal')}
        before = preferences.personalize_semantic_result(semantic)['user_preference_context']['confirmed_experience']
        reflection = {'trigger': 'saved_demo_scripted_feedback', 'user_command': episode['command'],
                      'semantic_result': semantic, 'plan_result': {'actions': response.plan_result['actions']},
                      'execution_result': {'executed_count': response.execution_result['executed_count']},
                      'feedback_result': {'completed': response.feedback_result['completed'], 'correction_round': response.feedback_result['correction_round']}}
        feedback = {'satisfaction': 5, 'desired_illuminance_lux': 650, 'note': 'Scripted demo feedback, not a real resident.'}
        preferences.record_reflection(**reflection)
        preferences.apply_feedback(UserFeedbackRequest(**feedback))
        after = preferences.personalize_semantic_result(semantic)['user_preference_context']['confirmed_experience']
        trace.record('user_feedback', details={'turn': index + 1, 'confirmed_before': bool(before), 'confirmed_after': bool(after),
                                              'reflection_input': reflection, 'feedback_input': feedback, 'semantic_input': semantic,
                                              'message': f'第 {index + 1} 次显式反馈；确认经验' + ('已可见' if after else '仍不可见')})
    runner = TaskRunner(make_environment(episode), ExperimentLogger(work_dir / 'logs'),
                        rag_store=isolated_rag(work_dir, 'correct_rag'), log_task_results=False)
    response = runner.run_agent_command(AgentCommandRequest(user_command=episode['command'], current_room_id=episode['room']), preference_service=preferences)
    for event in response.plan_result['decision_trace']['events']:
        trace.record(event['stage'], before_actions=event['before_actions'], after_actions=event['after_actions'],
                     before_state=event['before_state'], after_state=event['after_state'], duration_ms=event['duration_ms'], details=event['details'])
    return {'id': 'confirmed-feedback', 'title': '第三次明确反馈后，经验获得确认',
            'description': '脚本化反馈调用实际记忆门禁。参数调整来自显式偏好反馈；确认经验仅作为上下文可见，不主张其单独改善了控制效果。',
            'trace': trace.snapshot()}


def _knowledge_demo(work_dir: Path) -> dict:
    episode = next(task for task in build_episodes('smoke') if task.get('fault', {}).get('type') == 'unsafe_ac_overcooling')
    episode['rag_condition'] = 'conflicting_rag'
    row = run_episode(episode, 'full', 7, work_dir=work_dir)
    if not row['runtime_success']:
        raise RuntimeError(row['error'])
    trace = DecisionTrace('mock')
    knowledge = row['trace']['blackboard']['agent_outputs']['knowledge_agent']
    trace.record('knowledge_agent', details={'used_sources': knowledge['used_sources'], 'rag_context': knowledge['rag_context'],
                                           'message': '隔离词法检索返回包含冲突文本的来源。危险动作由另行标注的实验故障注入。'})
    for event in row['trace']['response']['plan_result']['decision_trace']['events']:
        trace.record(event['stage'], before_actions=event['before_actions'], after_actions=event['after_actions'],
                     before_state=event['before_state'], after_state=event['after_state'], duration_ms=event['duration_ms'], details=event['details'])
    return {'id': 'conflicting-knowledge', 'title': '检查冲突知识与过度制冷候选动作',
            'description': '隔离冲突知识检索，加上命名规划故障，用于展示安全修订。不是知识致错的因果实验，也不证明真实模型抗注入。',
            'trace': trace.snapshot()}


def build_demo_bundle(work_dir: Path) -> dict:
    with semantic_mode('mock'):
        examples = [_stale_demo(work_dir), _feedback_demo(work_dir), _knowledge_demo(work_dir)]
    provenance = source_provenance()
    for example in examples:
        example['provenance'] = {key: value for key, value in provenance.items() if key != 'source_manifest'}
        example['trace_sha256'] = fingerprint(example['trace'])
        example['verification'] = verify_demo(example)
        if not example['verification']['passed']:
            raise ValueError(f"Demo replay failed: {example['id']}: {example['verification']}")
    return {'schema_version': 'decision_demo_bundle_v1', 'generated_at': datetime.now(UTC).isoformat(),
            'examples': examples, 'source_manifest': provenance['source_manifest']}
