"""Check fixed total time and redundant-batch invariance in the opt-in simulator."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.simulation.environment import SmartHomeEnvironment  # noqa: E402
from app.simulation.integrated_environment import IntegratedSmartHomeEnvironment  # noqa: E402


def run():
    output = ROOT / 'data/results/integrated_accounting' / datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    output.mkdir(parents=True, exist_ok=False)
    initial = SmartHomeEnvironment().get_state(False).model_copy(deep=True)
    initial_json = initial.model_dump(mode='json')
    policies = {
        'idle': [],
        'light_40': [{'entity_id': 'light.living_room_main', 'action': 'turn_on', 'parameters': {'brightness_pct': 40}}],
        'cool_20': [{'entity_id': 'ac.living_room_main', 'action': 'turn_on', 'parameters': {'mode': 'cool', 'setpoint_c': 20}}],
    }
    records = []
    for policy, actions in policies.items():
        for batches in (1, 2):
            env = IntegratedSmartHomeEnvironment(initial)
            execution = []
            for _ in range(batches):
                results, _state = env.apply_device_actions_batch(actions)
                execution.extend(results)
            control_minutes = env.get_state(False).current_time_step - initial.current_time_step
            env.step(30 - control_minutes, refresh_realtime=False)
            final = env.get_state(False)
            records.append({'policy': policy, 'requested_batches': batches,
                            'successful_actions': sum(x['success'] for x in execution),
                            'control_minutes': control_minutes,
                            'total_minutes': final.current_time_step - initial.current_time_step,
                            'energy_kwh': final.energy_metrics.cumulative_energy_kwh - initial.energy_metrics.cumulative_energy_kwh,
                            'final_state_sha256': hashlib.sha256(final.model_dump_json().encode()).hexdigest(),
                            'initial_state_sha256': hashlib.sha256(initial.model_dump_json().encode()).hexdigest()})
    checks = {'all_total_horizons_30_minutes': all(x['total_minutes'] == 30 for x in records),
              'redundant_batch_final_state_invariant': all(
                  len({x['final_state_sha256'] for x in records if x['policy'] == policy}) == 1 for policy in policies),
              'all_energy_positive': all(x['energy_kwh'] > 0 for x in records)}
    paths = [Path(__file__), ROOT / 'backend/app/simulation/integrated_environment.py',
             ROOT / 'backend/app/simulation/environment.py', ROOT / 'backend/app/simulation/energy_model.py',
             ROOT / 'backend/app/simulation/thermal_model.py', ROOT / 'backend/app/simulation/humidity_model.py',
             ROOT / 'backend/app/simulation/weather_model.py', ROOT / 'backend/app/simulation/lighting_model.py']
    paths += sorted((ROOT / 'backend/app/config').glob('*.yaml'))
    protocol = {'schema_version': 'integrated_accounting_diagnostic_v1', 'accounting_version': IntegratedSmartHomeEnvironment.accounting_version,
                'total_horizon_minutes': 30, 'action_batch_minutes': 5, 'integration_step_minutes': 1,
                'quadrature': 'end_of_minute_power_with_existing_5_decimal_kwh_rounding',
                'policies': policies, 'source_manifest': {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                'boundary': 'Deterministic simulator accounting diagnostic, no LLM calls, no population inference, no physical calibration or field savings claim.'}
    (output / 'initial_state.json').write_text(json.dumps(initial_json, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'records.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in records), encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps({'record_count': len(records), 'checks': checks, 'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(output), 'record_count': len(records), 'checks': checks}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(run())
