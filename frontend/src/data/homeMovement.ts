import { containsPoint, homeGeometry } from "./homeGeometry";
import { splitWall, wallRuns, WALL_THICKNESS } from "./floorPlan";

export type HomePosition = { x: number; z: number };

export function roomAtPosition(position: HomePosition) {
  return homeGeometry.find((room) => containsPoint(room.polygon, position.x, position.z))?.id ?? null;
}

/** Swept point vs wall footprint. Door gaps remain traversable; furniture is decorative. */
function hitsWall(from: HomePosition, to: HomePosition): boolean {
  for (const wall of wallRuns) {
    for (const [start, end] of splitWall(wall)) {
      const pad = WALL_THICKNESS / 2;
      const bounds = wall.orientation === "h"
        ? { x: [start, end], z: [wall.z1 - pad, wall.z1 + pad] }
        : { x: [wall.x1 - pad, wall.x1 + pad], z: [start, end] };
      let enter = 0, leave = 1;
      for (const axis of ["x", "z"] as const) {
        const delta = to[axis] - from[axis];
        if (Math.abs(delta) < 1e-10) {
          if (from[axis] < bounds[axis][0] || from[axis] > bounds[axis][1]) { enter = 2; break; }
        } else {
          const first = (bounds[axis][0] - from[axis]) / delta;
          const last = (bounds[axis][1] - from[axis]) / delta;
          enter = Math.max(enter, Math.min(first, last));
          leave = Math.min(leave, Math.max(first, last));
        }
      }
      if (enter <= leave && enter <= 1 && leave >= 0) return true;
    }
  }
  return false;
}

export function moveWithinHome(from: HomePosition, to: HomePosition): HomePosition {
  if (!roomAtPosition(from) || !roomAtPosition(to) || hitsWall(from, to)) return from;
  // Sample the swept path as well as its endpoint to prevent crossing a concave exterior gap.
  const steps = Math.max(1, Math.ceil(Math.hypot(to.x - from.x, to.z - from.z) / 0.04));
  for (let i = 1; i <= steps; i++) {
    if (!roomAtPosition({ x: from.x + (to.x - from.x) * i / steps, z: from.z + (to.z - from.z) * i / steps })) return from;
  }
  return to;
}
