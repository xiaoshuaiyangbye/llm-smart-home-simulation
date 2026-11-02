import json

import pytest
from pydantic import ValidationError

from app.energyplus.calibration import fit_calibration
from app.energyplus.contracts import CalibrationRequest, Controls, RunRequest
from app.energyplus.controllers import map_actions
from app.energyplus.model import runtime_directory
from app.energyplus.runner import run
from app.energyplus.service import JobService


def test_contract_rejects_bad_controls_and_time_grid():
    with pytest.raises(ValidationError):
        Controls(light_fraction=float("nan"))
    with pytest.raises(ValidationError):
        Controls(cooling_setpoint_c=20, heating_setpoint_c=20)
    with pytest.raises(ValidationError):
        RunRequest(control_interval_minutes=17)


def test_unsupported_action_does_not_partially_apply():
    previous = Controls(light_fraction=0.2)
    result, accepted, rejected = map_actions([
        {"entity_id": "light.living_room_main", "action": "set_brightness", "parameters": {"brightness_pct": 250}},
        {"entity_id": "light.bedroom_main", "action": "turn_on", "parameters": {}},
    ], previous)
    assert result == previous
    assert not accepted and len(rejected) == 2


def test_calibration_reports_point_holdout_and_declared_source():
    points = [{"dimming_fraction": x, "electric_illuminance_lux": 600 * x, "power_w": 200 * x}
              for x in (0, 0.2, 0.4, 0.6, 0.8, 1)]
    fitted = fit_calibration(CalibrationRequest(source_description="bench meter trial", sensor_location="desk 0.8m",
        ambient_subtracted=True, points=points))
    assert fitted["illuminance"]["holdout_mae"] < 1e-9
    assert fitted["power"]["holdout_mae"] < 1e-9
    assert fitted["source_authenticity"] == "user_declared_not_independently_verified"


def test_owner_isolation(tmp_path):
    directory = tmp_path / ("a" * 32)
    directory.mkdir()
    from app.energyplus.service import owner_key
    (directory / "config.json").write_text(json.dumps({"owner": owner_key("resident-a")}), encoding="utf-8")
    service = JobService(tmp_path)
    assert service.directory(directory.name, "resident-a") == directory
    with pytest.raises(KeyError):
        service.directory(directory.name, "resident-b")


def test_real_engine_actuators_and_sql_accounting(tmp_path):
    try:
        runtime_directory()
    except FileNotFoundError:
        pytest.skip("Pinned local EnergyPlus runtime not installed")
    summaries = []
    for name, light in (("off", 0), ("on", 1)):
        directory = tmp_path / name
        directory.mkdir()
        request = RunRequest(spatial_scope="single_room", controller="manual", manual_controls=Controls(light_fraction=light, ventilation_fraction=0.25))
        (directory / "config.json").write_text(json.dumps({"request": request.model_dump(), "calibration": None}), encoding="utf-8")
        summary = run(directory / "config.json")
        assert summary["sample_count"] == 288
        assert summary["severe_error_count"] == 0
        assert summary["accounting"]["canonical_energy_source"].startswith("EnergyPlus SQLite")
        assert (directory / "available_api_data.json").is_file()
        assert (directory / "raw_callback_observations.jsonl").is_file()
        summaries.append(summary)
    assert summaries[0]["initial_state_fingerprint"] == summaries[1]["initial_state_fingerprint"]
    assert summaries[0]["provenance"]["weather_sha256"] == summaries[1]["provenance"]["weather_sha256"]
    assert summaries[1]["modeled_lighting_kwh"] > summaries[0]["modeled_lighting_kwh"]
    assert summaries[1]["modeled_electricity_kwh"] > summaries[0]["modeled_electricity_kwh"]
