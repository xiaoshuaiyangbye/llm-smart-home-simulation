import pytest

from app.simulation.environment import SmartHomeEnvironment
from app.simulation.integrated_environment import IntegratedSmartHomeEnvironment


def action():
    return {'entity_id': 'light.living_room_main', 'action': 'turn_on',
            'parameters': {'brightness_pct': 40}}


def test_successful_batch_advances_clock_and_energy_together():
    env = IntegratedSmartHomeEnvironment()
    before = env.get_state(False).model_copy(deep=True)
    results, after = env.apply_device_actions_batch([action()])
    assert results[0]['success']
    assert after.current_time_step - before.current_time_step == 5
    before_clock = before.outdoor_environment.time_hour * 60 + before.outdoor_environment.time_minute
    after_clock = after.outdoor_environment.time_hour * 60 + after.outdoor_environment.time_minute
    assert (after_clock - before_clock) % 1440 == 5
    assert after.energy_metrics.cumulative_energy_kwh > before.energy_metrics.cumulative_energy_kwh
    expected = after.energy_metrics.current_power_w * 5 / 60000
    assert after.energy_metrics.cumulative_energy_kwh == pytest.approx(expected, abs=5e-5)


def test_long_step_is_identical_to_minute_steps():
    initial = SmartHomeEnvironment().get_state(False).model_copy(deep=True)
    a, b = IntegratedSmartHomeEnvironment(initial), IntegratedSmartHomeEnvironment(initial)
    a.apply_device_action('ac.living_room_main', 'turn_on', {'mode': 'cool', 'setpoint_c': 20})
    b.apply_device_action('ac.living_room_main', 'turn_on', {'mode': 'cool', 'setpoint_c': 20})
    a.step(30, refresh_realtime=False)
    for _ in range(30):
        b.step(1, refresh_realtime=False)
    assert a.get_state(False).model_dump() == b.get_state(False).model_dump()
    assert a.get_state(False).current_time_step == 35


def test_zero_step_and_empty_or_failed_batch_do_not_advance():
    env = IntegratedSmartHomeEnvironment()
    before = env.get_state(False).model_dump()
    env.step(0, refresh_realtime=False)
    env.apply_device_actions_batch([])
    results, _ = env.apply_device_actions_batch([{'entity_id': 'missing', 'action': 'turn_on', 'parameters': {}}])
    assert not results[0]['success']
    assert env.get_state(False).model_dump() == before


def test_partial_batch_accounts_for_successful_actions():
    env = IntegratedSmartHomeEnvironment()
    results, state = env.apply_device_actions_batch([
        action(), {'entity_id': 'missing', 'action': 'turn_on', 'parameters': {}}])
    assert [x['success'] for x in results] == [True, False]
    assert state.current_time_step == 5
    assert state.energy_metrics.cumulative_energy_kwh > 0


def test_total_horizon_includes_control_stage():
    env = IntegratedSmartHomeEnvironment()
    env.apply_device_actions_batch([action()])
    env.step(30 - env.get_state(False).current_time_step, refresh_realtime=False)
    assert env.get_state(False).current_time_step == 30


@pytest.mark.parametrize('minutes', [-1, 1.5])
def test_invalid_duration_is_rejected(minutes):
    env = IntegratedSmartHomeEnvironment()
    with pytest.raises(ValueError):
        env.step(minutes, refresh_realtime=False)
