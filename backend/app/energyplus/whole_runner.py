"""Multi-zone runtime: independent room observations, shared physical engine."""
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time

from app.energyplus.contracts import Controls, finite_observation
from app.energyplus.model import runtime_directory, sha
from app.energyplus.runner import summarize, write_json
from app.energyplus.whole_controller import WholeController
from app.energyplus.whole_model import build_whole_model

FACILITY_METERS = {"electricity_step_j": "Electricity:Facility", "lighting_step_j": "InteriorLights:Electricity",
                   "cooling_electricity_step_j": "Cooling:Electricity", "heating_electricity_step_j": "Heating:Electricity"}


def reconcile_home(database, observations, bindings):
    diagnostics = {}
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        def series(name, key=None):
            rows = connection.execute("""SELECT r.Value,t.Interval,d.Units FROM ReportData r
                JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex)
                WHERE upper(d.Name)=upper(?) AND (? IS NULL OR upper(d.KeyValue)=upper(?))
                AND d.ReportingFrequency='Zone Timestep' AND t.WarmupFlag=0 ORDER BY t.TimeIndex""", (name, key, key)).fetchall()
            if len(rows) != len(observations) or any(dt != 5 or unit != "J" for _, dt, unit in rows):
                raise ValueError(f"Invalid room/facility SQL grid: {name}/{key}: {len(rows)}")
            return [v for v, _, _ in rows]

        def apply(name, field, target, key=None, thermal=False):
            values = series(name, key)
            maximum = max(abs(row[field]-v) for row, v in zip(target, values))
            if not thermal and maximum > 1e-5:
                raise ValueError(f"API/SQL electricity mismatch: {name}: {maximum}")
            if min(values) < -1e-8:
                raise ValueError(f"Negative energy: {name}")
            for row, v in zip(target, values):
                row[field] = max(0, v)
            diagnostics[f"{key or name}/{field}"] = {"api_sql_max_interval_difference_j": maximum, "sql_sum_j": sum(values)}

        for field, name in FACILITY_METERS.items():
            apply(name, field, observations)
        for rid, binding in bindings.items():
            target = [o["rooms"][rid] for o in observations]
            apply(f"Electricity:Zone:{rid}", "zone_base_electricity_step_j", target)
            for field, name in [("cooling_thermal_step_j", "Zone Ideal Loads Supply Air Total Cooling Energy"),
                                ("heating_thermal_step_j", "Zone Ideal Loads Supply Air Total Heating Energy")]:
                if binding["hvac_key"]:
                    apply(name, field, target, binding["hvac_key"], thermal=True)
            for field, name in [("cooling_electricity_step_j", "Zone Ideal Loads Supply Air Total Cooling Fuel Energy"),
                                ("heating_electricity_step_j", "Zone Ideal Loads Supply Air Total Heating Fuel Energy")]:
                if binding["hvac_key"]:
                    apply(name, field, target, binding["hvac_key"], thermal=True)
            for row in target:
                row["electricity_step_j"] = row["zone_base_electricity_step_j"] + row["cooling_electricity_step_j"] + row["heating_electricity_step_j"]
        residual = max(abs(o["electricity_step_j"]-sum(r["electricity_step_j"] for r in o["rooms"].values())) for o in observations)
        if residual > 1e-4:
            raise ValueError(f"Room/facility electricity conservation failed: {residual} J")
    return {"canonical_energy_source": "EnergyPlus SQLite Zone Timestep, J, excluding warmup",
            "room_facility_max_interval_difference_j": residual, "series": diagnostics}


def run_whole_home(config_path, request, calibration=None):
    output = config_path.parent
    from app.energyplus.spatial import inventory
    room_ids = set(inventory()[0]["polygons"])
    if request.current_room_id not in room_ids or set(request.manual_room_controls) - room_ids:
        raise ValueError("Request references a room outside the designed home")
    write_json(output / "status.json", {"status": "running", "phase": "building_whole_home", "samples": 0})
    model, weather, provenance, bindings = build_whole_model(request, output, calibration)
    if request.current_room_id not in bindings:
        raise ValueError("Current room is not in the designed home")
    sys.path.insert(0, str(runtime_directory()))
    from pyenergyplus.api import EnergyPlusAPI
    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    api.runtime.set_console_output_status(state, False)
    controller = WholeController(request, output, bindings, calibration)
    # Same warmup controls for every controller: independent of the experiment policy.
    controls = {rid: Controls(hvac_enabled=True, ventilation_fraction=0.25) for rid in bindings}
    variables = {"outdoor_temperature_c": ("Site Outdoor Air Drybulb Temperature", "ENVIRONMENT")}
    for rid, binding in bindings.items():
        for field, name in [("temperature_c", "Zone Mean Air Temperature"),
                            ("relative_humidity_pct", "Zone Air Relative Humidity"),
                            ("co2_ppm", "Zone Air CO2 Concentration"), ("occupants", "Zone People Occupant Count"),
                            ("lighting_power_w", "Zone Lights Electricity Rate")]:
            variables[f"{rid}/{field}"] = name, rid
        if binding["daylight_key"]:
            variables[f"{rid}/daylight_lux"] = "Daylighting Reference Point 1 Illuminance", binding["daylight_key"]
        if binding["hvac_key"]:
            for field, name in [("cooling_thermal_step_j", "Zone Ideal Loads Supply Air Total Cooling Energy"),
                                ("heating_thermal_step_j", "Zone Ideal Loads Supply Air Total Heating Energy"),
                                ("cooling_electricity_step_j", "Zone Ideal Loads Supply Air Total Cooling Fuel Energy"),
                                ("heating_electricity_step_j", "Zone Ideal Loads Supply Air Total Heating Fuel Energy")]:
                variables[f"{rid}/{field}"] = name, binding["hvac_key"]
    meters = {**FACILITY_METERS, **{f"{rid}/zone_base_electricity_step_j": f"Electricity:Zone:{rid}" for rid in bindings}}
    for name, key in variables.values():
        api.exchange.request_variable(state, name, key)
    handles, observations, traces, errors = {}, [], [], []
    initial = None
    start = time.perf_counter()
    engine_output = output / "engine"
    engine_output.mkdir()

    def active(s):
        return api.exchange.api_data_fully_ready(s) and not api.exchange.warmup_flag(s) and api.exchange.kind_of_sim(s) == 3

    def bind(s):
        if handles:
            return
        catalog = [{k: getattr(x, k) for k in ("what", "name", "key", "type", "unit")} for x in api.exchange.get_api_data(s)]
        write_json(output / "available_api_data.json", catalog)
        for field, (name, key) in variables.items():
            handles[field] = api.exchange.get_variable_handle(s, name, key)
        for field, name in meters.items():
            handles[field] = api.exchange.get_meter_handle(s, name)
        for rid, binding in bindings.items():
            for field, name in binding["schedules"].items():
                handles[f"{rid}/actuator_{field}"] = api.exchange.get_actuator_handle(s, "Schedule:Constant", "Schedule Value", name)
        missing = [k for k, h in handles.items() if h < 0]
        if missing:
            raise RuntimeError(f"Required whole-home bindings unavailable: {missing}")
        write_json(output / "bindings.json", {"handles": handles, "variables": variables, "meters": meters, "rooms": bindings})

    def read(s):
        values = {key: api.exchange.get_variable_value(s, handles[key]) for key in variables}
        values.update({key: api.exchange.get_meter_value(s, handles[key]) for key in meters})
        obs = {"minute": len(observations)*5, "outdoor_temperature_c": values["outdoor_temperature_c"],
               **{k: values[k] for k in FACILITY_METERS}, "rooms": {}}
        for rid, binding in bindings.items():
            row = {k.split("/", 1)[1]: v for k, v in values.items() if k.startswith(rid + "/")}
            row.setdefault("daylight_lux", 0)
            row["daylight_lux"] = max(0, row["daylight_lux"])
            light = controls[rid].light_fraction
            lamp = light*binding["full_lamp_lux"] if not calibration or rid != request.current_room_id else max(0,
                calibration["illuminance"]["intercept"]+calibration["illuminance"]["slope"]*light) if light else 0
            row.update(minute=obs["minute"], outdoor_temperature_c=obs["outdoor_temperature_c"],
                electric_illuminance_lux=lamp, total_illuminance_lux=row["daylight_lux"]+lamp,
                lighting_step_j=row["lighting_power_w"]*300,
                **{"control_"+k: v for k, v in controls[rid].model_dump().items()})
            row.setdefault("cooling_thermal_step_j", 0)
            row.setdefault("heating_thermal_step_j", 0)
            row.setdefault("cooling_electricity_step_j", 0)
            row.setdefault("heating_electricity_step_j", 0)
            row["electricity_step_j"] = row["zone_base_electricity_step_j"] + row["cooling_electricity_step_j"] + row["heating_electricity_step_j"]
            obs["rooms"][rid] = finite_observation(row)
        return finite_observation(obs)

    def before(s):
        nonlocal controls, initial
        try:
            if not active(s):
                return
            if (output / "cancel.request").exists():
                raise RuntimeError("Cancelled by user")
            if time.perf_counter()-start > 3600:
                raise RuntimeError("Experiment exceeded one-hour wall-clock limit")
            bind(s)
            if initial is None:
                initial = read(s)
                write_json(output / "initial_observation.json", initial)
            if len(observations)*5 % request.control_interval_minutes == 0:
                controls, trace = controller.propose(read(s))
                traces.append(trace)
                with (output / "control_trace.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(trace, ensure_ascii=False, allow_nan=False)+"\n")
            for rid, control in controls.items():
                for field, value in control.model_dump().items():
                    if field == "light_fraction" and calibration and rid == request.current_room_id:
                        full = calibration["power"]["intercept"]+calibration["power"]["slope"]
                        value = max(0, calibration["power"]["intercept"]+calibration["power"]["slope"]*value)/full if value else 0
                    api.exchange.set_actuator_value(s, handles[f"{rid}/actuator_{field}"], float(value))
            if api.exchange.api_error_flag(s):
                raise RuntimeError("EnergyPlus whole-home data-transfer API error")
        except Exception as exc:
            errors.append(str(exc))
            api.runtime.stop_simulation(s)

    def after(s):
        try:
            if not active(s) or not handles or errors:
                return
            obs = read(s)
            obs["minute"] = (len(observations)+1)*5
            for room in obs["rooms"].values():
                room["minute"] = obs["minute"]
            observations.append(obs)
            with (output / "raw_callback_observations.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(obs, ensure_ascii=False, allow_nan=False)+"\n")
            if len(observations) % 12 == 0:
                write_json(output / "status.json", {"status": "running", "phase": "simulating_whole_home",
                    "samples": len(observations), "room_count": len(bindings)})
        except Exception as exc:
            errors.append(str(exc))
            api.runtime.stop_simulation(s)

    api.runtime.callback_begin_zone_timestep_after_init_heat_balance(state, before)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, after)
    exit_code = api.runtime.run_energyplus(state, ["-w", str(weather), "-d", str(engine_output), str(model)])
    api.state_manager.delete_state(state)
    engine_errors = (engine_output / "eplusout.err").read_text(encoding="utf-8", errors="replace")
    severe = len(re.findall(r"\*\*\s+Severe\s+\*\*", engine_errors))
    if exit_code or severe or errors or len(observations) != request.days*288:
        raise RuntimeError(f"Whole-home engine/control failed: exit={exit_code}, severe={severe}, samples={len(observations)}, errors={errors}")
    accounting = reconcile_home(engine_output / "eplusout.sql", observations, bindings)
    write_json(output / "accounting_audit.json", accounting)
    room_summaries = {rid: {"name": binding["name"], "area_m2": binding["area_m2"],
        **summarize([o["rooms"][rid] for o in observations], request)} for rid, binding in bindings.items()}
    all_rooms = [room for obs in observations for room in obs["rooms"].values()]
    summary = summarize(all_rooms, request)
    summary.update(sample_count=len(observations), elapsed_simulation_minutes=len(observations)*5,
        spatial_scope="whole_home", room_count=len(bindings), room_sample_count=len(all_rooms),
        room_summaries=room_summaries, controller=request.controller, request=request.model_dump(),
        wall_clock_runtime_seconds=time.perf_counter()-start, control_count=len(traces),
        control_latency_ms_mean=sum(t["wall_clock_latency_ms"] for t in traces)/len(traces),
        initial_observation_sha256=sha(output / "initial_observation.json"),
        initial_state_fingerprint=hashlib.sha256(json.dumps(initial, sort_keys=True).encode()).hexdigest(),
        engine_exit_code=exit_code, severe_error_count=severe, accounting=accounting, provenance=provenance,
        boundary="nine-zone uncalibrated physical software simulation; no field savings claim")
    # Facility meter is authoritative for global totals; never multiply it by room count.
    for field in FACILITY_METERS:
        target = {"electricity_step_j": "modeled_electricity_kwh", "lighting_step_j": "modeled_lighting_kwh",
                  "cooling_electricity_step_j": "modeled_cooling_electricity_kwh", "heating_electricity_step_j": "modeled_heating_electricity_kwh"}[field]
        summary[target] = sum(o[field] for o in observations)/3600000
    (output / "observations.jsonl").write_text("".join(json.dumps(o, ensure_ascii=False, allow_nan=False)+"\n" for o in observations), encoding="utf-8")
    with (output / "observations.csv").open("w", encoding="utf-8", newline="") as stream:
        rows = [{"room_id": rid, **row} for obs in observations for rid, row in obs["rooms"].items()]
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(output / "summary.json", summary)
    write_json(output / "status.json", {"status": "completed", "phase": "completed", "samples": len(observations), "summary": summary})
    return summary
