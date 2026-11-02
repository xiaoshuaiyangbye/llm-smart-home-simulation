import pytest

from app.experiments.logger import ExperimentLogger
from app.experiments.task_runner import TaskRunner
from app.research import UserPreferenceService
from app.research.personalization import UserPreferenceUpdate
from app.schemas.task_schema import AgentCommandRequest
from app.simulation.environment import SmartHomeEnvironment


@pytest.mark.parametrize('command,entity,field,expected', [
    ('关闭卧室的灯', 'light.bedroom_main', 'is_on', False),
    ('关闭卧室空调', 'ac.bedroom_main', 'is_on', False),
    ('关闭卧室窗户', 'window.bedroom_main', 'opening_pct', 0),
    ('把书房空调设为27度', 'ac.study_room_main', 'setpoint_c', 27),
    ('把书房灯光亮度设为40%', 'light.study_room_main', 'brightness_pct', 40),
    ('把客厅风扇速度调到30%', 'fan.living_room_main', 'speed_pct', 30),
])
def test_explicit_request_survives_preferences_and_feedback(tmp_path, monkeypatch, command, entity, field, expected):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    prefs = UserPreferenceService()
    prefs.update(UserPreferenceUpdate(preferred_temperature_c=24, preferred_illuminance_lux=900))
    runner = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False)
    response = runner.run_agent_command(AgentCommandRequest(user_command=command), preference_service=prefs)
    assert response.success, response.error
    device = next(item for item in response.final_state.devices if item.entity_id == entity)
    assert getattr(device, field) == expected


def test_negated_switch_does_not_turn_off_device(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    env.apply_device_action('light.living_room_main', 'turn_on', {'brightness_pct': 60})
    response = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False).run_agent_command(
        AgentCommandRequest(user_command='不要关闭客厅灯'))
    assert response.success
    light = next(item for item in response.final_state.devices if item.entity_id == 'light.living_room_main')
    assert light.is_on and light.brightness_pct == 60


def test_out_of_range_explicit_parameter_fails_without_device_execution(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    response = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False).run_agent_command(
        AgentCommandRequest(user_command='把客厅空调设为90度'))
    assert response.success is False
    assert '范围' in response.error
    assert not response.execution_result


@pytest.mark.parametrize('command,field,expected', [
    ('把客厅空调制热到27度', 'mode', 'heat'),
    ('把客厅空调制热到27度', 'setpoint_c', 27),
    ('把客厅空调设在24到26度', 'setpoint_c', 25),
])
def test_explicit_mode_and_interval_survive_execution(tmp_path, monkeypatch, command, field, expected):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    env.apply_device_action('ac.living_room_main', 'turn_on', {'mode': 'cool', 'setpoint_c': 22})
    response = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False).run_agent_command(
        AgentCommandRequest(user_command=command))
    assert response.success, response.error
    ac = next(d for d in response.final_state.devices if d.entity_id == 'ac.living_room_main')
    assert getattr(ac, field) == expected
    assert response.feedback_result['completed']
    if '到26' in command:
        assert response.semantic_result['targets']['temperature_c_range'] == [24, 26]


def test_negation_is_scoped_to_switch_clause(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    env.apply_device_action('light.living_room_main', 'turn_on', {'brightness_pct': 60})
    response = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False).run_agent_command(
        AgentCommandRequest(user_command='不要关闭客厅灯，把亮度调到40%'))
    light = next(d for d in response.final_state.devices if d.entity_id == 'light.living_room_main')
    assert response.success and light.is_on and light.brightness_pct == 40


@pytest.mark.parametrize('command', ['把客厅空调设在28到24度', '把客厅空调设在14到26度'])
def test_invalid_interval_is_rejected(tmp_path, monkeypatch, command):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    response = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False).run_agent_command(
        AgentCommandRequest(user_command=command))
    assert response.success is False
    assert not response.execution_result


@pytest.mark.parametrize('command,success,mode', [
    ('不要制热，把客厅空调设为24度', False, 'off'),
    ('客厅空调不要制热，制冷到24度', True, 'cool'),
    ('客厅空调不要制冷，制热到27度', True, 'heat'),
])
def test_negated_mode_is_never_activated(tmp_path, monkeypatch, command, success, mode):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    response = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False).run_agent_command(
        AgentCommandRequest(user_command=command))
    assert response.success is success
    ac = next(d for d in env.get_state(False).devices if d.entity_id == 'ac.living_room_main')
    assert ac.mode == mode


@pytest.mark.parametrize('command', [
    '不要关闭客厅灯把亮度调到40%',
    '别关闭客厅灯将亮度调到40%',
])
def test_unpunctuated_negation_preserves_positive_parameter(tmp_path, monkeypatch, command):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    env.apply_device_action('light.living_room_main', 'turn_on', {'brightness_pct': 60})
    response = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False).run_agent_command(
        AgentCommandRequest(user_command=command))
    light = next(d for d in env.get_state(False).devices if d.entity_id == 'light.living_room_main')
    assert response.success, response.error
    assert light.is_on and light.brightness_pct == 40
    assert response.feedback_result['completed']


def test_unpunctuated_switch_conflict_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODE', 'mock')
    env = SmartHomeEnvironment()
    response = TaskRunner(env, ExperimentLogger(tmp_path), log_task_results=False).run_agent_command(
        AgentCommandRequest(user_command='不要打开客厅灯把亮度调到40%'))
    assert not response.success
    assert not response.execution_result
    light = next(d for d in env.get_state(False).devices if d.entity_id == 'light.living_room_main')
    assert not light.is_on
