import type { DeviceType, RoomId } from "../types/state";

export type WallOrientation = "h" | "v";
export type OpeningKind = "door" | "entry" | "window" | "glass";
export type FloorKind = "wood" | "tile";
export type FurnitureType =
  | "bed"
  | "nightstand"
  | "wardrobe"
  | "desk"
  | "chair"
  | "bookcase"
  | "sofa"
  | "coffeeTable"
  | "tvConsole"
  | "diningTable"
  | "diningChair"
  | "cabinet"
  | "sink"
  | "cooktop"
  | "fridge"
  | "toilet"
  | "shower"
  | "vanity"
  | "washer"
  | "plant"
  | "glassRail"
  | "rug";

export interface RoomPlan {
  id: RoomId;
  label: string;
  x: number;
  z: number;
  width: number;
  depth: number;
  floor: FloorKind;
  showLabel?: boolean;
}

export interface WallRun {
  id: string;
  orientation: WallOrientation;
  x1: number;
  z1: number;
  x2: number;
  z2: number;
  gaps?: Array<{ center: number; width: number }>;
}

export interface OpeningPlan {
  id: string;
  kind: OpeningKind;
  orientation: WallOrientation;
  x: number;
  z: number;
  width: number;
  swing?: "left" | "right";
  label?: string;
}

export interface FurniturePlan {
  id: string;
  roomId: RoomId;
  type: FurnitureType;
  x: number;
  z: number;
  width: number;
  depth: number;
  rotation?: number;
  color?: string;
  variant?: "dark" | "light" | "round" | "pillow" | "duvet";
}

export interface DevicePointPlan {
  id: string;
  roomId: RoomId;
  type: DeviceType;
  x: number;
  z: number;
}

export const WALL_THICKNESS = 0.16;
export const WALL_HEIGHT = 0.68;

export const rooms: RoomPlan[] = [
  { id: "bedroom", label: "卧室", x: -4.4, z: -2.75, width: 4.0, depth: 2.9, floor: "wood" },
  { id: "study_room", label: "书房", x: -0.5, z: -2.75, width: 3.8, depth: 2.9, floor: "wood" },
  { id: "bathroom", label: "卫生间", x: 2.95, z: -2.75, width: 3.0, depth: 2.9, floor: "tile" },
  { id: "living_room", label: "客厅", x: -4.45, z: 0.55, width: 3.9, depth: 3.6, floor: "tile" },
  { id: "dining_room", label: "餐厅", x: -0.45, z: 1.1, width: 4.1, depth: 4.7, floor: "tile" },
  { id: "kitchen", label: "厨房", x: 3.0, z: 0.65, width: 2.8, depth: 3.8, floor: "tile" },
  { id: "laundry", label: "洗衣区", x: 2.95, z: 3.65, width: 3.0, depth: 2.3, floor: "tile" },
  { id: "balcony", label: "阳台", x: -5.25, z: 3.4, width: 2.2, depth: 2.2, floor: "tile" },
  { id: "corridor", label: "走廊", x: -0.45, z: 3.6, width: 4.1, depth: 2.4, floor: "tile", showLabel: false },
];

export const wallRuns: WallRun[] = [
  { id: "outer-top", orientation: "h", x1: -6.45, z1: -4.2, x2: 4.55, z2: -4.2 },
  { id: "outer-left-main", orientation: "v", x1: -6.45, z1: -4.2, x2: -6.45, z2: 2.35 },
  { id: "outer-left-balcony", orientation: "v", x1: -6.45, z1: 2.35, x2: -6.45, z2: 4.5 },
  { id: "outer-right", orientation: "v", x1: 4.55, z1: -4.2, x2: 4.55, z2: 4.8 },
  { id: "outer-balcony-bottom", orientation: "h", x1: -6.45, z1: 4.5, x2: -4.05, z2: 4.5 },
  { id: "outer-entry-bottom", orientation: "h", x1: -1.55, z1: 4.8, x2: 4.55, z2: 4.8, gaps: [{ center: 0.05, width: 0.95 }] },
  { id: "top-row-bottom", orientation: "h", x1: -6.45, z1: -1.3, x2: 4.55, z2: -1.3, gaps: [{ center: -3.1, width: 0.92 }, { center: -0.55, width: 0.92 }, { center: 2.25, width: 0.88 }] },
  { id: "bed-study", orientation: "v", x1: -2.4, z1: -4.2, x2: -2.4, z2: -1.3 },
  { id: "study-bath", orientation: "v", x1: 1.4, z1: -4.2, x2: 1.4, z2: -1.3 },
  { id: "living-dining", orientation: "v", x1: -2.45, z1: -1.3, x2: -2.45, z2: 2.35, gaps: [{ center: 0.55, width: 1.6 }] },
  { id: "dining-kitchen", orientation: "v", x1: 1.55, z1: -1.3, x2: 1.55, z2: 2.55, gaps: [{ center: 0.65, width: 1.2 }] },
  { id: "kitchen-laundry", orientation: "h", x1: 1.55, z1: 2.55, x2: 4.55, z2: 2.55, gaps: [{ center: 2.55, width: 0.85 }] },
  { id: "balcony-living", orientation: "h", x1: -6.45, z1: 2.35, x2: -4.05, z2: 2.35, gaps: [{ center: -5.25, width: 1.35 }] },
  { id: "balcony-right", orientation: "v", x1: -4.05, z1: 2.35, x2: -4.05, z2: 4.5, gaps: [{ center: 3.25, width: 1.1 }] },
  { id: "laundry-left", orientation: "v", x1: 1.45, z1: 2.55, x2: 1.45, z2: 4.8, gaps: [{ center: 3.55, width: 0.86 }] },
];

export const openings: OpeningPlan[] = [
  { id: "bedroom-door", kind: "door", orientation: "h", x: -3.1, z: -1.3, width: 0.92, swing: "left" },
  { id: "study-door", kind: "door", orientation: "h", x: -0.55, z: -1.3, width: 0.92, swing: "right" },
  { id: "bathroom-door", kind: "door", orientation: "h", x: 2.25, z: -1.3, width: 0.88, swing: "right" },
  { id: "kitchen-door", kind: "door", orientation: "v", x: 1.55, z: 0.65, width: 1.2, swing: "left" },
  { id: "laundry-door", kind: "door", orientation: "v", x: 1.45, z: 3.55, width: 0.86, swing: "right" },
  { id: "balcony-door", kind: "glass", orientation: "h", x: -5.25, z: 2.35, width: 1.35, swing: "left" },
  { id: "entry-door", kind: "entry", orientation: "h", x: 0.05, z: 4.8, width: 0.95, swing: "right", label: "入户门" },
  { id: "bedroom-top-window", kind: "window", orientation: "h", x: -4.8, z: -4.2, width: 1.65 },
  { id: "study-top-window", kind: "window", orientation: "h", x: -0.5, z: -4.2, width: 1.65 },
  { id: "bath-top-window", kind: "window", orientation: "h", x: 3.1, z: -4.2, width: 1.0 },
  { id: "bath-right-window", kind: "window", orientation: "v", x: 4.55, z: -2.65, width: 0.85 },
  { id: "living-left-window", kind: "window", orientation: "v", x: -6.45, z: 0.45, width: 1.55 },
  { id: "kitchen-right-window", kind: "window", orientation: "v", x: 4.55, z: 0.75, width: 1.45 },
  { id: "laundry-bottom-window", kind: "window", orientation: "h", x: 2.8, z: 4.8, width: 1.2 },
  { id: "balcony-left-glass", kind: "glass", orientation: "v", x: -6.45, z: 3.45, width: 1.5 },
  { id: "balcony-bottom-glass", kind: "glass", orientation: "h", x: -5.25, z: 4.5, width: 1.65 },
];

export const furniture: FurniturePlan[] = [
  { id: "bed", roomId: "bedroom", type: "bed", x: -5.3, z: -3.1, width: 1.75, depth: 1.55 },
  { id: "bed-duvet", roomId: "bedroom", type: "bed", x: -5.02, z: -2.98, width: 1.05, depth: 1.2, variant: "duvet" },
  { id: "pillow-left", roomId: "bedroom", type: "nightstand", x: -5.85, z: -3.58, width: 0.38, depth: 0.28, variant: "pillow" },
  { id: "pillow-right", roomId: "bedroom", type: "nightstand", x: -5.25, z: -3.58, width: 0.38, depth: 0.28, variant: "pillow" },
  { id: "bed-nightstand-a", roomId: "bedroom", type: "nightstand", x: -6.08, z: -3.35, width: 0.35, depth: 0.4 },
  { id: "bed-wardrobe", roomId: "bedroom", type: "wardrobe", x: -3.38, z: -1.78, width: 1.65, depth: 0.36 },
  { id: "study-desk", roomId: "study_room", type: "desk", x: -0.55, z: -2.8, width: 1.45, depth: 0.8 },
  { id: "study-chair", roomId: "study_room", type: "chair", x: -0.55, z: -2.1, width: 0.46, depth: 0.46 },
  { id: "study-bookcase", roomId: "study_room", type: "bookcase", x: 0.95, z: -2.75, width: 0.42, depth: 1.85 },
  { id: "living-rug", roomId: "living_room", type: "rug", x: -4.7, z: 0.55, width: 2.35, depth: 1.55 },
  { id: "living-sofa-long", roomId: "living_room", type: "sofa", x: -5.75, z: 0.55, width: 0.62, depth: 2.35 },
  { id: "living-sofa-chaise", roomId: "living_room", type: "sofa", x: -4.85, z: 1.55, width: 1.55, depth: 0.6 },
  { id: "living-coffee", roomId: "living_room", type: "coffeeTable", x: -4.7, z: 0.52, width: 0.85, depth: 0.52 },
  { id: "living-tv-console", roomId: "living_room", type: "tvConsole", x: -2.9, z: 0.55, width: 0.25, depth: 1.55 },
  { id: "dining-table", roomId: "dining_room", type: "diningTable", x: -0.35, z: 0.78, width: 1.25, depth: 0.95 },
  { id: "dining-chair-1", roomId: "dining_room", type: "diningChair", x: -1.15, z: 0.78, width: 0.34, depth: 0.42 },
  { id: "dining-chair-2", roomId: "dining_room", type: "diningChair", x: 0.45, z: 0.78, width: 0.34, depth: 0.42 },
  { id: "dining-chair-3", roomId: "dining_room", type: "diningChair", x: -0.75, z: 0.1, width: 0.38, depth: 0.34 },
  { id: "dining-chair-4", roomId: "dining_room", type: "diningChair", x: 0.05, z: 0.1, width: 0.38, depth: 0.34 },
  { id: "dining-chair-5", roomId: "dining_room", type: "diningChair", x: -0.75, z: 1.46, width: 0.38, depth: 0.34 },
  { id: "dining-chair-6", roomId: "dining_room", type: "diningChair", x: 0.05, z: 1.46, width: 0.38, depth: 0.34 },
  { id: "kitchen-counter-right", roomId: "kitchen", type: "cabinet", x: 4.05, z: 0.45, width: 0.55, depth: 2.6 },
  { id: "kitchen-counter-top", roomId: "kitchen", type: "cabinet", x: 3.1, z: -0.95, width: 1.45, depth: 0.42 },
  { id: "kitchen-sink", roomId: "kitchen", type: "sink", x: 4.05, z: -0.35, width: 0.38, depth: 0.5 },
  { id: "kitchen-cooktop", roomId: "kitchen", type: "cooktop", x: 4.05, z: 0.85, width: 0.42, depth: 0.58 },
  { id: "kitchen-fridge", roomId: "kitchen", type: "fridge", x: 4.05, z: 2.0, width: 0.62, depth: 0.62 },
  { id: "bath-vanity", roomId: "bathroom", type: "vanity", x: 1.95, z: -3.3, width: 0.62, depth: 0.95 },
  { id: "bath-toilet", roomId: "bathroom", type: "toilet", x: 3.0, z: -3.35, width: 0.5, depth: 0.68 },
  { id: "bath-shower", roomId: "bathroom", type: "shower", x: 3.65, z: -2.0, width: 0.72, depth: 0.9 },
  { id: "laundry-washer-a", roomId: "laundry", type: "washer", x: 2.0, z: 4.25, width: 0.52, depth: 0.52 },
  { id: "laundry-washer-b", roomId: "laundry", type: "washer", x: 2.65, z: 4.25, width: 0.52, depth: 0.52, variant: "dark" },
  { id: "laundry-sink", roomId: "laundry", type: "sink", x: 3.25, z: 4.25, width: 0.46, depth: 0.52 },
  { id: "laundry-cabinet", roomId: "laundry", type: "cabinet", x: 3.75, z: 3.15, width: 0.52, depth: 0.95 },
  { id: "balcony-rail", roomId: "balcony", type: "glassRail", x: -5.25, z: 4.2, width: 1.75, depth: 0.08 },
  { id: "balcony-plant-a", roomId: "balcony", type: "plant", x: -6.05, z: 3.95, width: 0.38, depth: 0.38 },
  { id: "balcony-plant-b", roomId: "balcony", type: "plant", x: -4.55, z: 2.9, width: 0.32, depth: 0.32 },
  { id: "living-plant", roomId: "living_room", type: "plant", x: -5.95, z: 1.85, width: 0.32, depth: 0.32 },
  { id: "study-plant", roomId: "study_room", type: "plant", x: 0.85, z: -1.75, width: 0.28, depth: 0.28 },
];

export const devicePoints: DevicePointPlan[] = [
  { id: "living-light", roomId: "living_room", type: "light", x: -4.45, z: 0.45 },
  { id: "bedroom-light", roomId: "bedroom", type: "light", x: -4.4, z: -2.8 },
  { id: "study-light", roomId: "study_room", type: "light", x: -0.45, z: -2.75 },
  { id: "dining-light", roomId: "dining_room", type: "light", x: -0.35, z: 0.8 },
  { id: "kitchen-sensor", roomId: "kitchen", type: "sensor", x: 3.0, z: 0.45 },
  { id: "bath-sensor", roomId: "bathroom", type: "sensor", x: 2.95, z: -2.75 },
];

export const floorPlanBounds = {
  center: [-0.95, 0.3] as [number, number],
  size: [11.6, 9.45] as [number, number],
};

export function splitWall(run: WallRun) {
  const from = run.orientation === "h" ? run.x1 : run.z1;
  const to = run.orientation === "h" ? run.x2 : run.z2;
  const gaps = [...(run.gaps ?? [])].sort((a, b) => a.center - b.center);
  const spans: Array<[number, number]> = [];
  let cursor = from;

  for (const gap of gaps) {
    const start = Math.max(from, gap.center - gap.width / 2);
    const end = Math.min(to, gap.center + gap.width / 2);
    if (start > cursor) spans.push([cursor, start]);
    cursor = Math.max(cursor, end);
  }

  if (cursor < to) spans.push([cursor, to]);
  return spans.filter(([start, end]) => end - start > 0.05);
}
