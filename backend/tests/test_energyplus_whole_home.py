import json

import pytest

from app.energyplus.contracts import Controls, RunRequest
from app.energyplus.controllers import map_actions
from app.energyplus.model import runtime_directory
from app.energyplus.runner import run
from app.energyplus.spatial import area, inventory, split_edges


def test_layout_covers_every_room_without_overlap_and_has_paired_walls():
    layout, rooms = inventory()
    assert len(rooms) == 9
    # Sample each rectangular cell induced by the polygon vertices: no positive-area overlaps.
    def contains(poly, x, y):
        return sum((a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]
                   for a, b in zip(poly, poly[1:]+poly[:1]) if a[1] != b[1]) % 2 == 1
    polygons = layout["polygons"]
    xs = sorted({p[0] for poly in polygons.values() for p in poly})
    ys = sorted({p[1] for poly in polygons.values() for p in poly})
    for a, b in zip(xs, xs[1:]):
        for c, d in zip(ys, ys[1:]):
            assert sum(contains(poly, (a+b)/2, (c+d)/2) for poly in polygons.values()) <= 1
    edges = split_edges(polygons)
    paired = [(rid, a, b) for rid, a, b in edges if any(r != rid and x == b and y == a for r, x, y in edges)]
    assert len(paired) >= 16
    assert sum(area(r["polygon"]) for r in rooms) > 90


def test_bedroom_action_is_room_specific_and_inventory_constrained():
    action = {"entity_id": "light.bedroom_main", "action": "turn_on", "parameters": {}}
    previous = Controls(light_fraction=0)
    changed, accepted, denied = map_actions([action], previous, "bedroom", {"light.bedroom_main"})
    assert changed.light_fraction == 1 and accepted and not denied
    unchanged, accepted, denied = map_actions([action], previous, "living_room", {"light.living_room_main"})
    assert unchanged == previous and not accepted and denied


def test_harness_receives_all_rooms_and_maps_whole_home_lights(tmp_path):
    from app.energyplus.whole_controller import WholeController
    _, rooms = inventory()
    bindings = {r["room_id"]: {"devices": r["devices"], "capabilities": sorted({d["device_type"] for d in r["devices"]}),
        "exterior_windows": [], "full_lamp_lux": 600} for r in rooms}
    request = RunRequest(controller="harness_mock", user_command="打开所有房间的灯")
    controller = WholeController(request, tmp_path, bindings)
    obs = {"minute": 0, "outdoor_temperature_c": 25, "rooms": {
        rid: {"temperature_c": 25, "relative_humidity_pct": 50, "total_illuminance_lux": 0,
              "daylight_lux": 0, "occupants": 0, "co2_ppm": 430} for rid in bindings}}
    controls, trace = controller.propose(obs)
    assert len(controls) == 9
    assert all(c.light_fraction > 0 for c in controls.values())
    assert {a["entity_id"] for a in trace["mapped_actions"]} == {f"light.{rid}_main" for rid in bindings}


def test_trace_diagnostics_counts_room_guard_events(tmp_path):
    import importlib.util
    from app.energyplus.model import ROOT
    spec = importlib.util.spec_from_file_location("eplus_comparison", ROOT / "scripts/run_energyplus_experiment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [{"guard_interventions": [{"room_id": "bedroom", "guard": "co2_ventilation"},
                                    {"room_id": "living_room", "guard": "co2_ventilation"}]},
            {"window_hvac_guard_intervention": True}]
    (tmp_path / "control_trace.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    result = module.trace_diagnostics(tmp_path)
    assert result["co2_guard_intervention_count"] == 2
    assert result["window_hvac_guard_intervention_count"] == 1


def test_real_whole_home_room_controls_and_conservation(tmp_path):
    try:
        runtime_directory()
    except FileNotFoundError:
        pytest.skip("Pinned EnergyPlus runtime not installed")
    summaries = []
    for label, fraction in (("off", 0), ("bedroom_on", 1)):
        output = tmp_path / label
        output.mkdir()
        off = Controls(light_fraction=0, hvac_enabled=False, ventilation_fraction=0)
        request = RunRequest(controller="manual", manual_controls=off,
            manual_room_controls={"bedroom": off.model_copy(update={"light_fraction": fraction})})
        (output / "config.json").write_text(json.dumps({"request": request.model_dump()}), encoding="utf-8")
        summary = run(output / "config.json")
        assert summary["room_count"] == 9 and summary["sample_count"] == 288
        assert summary["room_sample_count"] == 2592
        assert summary["severe_error_count"] == 0
        assert summary["accounting"]["room_facility_max_interval_difference_j"] < 1e-4
        assert all(r["sample_count"] == 288 for r in summary["room_summaries"].values())
        obs = json.loads((output / "observations.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        assert len(obs["rooms"]) == 9
        assert obs["rooms"]["living_room"]["control_light_fraction"] == 0
        assert obs["rooms"]["bedroom"]["control_light_fraction"] == fraction
        assert len({round(r["temperature_c"], 3) for r in obs["rooms"].values()}) > 1
        model = json.loads((output / "whole_home.epJSON").read_text(encoding="utf-8"))
        assert len(model["Zone"]) == 9
        assert len(model["ZoneHVAC:IdealLoadsAirSystem"]) == 4
        for name, surface in model["BuildingSurface:Detailed"].items():
            if surface["outside_boundary_condition"] == "Surface":
                other = model["BuildingSurface:Detailed"][surface["outside_boundary_condition_object"]]
                assert other["outside_boundary_condition_object"] == name
        summaries.append(summary)
    assert summaries[0]["initial_state_fingerprint"] == summaries[1]["initial_state_fingerprint"]
    assert summaries[1]["room_summaries"]["bedroom"]["modeled_lighting_kwh"] > summaries[0]["room_summaries"]["bedroom"]["modeled_lighting_kwh"]
    assert summaries[1]["room_summaries"]["living_room"]["modeled_lighting_kwh"] == 0
