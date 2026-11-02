import layout from "../../../data/energyplus/home_layout.json";
import type { RoomId } from "../types/state";

export function containsPoint(polygon: number[][], x: number, z: number): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if ((a[1] > z) !== (b[1] > z) && x < (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

export const homeGeometry = Object.entries(layout.polygons).map(([id, polygon]) => {
  const xs = [...new Set(polygon.map((p) => p[0]))].sort((a, b) => a - b);
  const zs = [...new Set(polygon.map((p) => p[1]))].sort((a, b) => a - b);
  const tiles: Array<{ x: number; z: number; width: number; depth: number }> = [];
  for (let i = 0; i < xs.length - 1; i++) {
    for (let j = 0; j < zs.length - 1; j++) {
      const x = (xs[i] + xs[i + 1]) / 2, z = (zs[j] + zs[j + 1]) / 2;
      if (containsPoint(polygon, x, z)) tiles.push({ x, z, width: xs[i + 1] - xs[i], depth: zs[j + 1] - zs[j] });
    }
  }
  return { id: id as RoomId, polygon, tiles,
    x: polygon.reduce((s, p) => s + p[0], 0) / polygon.length,
    z: polygon.reduce((s, p) => s + p[1], 0) / polygon.length,
    width: xs[xs.length - 1] - xs[0], depth: zs[zs.length - 1] - zs[0] };
});
