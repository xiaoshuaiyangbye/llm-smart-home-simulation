"""Preserve unambiguous user device constraints through planning and feedback.

This deterministic adapter is deliberately limited to one device family.
It does not infer a multi-device plan or override contextual safety constraints.
"""
from __future__ import annotations

import re
from copy import deepcopy

DEVICE_PATTERNS = {'light': r'灯|照明|\blights?\b', 'ac': r'空调|\bac\b|air conditioner',
                   'curtain': r'窗帘|\bcurtains?\b', 'window': r'窗户|窗子|\bwindows?\b',
                   'fan': r'风扇|\bfans?\b'}
NUMBER = r'(-?\d+(?:\.\d+)?)'
ON = r'打开|开启|开灯|点亮|turn on|switch on|\bopen\b'
OFF = r'关闭|关掉|关灯|熄灭|turn off|switch off|\bclose\b'
NEGATION = r'(?:不要|别|勿|do not|don.t)\s*(?:关闭|打开|开启|关掉|关灯|设为|制热|制冷|turn|switch|open|close|heat|cool)'
MODE_PATTERNS = [('heat', r'制热|暖风|\bheat(?:ing)?\b'), ('cool', r'制冷|\bcool(?:ing)?\b')]


def preserve_explicit_control(result: dict, command: str) -> dict:
    if result.get('error'):
        return result
    kinds = [kind for kind, pattern in DEVICE_PATTERNS.items() if re.search(pattern, command, re.I)]
    if len(kinds) != 1:
        return result
    kind = kinds[0]
    if re.search(r'学习|看书|阅读|观影|电影|睡觉|睡眠模式|节能模式|离家模式|\b(?:sleep|movie|away) mode\b', command, re.I):
        return result
    # Explicit parameter directives can start a new clause without punctuation.
    # Keep the split narrow: arbitrary 把/将 occurrences are not clause boundaries.
    clauses = re.split(r'[,，。;；]|(?:并且|然后)|(?=(?:把|将)(?:亮度|温度|速度|开度))', command)
    negative_clauses = [clause for clause in clauses if re.search(NEGATION, clause, re.I)]
    positive = ','.join(clause for clause in clauses if clause not in negative_clauses)
    on, off = re.search(ON, positive, re.I), re.search(OFF, positive, re.I)
    unit = r'(?:度|℃|°\s*C|celsius)' if kind == 'ac' else r'[%％]'
    interval = re.search(NUMBER + r'\s*(?:到|至|[-~～–])\s*' + NUMBER + r'\s*' + unit, positive, re.I)
    temperature = re.search(NUMBER + r'\s*' + unit, positive, re.I) if kind == 'ac' else None
    percent = re.search(NUMBER + r'\s*[%％]', positive) if kind != 'ac' else None
    modes = [mode for mode, pattern in MODE_PATTERNS
             if kind == 'ac' and re.search(pattern, positive, re.I)]
    forbidden_modes = {mode for mode, pattern in MODE_PATTERNS
                       if kind == 'ac' and any(re.search(pattern, clause, re.I) for clause in negative_clauses)}
    if forbidden_modes and (not modes or any(mode in forbidden_modes for mode in modes)):
        return {**result, 'error': '存在禁止的空调模式，请明确选择允许的制热或制冷模式。'}
    negated = bool(negative_clauses) and not (on or off or temperature or percent or modes)
    if not (on or off or temperature or percent or modes or negated):
        return result
    # Conflicting positive verbs require the general semantic path, not a guess.
    if (on and off) or len(modes) > 1:
        return {**result, 'error': '明确设备指令相互冲突，请确认目标操作。'}
    contract = {'schema_version': 'explicit_device_control_v2', 'source': 'user_explicit_constraint',
                'device_type': kind, 'parameters': {}, 'parameter_ranges': {},
                'target_fields': [], 'preserve_state': negated}
    goal = 'turn_off' if off else 'turn_on'
    if negated:
        contract['action'] = 'preserve_state'
    elif temperature or percent:
        bounds = [float(interval.group(i)) for i in (1, 2)] if interval else None
        value = sum(bounds) / 2 if bounds else float((temperature or percent).group(1))
        low, high = (16, 30) if kind == 'ac' else (0, 100)
        if not low <= value <= high or (bounds and not low <= bounds[0] <= bounds[1] <= high):
            return {**result, 'error': f'明确参数或区间超出支持范围 [{low}, {high}] 或上下限顺序错误，请确认目标值。'}
        field = {'light': 'brightness_pct', 'ac': 'setpoint_c', 'fan': 'speed_pct',
                 'window': 'opening_pct', 'curtain': 'opening_pct'}[kind]
        contract.update(action={'light': 'set_brightness', 'ac': 'set_temperature', 'fan': 'set_speed',
                                'window': 'set_opening', 'curtain': 'set_opening'}[kind], parameters={field: value})
        if kind == 'ac':
            contract['target_fields'] = ['temperature_c_range']
        if bounds:
            contract['parameter_ranges'][field] = bounds
        goal = 'set_target'
    else:
        contract['action'] = ('close' if off else 'open') if kind in {'window', 'curtain'} else goal
    if modes:
        contract['parameters']['mode'] = modes[0]
    # A positive clause must not contradict a prohibited switch operation.
    forbidden_on = any(re.search(ON, clause, re.I) for clause in negative_clauses)
    forbidden_off = any(re.search(OFF, clause, re.I) for clause in negative_clauses)
    activates = contract['action'] in {'turn_on', 'set_temperature'} or (
        contract['action'] in {'set_brightness', 'set_speed', 'set_opening'} and value > 0)
    deactivates = contract['action'] in {'turn_off', 'close'} or (
        contract['action'] in {'set_brightness', 'set_speed', 'set_opening'} and value == 0)
    if not negated and ((forbidden_on and activates) or (forbidden_off and deactivates)):
        return {**result, 'error': '参数调整与禁止开关的约束冲突，请确认目标操作。'}
    output = deepcopy(result)
    output['explicit_control'] = contract
    output['devices'] = [kind]
    output['intent'] = {'light': 'basic_light_control', 'ac': 'basic_ac_control', 'curtain': 'basic_curtain_control',
                        'window': 'basic_curtain_control', 'fan': 'thermal_comfort_control'}[kind]
    output['task_type'] = 'device_control'
    output['control_goal'] = 'preserve_state' if negated else goal
    if temperature and not negated:
        value = contract['parameters']['setpoint_c']
        output.setdefault('targets', {})['temperature_c_range'] = contract['parameter_ranges'].get('setpoint_c', [value - .5, value + .5])
    return output


def explicit_actions(semantic: dict, state) -> list[dict]:
    contract = semantic['explicit_control']
    if contract['preserve_state']:
        return []
    actions = []
    for device in state.devices:
        if device.device_type != contract['device_type'] or (semantic['room'] != 'all_rooms' and device.room != semantic['room']):
            continue
        parameters = dict(contract['parameters'])
        action = contract['action']
        if contract['action'] == 'turn_on':
            if device.device_type == 'light':
                parameters = {'brightness_pct': 70, 'color_temperature_k': 4000}
            elif device.device_type == 'fan':
                parameters = {'speed_pct': 30}
            elif device.device_type == 'ac':
                target = semantic.get('targets', {}).get('temperature_c_range', [25, 27])
                parameters = {'setpoint_c': sum(target) / 2,
                              'mode': parameters.get('mode', device.mode if device.mode != 'off' else 'cool')}
        if contract['action'] == 'set_temperature':
            # set_temperature intentionally does not change mode in the device API.
            # turn_on atomically applies both a setpoint and a validated mode.
            action = 'turn_on'
            parameters['mode'] = parameters.get('mode', device.mode if device.mode != 'off' else 'cool')
        actions.append({'entity_id': device.entity_id, 'action': action, 'parameters': parameters,
                        'reason': 'preserve explicit user device constraint; subject to safety review'})
    return actions


def explicit_feedback(semantic: dict, state, revision_round: int) -> dict:
    contract = semantic['explicit_control']
    if contract['preserve_state']:
        return {'completed': True, 'feedback': '保留明确否定指令涉及的设备状态。',
                'metrics': {'explicit_control': True, 'preserve_state': True}, 'correction_round': revision_round, 'correction_actions': []}
    devices = [device for device in state.devices if device.device_type == contract['device_type']
               and (semantic['room'] == 'all_rooms' or device.room == semantic['room'])]
    checks = []
    for device in devices:
        expected = contract['parameters'].copy()
        action = contract['action']
        ranges = contract.get('parameter_ranges', {})
        if action == 'set_temperature':
            expected['is_on'] = True
        if action in {'turn_on', 'turn_off'}:
            expected['is_on'] = action == 'turn_on'
        elif action in {'open', 'close'}:
            expected['opening_pct'] = 100 if action == 'open' else 0
        for field, value in expected.items():
            actual = getattr(device, field, None)
            bounds = ranges.get(field)
            passed = actual is not None and bounds[0] <= actual <= bounds[1] if bounds else actual == value
            checks.append({'entity_id': device.entity_id, 'field': field, 'expected': bounds or value,
                           'actual': actual, 'passed': passed})
    completed = bool(checks) and all(check['passed'] for check in checks)
    return {'completed': completed, 'feedback': '明确设备目标已满足。' if completed else '明确目标未满足；请查看安全审查或执行结果。',
            'metrics': {'explicit_control': True, 'device_checks': checks}, 'correction_round': revision_round,
            # A policy-blocked explicit target must not be retried as a comfort correction.
            'correction_actions': []}
