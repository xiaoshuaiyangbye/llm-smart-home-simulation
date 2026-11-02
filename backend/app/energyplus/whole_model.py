"""One building, nine thermal zones derived from the designed floor plan."""
import copy
import json
import math

from app.energyplus.model import ROOT, SCHEDULES, ZONE, build_model, sha
from app.energyplus.spatial import FLOOR_PLAN, LAYOUT, area, inventory, plan_openings, room_capabilities, split_edges


def renamed(value, room):
    if isinstance(value, str):
        return value.replace(ZONE.title(), room).replace(ZONE, room).replace("Zone One", room).replace("Agent", room + "_")
    if isinstance(value, list):
        return [renamed(x, room) for x in value]
    if isinstance(value, dict):
        return {renamed(k, room): renamed(v, room) for k, v in value.items()}
    return value


def vertices(points):
    return [{f"vertex_{axis}_coordinate": float(value) for axis, value in zip("xyz", point)} for point in points]


def build_whole_model(request, output, calibration=None):
    # Reuse the pinned official construction library and weather/run-period contract.
    template_dir = output / "single_room_template"
    template_dir.mkdir()
    path, weather, provenance = build_model(request, template_dir, None)
    template = json.loads(path.read_text(encoding="utf-8"))
    layout, rooms = inventory()
    height = layout["height_m"]
    model = copy.deepcopy(template)
    per_zone = ["Zone", "People", "Lights", "ZoneVentilation:DesignFlowRate", "ZoneVentilation:WindandStackOpenArea",
                "ZoneHVAC:EquipmentConnections", "ZoneHVAC:EquipmentList", "ZoneHVAC:IdealLoadsAirSystem",
                "ZoneControl:Thermostat", "ThermostatSetpoint:DualSetpoint", "Daylighting:ReferencePoint",
                "Daylighting:Controls", "Schedule:Constant", "Schedule:Compact"]
    for kind in per_zone + ["BuildingSurface:Detailed", "FenestrationSurface:Detailed"]:
        model[kind] = {}
    model["GlobalGeometryRules"] = {"": {"starting_vertex_position": "UpperLeftCorner",
        "vertex_entry_direction": "Counterclockwise", "coordinate_system": "World"}}
    # Shared CO2 background must refer to a global schedule, not a room-local copy.
    model["Schedule:Constant"]["AgentOutdoorCO2"] = {"hourly_value": 430, "schedule_type_limits_name": "AgentAnyNumber"}
    model["Schedule:Constant"]["HomeMixing"] = {"hourly_value": 1, "schedule_type_limits_name": "AgentAnyNumber"}
    wall_construction = next(x["construction_name"] for x in template["BuildingSurface:Detailed"].values() if x["surface_type"] == "Wall")
    floor_construction = next(x["construction_name"] for x in template["BuildingSurface:Detailed"].values() if x["surface_type"] == "Floor")
    roof_construction = next(x["construction_name"] for x in template["BuildingSurface:Detailed"].values() if x["surface_type"] == "Roof")
    # Symmetric internal construction makes reverse-facing paired walls physically consistent.
    model.setdefault("Material:NoMass", {})["HomePartitionMaterial"] = {
        "roughness": "MediumSmooth", "thermal_resistance": 0.4,
        "thermal_absorptance": 0.9, "solar_absorptance": 0.6, "visible_absorptance": 0.6}
    model["Construction"]["HomePartition"] = {"outside_layer": "HomePartitionMaterial"}
    model["Construction:AirBoundary"] = {"HomeOpenBoundary": {"air_exchange_method": "None"}}
    bindings = {}
    for room in rooms:
        rid = room["room_id"]
        caps = room_capabilities(room)
        for kind in per_zone:
            if kind.startswith(("Daylighting:",)):
                continue
            if kind.startswith(("ZoneHVAC:", "ZoneControl:", "ThermostatSetpoint:")) and "ac" not in caps:
                continue
            if kind == "ZoneVentilation:DesignFlowRate" and "fan" not in caps:
                continue
            if kind == "ZoneVentilation:WindandStackOpenArea":
                continue  # Added only after a genuine exterior opening is found.
            model[kind].update(renamed(template[kind], rid))
        for schedules in (model["Schedule:Constant"], model["Schedule:Compact"]):
            for schedule in schedules.values():
                schedule["schedule_type_limits_name"] = "AgentAnyNumber"
        zone = next(iter(renamed(template["Zone"], rid)))
        if zone != rid:
            raise ValueError(f"Unexpected template zone spelling: {zone}")
        poly = [(x, -z) for x, z in room["polygon"]][::-1]
        model["Zone"][rid] = {"direction_of_relative_north": 0, "x_origin": 0, "y_origin": 0,
            "z_origin": 0, "type": 1, "multiplier": 1, "ceiling_height": height,
            "floor_area": area(room["polygon"]), "volume": area(room["polygon"])*height}
        for kind, points, construction, boundary in [
            ("Floor", [(x, y, 0) for x, y in reversed(poly)], floor_construction, "Ground"),
            ("Roof", [(x, y, height) for x, y in poly], roof_construction, "Outdoors")]:
            model["BuildingSurface:Detailed"][f"{rid}_{kind}"] = {
                "surface_type": kind, "zone_name": rid, "construction_name": construction,
                "outside_boundary_condition": boundary, "sun_exposure": "SunExposed" if kind == "Roof" else "NoSun",
                "wind_exposure": "WindExposed" if kind == "Roof" else "NoWind",
                "number_of_vertices": len(points), "vertices": vertices(points)}
        # Keep the historical synthetic occupancy only in the selected occupied room;
        # other rooms still have independent modeled states and controllable equipment.
        model["People"][f"{rid}_People"]["number_of_people"] = 2 if rid == request.current_room_id else 0
        light = next(d for d in room["devices"] if d["device_type"] == "light")
        if calibration and rid == request.current_room_id:
            model["Lights"][f"{rid}_Lights"]["lighting_level"] = max(1, calibration["power"]["intercept"]+calibration["power"]["slope"])
        bindings[rid] = {"zone": rid, "name": room["name"], "area_m2": area(room["polygon"]),
            "schedules": {k: name.replace("Agent", rid + "_") for k, name in SCHEDULES.items()},
            "daylight_key": None, "hvac_key": f"{rid}_Ideal" if "ac" in caps else None,
            "exterior_windows": [], "capabilities": sorted(caps), "devices": room["devices"],
            "full_lamp_lux": light["max_lux_contribution"]}
    edges = split_edges(layout["polygons"])
    names = {(rid, a, b): f"{rid}_Wall_{i}" for i, (rid, a, b) in enumerate(edges)}
    for rid, a, b in edges:
        neighbor = next(((r, c, d) for r, c, d in edges if r != rid and c == b and d == a), None)
        # Polygon coordinates are clockwise after z -> -y; reverse each edge for outward normals.
        ax, ay = a[0], -a[1]
        bx, by = b[0], -b[1]
        obj = {"surface_type": "Wall", "zone_name": rid,
            "construction_name": "HomePartition" if neighbor else wall_construction,
            "outside_boundary_condition": "Surface" if neighbor else "Outdoors",
            "sun_exposure": "NoSun" if neighbor else "SunExposed",
            "wind_exposure": "NoWind" if neighbor else "WindExposed", "number_of_vertices": 4,
            "vertices": vertices([(bx, by, 0), (ax, ay, 0), (ax, ay, height), (bx, by, height)])}
        if neighbor:
            obj["outside_boundary_condition_object"] = names[neighbor]
            if {rid, neighbor[0]} == {"dining_room", "corridor"}:
                obj["construction_name"] = "HomeOpenBoundary"
        model["BuildingSurface:Detailed"][names[(rid, a, b)]] = obj
    # Locate the existing windows/glass on the physical exterior, not on room display boxes.
    for opening in plan_openings():
        kind = opening["kind"].strip('"')
        if kind not in {"window", "glass"}:
            continue
        x, z, width = (float(opening[k]) for k in ("x", "z", "width"))
        horizontal = opening["orientation"] == '"h"'
        for rid, a, b in edges:
            surface = model["BuildingSurface:Detailed"][names[(rid, a, b)]]
            if surface["outside_boundary_condition"] != "Outdoors":
                continue
            lo, hi = sorted((a[0], b[0]) if horizontal else (a[1], b[1]))
            coord, fixed, edge_fixed = (x, z, a[1]) if horizontal else (z, x, a[0])
            if abs(fixed-edge_fixed) > 1e-6 or (a[1] != b[1]) == horizontal or not lo < coord < hi:
                continue
            half = min(width/2, coord-lo-0.02, hi-coord-0.02)
            if half <= 0:
                raise ValueError("Opening does not fit physical wall")
            start, end = coord-half, coord+half
            pa, pb = ((start, z), (end, z)) if horizontal else ((x, start), (x, end))
            if (b[0]-a[0]) + (b[1]-a[1]) > 0:
                pa, pb = pb, pa
            points = [(pa[0], -pa[1], 0.9), (pb[0], -pb[1], 0.9),
                      (pb[0], -pb[1], 2.4), (pa[0], -pa[1], 2.4)]
            win = {"surface_type": "Window", "construction_name": "AgentGlazing",
                "building_surface_name": names[(rid, a, b)], "number_of_vertices": 4}
            for i, point in enumerate(points, 1):
                for axis, value in zip("xyz", point):
                    win[f"vertex_{i}_{axis}_coordinate"] = value
            name = opening["id"].strip('"')
            model["FenestrationSurface:Detailed"][name] = win
            bindings[rid]["exterior_windows"].append(name)
            break
    for room in rooms:
        rid, poly = room["room_id"], room["polygon"]
        if not bindings[rid]["exterior_windows"]:
            continue
        ref, control = f"{rid}_Desk", f"{rid}_Daylight"
        model["Daylighting:ReferencePoint"][ref] = {"zone_or_space_name": rid,
            "x_coordinate_of_reference_point": sum(p[0] for p in poly)/len(poly),
            "y_coordinate_of_reference_point": -sum(p[1] for p in poly)/len(poly), "z_coordinate_of_reference_point": 0.8}
        model["Daylighting:Controls"][control] = {"zone_or_space_name": rid, "daylighting_method": "SplitFlux",
            "lighting_control_type": "Continuous", "glare_calculation_daylighting_reference_point_name": ref,
            "control_data": [{"daylighting_reference_point_name": ref,
                              "fraction_of_lights_controlled_by_reference_point": 0, "illuminance_setpoint_at_reference_point": 500}]}
        bindings[rid]["daylight_key"] = control
        for index, window_name in enumerate(bindings[rid]["exterior_windows"]):
            window = model["FenestrationSurface:Detailed"][window_name]
            wall = model["BuildingSurface:Detailed"][window["building_surface_name"]]
            v1, v2 = wall["vertices"][:2]
            dx = v2["vertex_x_coordinate"]-v1["vertex_x_coordinate"]
            dy = v2["vertex_y_coordinate"]-v1["vertex_y_coordinate"]
            azimuth = math.degrees(math.atan2(dy, -dx)) % 360
            width = math.hypot(window["vertex_2_x_coordinate"]-window["vertex_1_x_coordinate"],
                               window["vertex_2_y_coordinate"]-window["vertex_1_y_coordinate"])
            obj = next(iter(renamed(template["ZoneVentilation:WindandStackOpenArea"], rid).values()))
            obj.update(opening_area=width*1.5, effective_angle=azimuth)
            model["ZoneVentilation:WindandStackOpenArea"][f"{rid}_OpenWindow_{index}"] = obj
    # Open living/dining, dining/kitchen and dining/corridor passages exchange air.
    # Fixed flow is a declared sensitivity parameter, not measured door airflow.
    model["ZoneCrossMixing"] = {f"HomePassage{i}": {"zone_or_space_name": a,
        "source_zone_or_space_name": b, "schedule_name": "HomeMixing",
        "design_flow_rate_calculation_method": "Flow/Zone", "design_flow_rate": 0.05,
        "delta_temperature": 0} for i, (a, b) in enumerate([
            ("living_room", "dining_room"), ("dining_room", "kitchen"), ("dining_room", "corridor")])}
    # Room meters allow room/facility conservation checks without counting facility energy nine times.
    for i, name in enumerate(["Zone Ideal Loads Supply Air Total Heating Fuel Energy",
                              "Zone Ideal Loads Supply Air Total Cooling Fuel Energy"]):
        model["Output:Variable"][f"HomeFuel{i}"] = {"key_value": "*", "variable_name": name, "reporting_frequency": "Timestep"}
    for i, name in enumerate([f"Electricity:Zone:{r['room_id']}" for r in rooms]):
        model["Output:Meter"][f"HomeRoom{i}"] = {"key_name": name, "reporting_frequency": "Timestep"}
    model_path = output / "whole_home.epJSON"
    model_path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    provenance.update(spatial_scope="whole_home", room_count=len(rooms), room_ids=list(bindings),
        model_sha256=sha(model_path), layout_sha256=sha(LAYOUT), floor_plan_sha256=sha(FLOOR_PLAN),
        room_config_sha256=sha(ROOT / "backend/app/config/rooms.yaml"),
        device_config_sha256=sha(ROOT / "backend/app/config/devices.yaml"),
        calibration=calibration or {"status": "uncalibrated"},
        calibration_room_id=request.current_room_id if calibration else None,
        unsupported_device_scope="Curtains have no physical actuator; dining/corridor configured windows have no exterior opening and are rejected. Fan models mechanical ventilation, not room air-speed comfort.",
        ground_temperature_scope="EnergyPlus default 18 C ground boundary, not measured soil temperature",
        code_sha256={name: sha(ROOT / "backend/app/energyplus" / name) for name in ["whole_model.py", "whole_runner.py", "whole_controller.py", "controllers.py", "spatial.py", "contracts.py"]},
        geometry_m=None, height_m=height, floor_area_m2=sum(b["area_m2"] for b in bindings.values()),
        layout=layout, occupancy_scope=f"synthetic 2 persons 08:00-18:00 in {request.current_room_id}; other rooms unoccupied",
        mixing_scope="0.05 m3/s fixed bidirectional cross-mixing on three open passages; closed doors elsewhere",
        boundary="designed whole-home geometry with declared assumptions; uncalibrated software simulation")
    (output / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "spatial_bindings.json").write_text(json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8")
    return model_path, weather, provenance, bindings
