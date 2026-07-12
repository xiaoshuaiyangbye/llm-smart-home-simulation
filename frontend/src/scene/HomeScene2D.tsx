import { Line, Text } from "@react-three/drei";

import type { RoomId, SmartHomeState } from "../types/state";
import {
  WALL_THICKNESS,
  floorPlanBounds,
  furniture,
  openings,
  rooms,
  splitWall,
  wallRuns,
  type FloorKind,
  type FurniturePlan,
  type OpeningPlan,
  type RoomPlan,
  type WallOrientation,
} from "../data/floorPlan";

interface HomeScene2DProps {
  state: SmartHomeState;
  avatarPosition: { x: number; z: number };
  currentRoomId: RoomId;
  avatarVisible: boolean;
  sceneLayer: "sensors" | "devices" | "structure";
  onSelect: (value: string) => void;
}

const colors = {
  paper: "#fbf8f1",
  wall: "#393a37",
  tile: "#f3eee5",
  tileLine: "#ddd5c9",
  woodA: "#edc78f",
  woodB: "#dfb16e",
  woodLine: "#bb8550",
  label: "#0b4a6a",
  glass: "#31bfdf",
  furnitureStroke: "#967c62",
};

export function HomeScene2D({
  avatarPosition,
  currentRoomId,
  avatarVisible,
}: HomeScene2DProps) {
  return (
    <group scale={[0.94, 0.94, 0.94]} position={[0, 0, -0.05]}>
      <PlanPaper />
      {rooms.map((room) => (
        <RoomFloor2D key={room.id} room={room} active={room.id === currentRoomId} />
      ))}
      <Furniture2D />
      <Walls2D />
      <Openings2D />
      {rooms.filter((room) => room.showLabel !== false).map((room) => (
        <RoomLabel2D key={`${room.id}-label`} room={room} />
      ))}
      {avatarVisible && <Avatar2D position={avatarPosition} />}
    </group>
  );
}

function PlanPaper() {
  return (
    <mesh position={[floorPlanBounds.center[0], -0.045, floorPlanBounds.center[1]]}>
      <boxGeometry args={[floorPlanBounds.size[0] + 0.72, 0.03, floorPlanBounds.size[1] + 0.64]} />
      <meshBasicMaterial color={colors.paper} />
    </mesh>
  );
}

function RoomFloor2D({ room, active }: { room: RoomPlan; active: boolean }) {
  return (
    <group position={[room.x, 0, room.z]}>
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[room.width, 0.026, room.depth]} />
        <meshBasicMaterial color={room.floor === "wood" ? colors.woodA : colors.tile} />
      </mesh>
      <FloorPattern2D floor={room.floor} width={room.width} depth={room.depth} />
      {active && (
        <mesh position={[0, 0.035, 0]}>
          <boxGeometry args={[room.width * 0.92, 0.01, room.depth * 0.9]} />
          <meshBasicMaterial color="#0d9a87" transparent opacity={0.1} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}

function FloorPattern2D({ floor, width, depth }: { floor: FloorKind; width: number; depth: number }) {
  const isWood = floor === "wood";
  const xCount = Math.max(4, Math.floor(width / (isWood ? 0.42 : 0.58)));
  const zCount = Math.max(3, Math.floor(depth / (isWood ? 0.72 : 0.58)));
  return (
    <group position={[0, 0.024, 0]}>
      {isWood &&
        Array.from({ length: xCount }, (_, index) => {
          const x = -width / 2 + (index + 0.5) * (width / xCount);
          return (
            <mesh key={`wood-fill-${index}`} position={[x, 0, 0]}>
              <boxGeometry args={[width / xCount - 0.018, 0.005, depth * 0.98]} />
              <meshBasicMaterial color={index % 2 ? colors.woodA : colors.woodB} transparent opacity={0.44} />
            </mesh>
          );
        })}
      {Array.from({ length: xCount - 1 }, (_, index) => {
        const x = -width / 2 + (index + 1) * (width / xCount);
        return (
          <mesh key={`x-${index}`} position={[x, 0.004, 0]}>
            <boxGeometry args={[0.011, 0.006, depth * 0.98]} />
            <meshBasicMaterial color={isWood ? colors.woodLine : colors.tileLine} transparent opacity={isWood ? 0.36 : 0.68} />
          </mesh>
        );
      })}
      {Array.from({ length: zCount - 1 }, (_, index) => {
        const z = -depth / 2 + (index + 1) * (depth / zCount);
        return (
          <mesh key={`z-${index}`} position={[0, 0.005, z]}>
            <boxGeometry args={[width * 0.98, 0.006, 0.011]} />
            <meshBasicMaterial color={isWood ? colors.woodLine : colors.tileLine} transparent opacity={isWood ? 0.22 : 0.68} />
          </mesh>
        );
      })}
    </group>
  );
}

function Walls2D() {
  return (
    <group>
      {wallRuns.map((run) =>
        splitWall(run).map(([start, end], index) => (
          <WallSegment2D key={`${run.id}-${index}`} orientation={run.orientation} fixed={run.orientation === "h" ? run.z1 : run.x1} start={start} end={end} />
        )),
      )}
    </group>
  );
}

function WallSegment2D({ orientation, fixed, start, end }: { orientation: WallOrientation; fixed: number; start: number; end: number }) {
  const length = end - start;
  const center = (start + end) / 2;
  const position: [number, number, number] = orientation === "h" ? [center, 0.12, fixed] : [fixed, 0.12, center];
  const size: [number, number, number] = orientation === "h" ? [length, 0.08, WALL_THICKNESS] : [WALL_THICKNESS, 0.08, length];
  return (
    <mesh position={position}>
      <boxGeometry args={size} />
      <meshBasicMaterial color={colors.wall} />
    </mesh>
  );
}

function Openings2D() {
  return (
    <group>
      {openings.filter((item) => item.kind === "window" || item.kind === "glass").map((opening) => (
        <WindowLine2D key={opening.id} opening={opening} />
      ))}
      {openings.filter((item) => item.kind === "door" || item.kind === "entry").map((opening) => (
        <Door2D key={opening.id} opening={opening} />
      ))}
    </group>
  );
}

function WindowLine2D({ opening }: { opening: OpeningPlan }) {
  const horizontal = opening.orientation === "h";
  const frameSize: [number, number, number] = horizontal ? [opening.width + 0.14, 0.07, 0.045] : [0.045, 0.07, opening.width + 0.14];
  const glassSize: [number, number, number] = horizontal ? [opening.width, 0.08, 0.055] : [0.055, 0.08, opening.width];
  return (
    <group position={[opening.x, 0.22, opening.z]}>
      <mesh>
        <boxGeometry args={frameSize} />
        <meshBasicMaterial color="#f4fbff" />
      </mesh>
      <mesh position={[0, 0.015, 0]}>
        <boxGeometry args={glassSize} />
        <meshBasicMaterial color={colors.glass} transparent opacity={opening.kind === "glass" ? 0.86 : 0.75} />
      </mesh>
    </group>
  );
}

function Door2D({ opening }: { opening: OpeningPlan }) {
  const isEntry = opening.kind === "entry";
  const radius = isEntry ? 0.72 : 0.58;
  const rotation = opening.orientation === "h" ? 0 : Math.PI / 2;
  const leafOffset = opening.orientation === "h"
    ? [opening.swing === "right" ? radius / 2 : -radius / 2, 0] as [number, number]
    : [0, opening.swing === "right" ? radius / 2 : -radius / 2] as [number, number];
  return (
    <group>
      <mesh position={[opening.x + leafOffset[0], 0.24, opening.z + leafOffset[1]]} rotation={[0, rotation, 0]}>
        <boxGeometry args={[radius, 0.035, 0.034]} />
        <meshBasicMaterial color={isEntry ? "#c27614" : "#515654"} transparent opacity={isEntry ? 0.95 : 0.62} />
      </mesh>
      <Line points={doorArcPoints(opening, radius)} color={isEntry ? "#c27614" : "#515654"} lineWidth={1.5} />
      {isEntry && (
        <group position={[opening.x, 0.3, opening.z - 0.22]} rotation={[-Math.PI / 2, 0, 0]}>
          <mesh renderOrder={20}>
            <coneGeometry args={[0.18, 0.28, 3]} />
            <meshBasicMaterial color="#d07812" depthTest={false} />
          </mesh>
          <Text position={[0, -0.24, 0.012]} fontSize={0.22} color="#2b2722" anchorX="center" anchorY="middle" renderOrder={21}>
            入户门
          </Text>
        </group>
      )}
    </group>
  );
}

function doorArcPoints(opening: OpeningPlan, radius: number): Array<[number, number, number]> {
  const start = opening.orientation === "h" ? (opening.swing === "right" ? Math.PI : 0) : (opening.swing === "right" ? -Math.PI / 2 : Math.PI / 2);
  const end = start + (opening.swing === "right" ? Math.PI / 2 : -Math.PI / 2);
  return Array.from({ length: 20 }, (_, index) => {
    const t = index / 19;
    const angle = start + (end - start) * t;
    return [opening.x + Math.cos(angle) * radius, 0.28, opening.z + Math.sin(angle) * radius];
  });
}

function Furniture2D() {
  return (
    <group>
      {furniture.map((item) => (
        <FurnitureItem2D key={item.id} item={item} />
      ))}
    </group>
  );
}

function FurnitureItem2D({ item }: { item: FurniturePlan }) {
  const rotation: [number, number, number] = [0, item.rotation ?? 0, 0];
  if (item.type === "coffeeTable" || item.type === "plant" || item.type === "toilet") {
    const color = item.type === "plant" ? "#68a554" : item.type === "toilet" ? "#f8f8f3" : "#fff9ef";
    return <PlanCircle item={item} color={color} />;
  }
  if (item.type === "sink") return <Sink2D item={item} />;
  if (item.type === "cooktop") return <Cooktop2D item={item} />;
  if (item.type === "washer") return <Washer2D item={item} />;
  if (item.type === "shower" || item.type === "glassRail") return <PlanBox item={item} color="#bfe7f7" opacity={0.62} rotation={rotation} />;
  if (item.type === "rug") return <PlanBox item={item} color="#eadfce" opacity={0.85} rotation={rotation} noStroke />;
  if (item.type === "bed") return <PlanBox item={item} color={item.variant === "duvet" ? "#eadbc7" : "#f6eadc"} rotation={rotation} stroke="#9e7b5d" />;
  if (item.type === "nightstand") return <PlanBox item={item} color={item.variant === "pillow" ? "#fffaf3" : "#b88956"} rotation={rotation} />;
  if (item.type === "sofa") return <PlanBox item={item} color="#eee0ce" rotation={rotation} stroke="#b89f82" />;
  if (item.type === "diningTable") return <PlanBox item={item} color="#fbf6ed" rotation={rotation} stroke="#9a7f61" />;
  if (item.type === "diningChair" || item.type === "chair") return <PlanBox item={item} color="#ceb99c" rotation={rotation} />;
  if (item.type === "tvConsole") return <PlanBox item={item} color="#8b633e" rotation={rotation} />;
  if (item.type === "fridge") return <PlanBox item={item} color="#dedbd4" rotation={rotation} />;
  if (item.type === "bookcase" || item.type === "wardrobe" || item.type === "desk" || item.type === "cabinet" || item.type === "vanity") {
    return <PlanBox item={item} color={item.type === "desk" || item.type === "bookcase" ? "#9c724b" : "#f0e9df"} rotation={rotation} />;
  }
  return <PlanBox item={item} color="#e7dccd" rotation={rotation} />;
}

function PlanBox({ item, color, rotation, stroke = colors.furnitureStroke, opacity = 1, noStroke = false }: { item: FurniturePlan; color: string; rotation: [number, number, number]; stroke?: string; opacity?: number; noStroke?: boolean }) {
  return (
    <group position={[item.x, 0.08, item.z]} rotation={rotation}>
      <mesh>
        <boxGeometry args={[item.width, 0.035, item.depth]} />
        <meshBasicMaterial color={color} transparent={opacity < 1} opacity={opacity} />
      </mesh>
      {!noStroke && (
        <>
          <mesh position={[0, 0.021, -item.depth / 2]}>
            <boxGeometry args={[item.width, 0.008, 0.018]} />
            <meshBasicMaterial color={stroke} transparent opacity={0.36} />
          </mesh>
          <mesh position={[0, 0.021, item.depth / 2]}>
            <boxGeometry args={[item.width, 0.008, 0.018]} />
            <meshBasicMaterial color={stroke} transparent opacity={0.36} />
          </mesh>
          <mesh position={[-item.width / 2, 0.021, 0]}>
            <boxGeometry args={[0.018, 0.008, item.depth]} />
            <meshBasicMaterial color={stroke} transparent opacity={0.36} />
          </mesh>
          <mesh position={[item.width / 2, 0.021, 0]}>
            <boxGeometry args={[0.018, 0.008, item.depth]} />
            <meshBasicMaterial color={stroke} transparent opacity={0.36} />
          </mesh>
        </>
      )}
    </group>
  );
}

function PlanCircle({ item, color }: { item: FurniturePlan; color: string }) {
  return (
    <mesh position={[item.x, 0.1, item.z]} rotation={[-Math.PI / 2, 0, 0]}>
      <circleGeometry args={[Math.max(item.width, item.depth) / 2, 42]} />
      <meshBasicMaterial color={color} />
    </mesh>
  );
}

function Sink2D({ item }: { item: FurniturePlan }) {
  return (
    <group position={[item.x, 0.11, item.z]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[Math.min(item.width, item.depth) * 0.2, Math.min(item.width, item.depth) * 0.36, 32]} />
        <meshBasicMaterial color="#b9c8cc" />
      </mesh>
      <mesh position={[0.12, 0.02, -0.06]}>
        <boxGeometry args={[0.16, 0.012, 0.035]} />
        <meshBasicMaterial color="#879195" />
      </mesh>
    </group>
  );
}

function Cooktop2D({ item }: { item: FurniturePlan }) {
  return (
    <group position={[item.x, 0.11, item.z]}>
      {[-0.12, 0.12].map((x) => (
        <mesh key={x} position={[x, 0, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.07, 0.12, 28]} />
          <meshBasicMaterial color="#242424" />
        </mesh>
      ))}
    </group>
  );
}

function Washer2D({ item }: { item: FurniturePlan }) {
  return (
    <group position={[item.x, 0.1, item.z]}>
      <mesh>
        <boxGeometry args={[item.width, 0.035, item.depth]} />
        <meshBasicMaterial color={item.variant === "dark" ? "#d4d8da" : "#eceeed"} />
      </mesh>
      <mesh position={[0, 0.03, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.12, 0.2, 32]} />
        <meshBasicMaterial color={item.variant === "dark" ? "#1f2831" : "#607a87"} />
      </mesh>
    </group>
  );
}

function RoomLabel2D({ room }: { room: RoomPlan }) {
  return (
    <group position={[room.x, 0.32, room.z]} rotation={[-Math.PI / 2, 0, 0]}>
      <mesh renderOrder={30}>
        <planeGeometry args={[0.92, 0.36]} />
        <meshBasicMaterial color={colors.label} transparent opacity={0.96} depthTest={false} />
      </mesh>
      <Text position={[0, 0, 0.012]} fontSize={0.21} color="#ffffff" anchorX="center" anchorY="middle" renderOrder={31}>
        {room.label}
      </Text>
    </group>
  );
}

function Avatar2D({ position }: { position: { x: number; z: number } }) {
  return (
    <group position={[position.x, 0.34, position.z]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.13, 28]} />
        <meshBasicMaterial color="#1d6fb8" />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.16, 0.23, 32]} />
        <meshBasicMaterial color="#1d6fb8" transparent opacity={0.2} />
      </mesh>
    </group>
  );
}
