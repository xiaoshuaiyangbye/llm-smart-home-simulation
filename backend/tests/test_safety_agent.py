from app.agents.safety_agent import SafetyAgent


def test_safety_review_blocks_fan_speed_that_violates_airflow_constraint() -> None:
    result = SafetyAgent().review(
        {"constraints": {"avoid_strong_fan": True, "fan_speed_limit_pct": 30}},
        {
            "actions": [
                {
                    "entity_id": "fan.bedroom_main",
                    "action": "set_speed",
                    "parameters": {"speed_pct": 100},
                }
            ]
        },
    )

    assert result["actions_changed"] is True
    assert result["issues"][0]["severity"] == "high"
    assert result["remaining_issues"] == []
    assert result["actions"][0]["parameters"] == {"speed_pct": 0}


def test_safety_review_raises_overcooling_setpoint_to_health_floor() -> None:
    result = SafetyAgent().review(
        {"constraints": {"avoid_overcooling": True, "cooling_setpoint_floor_c": 26}},
        {
            "actions": [
                {
                    "entity_id": "ac.bedroom_main",
                    "action": "set_temperature",
                    "parameters": {"mode": "cool", "setpoint_c": 16},
                }
            ]
        },
    )

    assert result["actions_changed"] is True
    assert result["issues"][0]["severity"] == "high"
    assert result["remaining_issues"] == []
    assert result["actions"][0]["parameters"] == {"mode": "cool", "setpoint_c": 26.0}
