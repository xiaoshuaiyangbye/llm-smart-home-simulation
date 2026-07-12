from app.agents.llm_client import _normalize_semantic_result
from app.simulation.environment import SmartHomeEnvironment


def test_unqualified_light_switch_uses_stable_basic_device_semantics() -> None:
    state = SmartHomeEnvironment().get_state(refresh_realtime=False)
    result = _normalize_semantic_result(
        {
            "intent": "lighting_comfort_control",
            "control_goal": "set_target",
            "targets": {"illuminance_lux_range": [100, 500], "temperature_c_range": [18, 29]},
        },
        "打开客厅灯光",
        state,
        "real",
    )

    assert result["intent"] == "basic_light_control"
    assert result["control_goal"] == "turn_on"
    assert result["targets"] == {"illuminance_lux_range": [100, 500], "temperature_c_range": [20, 30]}
