import csv
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.experiments.semantic_targets import evaluate_applicable_targets, summarize_applicable_targets


def test_unrequested_temperature_defaults_do_not_count_as_control_errors():
    result = evaluate_applicable_targets('把书房窗帘打开一些', {'temperature_c_range': [20, 30]}, {'temperature_c_range': [18, 29]})
    assert result['applicable'] is False
    assert result['exact_match'] is None
    assert result['denominator'] == 0
    assert result['excluded_fields'] == ['temperature_c_range']


def test_explicit_temperature_keeps_its_reference_and_missing_prediction_fails():
    result = evaluate_applicable_targets('把空调设为26度', {'temperature_c_range': [26, 26]}, {'temperature_c_range': [24, 24]})
    assert result['applicable'] is True
    assert result['exact_match'] is False
    assert result['denominator'] == 1
    assert evaluate_applicable_targets('温度24到26度', {'temperature_c_range': [24, 26]}, {})['exact_match'] is False


def test_extra_unrequested_prediction_does_not_inflate_denominator():
    result = evaluate_applicable_targets('保持500 lux', {'illuminance_lux_range': [500, 500]},
                                         {'illuminance_lux_range': [500, 500], 'temperature_c_range': [18, 29]})
    assert result['exact_match'] is True
    assert result['denominator'] == 1
    assert result['reference_status'] == 'existing_labels_not_independently_adjudicated'


@pytest.mark.parametrize('prediction', [[float('nan'), 26], [27, 25], ['bad', 25]])
def test_malformed_prediction_is_a_failure_not_an_exclusion(prediction):
    result = evaluate_applicable_targets('空调设为26度', {'temperature_c_range': [26, 26]}, {'temperature_c_range': prediction})
    assert result['exact_match'] is False
    assert result['denominator'] == 1


def test_negated_target_is_marked_for_review_instead_of_positive_scoring():
    result = evaluate_applicable_targets('不要设为26度', {'temperature_c_range': [26, 26]}, {'temperature_c_range': [26, 26]})
    assert result['applicable'] is False
    assert result['review_required'] is True


def test_multiple_explicit_fields_expose_field_and_task_denominators():
    expected = {'temperature_c_range': [26, 26], 'illuminance_lux_range': [500, 500], 'humidity_percent_range': [50, 50]}
    prediction = {**expected, 'humidity_percent_range': [60, 60]}
    result = evaluate_applicable_targets('温度设为26度，照度保持500 lux，湿度设为50%', expected, prediction)
    assert result['denominator'] == 3
    assert result['matched_field_count'] == 2
    assert result['exact_match'] is False
    summary = summarize_applicable_targets([result, evaluate_applicable_targets('打开灯', expected, expected)])
    assert summary['record_count'] == 2
    assert summary['applicable_task_count'] == 1
    assert summary['field_denominator'] == 3
    assert summary['field_exact_match_percent'] == 66.67
    assert summary['exact_match_percent'] == 0


@pytest.mark.parametrize('command', ['温度降低2度', '温度不低于26度', '如果温度26度就开灯', '当前温度26度', '温度设为26度左右', '温度设为26度或27度'])
def test_relative_conditional_observed_and_ambiguous_requests_need_review(command):
    result = evaluate_applicable_targets(command, {'temperature_c_range': [26, 26]}, {'temperature_c_range': [26, 26]})
    assert result['denominator'] == 0
    assert result['exact_match'] is None
    assert result['review_required'] is True


@pytest.mark.parametrize(('command', 'field'), [
    ('亮度设置为50%', 'illuminance_lux_range'),
    ('温度设置为75华氏度', 'temperature_c_range'),
    ('窗帘打开30度', 'temperature_c_range'),
    ('温度设为二十六度', 'temperature_c_range'),
])
def test_unsupported_units_and_numeric_forms_are_not_silently_scored(command, field):
    result = evaluate_applicable_targets(command, {field: [26, 26]}, {field: [26, 26]})
    assert result['denominator'] == 0
    assert result['review_required'] is True


def test_unrelated_percentage_does_not_make_humidity_or_lux_applicable():
    expected = {'temperature_c_range': [26, 26], 'illuminance_lux_range': [50, 50], 'humidity_percent_range': [50, 50]}
    result = evaluate_applicable_targets('湿度高而亮度设为50%，温度设为26度', expected, expected)
    assert result['applicable_fields'] == ['temperature_c_range']
    assert result['denominator'] == 1


def test_missing_reference_is_reported_instead_of_generated_from_command():
    result = evaluate_applicable_targets('温度26度', {}, {'temperature_c_range': [26, 26]})
    assert result['denominator'] == 0
    assert result['review_required'] is True
    assert result['field_results']['temperature_c_range']['reason'] == 'missing_or_invalid_existing_reference'


def test_zero_denominator_summary_reports_na_instead_of_perfect_accuracy():
    summary = summarize_applicable_targets([evaluate_applicable_targets('开灯', {'temperature_c_range': [20, 30]}, {})])
    assert summary['field_denominator'] == 0
    assert summary['exact_match_percent'] is None
    assert summary['field_exact_match_percent'] is None


@pytest.mark.parametrize(('command', 'field', 'value'), [
    ('空调设为26°C并开灯', 'temperature_c_range', 26),
    ('保持500lux并开灯', 'illuminance_lux_range', 500),
    ('湿度调成50%', 'humidity_percent_range', 50),
])
def test_supported_numeric_units_work_next_to_chinese_text(command, field, value):
    result = evaluate_applicable_targets(command, {field: [value, value]}, {})
    assert result['denominator'] == 1
    assert result['exact_match'] is False


def _script(name):
    path = Path(__file__).resolve().parents[2] / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'target_test_{name}', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _audit_fixture(tmp_path, *, predicted='{"temperature_c_range": [26, 26]}', include_prediction=True, repeat=False):
    tasks = tmp_path / 'tasks.json'
    tasks.write_text(json.dumps({'tasks': [{'task_id': 'T1', 'user_command': '温度26度', 'expected_targets': {'temperature_c_range': [26, 26]}}]}, ensure_ascii=False), encoding='utf-8')
    row = {'task_id': 'T1', 'user_command': '温度26度', 'group_id': 'saved_real', 'effective_llm_mode': 'real', 'repeat_index': '1', 'semantic_applicable': 'True', 'expected_targets': '{"temperature_c_range": [26, 26]}', 'target_applicable': 'True', 'target_exact_match': 'True'}
    if include_prediction:
        row['predicted_targets'] = predicted
    records = tmp_path / 'records.csv'
    with records.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        if repeat:
            writer.writerow({**row, 'repeat_index': '2', 'predicted_targets': '{}', 'target_exact_match': 'False'})
    return records, tasks


def test_audit_keeps_original_records_and_primary_repeat_denominator(tmp_path):
    module = _script('audit_semantic_target_applicability')
    records, tasks = _audit_fixture(tmp_path, repeat=True)
    before = [path.read_bytes() for path in (records, tasks)]
    audited, summary = module.audit_records(records, tasks)
    assert [path.read_bytes() for path in (records, tasks)] == before
    assert summary['historical_record_count'] == 2
    assert summary['primary_record_count'] == 1
    assert summary['group_summaries'][0]['explicit_target_metrics']['field_denominator'] == 1
    assert summary['group_summaries'][0]['explicit_target_metrics']['exact_match_percent'] == 100
    assert audited[1]['audit_exact_match'] is False
    assert audited[1]['target_exact_match'] == 'False'
    assert summary['model_calls_made'] == 0
    assert summary['rq5_blocker_resolved'] is False
    assert '现有标签尚未独立裁决' in module.render_report(summary)


@pytest.mark.parametrize('predicted', ['{}', 'broken JSON', '{"temperature_c_range": [27, 25]}', '{"temperature_c_range": [NaN, 26]}'])
def test_audit_saved_bad_prediction_is_failure_not_missing_evidence(tmp_path, predicted):
    module = _script('audit_semantic_target_applicability')
    records, tasks = _audit_fixture(tmp_path, predicted=predicted)
    audited, summary = module.audit_records(records, tasks)
    assert audited[0]['audit_status'] == 'rescored_saved_prediction'
    assert audited[0]['audit_exact_match'] is False
    assert summary['group_summaries'][0]['explicit_target_metrics']['field_denominator'] == 1


def test_audit_absent_prediction_column_is_not_reconstructed(tmp_path):
    module = _script('audit_semantic_target_applicability')
    records, tasks = _audit_fixture(tmp_path, include_prediction=False)
    audited, summary = module.audit_records(records, tasks)
    assert audited[0]['audit_status'] == 'prediction_not_recorded'
    assert audited[0]['audit_exact_match'] is None
    assert summary['group_summaries'][0]['explicit_target_metrics']['field_denominator'] == 0


def test_audit_mismatched_reference_is_unavailable_not_a_new_gold_label(tmp_path):
    module = _script('audit_semantic_target_applicability')
    records, tasks = _audit_fixture(tmp_path)
    tasks.write_text(tasks.read_text(encoding='utf-8').replace('[26, 26]', '[24, 26]'), encoding='utf-8')
    audited, _ = module.audit_records(records, tasks)
    assert audited[0]['audit_status'] == 'reference_mismatch_with_source_suite'
    assert audited[0]['audit_exact_match'] is None


@pytest.mark.parametrize('malformed', [False, True])
def test_reproduction_record_preserves_legacy_metrics_and_adds_applicability(malformed):
    module = _script('run_reproduction_experiments')
    group = module.GROUPS_BY_ID['rule_semantic_full']
    environment = module.SmartHomeEnvironment()
    expected = {'temperature_c_range': [26, 26], 'illuminance_lux_range': [100, 500]}
    predicted = {'temperature_c_range': ['bad', 26] if malformed else [26, 26]}
    task = {'task_id': 'T1', 'user_command': '空调设为26度', 'expected_targets': expected}
    response = SimpleNamespace(semantic_result={'targets': predicted}, plan_result={}, feedback_result={}, execution_result={}, final_state=None, success=True, error='')
    record = module.build_record(group=group, task=task, task_index=1, repeat_index=1, response=response, environment=environment, response_time_ms=1, pre_context_success=True, effective_llm_mode='mock', real_mode='mock', semantic_provenance=module.semantic_runtime_provenance('mock'))
    assert record['target_exact_match'] is False
    assert record['target_range_iou_percent'] == (0 if malformed else 50)
    assert json.loads(record['predicted_targets']) == predicted
    assert record['explicit_target_field_denominator'] == 1
    assert record['explicit_target_exact_match'] is (not malformed)
    summary = module.summarize_records([record], group)
    assert summary['target_exact_match_percent'] == 0
    assert summary['explicit_target_metrics']['field_denominator'] == 1
    category = module.summarize_by_group_and_category([record])[0]
    assert category['explicit_target_metrics'] == summary['explicit_target_metrics']
