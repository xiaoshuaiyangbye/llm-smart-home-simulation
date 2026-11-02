import { expect, test } from "vitest";
import { moveWithinHome, roomAtPosition } from "./homeMovement";

test("屋外坐标不冒充走廊，连续向外移动始终留在户型内", () => {
  expect(roomAtPosition({ x: -7, z: 0 })).toBeNull();
  let position = { x: -4.45, z: 0.55 };
  for (let i = 0; i < 100; i++) position = moveWithinHome(position, { ...position, x: position.x - .42 });
  expect(roomAtPosition(position)).toBe("living_room");
  expect(position.x).toBeGreaterThan(-6.45);
});

test("实体墙阻挡正常/加速移动，已有门洞可通行", () => {
  const from = { x: -4.45, z: -1.05 };
  expect(moveWithinHome(from, { ...from, z: -1.47 })).toEqual(from);
  const door = { x: -3.1, z: -1.05 };
  expect(roomAtPosition(moveWithinHome(door, { ...door, z: -1.47 }))).toBe("bedroom");
  const passage = { x: -2.7, z: .55 };
  expect(roomAtPosition(moveWithinHome(passage, { x: -2.28, z: .55 }))).toBe("dining_room");
});
