"""Real EnergyPlus process runner with callback-local control and complete traces."""
import argparse
import csv
import hashlib
import json
import re
import sys
import time
import traceback
from pathlib import Path

from app.energyplus.contracts import Controls, RunRequest, finite_observation
from app.energyplus.accounting import reconcile_energy
from app.energyplus.controllers import Controller
from app.energyplus.model import SCHEDULES, ZONE, build_model, runtime_directory, sha


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def summarize(observations, request):
    occupied = [x for x in observations if x["occupants"] > 0]
    satisfied = [x for x in occupied if abs(x["temperature_c"] - request.temperature_target_c) <= 1
                 and x["total_illuminance_lux"] >= request.illuminance_target_lux - 50
                 and x["co2_ppm"] <= request.co2_limit_ppm]
    return {"sample_count": len(observations), "elapsed_simulation_minutes": len(observations)*5,
        "occupied_sample_count": len(occupied),
        "occupied_target_satisfaction_rate": len(satisfied)/len(occupied) if occupied else None,
        "temperature_violation_degree_minutes": sum(max(0, abs(x["temperature_c"]-request.temperature_target_c)-1)*5 for x in occupied),
        "illuminance_deficit_lux_minutes": sum(max(0, request.illuminance_target_lux-x["total_illuminance_lux"])*5 for x in occupied),
        "co2_excess_ppm_minutes": sum(max(0, x["co2_ppm"]-request.co2_limit_ppm)*5 for x in occupied),
        "modeled_electricity_kwh": sum(x["electricity_step_j"] for x in observations)/3600000,
        "modeled_lighting_kwh": sum(x["lighting_step_j"] for x in observations)/3600000,
        "modeled_cooling_electricity_kwh": sum(x["cooling_electricity_step_j"] for x in observations)/3600000,
        "modeled_heating_electricity_kwh": sum(x["heating_electricity_step_j"] for x in observations)/3600000,
        "cooling_thermal_load_kwh": sum(x["cooling_thermal_step_j"] for x in observations)/3600000,
        "heating_thermal_load_kwh": sum(x["heating_thermal_step_j"] for x in observations)/3600000,
        "max_co2_ppm": max(x["co2_ppm"] for x in observations),
        "energy_boundary": "EnergyPlus modeled electricity with specified COP/efficiency, not measured consumption"}


def run(config_path):
    output = config_path.parent
    config = json.loads(config_path.read_text(encoding="utf-8"))
    request = RunRequest.model_validate(config["request"])
    if request.spatial_scope == "whole_home":
        from app.energyplus.whole_runner import run_whole_home
        return run_whole_home(config_path, request, config.get("calibration"))
    calibration = config.get("calibration")
    write_json(output / "status.json", {"status": "running", "phase": "building_model", "samples": 0})
    model_path, weather, provenance = build_model(request, output, calibration)
    runtime = runtime_directory()
    sys.path.insert(0, str(runtime))
    from pyenergyplus.api import EnergyPlusAPI
    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    api.runtime.set_console_output_status(state, False)
    controller = Controller(request, output, calibration)
    handles, observations, traces, errors = {}, [], [], []
    controls = Controls(hvac_enabled=True, ventilation_fraction=0.25, light_fraction=0)
    initial = None
    started = time.perf_counter()
    engine_output = output / "engine"
    engine_output.mkdir()
    variable_specs = {
        "temperature_c": ("Zone Mean Air Temperature", ZONE),
        "relative_humidity_pct": ("Zone Air Relative Humidity", ZONE),
        "co2_ppm": ("Zone Air CO2 Concentration", ZONE),
        "daylight_lux": ("Daylighting Reference Point 1 Illuminance", "AGENTDAYLIGHT"),
        "lighting_power_w": ("Zone Lights Electricity Rate", ZONE),
        "cooling_thermal_step_j": ("Zone Ideal Loads Supply Air Total Cooling Energy", "AGENTIDEAL"),
        "heating_thermal_step_j": ("Zone Ideal Loads Supply Air Total Heating Energy", "AGENTIDEAL"),
        "outdoor_temperature_c": ("Site Outdoor Air Drybulb Temperature", "ENVIRONMENT"),
        "occupants": ("Zone People Occupant Count", ZONE),
    }
    meters = {"electricity_step_j": "Electricity:Facility", "lighting_step_j": "InteriorLights:Electricity",
              "cooling_electricity_step_j": "Cooling:Electricity", "heating_electricity_step_j": "Heating:Electricity"}
    for name, key in variable_specs.values():
        api.exchange.request_variable(state, name, key)

    def active(s):
        return api.exchange.api_data_fully_ready(s) and not api.exchange.warmup_flag(s) and api.exchange.kind_of_sim(s) == 3

    def bind(s):
        if handles:
            return
        catalog = [{k: getattr(x, k) for k in ("what", "name", "key", "type", "unit")} for x in api.exchange.get_api_data(s)]
        write_json(output / "available_api_data.json", catalog)
        for key, (name, variable_key) in variable_specs.items():
            handle = api.exchange.get_variable_handle(s, name, variable_key)
            if handle < 0:
                raise RuntimeError(f"Required variable unavailable: {name} / {variable_key}")
            handles[key] = handle
        for key, name in meters.items():
            handle = api.exchange.get_meter_handle(s, name)
            if handle < 0:
                raise RuntimeError(f"Required meter unavailable: {name}")
            handles[key] = handle
        for key, name in SCHEDULES.items():
            handle = api.exchange.get_actuator_handle(s, "Schedule:Constant", "Schedule Value", name)
            if handle < 0:
                raise RuntimeError(f"Required actuator unavailable: {name}")
            handles["actuator_" + key] = handle
        write_json(output / "bindings.json", {"zone": ZONE, "handles": handles, "variables": variable_specs, "meters": meters})

    def read(s):
        data = {key: api.exchange.get_variable_value(s, handles[key]) for key in variable_specs}
        data.update({key: api.exchange.get_meter_value(s, handles[key]) for key in meters})
        electric_lux = controls.light_fraction*600 if not calibration else max(0, calibration["illuminance"]["intercept"] + calibration["illuminance"]["slope"]*controls.light_fraction) if controls.light_fraction else 0
        data.update(minute=len(observations)*5, electric_illuminance_lux=electric_lux,
                    total_illuminance_lux=max(0, data["daylight_lux"])+electric_lux)
        data["daylight_lux"] = max(0, data["daylight_lux"])
        data.update({"control_"+k: v for k, v in controls.model_dump().items()})
        return finite_observation(data)

    def before(s):
        nonlocal controls, initial
        try:
            if (output / "cancel.request").exists():
                raise RuntimeError("Cancelled by user")
            if time.perf_counter() - started > 3600:
                raise RuntimeError("Experiment exceeded the one-hour wall-clock limit")
            if not active(s):
                return
            bind(s)
            if initial is None:
                initial = read(s)
                write_json(output / "initial_observation.json", initial)
            if (len(observations)*5) % request.control_interval_minutes == 0:
                controls, trace = controller.propose(read(s))
                traces.append(trace)
                with (output / "control_trace.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(trace, ensure_ascii=False, allow_nan=False) + "\n")
            for key, value in controls.model_dump().items():
                if key == "light_fraction" and calibration:
                    full = calibration["power"]["intercept"] + calibration["power"]["slope"]
                    value = max(0, calibration["power"]["intercept"] + calibration["power"]["slope"]*value)/full
                api.exchange.set_actuator_value(s, handles["actuator_"+key], float(value))
            if api.exchange.api_error_flag(s):
                raise RuntimeError("EnergyPlus data-transfer API error")
        except Exception as exc:
            errors.append(str(exc))
            api.runtime.stop_simulation(s)

    def after(s):
        try:
            if not active(s) or not handles or errors:
                return
            obs = read(s)
            obs["minute"] = (len(observations)+1)*5
            observations.append(obs)
            with (output / "observations.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(obs, ensure_ascii=False, allow_nan=False) + "\n")
            if len(observations) % 12 == 0:
                write_json(output / "status.json", {"status": "running", "phase": "simulating", "samples": len(observations),
                    "expected_samples": request.days*288, "latest": obs})
        except Exception as exc:
            errors.append(str(exc))
            api.runtime.stop_simulation(s)

    api.runtime.callback_begin_zone_timestep_after_init_heat_balance(state, before)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, after)
    exit_code = api.runtime.run_energyplus(state, ["-w", str(weather), "-d", str(engine_output), str(model_path)])
    api.state_manager.delete_state(state)
    engine_errors = (engine_output / "eplusout.err").read_text(encoding="utf-8", errors="replace")
    severe = len(re.findall(r"\*\*\s+Severe\s+\*\*", engine_errors))
    if exit_code or severe or errors or len(observations) != request.days*288:
        raise RuntimeError(f"Engine/control failed: exit={exit_code}, severe={severe}, samples={len(observations)}, errors={errors}")
    accounting = reconcile_energy(engine_output / "eplusout.sql", observations)
    (output / "observations.jsonl").replace(output / "raw_callback_observations.jsonl")
    (output / "observations.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, allow_nan=False) + "\n" for x in observations), encoding="utf-8")
    write_json(output / "accounting_audit.json", accounting)
    with (output / "observations.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(observations[0]))
        writer.writeheader()
        writer.writerows(observations)
    summary = {**summarize(observations, request), "controller": request.controller, "request": request.model_dump(),
        "wall_clock_runtime_seconds": time.perf_counter()-started, "control_count": len(traces),
        "control_latency_ms_mean": sum(x["wall_clock_latency_ms"] for x in traces)/len(traces),
        "initial_observation_sha256": sha(output / "initial_observation.json"),
        "initial_state_fingerprint": hashlib.sha256(json.dumps(initial, sort_keys=True).encode()).hexdigest(),
        "engine_exit_code": exit_code, "severe_error_count": severe,
        "accounting": accounting, "provenance": provenance,
        "boundary": "software physical simulation with declared synthetic inputs; no field savings claim"}
    write_json(output / "summary.json", summary)
    write_json(output / "status.json", {"status": "completed", "phase": "completed", "samples": len(observations), "summary": summary})
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.config.resolve())
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except Exception as exc:
        write_json(args.config.parent / "status.json", {"status": "cancelled" if (args.config.parent / "cancel.request").exists() else "failed", "error": str(exc)})
        traceback.print_exc()
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
