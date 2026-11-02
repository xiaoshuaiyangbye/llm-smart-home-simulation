"""Designed-home topology and explicit room-to-actuator inventory."""
import json
import re

import yaml

from app.energyplus.model import ROOT

LAYOUT = ROOT / "data/energyplus/home_layout.json"
FLOOR_PLAN = ROOT / "frontend/src/data/floorPlan.ts"


def plan_openings():
    text = FLOOR_PLAN.read_text(encoding="utf-8").split("export const openings:")[1].split("];", 1)[0]
    return [dict(re.findall(r'(\w+):\s*("[^"]*"|-?\d+(?:\.\d+)?)', row))
            for row in re.findall(r'\{([^{}]+)\}', text)]


def inventory():
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    rooms = yaml.safe_load((ROOT / "backend/app/config/rooms.yaml").read_text(encoding="utf-8"))["rooms"]
    devices = yaml.safe_load((ROOT / "backend/app/config/devices.yaml").read_text(encoding="utf-8"))["devices"]
    if {r["room_id"] for r in rooms} != set(layout["polygons"]):
        raise ValueError("EnergyPlus layout must cover exactly the configured rooms")
    return layout, [{**r, "polygon": layout["polygons"][r["room_id"]],
                    "devices": [d for d in devices if d["room"] == r["room_id"]]} for r in rooms]


def area(polygon):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(polygon, polygon[1:]+polygon[:1]))) / 2


def split_edges(polygons):
    """Split all touching wall segments so both sides have identical vertices."""
    points = [p for poly in polygons.values() for p in poly]
    edges = []
    for room, poly in polygons.items():
        for a, b in zip(poly, poly[1:]+poly[:1]):
            axis = 0 if a[1] == b[1] else 1
            candidates = {tuple(p) for p in points if p[1-axis] == a[1-axis]
                          and min(a[axis], b[axis]) <= p[axis] <= max(a[axis], b[axis])}
            ordered = sorted(candidates, key=lambda p: p[axis], reverse=b[axis] < a[axis])
            edges.extend((room, x, y) for x, y in zip(ordered, ordered[1:]))
    return edges


def room_capabilities(room):
    return {d["device_type"] for d in room["devices"]}
