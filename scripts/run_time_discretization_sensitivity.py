"""Isolated numerical sensitivity; one-minute reference is not physical ground truth."""
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.simulation.environment import SmartHomeEnvironment  # noqa: E402


def run():
    output = ROOT / 'data/results/time_discretization' / datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
    output.mkdir(parents=True, exist_ok=False)
    policies = {'idle': [], 'light_40': [{'entity_id': 'light.living_room_main', 'action': 'turn_on', 'parameters': {'brightness_pct': 40}}],
                'cool_20': [{'entity_id': 'ac.living_room_main', 'action': 'turn_on', 'parameters': {'mode': 'cool', 'setpoint_c': 20}}]}
    steps = [1, 2, 5, 30]
    rows, initial_states = [], {}
    for temperature in [22, 26, 30]:
        for policy, actions in policies.items():
            base = SmartHomeEnvironment().get_state(False).model_copy(deep=True)
            for room in base.rooms:
                room.indoor_temperature_c = temperature
            base.outdoor_environment.data_updated_at = 'frozen_software_sensitivity_fixture'
            setup = SmartHomeEnvironment(base)
            setup.apply_device_actions_batch(actions, dt_minutes=0)
            initial = setup.get_state(False).model_copy(deep=True)
            key = f'{temperature}_{policy}'
            initial_states[key] = initial.model_dump(mode='json')
            digest = hashlib.sha256(initial.model_dump_json().encode()).hexdigest()
            for step in steps:
                env = SmartHomeEnvironment(initial)
                for _ in range(30 // step):
                    env.step(step, refresh_realtime=False)
                state = env.get_state(False)
                room = next(r for r in state.rooms if r.room_id == 'living_room')
                rows.append({'scenario': key, 'initial_temperature_c': temperature, 'policy': policy,
                             'step_minutes': step, 'total_minutes': state.current_time_step - initial.current_time_step,
                             'initial_state_sha256': digest, 'energy_kwh': state.energy_metrics.cumulative_energy_kwh - initial.energy_metrics.cumulative_energy_kwh,
                             'final_temperature_c': room.indoor_temperature_c})
    for row in rows:
        ref = next(r for r in rows if r['scenario'] == row['scenario'] and r['step_minutes'] == 1)
        row['energy_delta_vs_1min_kwh'] = row['energy_kwh'] - ref['energy_kwh']
        row['temperature_delta_vs_1min_c'] = row['final_temperature_c'] - ref['final_temperature_c']
    summary = {'record_count': len(rows), 'scenario_count': len(initial_states),
               'total_horizon_check': all(r['total_minutes'] == 30 for r in rows),
               'by_step': {str(step): {'mean_absolute_energy_delta_kwh': mean(abs(r['energy_delta_vs_1min_kwh']) for r in rows if r['step_minutes'] == step),
                                    'max_absolute_energy_delta_kwh': max(abs(r['energy_delta_vs_1min_kwh']) for r in rows if r['step_minutes'] == step),
                                    'mean_absolute_temperature_delta_c': mean(abs(r['temperature_delta_vs_1min_c']) for r in rows if r['step_minutes'] == step)} for step in steps},
               'boundary': 'Fixed synthetic software fixtures; one-minute reference is a numerical convention, not measured physical truth. No LLM or control-method superiority claim.'}
    paths = [Path(__file__)] + sorted((ROOT / 'backend/app/simulation').glob('*.py')) + sorted((ROOT / 'backend/app/config').glob('*.yaml'))
    protocol = {'schema_version': 'time_discretization_sensitivity_v1', 'step_minutes': steps, 'horizon_minutes': 30,
                'policies': policies, 'initial_temperatures_c': [22,26,30], 'refresh_realtime': False,
                'control_setup': 'instantaneous dt=0, shared initial state; integration sensitivity only',
                'source_manifest': {str(p.relative_to(ROOT)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    for name, obj in [('protocol',protocol),('initial_states',initial_states),('summary',summary)]:
        (output/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    print(json.dumps({'output_dir':str(output),**summary},ensure_ascii=False))
    return 0 if summary['total_horizon_check'] else 1


if __name__ == '__main__':
    raise SystemExit(run())
