import hashlib
import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

from app.energyplus.contracts import RunRequest

ROOT = Path(__file__).resolve().parents[3]
ZONE = "ZONE ONE"
SCHEDULES = {
    "light_fraction": "AgentLightPower", "cooling_setpoint_c": "AgentCoolTarget",
    "heating_setpoint_c": "AgentHeatTarget", "hvac_enabled": "AgentHVACEnabled",
    "ventilation_fraction": "AgentVentilation", "window_fraction": "AgentWindow",
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_directory():
    configured = os.getenv("ENERGYPLUS_HOME")
    if configured:
        path = Path(configured)
        if (path / "energyplus.exe").is_file() or (path / "energyplus").is_file():
            return path.resolve()
        raise ValueError("ENERGYPLUS_HOME does not contain an EnergyPlus executable")
    found = sorted((ROOT / ".runtime" / "energyplus" / "26.2.0").glob("*/energyplus.exe"))
    if not found:
        raise FileNotFoundError("EnergyPlus unavailable; run scripts/setup_energyplus.py")
    return found[0].parent


def build_model(request: RunRequest, output: Path, calibration=None):
    runtime = runtime_directory()
    source = ROOT / "data" / "energyplus" / "references" / "1ZoneUncontrolled.idf"
    converted = output / "reference"
    converted.mkdir(parents=True)
    executable = runtime / ("energyplus.exe" if os.name == "nt" else "energyplus")
    conversion = subprocess.run([str(executable), "--convert-only", "-d", str(converted), str(source)],
                                capture_output=True, text=True, check=True)
    (converted / "conversion.log").write_text(conversion.stdout + conversion.stderr, encoding="utf-8")
    model = json.loads(next(converted.glob("*.epJSON")).read_text(encoding="utf-8"))
    zone = next(iter(model["Zone"]))
    if zone.upper() != ZONE:
        raise ValueError("Unexpected reference zone")
    # Transform the documented 232m2 test box into an explicitly uncalibrated 5x4x3m room.
    all_vertices = [v for obj in model["BuildingSurface:Detailed"].values() for v in obj["vertices"]]
    extent = {axis: max(v[f"vertex_{axis}_coordinate"] for v in all_vertices) for axis in "xyz"}
    for obj in model["BuildingSurface:Detailed"].values():
        for v in obj["vertices"]:
            for axis, target in zip("xyz", (5, 4, 3)):
                v[f"vertex_{axis}_coordinate"] *= target / extent[axis]
    for key in ("floor_area", "volume", "ceiling_height"):
        model["Zone"][zone].pop(key, None)
    for key in list(model):
        if key.startswith(("Output:", "SizingPeriod:", "Exterior:")) or key in {"RunPeriod", "Lights", "People", "ElectricEquipment", "OtherEquipment", "ZoneInfiltration:DesignFlowRate"}:
            model.pop(key)
    model["Timestep"] = {"": {"number_of_timesteps_per_hour": 12}}
    model["SimulationControl"] = {"": {"do_zone_sizing_calculation": "No", "do_system_sizing_calculation": "No",
        "do_plant_sizing_calculation": "No", "run_simulation_for_sizing_periods": "No",
        "run_simulation_for_weather_file_run_periods": "Yes"}}
    start = date(2020, 7 if request.season == "summer" else 1, 21)
    end = start + timedelta(days=request.days - 1)
    model["RunPeriod"] = {"AgentRun": {"begin_month": start.month, "begin_day_of_month": start.day,
        "end_month": end.month, "end_day_of_month": end.day, "day_of_week_for_start_day": "Monday",
        "use_weather_file_holidays_and_special_days": "No", "use_weather_file_daylight_saving_period": "No"}}
    model["Schedule:Constant"] = {name: {"hourly_value": value} for name, value in {
        **{n: 0 for n in SCHEDULES.values()}, "AgentCoolTarget": 25, "AgentHeatTarget": 20,
        "AgentHVACEnabled": 1, "AgentVentilation": 0.25,
        "AgentThermostatType": 4, "AgentOutdoorCO2": 430, "AgentActivity": 120,
        "AgentCoolingCOP": 3.2, "AgentHeatingEfficiency": 1}.items()}
    model["Schedule:Compact"] = {"AgentOccupancy": {"data": [{"field": x} for x in
        ["Through: 12/31", "For: AllDays", "Until: 08:00", 0, "Until: 18:00", 1, "Until: 24:00", 0]]}}
    model.setdefault("ScheduleTypeLimits", {})["AgentAnyNumber"] = {"numeric_type": "Continuous"}
    for schedules in (model["Schedule:Constant"], model["Schedule:Compact"]):
        for schedule in schedules.values():
            schedule["schedule_type_limits_name"] = "AgentAnyNumber"
    model["People"] = {"AgentPeople": {"zone_or_zonelist_or_space_or_spacelist_name": zone,
        "number_of_people_schedule_name": "AgentOccupancy", "number_of_people_calculation_method": "People",
        "number_of_people": 2, "fraction_radiant": 0.3, "activity_level_schedule_name": "AgentActivity",
        "carbon_dioxide_generation_rate": 3.82e-8}}
    lamp_power = 200 if not calibration else max(1, calibration["power"]["intercept"] + calibration["power"]["slope"])
    model["Lights"] = {"AgentLights": {"zone_or_zonelist_or_space_or_spacelist_name": zone,
        "schedule_name": "AgentLightPower", "design_level_calculation_method": "LightingLevel",
        "lighting_level": lamp_power, "fraction_radiant": 0.4, "fraction_visible": 0.2,
        "fraction_replaceable": 1, "end_use_subcategory": "ResearchLighting"}}
    model["ZoneAirContaminantBalance"] = {"": {"carbon_dioxide_concentration": "Yes",
        "outdoor_carbon_dioxide_schedule_name": "AgentOutdoorCO2"}}
    model["ZoneVentilation:DesignFlowRate"] = {"AgentMechanicalVentilation": {
        "zone_or_zonelist_or_space_or_spacelist_name": zone, "schedule_name": "AgentVentilation",
        "design_flow_rate_calculation_method": "Flow/Zone", "design_flow_rate": 0.06,
        "ventilation_type": "Intake", "fan_pressure_rise": 100, "fan_total_efficiency": 0.5,
        "constant_term_coefficient": 1, "minimum_indoor_temperature": -100, "maximum_indoor_temperature": 100,
        "delta_temperature": -100, "minimum_outdoor_temperature": -100, "maximum_outdoor_temperature": 100}}
    model["ZoneVentilation:WindandStackOpenArea"] = {"AgentOpenWindow": {"zone_or_space_name": zone,
        "opening_area": 1, "opening_area_fraction_schedule_name": "AgentWindow", "opening_effectiveness": 0.5,
        "effective_angle": 180, "height_difference": 1.5, "discharge_coefficient_for_opening": 0.6,
        "minimum_indoor_temperature": -100, "maximum_indoor_temperature": 100,
        "delta_temperature": -100, "minimum_outdoor_temperature": -100, "maximum_outdoor_temperature": 100}}
    model["ZoneHVAC:EquipmentConnections"] = {"AgentConnections": {"zone_name": zone,
        "zone_conditioning_equipment_list_name": "AgentEquipment", "zone_air_inlet_node_or_nodelist_name": "AgentSupply",
        "zone_air_exhaust_node_or_nodelist_name": "AgentExhaust",
        "zone_air_node_name": "AgentZoneAir", "zone_return_air_node_or_nodelist_name": "AgentReturn"}}
    model["ZoneHVAC:EquipmentList"] = {"AgentEquipment": {"load_distribution_scheme": "SequentialLoad", "equipment": [{
        "zone_equipment_object_type": "ZoneHVAC:IdealLoadsAirSystem", "zone_equipment_name": "AgentIdeal",
        "zone_equipment_cooling_sequence": 1, "zone_equipment_heating_or_no_load_sequence": 1}]}}
    model["ZoneHVAC:IdealLoadsAirSystem"] = {"AgentIdeal": {"availability_schedule_name": "AgentHVACEnabled",
        "zone_supply_air_node_name": "AgentSupply", "zone_exhaust_air_node_name": "AgentExhaust",
        "maximum_heating_supply_air_temperature": 50, "minimum_cooling_supply_air_temperature": 13,
        "heating_limit": "NoLimit", "cooling_limit": "NoLimit", "dehumidification_control_type": "None",
        "humidification_control_type": "None", "cooling_fuel_type": "Electricity",
        "cooling_fuel_efficiency_schedule_name": "AgentCoolingCOP", "heating_fuel_type": "Electricity",
        "heating_fuel_efficiency_schedule_name": "AgentHeatingEfficiency"}}
    model["ZoneControl:Thermostat"] = {"AgentThermostat": {"zone_or_zonelist_name": zone,
        "control_type_schedule_name": "AgentThermostatType", "control_1_object_type": "ThermostatSetpoint:DualSetpoint",
        "control_1_name": "AgentDualSetpoint"}}
    model["ThermostatSetpoint:DualSetpoint"] = {"AgentDualSetpoint": {
        "heating_setpoint_temperature_schedule_name": "AgentHeatTarget",
        "cooling_setpoint_temperature_schedule_name": "AgentCoolTarget"}}
    model["WindowMaterial:SimpleGlazingSystem"] = {"AgentGlass": {"u_factor": 2.7,
        "solar_heat_gain_coefficient": 0.6, "visible_transmittance": 0.7}}
    model.setdefault("Construction", {})["AgentGlazing"] = {"outside_layer": "AgentGlass"}
    south = next(name for name, obj in model["BuildingSurface:Detailed"].items()
                 if obj["surface_type"] == "Wall" and all(abs(v["vertex_y_coordinate"]) < 1e-8 for v in obj["vertices"]))
    window = {"surface_type": "Window", "construction_name": "AgentGlazing", "building_surface_name": south,
              "number_of_vertices": 4}
    for index, point in enumerate(((1, 0, 2.5), (1, 0, 1), (4, 0, 1), (4, 0, 2.5)), 1):
        for axis, value in zip("xyz", point):
            window[f"vertex_{index}_{axis}_coordinate"] = value
    model["FenestrationSurface:Detailed"] = {"AgentSouthWindow": window}
    model["Daylighting:ReferencePoint"] = {"AgentDesk": {"zone_or_space_name": zone,
        "x_coordinate_of_reference_point": 2.5, "y_coordinate_of_reference_point": 2,
        "z_coordinate_of_reference_point": 0.8}}
    model["Daylighting:Controls"] = {"AgentDaylight": {"zone_or_space_name": zone,
        "daylighting_method": "SplitFlux", "lighting_control_type": "Continuous",
        "glare_calculation_daylighting_reference_point_name": "AgentDesk",
        "control_data": [{"daylighting_reference_point_name": "AgentDesk",
            "fraction_of_lights_controlled_by_reference_point": 0, "illuminance_setpoint_at_reference_point": 500}]}}
    model["Output:Variable"] = {f"Observation{i}": {"key_value": "*", "variable_name": name,
        "reporting_frequency": "Timestep"} for i, name in enumerate([
            "Zone Mean Air Temperature", "Zone Air Relative Humidity", "Zone Air CO2 Concentration",
            "Daylighting Reference Point 1 Illuminance", "Zone Lights Electricity Rate",
            "Zone Ideal Loads Supply Air Total Cooling Energy", "Zone Ideal Loads Supply Air Total Heating Energy",
            "Site Outdoor Air Drybulb Temperature", "Zone People Occupant Count"])}
    model["Output:Meter"] = {f"Energy{i}": {"key_name": name, "reporting_frequency": "Timestep"}
                            for i, name in enumerate(["Electricity:Facility", "Cooling:Electricity", "Heating:Electricity", "Fans:Electricity", "InteriorLights:Electricity"])}
    model["Output:SQLite"] = {"": {"option_type": "SimpleAndTabular"}}
    path = output / "single_room.epJSON"
    path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    weather = Path(os.getenv("ENERGYPLUS_WEATHER_FILE", str(runtime / "WeatherData" / "USA_CO_Golden-NREL.724666_TMY3.epw")))
    provenance = {"engine": "EnergyPlus", "version": "26.2.0", "runtime": str(runtime),
        "spatial_scope": "single_room", "room_count": 1,
        "model_sha256": sha(path), "reference_sha256": sha(source), "weather_sha256": sha(weather),
        "weather_name": weather.name, "geometry_m": [5, 4, 3], "zone_step_minutes": 5,
        "calibration": calibration or {"status": "uncalibrated", "full_power_w": 200, "full_lamp_lux": 600},
        "co2_scope": "well-mixed zone CO2 mass balance, not PM2.5/VOC",
        "hvac_scope": "ideal-loads system, configured modeled fuel efficiency/COP; not calibrated DX equipment",
        "boundary": "uncalibrated example physical simulation, not a measured residence"}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return path, weather, provenance
