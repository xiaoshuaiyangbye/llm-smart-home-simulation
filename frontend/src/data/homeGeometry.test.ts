import { describe, expect, it } from "vitest";
import { containsPoint, homeGeometry } from "./homeGeometry";

describe("shared physical home geometry", () => {
  it("covers nine spaces with no overlapping floor tiles", () => {
    expect(homeGeometry).toHaveLength(9);
    const tiles = homeGeometry.flatMap((room) => room.tiles);
    for (let i = 0; i < tiles.length; i++) {
      for (let j = i + 1; j < tiles.length; j++) {
        const a = tiles[i], b = tiles[j];
        const overlapX = Math.min(a.x + a.width / 2, b.x + b.width / 2) - Math.max(a.x - a.width / 2, b.x - b.width / 2);
        const overlapZ = Math.min(a.z + a.depth / 2, b.z + b.depth / 2) - Math.max(a.z - a.depth / 2, b.z - b.depth / 2);
        expect(overlapX > 1e-8 && overlapZ > 1e-8).toBe(false);
      }
    }
  });
  it("separates the dining room from the corridor and places room avatars inside their zone", () => {
    const dining = homeGeometry.find((r) => r.id === "dining_room")!;
    const corridor = homeGeometry.find((r) => r.id === "corridor")!;
    expect(containsPoint(dining.polygon, 0, 3)).toBe(false);
    expect(containsPoint(corridor.polygon, 0, 3)).toBe(true);
    for (const room of homeGeometry) expect(containsPoint(room.polygon, room.x, room.z)).toBe(true);
  });
});
