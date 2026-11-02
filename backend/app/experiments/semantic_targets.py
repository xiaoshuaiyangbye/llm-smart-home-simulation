"""Additive target scoring for explicit numeric requests, using existing labels.

This conservative lexical applicability check is not a semantic gold standard.
It never generates reference targets, adjudicates ambiguous requests, or replaces
the reproduction benchmark's historical full-target metrics.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

SCHEMA_VERSION = "semantic_target_applicability_v1"
REFERENCE_STATUS = "existing_labels_not_independently_adjudicated"
FIELDS = (
    "temperature_c_range",
    "illuminance_lux_range",
    "humidity_percent_range",
)
_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_FIELD_CUES = {
    FIELDS[0]: r"温度|气温|室温|temperature|thermostat",
    FIELDS[1]: r"照度|illuminance",
    FIELDS[2]: r"湿度|humidity",
}
_UNITS = {
    FIELDS[0]: r"(?:摄氏度|摄氏|°\s*c(?![a-z])|℃|度|degrees?\s*(?:celsius|c)?(?![a-z])|celsius(?![a-z]))",
    FIELDS[1]: r"(?:lux(?![a-z])|勒克斯|勒克司|lx(?![a-z]))",
    FIELDS[2]: r"(?:%|％|percent(?![a-z]))",
}
_QUALITATIVE = {
    FIELDS[0]: r"太热|太冷|有点热|有点冷|凉快|凉爽|降温|升温|冷一点|热一点|温度.{0,8}(?:点|些|舒服)|cooler|warmer",
    FIELDS[1]: r"太亮|太暗|亮一点|暗一点|亮一些|暗一些|光线.{0,6}(?:低|高)|brighter|dimmer",
    FIELDS[2]: r"潮|太干|干燥|除湿|降湿|湿度.{0,6}(?:低|高|点|些)|drier|wetter",
}
_REVIEW_LANGUAGE = re.compile(
    r"不|别|勿|禁止|至少|至多|低于|高于|超过|以上|以下|"
    r"如果|当.*时|当前|现在|目前|室温|大约|左右|差不多|或|还是|"
    r"升高|降低|增加|减少|调高|调低|提高|下降|"
    r"\b(?:not|never|avoid|unless|if|when|current|currently|measured|about|around|or|"
    r"above|below|under|over|increase|decrease|raise|lower)\b|[<>≤≥]",
    re.IGNORECASE,
)


def _numeric_request(clause: str, field: str) -> bool:
    # A number must be attached to this field's unit or follow its own cue.
    # Thus a humidity percentage cannot make an unrelated temperature default
    # applicable merely because both fields occur in one command.
    unit = _UNITS[field]
    if field != FIELDS[2] and re.search(rf"{_NUMBER}\s*{unit}", clause, re.IGNORECASE):
        return True
    cue = _FIELD_CUES[field]
    return bool(re.search(
        rf"(?:{cue})\s*(?:(?:设为|设置为|设定为|调到|调成|调为|调整到|调整为|设置|设定|设|"
        rf"保持在|保持|控制在|为|到|是|目标|[:：=]|"
        rf"set\s+to|at|to|of|is|between|target)\s*)*{_NUMBER}",
        clause,
        re.IGNORECASE,
    ))


def _unsupported_numeric_form(clause: str, field: str) -> bool:
    """Do not equate percentage brightness, Fahrenheit or angles with targets."""
    patterns = {
        FIELDS[0]: r"华氏|°\s*f\b|fahrenheit|角度|旋转|窗帘.{0,12}\d+\s*度|风向.{0,12}\d+\s*度",
        FIELDS[1]: r"(?:亮度|brightness|照度).{0,12}\d+\s*[%％]",
        FIELDS[2]: r"湿度.{0,10}[零〇一二两三四五六七八九十百]+",
    }
    chinese_numerals = bool(re.search(
        rf"(?:{_FIELD_CUES[field]}).{{0,8}}[零〇一二两三四五六七八九十百]+(?:度|勒克斯|%)",
        clause,
        re.IGNORECASE,
    ))
    return chinese_numerals or bool(re.search(patterns[field], clause, re.IGNORECASE))


def _valid_range(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(endpoint, bool) for endpoint in value):
        return None
    try:
        low, high = (float(endpoint) for endpoint in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(low) or not math.isfinite(high) or low > high:
        return None
    return [low, high]


def evaluate_applicable_targets(
    command: str, expected_targets: object, predicted_targets: object,
) -> dict[str, Any]:
    """Score only explicitly requested fields; invalid predictions stay failures.

    ``denominator`` counts scored fields, while ``exact_match`` is a task-level
    conjunction over them. Zero denominators are N/A, never a success. Negation,
    relative adjustments, conditionals and alternatives require human review.
    """
    expected = expected_targets if isinstance(expected_targets, dict) else {}
    predicted = predicted_targets if isinstance(predicted_targets, dict) else {}
    clauses = [part.strip() for part in re.split(r"[，,。；;!?！？]|并且|同时|\band\b", str(command), flags=re.IGNORECASE) if part.strip()]
    results: dict[str, dict[str, Any]] = {}
    for field in FIELDS:
        candidates = [clause for clause in clauses if _numeric_request(clause, field)]
        qualitative = any(re.search(_QUALITATIVE[field], clause, re.IGNORECASE) for clause in clauses)
        unsupported = any(_unsupported_numeric_form(clause, field) for clause in clauses)
        reason = "not_explicitly_requested"
        review = qualitative
        if unsupported:
            reason, review = "unsupported_numeric_form_or_unit", True
        elif candidates:
            if any(_REVIEW_LANGUAGE.search(clause) for clause in candidates) or len(candidates) > 1:
                reason, review = "ambiguous_negated_conditional_or_relative", True
            elif _valid_range(expected.get(field)) is None:
                reason, review = "missing_or_invalid_existing_reference", True
            else:
                reference = _valid_range(expected[field])
                prediction = _valid_range(predicted.get(field))
                exact = prediction == reference
                iou = 0.0
                if prediction is not None:
                    intersection = max(0.0, min(reference[1], prediction[1]) - max(reference[0], prediction[0]))
                    union = max(reference[1], prediction[1]) - min(reference[0], prediction[0])
                    iou = 1.0 if exact and union == 0 else intersection / union if union else 0.0
                results[field] = {
                    "applicable": True, "reason": "explicit_numeric_request",
                    "review_required": False, "exact_match": exact,
                    "range_iou_percent": round(iou * 100, 2),
                    "prediction_status": "valid" if prediction is not None else "missing_or_malformed",
                }
                continue
        elif qualitative:
            reason = "qualitative_request_requires_adjudication"
        # Keep an explicit missing reference visible, but do not create a
        # default reference field merely because the prediction supplied it.
        if field in expected or candidates or qualitative or unsupported:
            results[field] = {
                "applicable": False, "reason": reason, "review_required": review,
                "exact_match": None, "range_iou_percent": None,
            }
    applicable = [key for key, value in results.items() if value["applicable"]]
    excluded = [key for key, value in results.items() if not value["applicable"]]
    denominator = len(applicable)
    matched = sum(results[key]["exact_match"] for key in applicable)
    return {
        "schema_version": SCHEMA_VERSION,
        "reference_status": REFERENCE_STATUS,
        "applicable": bool(denominator),
        "exact_match": matched == denominator if denominator else None,
        "denominator": denominator,
        "matched_field_count": matched,
        "range_iou_percent": round(sum(results[key]["range_iou_percent"] for key in applicable) / denominator, 2) if denominator else None,
        "applicable_fields": applicable,
        "excluded_fields": excluded,
        "review_required": any(value["review_required"] for value in results.values()),
        "field_results": results,
    }


def summarize_applicable_targets(measurements: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose task and field denominators separately, with exclusion reasons."""
    scored = [item for item in measurements if item["applicable"]]
    denominator = sum(item["denominator"] for item in measurements)
    matches = sum(item["matched_field_count"] for item in measurements)
    return {
        "schema_version": SCHEMA_VERSION,
        "reference_status": REFERENCE_STATUS,
        "record_count": len(measurements),
        "applicable_task_count": len(scored),
        "field_denominator": denominator,
        "matched_field_count": matches,
        "exact_match_percent": round(sum(item["exact_match"] for item in scored) / len(scored) * 100, 2) if scored else None,
        "field_exact_match_percent": round(matches / denominator * 100, 2) if denominator else None,
        "review_required_count": sum(item["review_required"] for item in measurements),
        "excluded_field_reasons": dict(Counter(
            value["reason"] for item in measurements for value in item["field_results"].values() if not value["applicable"]
        )),
    }
