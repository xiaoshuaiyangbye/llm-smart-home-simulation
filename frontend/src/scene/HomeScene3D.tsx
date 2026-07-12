import type { RoomId, SmartHomeState } from "../types/state";
import {
  WALL_HEIGHT,
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

interface HomeScene3DProps {
  state: SmartHomeState;
  avatarPosition: { x: number; z: number };
  currentRoomId: RoomId;
  avatarVisible: boolean;
  sceneLayer: "sensors" | "devices" | "structure";
  onSelect: (value: string) => void;
}

const palette = {
  wall: "#e8e1d6",
  wallInner: "#f3eee6",
  wallCap: "#5b554e",
  tile: "#f1eadf",
  tileLine: "#d8d0c5",
  woodA: "#d7b27d",
  woodB: "#c7985f",
  woodLine: "#9f7345",
  glass: "#9bdcf4",
  cream: "#efe4d5",
  fabric: "#e8dac8",
  darkWood: "#815b37",
};

export function HomeScene3D({
  avatarPosition,
  currentRoomId,
  avatarVisible,
}: HomeScene3DProps) {
  return (
    <group rotation={[0, -0.04, 0]} scale={[0.92, 0.92, 0.92]} position={[0, 0, -0.05]}>
      <ApartmentBase />
      {rooms.map((room) => (
        <RoomFloor3D key={room.id} room={room} active={room.id === currentRoomId} />
      ))}
      <Walls3D />
      <Openings3D />
      <Furniture3D />
      {avatarVisible && <Avatar3D position={avatarPosition} />}
    </group>
  );
}

function ApartmentBase() {
  return (
    <group>
      <mesh receiveShadow position={[floorPlanBounds.center[0], -0.16, floorPlanBounds.center[1]]}>
        <boxGeometry args={[floorPlanBounds.size[0] + 0.72, 0.16, floorPlanBounds.size[1] + 0.65]} />
        <meshStandardMaterial color="#bdb5aa" roughness={0.74} />
      </mesh>
      <mesh receiveShadow position={[floorPlanBounds.center[0], -0.065, floorPlanBounds.center[1]]}>
        <boxGeometry args={[floorPlanBounds.size[0] + 0.44, 0.1, floorPlanBounds.size[1] + 0.38]} />
        <meshStandardMaterial color="#faf6ee" roughness={0.55} />
      </mesh>
    </group>
  );
}

function RoomFloor3D({ room, active }: { room: RoomPlan; active: boolean }) {
  const color = room.floor === "wood" ? palette.woodA : palette.tile;
  return (
    <group position={[room.x, 0, room.z]}>
      <mesh receiveShadow position={[0, 0.015, 0]}>
        <boxGeometry args={[room.width, 0.055, room.depth]} />
        <meshStandardMaterial color={color} roughness={room.floor === "wood" ? 0.5 : 0.42} />
      </mesh>
      <FloorTexture3D floor={room.floor} width={room.width} depth={room.depth} />
      {active && (
        <mesh position={[0, 0.064, 0]}>
          <boxGeometry args={[room.width * 0.92, 0.012, room.depth * 0.9]} />
          <meshBasicMaterial color="#11a391" transparent opacity={0.08} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}

function FloorTexture3D({ floor, width, depth }: { floor: FloorKind; width: number; depth: number }) {
  const isWood = floor === "wood";
  const xCount = Math.max(4, Math.floor(width / (isWood ? 0.42 : 0.58)));
  const zCount = Math.max(3, Math.floor(depth / (isWood ? 0.72 : 0.58)));
  return (
    <group position={[0, 0.052, 0]}>
      {isWood &&
        Array.from({ length: xCount }, (_, index) => {
          const x = -width / 2 + (index + 0.5) * (width / xCount);
          return (
            <mesh key={`wood-${index}`} position={[x, 0, 0]}>
              <boxGeometry args={[width / xCount - 0.022, 0.006, depth * 0.96]} />
              <meshStandardMaterial color={index % 2 ? palette.woodA : palette.woodB} transparent opacity={0.42} roughness={0.72} />
            </mesh>
          );
        })}
      {Array.from({ length: xCount - 1 }, (_, index) => {
        const x = -width / 2 + (index + 1) * (width / xCount);
        return (
          <mesh key={`x-${index}`} position={[x, 0.004, 0]}>
            <boxGeometry args={[0.01, 0.008, depth * 0.96]} />
            <meshStandardMaterial color={isWood ? palette.woodLine : palette.tileLine} transparent opacity={isWood ? 0.22 : 0.5} />
          </mesh>
        );
      })}
      {Array.from({ length: zCount - 1 }, (_, index) => {
        const z = -depth / 2 + (index + 1) * (depth / zCount);
        return (
          <mesh key={`z-${index}`} position={[0, 0.005, z]}>
            <boxGeometry args={[width * 0.96, 0.008, 0.01]} />
            <meshStandardMaterial color={isWood ? palette.woodLine : palette.tileLine} transparent opacity={isWood ? 0.16 : 0.52} />
          </mesh>
        );
      })}
    </group>
  );
}

function Walls3D() {
  return (
    <group>
      {wallRuns.map((run) =>
        splitWall(run).map(([start, end], index) => (
          <WallSegment3D key={`${run.id}-${index}`} orientation={run.orientation} fixed={run.orientation === "h" ? run.z1 : run.x1} start={start} end={end} />
        )),
      )}
    </group>
  );
}

function WallSegment3D({ orientation, fixed, start, end }: { orientation: WallOrientation; fixed: number; start: number; end: number }) {
  const length = end - start;
  const center = (start + end) / 2;
  const wallPosition: [number, number, number] = orientation === "h" ? [center, WALL_HEIGHT / 2, fixed] : [fixed, WALL_HEIGHT / 2, center];
  const capPosition: [number, number, number] = orientation === "h" ? [center, WALL_HEIGHT + 0.04, fixed] : [fixed, WALL_HEIGHT + 0.04, center];
  const wallSize: [number, number, number] = orientation === "h" ? [length, WALL_HEIGHT, WALL_THICKNESS] : [WALL_THICKNESS, WALL_HEIGHT, length];
  const capSize: [number, number, number] = orientation === "h" ? [length + 0.03, 0.06, WALL_THICKNESS + 0.055] : [WALL_THICKNESS + 0.055, 0.06, length + 0.03];
  return (
    <group>
      <mesh castShadow receiveShadow position={wallPosition}>
        <boxGeometry args={wallSize} />
        <meshStandardMaterial color={palette.wall} roughness={0.32} />
      </mesh>
      <mesh castShadow receiveShadow position={capPosition}>
        <boxGeometry args={capSize} />
        <meshStandardMaterial color={palette.wallCap} roughness={0.4} />
      </mesh>
    </group>
  );
}

function Openings3D() {
  return (
    <group>
      {openings.filter((item) => item.kind === "window" || item.kind === "glass").map((opening) => (
        <Window3D key={opening.id} opening={opening} />
      ))}
      {openings.filter((item) => item.kind === "door").map((opening) => (
        <DoorThreshold3D key={opening.id} opening={opening} />
      ))}
      {openings.filter((item) => item.kind === "entry").map((opening) => (
        <EntryDoor3D key={opening.id} opening={opening} />
      ))}
    </group>
  );
}

function Window3D({ opening }: { opening: OpeningPlan }) {
  const horizontal = opening.orientation === "h";
  const glassSize: [number, number, number] = horizontal ? [opening.width, 0.46, 0.045] : [0.045, 0.46, opening.width];
  const frameSize: [number, number, number] = horizontal ? [opening.width + 0.14, 0.54, 0.07] : [0.07, 0.54, opening.width + 0.14];
  return (
    <group position={[opening.x, 0.48, opening.z]}>
      <mesh castShadow>
        <boxGeometry args={frameSize} />
        <meshStandardMaterial color="#f4f6f3" roughness={0.24} />
      </mesh>
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={glassSize} />
        <meshStandardMaterial color={palette.glass} emissive="#9fdcf2" emissiveIntensity={0.16} transparent opacity={opening.kind === "glass" ? 0.54 : 0.42} roughness={0.08} metalness={0.05} />
      </mesh>
    </group>
  );
}

function DoorThreshold3D({ opening }: { opening: OpeningPlan }) {
  return (
    <mesh receiveShadow position={[opening.x, 0.075, opening.z]} rotation={[0, opening.orientation === "h" ? 0 : Math.PI / 2, 0]}>
      <boxGeometry args={[opening.width * 0.84, 0.035, 0.12]} />
      <meshStandardMaterial color="#b69565" roughness={0.48} />
    </mesh>
  );
}

function EntryDoor3D({ opening }: { opening: OpeningPlan }) {
  return (
    <group position={[opening.x, 0.36, opening.z + 0.07]}>
      <mesh castShadow>
        <boxGeometry args={[opening.width * 0.82, 0.72, 0.08]} />
        <meshStandardMaterial color="#71492b" roughness={0.42} />
      </mesh>
      <mesh position={[0.26, 0.02, -0.052]}>
        <sphereGeometry args={[0.028, 16, 16]} />
        <meshStandardMaterial color="#d6bd80" metalness={0.28} roughness={0.22} />
      </mesh>
    </group>
  );
}

function Furniture3D() {
  return (
    <group>
      {furniture.map((item) => (
        <FurnitureItem3D key={item.id} item={item} />
      ))}
    </group>
  );
}

function FurnitureItem3D({ item }: { item: FurniturePlan }) {
  const rotation: [number, number, number] = [0, item.rotation ?? 0, 0];
  if (item.type === "bed") {
    const isDuvet = item.variant === "duvet";
    return <Box3D item={item} height={isDuvet ? 0.16 : 0.28} y={isDuvet ? 0.28 : 0.18} color={isDuvet ? "#efe2cf" : "#f6eee2"} rotation={rotation} />;
  }
  if (item.type === "nightstand") {
    return <Box3D item={item} height={item.variant === "pillow" ? 0.1 : 0.22} y={item.variant === "pillow" ? 0.36 : 0.18} color={item.variant === "pillow" ? "#fff9f0" : "#9b7146"} rotation={rotation} />;
  }
  if (item.type === "wardrobe" || item.type === "bookcase") {
    return (
      <group position={[item.x, 0, item.z]} rotation={rotation}>
        <Box size={[item.width, 0.72, item.depth]} y={0.36} color={item.type === "bookcase" ? "#8a623d" : "#a5774b"} />
        {item.type === "bookcase" && [-0.22, 0, 0.22].map((z, index) => <Box key={index} size={[item.width * 0.84, 0.04, 0.12]} position={[0, 0.52 + index * 0.09, z]} color={index % 2 ? "#315c73" : "#d2aa68"} />)}
      </group>
    );
  }
  if (item.type === "desk" || item.type === "cabinet" || item.type === "vanity" || item.type === "fridge") {
    return <Box3D item={item} height={item.type === "fridge" ? 0.92 : 0.42} y={item.type === "fridge" ? 0.46 : 0.25} color={item.type === "fridge" ? "#dedbd3" : "#f1ebe2"} rotation={rotation} />;
  }
  if (item.type === "chair" || item.type === "diningChair") {
    return (
      <group position={[item.x, 0, item.z]} rotation={rotation}>
        <Box size={[item.width, 0.18, item.depth]} y={0.14} color="#c7b39a" />
        <Box size={[item.width * 0.86, 0.34, 0.05]} position={[0, 0.32, -item.depth / 2]} color="#b99f7d" />
      </group>
    );
  }
  if (item.type === "sofa") {
    return (
      <group position={[item.x, 0, item.z]} rotation={rotation}>
        <Box size={[item.width, 0.34, item.depth]} y={0.2} color={palette.fabric} />
        <Box size={[item.width * 0.82, 0.12, item.depth * 0.26]} position={[0, 0.4, -item.depth * 0.27]} color="#f7efe4" />
      </group>
    );
  }
  if (item.type === "coffeeTable" || item.type === "diningTable") {
    return item.type === "coffeeTable" ? <CylinderTop item={item} height={0.16} color="#f6efe4" /> : <Box3D item={item} height={0.16} y={0.25} color="#faf4ea" rotation={rotation} />;
  }
  if (item.type === "tvConsole") {
    return (
      <group position={[item.x, 0, item.z]} rotation={rotation}>
        <Box size={[item.width, 0.26, item.depth]} y={0.18} color="#8b633e" />
        <Box size={[0.06, 0.48, item.depth * 0.76]} position={[0, 0.48, 0]} color="#26343a" />
      </group>
    );
  }
  if (item.type === "sink") return <Sink3D item={item} />;
  if (item.type === "cooktop") return <Cooktop3D item={item} />;
  if (item.type === "toilet") return <Toilet3D item={item} />;
  if (item.type === "shower" || item.type === "glassRail") return <GlassBox3D item={item} />;
  if (item.type === "washer") return <Washer3D item={item} />;
  if (item.type === "plant") return <Plant3D item={item} />;
  if (item.type === "rug") return <Rug3D item={item} />;
  return <Box3D item={item} height={0.24} y={0.16} color={item.color ?? palette.cream} rotation={rotation} />;
}

function Box3D({ item, height, y, color, rotation }: { item: FurniturePlan; height: number; y: number; color: string; rotation: [number, number, number] }) {
  return (
    <mesh castShadow receiveShadow position={[item.x, y, item.z]} rotation={rotation}>
      <boxGeometry args={[item.width, height, item.depth]} />
      <meshStandardMaterial color={color} roughness={0.45} />
    </mesh>
  );
}

function Box({ size, y, color, position = [0, 0, 0] }: { size: [number, number, number]; y?: number; color: string; position?: [number, number, number] }) {
  return (
    <mesh castShadow receiveShadow position={[position[0], y ?? position[1], position[2]]}>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} roughness={0.45} />
    </mesh>
  );
}

function CylinderTop({ item, height, color }: { item: FurniturePlan; height: number; color: string }) {
  return (
    <mesh castShadow receiveShadow position={[item.x, 0.2, item.z]} scale={[item.width / 2, 1, item.depth / 2]}>
      <cylinderGeometry args={[1, 1, height, 42]} />
      <meshStandardMaterial color={color} roughness={0.38} />
    </mesh>
  );
}

function Sink3D({ item }: { item: FurniturePlan }) {
  return (
    <group position={[item.x, 0.48, item.z]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[Math.min(item.width, item.depth) * 0.2, Math.min(item.width, item.depth) * 0.36, 32]} />
        <meshStandardMaterial color="#b9c8cc" metalness={0.2} roughness={0.24} />
      </mesh>
      <mesh position={[0.12, 0.08, -0.06]} rotation={[0, 0, 0.68]}>
        <cylinderGeometry args={[0.015, 0.015, 0.26, 12]} />
        <meshStandardMaterial color="#879195" metalness={0.25} roughness={0.2} />
      </mesh>
    </group>
  );
}

function Cooktop3D({ item }: { item: FurniturePlan }) {
  return (
    <group position={[item.x, 0.5, item.z]}>
      {[-0.12, 0.12].map((x) => (
        <mesh key={x} position={[x, 0, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.07, 0.12, 28]} />
          <meshStandardMaterial color="#242424" roughness={0.28} />
        </mesh>
      ))}
    </group>
  );
}

function Toilet3D({ item }: { item: FurniturePlan }) {
  return (
    <group position={[item.x, 0, item.z]}>
      <mesh castShadow position={[0, 0.2, 0]}>
        <cylinderGeometry args={[item.width * 0.32, item.width * 0.26, 0.28, 32]} />
        <meshStandardMaterial color="#f7f6f1" roughness={0.26} />
      </mesh>
      <Box size={[item.width * 0.72, 0.28, item.depth * 0.22]} position={[0, 0.28, -item.depth * 0.32]} color="#f7f6f1" />
    </group>
  );
}

function GlassBox3D({ item }: { item: FurniturePlan }) {
  return (
    <mesh castShadow position={[item.x, 0.36, item.z]}>
      <boxGeometry args={[item.width, 0.68, item.depth]} />
      <meshStandardMaterial color={palette.glass} transparent opacity={0.36} roughness={0.08} metalness={0.05} />
    </mesh>
  );
}

function Washer3D({ item }: { item: FurniturePlan }) {
  return (
    <group position={[item.x, 0, item.z]}>
      <Box size={[item.width, 0.48, item.depth]} y={0.24} color={item.variant === "dark" ? "#d4d8da" : "#eceeed"} />
      <mesh position={[0, 0.25, -item.depth / 2 - 0.006]} rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.12, 0.2, 32]} />
        <meshStandardMaterial color={item.variant === "dark" ? "#1f2831" : "#607a87"} metalness={0.16} roughness={0.28} />
      </mesh>
    </group>
  );
}

function Plant3D({ item }: { item: FurniturePlan }) {
  return (
    <group position={[item.x, 0, item.z]}>
      <mesh castShadow position={[0, 0.11, 0]}>
        <cylinderGeometry args={[item.width * 0.26, item.width * 0.36, 0.2, 16]} />
        <meshStandardMaterial color="#b78d57" roughness={0.58} />
      </mesh>
      {[0, 1, 2, 3, 4].map((index) => (
        <mesh key={index} castShadow position={[Math.cos(index * 1.25) * item.width * 0.22, 0.28, Math.sin(index * 1.25) * item.depth * 0.22]}>
          <sphereGeometry args={[item.width * 0.28, 14, 14]} />
          <meshStandardMaterial color={index % 2 ? "#5e8b50" : "#6aa357"} roughness={0.72} />
        </mesh>
      ))}
    </group>
  );
}

function Rug3D({ item }: { item: FurniturePlan }) {
  return (
    <mesh receiveShadow position={[item.x, 0.07, item.z]}>
      <boxGeometry args={[item.width, 0.018, item.depth]} />
      <meshStandardMaterial color="#eadfce" roughness={0.82} />
    </mesh>
  );
}

function Avatar3D({ position }: { position: { x: number; z: number } }) {
  return (
    <group position={[position.x, 0.14, position.z]}>
      <mesh castShadow position={[0, 0.16, 0]}>
        <cylinderGeometry args={[0.11, 0.13, 0.26, 22]} />
        <meshStandardMaterial color="#1d6fb8" roughness={0.42} />
      </mesh>
      <mesh castShadow position={[0, 0.36, 0]}>
        <sphereGeometry args={[0.11, 22, 22]} />
        <meshStandardMaterial color="#f0c6a2" roughness={0.45} />
      </mesh>
    </group>
  );
}
