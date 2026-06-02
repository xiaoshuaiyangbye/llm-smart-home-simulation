import { ContactShadows, OrbitControls, Text } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";

import type {
  AcDeviceState,
  CurtainDeviceState,
  DeviceState,
  FanDeviceState,
  LightDeviceState,
  RoomId,
  RoomState,
  SmartHomeState,
  WeatherType,
  WindowDeviceState,
} from "../types/state";

interface HouseSceneProps {
  state: SmartHomeState | null;
  avatarPosition: { x: number; z: number };
  currentRoomId: RoomId;
  avatarVisible?: boolean;
}

interface FloorRoom {
  id: string;
  label: string;
  position: [number, number, number];
  size: [number, number];
  floorColor: string;
  stateRoomId?: RoomId;
  furniture: "living" | "bed" | "study" | "dining" | "bath" | "kitchen" | "laundry" | "utility";
}

type WallSide = "north" | "south" | "east" | "west";

interface WindowPlacement {
  side: WallSide;
  offset: number;
  width: number;
  kind?: "standard" | "wide" | "frosted" | "balcony";
}

interface WallOpening {
  center: number;
  width: number;
}

const ROOM_DOORS: Record<string, Partial<Record<WallSide, number>>> = {
  bedroom: { south: 0.95 },
  study_room: { south: -1.1 },
  bathroom: { south: -0.65 },
  living_room: { east: -0.85, north: 1.1 },
  dining_room: { west: -0.55, east: 0.15, south: 0.65 },
  kitchen: { west: 0.1 },
  laundry: { north: -0.45 },
  balcony: { east: 0.25 },
};

const ROOM_WINDOWS: Record<string, WindowPlacement[]> = {
  bedroom: [
    { side: "north", offset: -0.45, width: 1.45, kind: "standard" },
    { side: "west", offset: -0.28, width: 0.9, kind: "standard" },
  ],
  study_room: [{ side: "north", offset: 0.22, width: 1.3, kind: "standard" }],
  bathroom: [{ side: "north", offset: 0.42, width: 0.82, kind: "frosted" }],
  living_room: [
    { side: "west", offset: -0.15, width: 1.15, kind: "standard" },
    { side: "south", offset: 0.95, width: 1.9, kind: "balcony" },
  ],
  dining_room: [],
  kitchen: [{ side: "east", offset: -0.45, width: 1.05, kind: "standard" }],
  laundry: [{ side: "south", offset: 0.25, width: 0.95, kind: "standard" }],
  balcony: [
    { side: "west", offset: 0.15, width: 1.1, kind: "wide" },
    { side: "south", offset: -0.1, width: 1.0, kind: "wide" },
  ],
};

const FLOOR_ROOMS: FloorRoom[] = [
  { id: "bedroom", label: "卧室", position: [-4.4, 0, -2.22], size: [4.2, 3.36], floorColor: "#d3ad78", stateRoomId: "bedroom", furniture: "bed" },
  { id: "study_room", label: "书房", position: [-0.35, 0, -2.22], size: [3.9, 3.36], floorColor: "#c99865", stateRoomId: "study_room", furniture: "study" },
  { id: "bathroom", label: "卫生间", position: [3.05, 0, -2.22], size: [2.9, 3.36], floorColor: "#dedbd2", stateRoomId: "bathroom", furniture: "bath" },
  { id: "living_room", label: "客厅", position: [-3.95, 0, 1.08], size: [5.1, 3.24], floorColor: "#eee7dc", stateRoomId: "living_room", furniture: "living" },
  { id: "dining_room", label: "餐厅", position: [0.55, 0, 1.08], size: [3.9, 3.24], floorColor: "#e8e0d3", stateRoomId: "dining_room", furniture: "dining" },
  { id: "kitchen", label: "厨房", position: [4.0, 0, 1.08], size: [3.0, 3.24], floorColor: "#f0ede5", stateRoomId: "kitchen", furniture: "kitchen" },
  { id: "laundry", label: "洗衣区", position: [1.4, 0, 3.9], size: [2.4, 2.4], floorColor: "#d8b77e", stateRoomId: "laundry", furniture: "laundry" },
  { id: "balcony", label: "阳台", position: [-6.35, 0, 3.45], size: [1.75, 2.35], floorColor: "#e5e1d7", stateRoomId: "balcony", furniture: "utility" },
];

export function HouseScene({ state, avatarPosition, currentRoomId, avatarVisible = true }: HouseSceneProps) {
  if (!state) {
    return <div className="scene-placeholder">正在加载户型场景...</div>;
  }

  return (
    <Canvas shadows camera={{ position: [7.1, 6.25, 7.3], fov: 39 }}>
      <color attach="background" args={[getSceneBackground(state.outdoor_environment.weather)]} />
      <fog attach="fog" args={[getSceneBackground(state.outdoor_environment.weather), 15, 32]} />
      <SceneLighting state={state} />
      <WeatherBackdrop weather={state.outdoor_environment.weather} />
      <group rotation={[0, -0.06, 0]}>
        <ApartmentBase />
        <UnifiedApartmentWalls />
        {FLOOR_ROOMS.map((room) => (
          <ApartmentRoom key={room.id} room={room} state={state} active={room.stateRoomId === currentRoomId || room.id === currentRoomId} />
        ))}
        <Corridor active={currentRoomId === "corridor"} />
        {avatarVisible && <Avatar position={avatarPosition} />}
      </group>
      <ContactShadows position={[0, -0.06, 0]} opacity={0.35} scale={15} blur={2.2} far={7} />
      <OrbitControls enableDamping maxPolarAngle={Math.PI / 2.12} minDistance={7} maxDistance={16} target={[-0.8, 0.2, 0.5]} />
    </Canvas>
  );
}

function SceneLighting({ state }: { state: SmartHomeState }) {
  const ambient = {
    sunny: 0.68,
    cloudy: 0.52,
    overcast: 0.4,
    rainy: 0.32,
  }[state.outdoor_environment.weather];

  return (
    <>
      <hemisphereLight args={["#f7fbff", "#d8cab7", ambient * 0.92]} />
      <ambientLight intensity={ambient * 0.48} />
      <directionalLight
        castShadow
        position={[4.8, 9, 5.8]}
        intensity={ambient * 1.55}
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
      />
      <pointLight position={[-3.5, 3.2, 2.8]} intensity={0.42} color="#ffe0b3" />
      <pointLight position={[2.6, 3.2, -2.4]} intensity={0.28} color="#d6ecff" />
    </>
  );
}

function WeatherBackdrop({ weather }: { weather: WeatherType }) {
  return (
    <group position={[0, 4.2, -5.8]}>
      <mesh>
        <planeGeometry args={[15, 5.6]} />
        <meshStandardMaterial color={getSkyColor(weather)} emissive={getSkyColor(weather)} emissiveIntensity={0.24} />
      </mesh>
      {weather !== "rainy" && <Sun weather={weather} />}
      {(weather === "cloudy" || weather === "overcast" || weather === "rainy") && (
        <>
          <Cloud position={[-3.9, 0.7, 0.08]} scale={weather === "overcast" ? 1.3 : 1} tone={weather === "overcast" ? "#d4d7d9" : "#ffffff"} />
          <Cloud position={[0.4, 1.03, 0.08]} scale={weather === "overcast" ? 1.55 : 1.18} tone={weather === "rainy" ? "#c4cbd0" : "#f3f5f6"} />
          <Cloud position={[4.1, 0.58, 0.08]} scale={1.05} tone={weather === "rainy" ? "#b8c2c8" : "#ffffff"} />
        </>
      )}
      {weather === "rainy" && <Rain />}
    </group>
  );
}

function Sun({ weather }: { weather: WeatherType }) {
  const opacity = weather === "sunny" ? 1 : 0.48;
  return (
    <group position={[-5.4, 1.25, 0.1]}>
      <mesh>
        <circleGeometry args={[0.42, 48]} />
        <meshBasicMaterial color="#ffd35a" transparent opacity={opacity} />
      </mesh>
      <mesh>
        <ringGeometry args={[0.5, 0.72, 48]} />
        <meshBasicMaterial color="#ffe7a3" transparent opacity={opacity * 0.35} />
      </mesh>
    </group>
  );
}

function Cloud({ position, scale, tone }: { position: [number, number, number]; scale: number; tone: string }) {
  return (
    <group position={position} scale={[scale, scale, scale]}>
      {[[-0.34, 0, 0], [0, 0.12, 0], [0.34, 0, 0], [0.08, -0.1, 0]].map(([x, y, z], index) => (
        <mesh key={index} position={[x, y, z]}>
          <sphereGeometry args={[index === 1 ? 0.3 : 0.24, 24, 24]} />
          <meshBasicMaterial color={tone} transparent opacity={0.92} />
        </mesh>
      ))}
    </group>
  );
}

function Rain() {
  return (
    <group>
      {Array.from({ length: 28 }, (_, index) => {
        const x = -6.2 + (index % 14) * 0.95;
        const y = 0.65 - Math.floor(index / 14) * 0.7;
        return (
          <mesh key={index} position={[x, y, 0.16]} rotation={[0, 0, -0.35]}>
            <boxGeometry args={[0.025, 0.38, 0.02]} />
            <meshBasicMaterial color="#5f8fad" transparent opacity={0.75} />
          </mesh>
        );
      })}
    </group>
  );
}

function ApartmentBase() {
  return (
    <group>
      <mesh receiveShadow position={[-0.75, -0.18, 0.45]}>
        <boxGeometry args={[13.7, 0.12, 8.8]} />
        <meshStandardMaterial color="#c8c3b8" roughness={0.72} />
      </mesh>
      <mesh receiveShadow position={[-0.75, -0.05, 0.45]}>
        <boxGeometry args={[13.95, 0.14, 9.05]} />
        <meshStandardMaterial color="#f9f7f1" roughness={0.58} />
      </mesh>
    </group>
  );
}

function UnifiedApartmentWalls() {
  return (
    <group>
      <WallRun orientation="h" fixed={-3.9} from={-6.5} to={4.5} openings={toWallOpenings("h", "north", -3.9)} />
      <WallRun orientation="h" fixed={-0.54} from={-6.5} to={5.5} gaps={[-4.05, 3.55]} />
      <WallRun orientation="h" fixed={2.7} from={-6.5} to={5.5} gaps={[1.4]} openings={toWallOpenings("h", "south", 2.7)} />
      <WallRun orientation="h" fixed={5.1} from={0.2} to={2.6} openings={toWallOpenings("h", "south", 5.1)} />
      <WallRun orientation="h" fixed={2.28} from={-7.22} to={-5.48} openings={toWallOpenings("h", "north", 2.28)} />
      <WallRun orientation="h" fixed={4.64} from={-7.22} to={-5.48} openings={toWallOpenings("h", "south", 4.64)} />
      <WallRun orientation="v" fixed={-6.5} from={-3.9} to={2.7} openings={toWallOpenings("v", "west", -6.5)} />
      <WallRun orientation="v" fixed={-2.3} from={-3.9} to={-0.9} />
      <WallRun orientation="v" fixed={1.6} from={-3.9} to={-0.9} />
      <WallRun orientation="v" fixed={4.5} from={-3.9} to={-0.9} />
      <WallRun orientation="v" fixed={-1.4} from={-0.54} to={2.7} gaps={[0.95]} />
      <WallRun orientation="v" fixed={2.5} from={-0.54} to={2.7} gaps={[0.95]} />
      <WallRun orientation="v" fixed={5.5} from={-0.54} to={2.7} openings={toWallOpenings("v", "east", 5.5)} />
      <WallRun orientation="v" fixed={0.2} from={2.7} to={5.1} gaps={[3.42]} />
      <WallRun orientation="v" fixed={2.6} from={2.7} to={5.1} />
      <WallRun orientation="v" fixed={-7.22} from={2.28} to={4.64} openings={toWallOpenings("v", "west", -7.22)} />
      <WallRun orientation="v" fixed={-5.48} from={2.28} to={4.64} />
      <SharedDoor position={[-4.05, 0.08, -0.54]} rotation={0} />
      <SharedDoor position={[3.55, 0.08, -0.54]} rotation={0} />
      <SharedDoor position={[1.4, 0.08, 2.7]} rotation={0} />
      <SharedDoor position={[-1.4, 0.08, 0.9]} rotation={Math.PI / 2} />
      <SharedDoor position={[2.5, 0.08, 0.9]} rotation={Math.PI / 2} />
      <SharedDoor position={[0.2, 0.08, 3.42]} rotation={Math.PI / 2} />
      <BalconyConnector />
    </group>
  );
}

function WallRun({
  orientation,
  fixed,
  from,
  to,
  gaps = [],
  openings = [],
}: {
  orientation: "h" | "v";
  fixed: number;
  from: number;
  to: number;
  gaps?: number[];
  openings?: WallOpening[];
}) {
  const gapWidth = 0.86;
  const voids = [
    ...gaps.map((gap) => ({ center: gap, width: gapWidth })),
    ...openings.map((opening) => ({ center: opening.center, width: opening.width + 0.22 })),
  ].sort((a, b) => a.center - b.center);
  const spans: Array<[number, number]> = [];
  let cursor = from;
  for (const gap of voids) {
    const start = Math.max(from, gap.center - gap.width / 2);
    const end = Math.min(to, gap.center + gap.width / 2);
    if (start > cursor) spans.push([cursor, start]);
    cursor = Math.max(cursor, end);
  }
  if (cursor < to) spans.push([cursor, to]);

  return (
    <>
      {spans.map(([start, end], index) => {
        const length = end - start;
        const center = (start + end) / 2;
        const position: [number, number, number] = orientation === "h" ? [center, 0.45, fixed] : [fixed, 0.45, center];
        const capPosition: [number, number, number] = orientation === "h" ? [center, 0.94, fixed] : [fixed, 0.94, center];
        const size: [number, number, number] = orientation === "h" ? [length, 0.9, 0.16] : [0.16, 0.9, length];
        const capSize: [number, number, number] = orientation === "h" ? [length + 0.06, 0.08, 0.22] : [0.22, 0.08, length + 0.06];
        return (
          <group key={`${orientation}-${fixed}-${index}`}>
            <WallBox position={position} size={size} color="#fbfaf6" />
            <WallBox position={capPosition} size={capSize} color="#ffffff" />
          </group>
        );
      })}
      {openings.map((opening, index) => (
        <WindowWallOpening key={`${orientation}-${fixed}-opening-${index}`} orientation={orientation} fixed={fixed} opening={opening} />
      ))}
    </>
  );
}

function WindowWallOpening({
  orientation,
  fixed,
  opening,
}: {
  orientation: "h" | "v";
  fixed: number;
  opening: WallOpening;
}) {
  const lowerPosition: [number, number, number] = orientation === "h" ? [opening.center, 0.18, fixed] : [fixed, 0.18, opening.center];
  const upperPosition: [number, number, number] = orientation === "h" ? [opening.center, 0.83, fixed] : [fixed, 0.83, opening.center];
  const sillPosition: [number, number, number] = orientation === "h" ? [opening.center, 0.37, fixed] : [fixed, 0.37, opening.center];
  const lowerSize: [number, number, number] = orientation === "h" ? [opening.width + 0.22, 0.34, 0.16] : [0.16, 0.34, opening.width + 0.22];
  const upperSize: [number, number, number] = orientation === "h" ? [opening.width + 0.22, 0.16, 0.16] : [0.16, 0.16, opening.width + 0.22];
  const sillSize: [number, number, number] = orientation === "h" ? [opening.width + 0.36, 0.055, 0.22] : [0.22, 0.055, opening.width + 0.36];

  return (
    <group>
      <WallBox position={lowerPosition} size={lowerSize} color="#fbfaf6" />
      <WallBox position={upperPosition} size={upperSize} color="#fbfaf6" />
      <WallBox position={sillPosition} size={sillSize} color="#ffffff" />
    </group>
  );
}

function toWallOpenings(orientation: "h" | "v", side: WallSide, wallFixed: number): WallOpening[] {
  return FLOOR_ROOMS.flatMap((room) => {
    const placements = ROOM_WINDOWS[room.id] ?? [];
    return placements
      .filter((placement) => placement.side === side)
      .filter((placement) => Math.abs(getPlacementWallFixed(room, placement) - wallFixed) < 0.08)
      .map((placement) => ({
        center: orientation === "h" ? room.position[0] + placement.offset : room.position[2] + placement.offset,
        width: placement.width,
      }));
  });
}

function getPlacementWallFixed(room: FloorRoom, placement: WindowPlacement): number {
  if (placement.side === "north") return room.position[2] - room.size[1] / 2;
  if (placement.side === "south") return room.position[2] + room.size[1] / 2;
  if (placement.side === "east") return room.position[0] + room.size[0] / 2;
  return room.position[0] - room.size[0] / 2;
}

function SharedDoor({ position, rotation }: { position: [number, number, number]; rotation: number }) {
  return (
    <group>
      <DoorThreshold position={position} rotation={rotation} />
      <mesh castShadow position={[position[0] + Math.cos(rotation) * 0.24, 0.35, position[2] + Math.sin(rotation) * 0.24]} rotation={[0, rotation + 0.72, 0]}>
        <boxGeometry args={[0.58, 0.58, 0.08]} />
        <meshStandardMaterial color="#c6a06d" roughness={0.42} />
      </mesh>
    </group>
  );
}

function BalconyConnector() {
  return (
    <group>
      <mesh receiveShadow position={[-5.85, 0.075, 2.9]}>
        <boxGeometry args={[1.35, 0.035, 0.72]} />
        <meshStandardMaterial color="#efe8d8" roughness={0.5} />
      </mesh>
      <mesh castShadow position={[-5.85, 0.52, 2.7]}>
        <boxGeometry args={[1.28, 0.9, 0.06]} />
        <meshStandardMaterial color="#c9e3f2" transparent opacity={0.42} roughness={0.08} metalness={0.04} />
      </mesh>
      <mesh position={[-5.85, 0.54, 2.735]}>
        <boxGeometry args={[1.44, 0.055, 0.08]} />
        <meshStandardMaterial color="#ffffff" roughness={0.24} />
      </mesh>
      <mesh position={[-5.85, 0.08, 2.735]}>
        <boxGeometry args={[1.52, 0.06, 0.12]} />
        <meshStandardMaterial color="#b58d5e" roughness={0.38} />
      </mesh>
      <mesh position={[-5.85, 0.52, 2.76]}>
        <boxGeometry args={[0.045, 0.78, 0.06]} />
        <meshStandardMaterial color="#ffffff" roughness={0.24} />
      </mesh>
      <mesh castShadow position={[-5.2, 0.4, 2.98]} rotation={[0, -0.45, 0]}>
        <boxGeometry args={[0.08, 0.72, 0.58]} />
        <meshStandardMaterial color="#c6a06d" roughness={0.42} />
      </mesh>
    </group>
  );
}

function ApartmentRoom({ room, state, active }: { room: FloorRoom; state: SmartHomeState; active: boolean }) {
  const roomState = room.stateRoomId ? getRoom(state, room.stateRoomId) : undefined;
  const roomDevices = room.stateRoomId ? state.devices.filter((device) => device.room === room.stateRoomId) : [];
  const light = findDevice<LightDeviceState>(roomDevices, "light");
  const curtain = findDevice<CurtainDeviceState>(roomDevices, "curtain");
  const ac = findDevice<AcDeviceState>(roomDevices, "ac");
  const fan = findDevice<FanDeviceState>(roomDevices, "fan");
  const windowDevice = findDevice<WindowDeviceState>(roomDevices, "window");
  const lampLevel = light?.is_on ? light.brightness_pct / 100 : 0;
  const daylight = getDaylight(state.outdoor_environment.weather, curtain?.opening_pct ?? 55);
  const roomGlow = Math.min(0.45, lampLevel * 0.22 + daylight * 0.12);

  return (
    <group position={room.position}>
      <mesh receiveShadow position={[0, 0, 0]}>
        <boxGeometry args={[room.size[0], 0.12, room.size[1]]} />
        <meshStandardMaterial color={room.floorColor} emissive={room.floorColor} emissiveIntensity={roomGlow} roughness={0.46} metalness={0.02} />
      </mesh>
      {active && (
        <mesh position={[0, 0.118, 0]}>
          <boxGeometry args={[room.size[0] * 0.94, 0.02, room.size[1] * 0.92]} />
          <meshBasicMaterial color="#61b58f" transparent opacity={0.18} depthWrite={false} />
        </mesh>
      )}
      <FloorTexture size={room.size} type={room.furniture} />
      <LightWash size={room.size} light={light} room={roomState} daylight={daylight} />
      {(ROOM_WINDOWS[room.id] ?? []).map((placement, index) => (
        <ExteriorWindow
          key={`${room.id}-${placement.side}-${index}`}
          size={room.size}
          placement={placement}
          curtain={curtain}
          windowDevice={windowDevice}
          weather={state.outdoor_environment.weather}
        />
      ))}
      <CeilingLights light={light} size={room.size} />
      <ClimateDevices ac={ac} fan={fan} size={room.size} />
      <Furniture type={room.furniture} />
      <RoomLabel label={room.label} size={room.size} />
      {roomState && <EnvironmentBadge room={roomState} size={room.size} />}
    </group>
  );
}

function RoomWalls({ roomId, size }: { roomId: string; size: [number, number] }) {
  const [width, depth] = size;
  const wallColor = "#fbfaf6";
  const capColor = "#ffffff";
  const doors = ROOM_DOORS[roomId] ?? {};
  return (
    <group>
      <HorizontalWall y={-depth / 2} width={width} gapCenter={doors.north} wallColor={wallColor} capColor={capColor} side="north" />
      <HorizontalWall y={depth / 2} width={width} gapCenter={doors.south} wallColor={wallColor} capColor={capColor} side="south" />
      <VerticalWall x={-width / 2} depth={depth} gapCenter={doors.west} wallColor={wallColor} capColor={capColor} side="west" />
      <VerticalWall x={width / 2} depth={depth} gapCenter={doors.east} wallColor={wallColor} capColor={capColor} side="east" />
    </group>
  );
}

function HorizontalWall({
  y,
  width,
  gapCenter,
  wallColor,
  capColor,
  side,
}: {
  y: number;
  width: number;
  gapCenter?: number;
  wallColor: string;
  capColor: string;
  side: "north" | "south";
}) {
  if (gapCenter === undefined) {
    return (
      <>
        <WallBox position={[0, 0.45, y]} size={[width + 0.22, 0.9, 0.16]} color={wallColor} />
        <WallBox position={[0, 0.94, y]} size={[width + 0.28, 0.08, 0.22]} color={capColor} />
      </>
    );
  }
  const gapWidth = 0.82;
  const leftLength = Math.max(0.1, gapCenter + width / 2 - gapWidth / 2);
  const rightLength = Math.max(0.1, width / 2 - gapCenter - gapWidth / 2);
  return (
    <>
      <WallBox position={[-width / 2 + leftLength / 2, 0.45, y]} size={[leftLength, 0.9, 0.16]} color={wallColor} />
      <WallBox position={[width / 2 - rightLength / 2, 0.45, y]} size={[rightLength, 0.9, 0.16]} color={wallColor} />
      <DoorThreshold position={[gapCenter, 0.09, y + (side === "south" ? -0.06 : 0.06)]} rotation={0} />
      <DoorLeaf position={[gapCenter + 0.24, 0.35, y + (side === "south" ? -0.13 : 0.13)]} rotation={side === "south" ? -0.65 : 0.65} />
    </>
  );
}

function VerticalWall({
  x,
  depth,
  gapCenter,
  wallColor,
  capColor,
  side,
}: {
  x: number;
  depth: number;
  gapCenter?: number;
  wallColor: string;
  capColor: string;
  side: "east" | "west";
}) {
  if (gapCenter === undefined) {
    return (
      <>
        <WallBox position={[x, 0.45, 0]} size={[0.16, 0.9, depth]} color={wallColor} />
        <WallBox position={[x, 0.94, 0]} size={[0.22, 0.08, depth]} color={capColor} />
      </>
    );
  }
  const gapWidth = 0.82;
  const topLength = Math.max(0.1, gapCenter + depth / 2 - gapWidth / 2);
  const bottomLength = Math.max(0.1, depth / 2 - gapCenter - gapWidth / 2);
  return (
    <>
      <WallBox position={[x, 0.45, -depth / 2 + topLength / 2]} size={[0.16, 0.9, topLength]} color={wallColor} />
      <WallBox position={[x, 0.45, depth / 2 - bottomLength / 2]} size={[0.16, 0.9, bottomLength]} color={wallColor} />
      <DoorThreshold position={[x + (side === "east" ? -0.06 : 0.06), 0.09, gapCenter]} rotation={Math.PI / 2} />
      <DoorLeaf position={[x + (side === "east" ? -0.13 : 0.13), 0.35, gapCenter + 0.24]} rotation={side === "east" ? 0.92 : -0.92} vertical />
    </>
  );
}

function WallBox({ position, size, color }: { position: [number, number, number]; size: [number, number, number]; color: string }) {
  return (
    <mesh castShadow position={position}>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} roughness={0.28} />
    </mesh>
  );
}

function DoorThreshold({ position, rotation }: { position: [number, number, number]; rotation: number }) {
  return (
    <mesh receiveShadow position={position} rotation={[0, rotation, 0]}>
      <boxGeometry args={[0.78, 0.035, 0.12]} />
      <meshStandardMaterial color="#b38b5b" roughness={0.45} />
    </mesh>
  );
}

function DoorLeaf({ position, rotation, vertical = false }: { position: [number, number, number]; rotation: number; vertical?: boolean }) {
  return (
    <mesh castShadow position={position} rotation={[0, rotation, 0]}>
      <boxGeometry args={vertical ? [0.08, 0.58, 0.58] : [0.58, 0.58, 0.08]} />
      <meshStandardMaterial color="#c6a06d" roughness={0.42} />
    </mesh>
  );
}

function LightWash({
  size,
  light,
  room,
  daylight,
}: {
  size: [number, number];
  light?: LightDeviceState;
  room?: RoomState;
  daylight: number;
}) {
  const lampOpacity = light?.is_on ? Math.min(0.58, 0.12 + light.brightness_pct / 145) : 0;
  const daylightOpacity = Math.min(0.32, daylight * 0.22);
  const environmentOpacity = room ? Math.min(0.2, room.indoor_illuminance_lux / 4500) : 0;
  const opacity = Math.max(lampOpacity, daylightOpacity, environmentOpacity);
  if (opacity < 0.04) return null;

  return (
    <mesh position={[0, 0.105, 0]}>
      <boxGeometry args={[size[0] * 0.88, 0.018, size[1] * 0.86]} />
      <meshBasicMaterial color={light?.is_on ? "#ffe2a0" : "#d7ecff"} transparent opacity={opacity} depthWrite={false} />
    </mesh>
  );
}

function FloorTexture({ size, type }: { size: [number, number]; type: FloorRoom["furniture"] }) {
  const isTile = ["bath", "kitchen", "utility"].includes(type);
  const lines = isTile ? Math.floor(size[0] / 0.55) : Math.floor(size[0] / 0.42);
  return (
    <group position={[0, 0.075, 0]}>
      {Array.from({ length: lines }, (_, index) => {
        const x = -size[0] / 2 + (index + 1) * (size[0] / (lines + 1));
        return (
          <mesh key={index} position={[x, 0, 0]}>
            <boxGeometry args={[0.015, 0.012, size[1] * 0.94]} />
            <meshStandardMaterial color={isTile ? "#c9c6bd" : "#b98e63"} transparent opacity={isTile ? 0.52 : 0.32} />
          </mesh>
        );
      })}
      {isTile && Array.from({ length: Math.floor(size[1] / 0.55) }, (_, index) => {
        const z = -size[1] / 2 + (index + 1) * (size[1] / (Math.floor(size[1] / 0.55) + 1));
        return (
          <mesh key={index} position={[0, 0, z]}>
            <boxGeometry args={[size[0] * 0.94, 0.012, 0.015]} />
            <meshStandardMaterial color="#c9c6bd" transparent opacity={0.52} />
          </mesh>
        );
      })}
    </group>
  );
}

function ExteriorWindow({
  size,
  placement,
  curtain,
  windowDevice,
  weather,
}: {
  size: [number, number];
  placement: WindowPlacement;
  curtain?: CurtainDeviceState;
  windowDevice?: WindowDeviceState;
  weather: WeatherType;
}) {
  const opening = curtain?.opening_pct ?? 65;
  const windowOpening = windowDevice?.opening_pct ?? 20;
  const daylight = getDaylight(weather, opening);
  const width = placement.width;
  const height = placement.kind === "balcony" ? 0.94 : placement.kind === "frosted" ? 0.48 : 0.68;
  const curtainWidth = Math.max(0.1, width * (1 - opening / 100) / 2);
  const curtainSideX = width / 2 - curtainWidth / 2;
  const windowAngle = placement.kind === "balcony" ? 0 : (windowOpening / 100) * 0.78;
  const glassGlow = daylight * (0.45 + windowOpening / 180);
  const transform = getWindowTransform(size, placement);
  const glassColor = placement.kind === "frosted" ? "#d9eef1" : "#bfe2f5";
  const glassOpacity = placement.kind === "frosted" ? 0.72 : 0.58;
  const frameColor = placement.kind === "balcony" ? "#5d6a6d" : "#7e9097";

  return (
    <group position={transform.position} rotation={[0, transform.rotationY, 0]}>
      <mesh castShadow position={[0, 0.02, -0.026]}>
        <boxGeometry args={[width + 0.22, height + 0.18, 0.055]} />
        <meshStandardMaterial color="#f8f6f0" roughness={0.22} />
      </mesh>
      <mesh position={[0, 0.02, -0.064]}>
        <boxGeometry args={[width + 0.06, height + 0.04, 0.028]} />
        <meshStandardMaterial color={frameColor} roughness={0.34} />
      </mesh>
      {placement.kind === "balcony" ? (
        <>
          <SlidingGlassPanel x={-width * 0.18} width={width * 0.52} height={height} glassColor={glassColor} glow={glassGlow} opacity={glassOpacity} />
          <SlidingGlassPanel x={width * (0.12 + windowOpening / 460)} width={width * 0.52} height={height} glassColor={glassColor} glow={glassGlow} opacity={glassOpacity} />
        </>
      ) : (
        <>
          <mesh castShadow position={[-width * 0.25, 0.02, 0.02]} rotation={[0, -windowAngle, 0]}>
            <boxGeometry args={[width * 0.48, height, 0.035]} />
            <meshStandardMaterial color={glassColor} emissive="#9ed5f3" emissiveIntensity={glassGlow} transparent opacity={glassOpacity} roughness={0.08} metalness={0.06} />
          </mesh>
          <mesh castShadow position={[width * 0.25, 0.02, 0.02]} rotation={[0, windowAngle, 0]}>
            <boxGeometry args={[width * 0.48, height, 0.035]} />
            <meshStandardMaterial color={glassColor} emissive="#9ed5f3" emissiveIntensity={glassGlow} transparent opacity={glassOpacity} roughness={0.08} metalness={0.06} />
          </mesh>
        </>
      )}
      <mesh position={[0, 0.02, 0.06]}>
        <boxGeometry args={[0.035, height + 0.08, 0.04]} />
        <meshStandardMaterial color="#eff2ee" roughness={0.24} />
      </mesh>
      <mesh position={[0, height / 2 + 0.17, 0.12]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.025, 0.025, width + 0.34, 18]} />
        <meshStandardMaterial color="#9a7858" metalness={0.12} roughness={0.38} />
      </mesh>
      <CurtainPanel side="left" width={curtainWidth} height={height + 0.12} x={-curtainSideX} opening={opening} />
      <CurtainPanel side="right" width={curtainWidth} height={height + 0.12} x={curtainSideX} opening={opening} />
      {opening > 25 && daylight > 0.12 && (
        <mesh position={[0, -0.55, 0.25]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[width * 1.15, placement.kind === "balcony" ? 1.05 : 0.7]} />
          <meshBasicMaterial color="#fff1bd" transparent opacity={Math.min(0.34, daylight * 0.32)} depthWrite={false} />
        </mesh>
      )}
      <DeviceStateTag text={`帘 ${opening.toFixed(0)}%`} position={[-width / 2 - 0.32, -height / 2 - 0.08, 0.1]} color="#5b4035" />
      <DeviceStateTag text={`窗 ${windowOpening.toFixed(0)}%`} position={[width / 2 + 0.32, -height / 2 - 0.08, 0.1]} color="#24404a" />
    </group>
  );
}

function SlidingGlassPanel({
  x,
  width,
  height,
  glassColor,
  glow,
  opacity,
}: {
  x: number;
  width: number;
  height: number;
  glassColor: string;
  glow: number;
  opacity: number;
}) {
  return (
    <mesh castShadow position={[x, 0.02, 0.02]}>
      <boxGeometry args={[width, height, 0.035]} />
      <meshStandardMaterial color={glassColor} emissive="#9ed5f3" emissiveIntensity={glow} transparent opacity={opacity} roughness={0.08} metalness={0.06} />
    </mesh>
  );
}

function getWindowTransform(size: [number, number], placement: WindowPlacement): { position: [number, number, number]; rotationY: number } {
  const [width, depth] = size;
  if (placement.side === "north") {
    return { position: [placement.offset, 0.72, -depth / 2 - 0.105], rotationY: 0 };
  }
  if (placement.side === "south") {
    return { position: [placement.offset, 0.72, depth / 2 + 0.105], rotationY: Math.PI };
  }
  if (placement.side === "east") {
    return { position: [width / 2 + 0.105, 0.72, placement.offset], rotationY: -Math.PI / 2 };
  }
  return { position: [-width / 2 - 0.105, 0.72, placement.offset], rotationY: Math.PI / 2 };
}

function CurtainPanel({
  side,
  width,
  height,
  x,
  opening,
}: {
  side: "left" | "right";
  width: number;
  height: number;
  x: number;
  opening: number;
}) {
  const foldCount = Math.max(2, Math.round(width / 0.11));
  const color = opening < 18 ? "#8d6c5d" : "#c8a28e";
  const opacity = opening > 92 ? 0.55 : 0.94;
  return (
    <group position={[x, 0.01, 0.145]}>
      <mesh castShadow>
        <boxGeometry args={[width, height, 0.07]} />
        <meshStandardMaterial color={color} transparent opacity={opacity} roughness={0.78} />
      </mesh>
      {Array.from({ length: foldCount }, (_, index) => {
        const offset = -width / 2 + (index + 0.5) * (width / foldCount);
        return (
          <mesh key={`${side}-${index}`} position={[offset, 0, 0.05]}>
            <boxGeometry args={[0.018, height * 0.98, 0.04]} />
            <meshStandardMaterial color={side === "left" ? "#765446" : "#9b7465"} transparent opacity={0.5} roughness={0.8} />
          </mesh>
        );
      })}
    </group>
  );
}

function CeilingLights({ light, size }: { light?: LightDeviceState; size: [number, number] }) {
  const brightness = light?.is_on ? light.brightness_pct / 100 : 0;
  const warmColor = light?.color_temperature_k && light.color_temperature_k < 3600 ? "#ffd2a0" : "#fff1d4";
  const shadeColor = light?.is_on ? "#fff0c4" : "#d7d1c4";
  return (
    <group>
      <mesh castShadow position={[0, 0.99, -0.24 * size[1]]}>
        <cylinderGeometry args={[0.33, 0.43, 0.16, 32]} />
        <meshStandardMaterial color={shadeColor} emissive={warmColor} emissiveIntensity={brightness * 0.7} roughness={0.42} />
      </mesh>
      <mesh castShadow position={[0, 0.88, -0.24 * size[1]]}>
        <sphereGeometry args={[0.16, 32, 32]} />
        <meshStandardMaterial color={warmColor} emissive={warmColor} emissiveIntensity={light?.is_on ? 0.8 + brightness * 1.6 : 0.02} transparent opacity={light?.is_on ? 0.98 : 0.45} />
      </mesh>
      <mesh position={[0, 0.12, -0.06 * size[1]]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[Math.min(size[0], size[1]) * 0.42, 48]} />
        <meshBasicMaterial color={warmColor} transparent opacity={light?.is_on ? Math.min(0.5, 0.16 + brightness * 0.42) : 0.02} depthWrite={false} />
      </mesh>
      <DeviceStateTag
        text={light?.is_on ? `灯 ${light.brightness_pct.toFixed(0)}%` : "灯 关"}
        position={[0.52, 1.03, -0.24 * size[1]]}
        color={light?.is_on ? "#6a3e12" : "#62645f"}
      />
      {light?.is_on && (
        <>
          <pointLight position={[0, 1.12, -0.24 * size[1]]} intensity={0.72 + brightness * 2.4} color={warmColor} distance={4.2} />
          <spotLight position={[0, 1.1, -0.24 * size[1]]} target-position={[0, 0, 0]} angle={0.82} penumbra={0.82} intensity={0.38 + brightness * 1.4} color={warmColor} distance={4.5} />
        </>
      )}
    </group>
  );
}

function DeviceStateTag({ text, position, color }: { text: string; position: [number, number, number]; color: string }) {
  return (
    <group position={position}>
      <mesh renderOrder={24}>
        <planeGeometry args={[0.68, 0.18]} />
        <meshBasicMaterial color="#fffdf7" transparent opacity={0.86} depthTest={false} />
      </mesh>
      <Text
        position={[0, 0, 0.012]}
        fontSize={0.08}
        color={color}
        anchorX="center"
        anchorY="middle"
        renderOrder={25}
      >
        {text}
      </Text>
    </group>
  );
}

function ClimateDevices({ ac, fan, size }: { ac?: AcDeviceState; fan?: FanDeviceState; size: [number, number] }) {
  return (
    <group>
      {ac && <CentralAirConditioner ac={ac} size={size} />}
      <mesh castShadow position={[-size[0] / 2 + 0.48, 0.18, size[1] / 2 - 0.42]}>
        <cylinderGeometry args={[0.18, 0.2, 0.1, 24]} />
        <meshStandardMaterial color={fan?.is_on ? "#527d70" : "#8b908d"} />
      </mesh>
      <mesh castShadow position={[-size[0] / 2 + 0.48, 0.43, size[1] / 2 - 0.42]}>
        <cylinderGeometry args={[0.035, 0.035, 0.46, 16]} />
        <meshStandardMaterial color="#68716d" />
      </mesh>
    </group>
  );
}

function CentralAirConditioner({ ac, size }: { ac: AcDeviceState; size: [number, number] }) {
  const isCooling = ac.is_on && ac.mode === "cool";
  const isHeating = ac.is_on && ac.mode === "heat";
  const accent = isCooling ? "#73c7ff" : isHeating ? "#ffba7a" : ac.is_on ? "#a4d7c1" : "#b8bfc0";
  const airflowColor = isCooling ? "#7fd0ff" : isHeating ? "#ffc07a" : "#b9d9c8";
  const ventPosition: [number, number, number] = [Math.min(size[0] / 2 - 0.78, 0.95), 1.02, -size[1] / 2 + 0.72];

  return (
    <group position={ventPosition}>
      <mesh castShadow>
        <boxGeometry args={[0.72, 0.05, 0.72]} />
        <meshStandardMaterial color="#f7f8f4" roughness={0.24} metalness={0.04} />
      </mesh>
      <mesh position={[0, 0.032, 0]}>
        <boxGeometry args={[0.58, 0.025, 0.58]} />
        <meshStandardMaterial color="#d7dedf" roughness={0.28} />
      </mesh>
      <mesh position={[0, 0.055, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.16, 0.018, 12, 32]} />
        <meshStandardMaterial color="#88979b" roughness={0.32} />
      </mesh>
      <mesh position={[0, 0.062, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.1, 32]} />
        <meshStandardMaterial color="#edf1f0" roughness={0.3} />
      </mesh>
      {[-0.22, -0.1, 0.1, 0.22].map((offset, index) => (
        <mesh key={`ac-x-${index}`} position={[offset, 0.075, -0.25]}>
          <boxGeometry args={[0.03, 0.018, 0.18]} />
          <meshStandardMaterial color="#77858a" roughness={0.28} />
        </mesh>
      ))}
      {[-0.22, -0.1, 0.1, 0.22].map((offset, index) => (
        <mesh key={`ac-z-${index}`} position={[0.25, 0.075, offset]}>
          <boxGeometry args={[0.18, 0.018, 0.03]} />
          <meshStandardMaterial color="#77858a" roughness={0.28} />
        </mesh>
      ))}
      <mesh position={[-0.28, 0.078, 0.28]}>
        <sphereGeometry args={[0.035, 16, 16]} />
        <meshStandardMaterial color={accent} emissive={accent} emissiveIntensity={ac.is_on ? 0.85 : 0.08} />
      </mesh>
      {ac.is_on && (
        <>
          <AirflowRibbon color={airflowColor} x={-0.22} z={0.34} opacity={0.24} />
          <AirflowRibbon color={airflowColor} x={0} z={0.46} opacity={0.28} />
          <AirflowRibbon color={airflowColor} x={0.22} z={0.34} opacity={0.24} />
          <pointLight position={[0, 0.22, 0.05]} intensity={isCooling ? 0.3 : 0.22} color={airflowColor} distance={2.1} />
        </>
      )}
      <DeviceStateTag
        text={ac.is_on ? `空调 ${ac.setpoint_c.toFixed(0)}C` : "空调 关"}
        position={[0, 0.18, 0.55]}
        color={ac.is_on ? "#24404a" : "#62645f"}
      />
    </group>
  );
}

function AirflowRibbon({ color, x, z, opacity }: { color: string; x: number; z: number; opacity: number }) {
  return (
    <mesh position={[x, -0.82, z]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[0.18, 0.9]} />
      <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
    </mesh>
  );
}

function Furniture({ type }: { type: FloorRoom["furniture"] }) {
  if (type === "bed") {
    return (
      <group>
        <mesh castShadow position={[-0.75, 0.18, 0.22]}>
          <boxGeometry args={[1.85, 0.32, 1.2]} />
          <meshStandardMaterial color="#f6ead9" roughness={0.55} />
        </mesh>
        <mesh castShadow position={[-1.25, 0.4, -0.22]}>
          <boxGeometry args={[0.46, 0.12, 0.34]} />
          <meshStandardMaterial color="#ffffff" roughness={0.5} />
        </mesh>
        <mesh castShadow position={[-0.25, 0.4, -0.22]}>
          <boxGeometry args={[0.46, 0.12, 0.34]} />
          <meshStandardMaterial color="#ded4c6" roughness={0.5} />
        </mesh>
        <mesh castShadow position={[1.0, 0.22, 0.72]}>
          <boxGeometry args={[1.2, 0.24, 0.42]} />
          <meshStandardMaterial color="#6b4b31" roughness={0.38} />
        </mesh>
        <TableLamp position={[1.36, 0.45, 0.72]} />
        <mesh castShadow position={[1.62, 0.48, -0.42]}>
          <boxGeometry args={[0.42, 0.9, 0.72]} />
          <meshStandardMaterial color="#a98258" roughness={0.5} />
        </mesh>
        <mesh position={[1.62, 0.96, -0.42]}>
          <boxGeometry args={[0.46, 0.045, 0.76]} />
          <meshStandardMaterial color="#d7c0a0" roughness={0.45} />
        </mesh>
      </group>
    );
  }
  if (type === "living") {
    return (
      <group>
        <mesh castShadow position={[0.15, 0.22, 0.48]}>
          <boxGeometry args={[2.05, 0.38, 0.72]} />
          <meshStandardMaterial color="#eadcc8" roughness={0.62} />
        </mesh>
        <mesh castShadow position={[-0.78, 0.48, 0.36]}>
          <boxGeometry args={[0.38, 0.14, 0.34]} />
          <meshStandardMaterial color="#c4b5a6" roughness={0.58} />
        </mesh>
        <mesh castShadow position={[0.82, 0.48, 0.36]}>
          <boxGeometry args={[0.38, 0.14, 0.34]} />
          <meshStandardMaterial color="#f4efe7" roughness={0.58} />
        </mesh>
        <mesh castShadow position={[0.12, 0.17, -0.46]}>
          <boxGeometry args={[0.88, 0.2, 0.6]} />
          <meshStandardMaterial color="#4a3528" roughness={0.42} />
        </mesh>
        <mesh castShadow position={[-1.65, 0.18, -0.65]}>
          <boxGeometry args={[0.95, 0.24, 0.28]} />
          <meshStandardMaterial color="#5b3f2a" roughness={0.4} />
        </mesh>
        <mesh castShadow position={[0.12, 0.3, -0.46]}>
          <boxGeometry args={[0.34, 0.06, 0.24]} />
          <meshStandardMaterial color="#e9d0a2" roughness={0.42} />
        </mesh>
        <mesh castShadow position={[0.37, 0.3, -0.46]}>
          <cylinderGeometry args={[0.055, 0.055, 0.08, 18]} />
          <meshStandardMaterial color="#6b3f2f" roughness={0.36} />
        </mesh>
        <Television position={[1.72, 0.4, -1.1]} />
        <StripedRug />
        <Plant position={[1.65, 0.14, -0.3]} />
      </group>
    );
  }
  if (type === "study") {
    return (
      <group>
        <mesh castShadow position={[0.6, 0.22, -0.7]}>
          <boxGeometry args={[1.35, 0.18, 0.52]} />
          <meshStandardMaterial color="#8c6848" roughness={0.36} />
        </mesh>
        <ComputerMonitor position={[0.55, 0.42, -0.7]} />
        <mesh castShadow position={[-0.8, 0.28, 0.45]}>
          <boxGeometry args={[0.58, 0.48, 0.58]} />
          <meshStandardMaterial color="#55706a" roughness={0.58} />
        </mesh>
        <TableLamp position={[1.12, 0.42, -0.7]} />
        <mesh castShadow position={[-1.28, 0.42, -0.6]}>
          <boxGeometry args={[0.36, 0.76, 0.82]} />
          <meshStandardMaterial color="#6c5136" roughness={0.48} />
        </mesh>
        {[-0.18, 0.02, 0.22].map((z, index) => (
          <mesh key={index} position={[-1.28, 0.5 + index * 0.12, z - 0.72]}>
            <boxGeometry args={[0.38, 0.035, 0.18]} />
            <meshStandardMaterial color={index % 2 ? "#4d7094" : "#d0b36f"} roughness={0.42} />
          </mesh>
        ))}
      </group>
    );
  }
  if (type === "dining") {
    return (
      <group>
        <mesh castShadow position={[0, 0.23, 0]}>
          <boxGeometry args={[1.15, 0.18, 0.85]} />
          <meshStandardMaterial color="#2f2823" roughness={0.34} />
        </mesh>
        {[[-0.86, 0], [0.86, 0], [0, -0.72], [0, 0.72]].map(([x, z], index) => (
          <mesh castShadow key={index} position={[x, 0.18, z]}>
            <boxGeometry args={[0.34, 0.28, 0.34]} />
            <meshStandardMaterial color="#b9ab98" roughness={0.55} />
          </mesh>
        ))}
        {[[-0.22, 0.08], [0.22, -0.08]].map(([x, z], index) => (
          <mesh castShadow key={index} position={[x, 0.35, z]} rotation={[-Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.13, 0.13, 0.025, 28]} />
            <meshStandardMaterial color={index ? "#f2eadc" : "#d8d0c5"} roughness={0.35} />
          </mesh>
        ))}
      </group>
    );
  }
  if (type === "bath") {
    return (
      <group>
        <mesh castShadow position={[-0.65, 0.18, -0.45]}>
          <boxGeometry args={[0.95, 0.22, 0.52]} />
          <meshStandardMaterial color="#f8f8f4" roughness={0.32} />
        </mesh>
        <mesh castShadow position={[0.85, 0.28, 0.55]}>
          <boxGeometry args={[0.55, 0.55, 0.55]} />
          <meshStandardMaterial color="#ecebe4" roughness={0.3} />
        </mesh>
        <mesh castShadow position={[0.2, 0.2, -0.95]}>
          <cylinderGeometry args={[0.22, 0.18, 0.32, 32]} />
          <meshStandardMaterial color="#f5f5f1" roughness={0.3} />
        </mesh>
        <mesh castShadow position={[-0.65, 0.56, -0.78]}>
          <boxGeometry args={[0.48, 0.38, 0.035]} />
          <meshStandardMaterial color="#d4e5ee" emissive="#d4e5ee" emissiveIntensity={0.12} roughness={0.2} metalness={0.1} />
        </mesh>
      </group>
    );
  }
  if (type === "kitchen") {
    return (
      <group>
        <mesh castShadow position={[-0.7, 0.32, -0.92]}>
          <boxGeometry args={[1.5, 0.58, 0.34]} />
          <meshStandardMaterial color="#f2eee6" roughness={0.35} />
        </mesh>
        <mesh position={[-1.05, 0.64, -0.92]} rotation={[-Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.13, 0.13, 0.025, 24]} />
          <meshStandardMaterial color="#b9c7cc" metalness={0.2} roughness={0.24} />
        </mesh>
        <mesh position={[-0.45, 0.64, -0.92]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.09, 0.13, 24]} />
          <meshStandardMaterial color="#303030" roughness={0.35} />
        </mesh>
        <mesh castShadow position={[0.88, 0.32, -0.85]}>
          <boxGeometry args={[0.56, 0.64, 0.42]} />
          <meshStandardMaterial color="#dedbd2" roughness={0.3} />
        </mesh>
      </group>
    );
  }
  if (type === "laundry") {
    return (
      <group>
        <mesh castShadow position={[-0.45, 0.28, 0]}>
          <boxGeometry args={[0.62, 0.56, 0.58]} />
          <meshStandardMaterial color="#d8dcdf" roughness={0.32} />
        </mesh>
        <mesh position={[-0.45, 0.29, -0.31]} rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.14, 0.2, 32]} />
          <meshStandardMaterial color="#5c7281" metalness={0.18} roughness={0.28} />
        </mesh>
        <mesh castShadow position={[0.45, 0.16, 0.22]}>
          <cylinderGeometry args={[0.22, 0.22, 0.18, 32]} />
          <meshStandardMaterial color="#1f4a75" emissive="#2d70b3" emissiveIntensity={0.18} roughness={0.25} />
        </mesh>
      </group>
    );
  }
  return (
    <group>
      <mesh castShadow position={[0, 0.18, 0]}>
        <cylinderGeometry args={[0.28, 0.28, 0.14, 32]} />
        <meshStandardMaterial color="#222b31" roughness={0.24} />
      </mesh>
      <mesh castShadow position={[0.62, 0.25, -0.45]}>
        <boxGeometry args={[0.45, 0.5, 0.4]} />
        <meshStandardMaterial color="#e6e4dc" roughness={0.36} />
      </mesh>
    </group>
  );
}

function Television({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh castShadow>
        <boxGeometry args={[0.9, 0.54, 0.07]} />
        <meshStandardMaterial color="#161718" roughness={0.2} metalness={0.18} />
      </mesh>
      <mesh position={[0, 0.015, -0.041]}>
        <boxGeometry args={[0.74, 0.39, 0.014]} />
        <meshStandardMaterial color="#173047" emissive="#6eb8ff" emissiveIntensity={0.34} roughness={0.18} />
      </mesh>
      <mesh position={[0, -0.34, 0]}>
        <boxGeometry args={[0.08, 0.18, 0.06]} />
        <meshStandardMaterial color="#2d2a27" roughness={0.32} />
      </mesh>
      <mesh position={[0, -0.45, 0]}>
        <boxGeometry args={[0.42, 0.04, 0.18]} />
        <meshStandardMaterial color="#2d2a27" roughness={0.32} />
      </mesh>
      <MiniObjectLabel text="电视" position={[0, 0.46, -0.05]} />
    </group>
  );
}

function ComputerMonitor({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh castShadow>
        <boxGeometry args={[0.56, 0.36, 0.05]} />
        <meshStandardMaterial color="#1b2022" roughness={0.2} metalness={0.14} />
      </mesh>
      <mesh position={[0, 0.01, -0.031]}>
        <boxGeometry args={[0.44, 0.26, 0.012]} />
        <meshStandardMaterial color="#1f4056" emissive="#8ac4ff" emissiveIntensity={0.28} roughness={0.2} />
      </mesh>
      <mesh position={[0, -0.25, 0]}>
        <boxGeometry args={[0.05, 0.16, 0.04]} />
        <meshStandardMaterial color="#333331" roughness={0.34} />
      </mesh>
      <mesh position={[0, -0.33, 0.03]}>
        <boxGeometry args={[0.34, 0.035, 0.14]} />
        <meshStandardMaterial color="#333331" roughness={0.34} />
      </mesh>
      <mesh position={[0.04, -0.32, 0.28]}>
        <boxGeometry args={[0.48, 0.035, 0.16]} />
        <meshStandardMaterial color="#d7d1c6" roughness={0.5} />
      </mesh>
      <MiniObjectLabel text="电脑" position={[0, 0.36, -0.04]} />
    </group>
  );
}

function MiniObjectLabel({ text, position }: { text: string; position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh renderOrder={15}>
        <planeGeometry args={[0.44, 0.18]} />
        <meshBasicMaterial color="#fffdf7" transparent opacity={0.88} depthTest={false} />
      </mesh>
      <Text
        position={[0, 0, 0.01]}
        fontSize={0.095}
        color="#203136"
        anchorX="center"
        anchorY="middle"
        renderOrder={16}
      >
        {text}
      </Text>
    </group>
  );
}

function TableLamp({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh castShadow position={[0, 0.08, 0]}>
        <cylinderGeometry args={[0.035, 0.045, 0.16, 16]} />
        <meshStandardMaterial color="#9b7b52" roughness={0.35} />
      </mesh>
      <mesh castShadow position={[0, 0.2, 0]}>
        <sphereGeometry args={[0.12, 24, 24]} />
        <meshStandardMaterial color="#fff3cf" emissive="#ffd27a" emissiveIntensity={0.55} roughness={0.4} />
      </mesh>
      <pointLight position={[0, 0.28, 0]} intensity={0.28} color="#ffd8a2" />
    </group>
  );
}

function Plant({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh castShadow>
        <cylinderGeometry args={[0.14, 0.18, 0.22, 18]} />
        <meshStandardMaterial color="#c6a26e" roughness={0.55} />
      </mesh>
      {[0, 1, 2, 3].map((index) => (
        <mesh key={index} castShadow position={[Math.cos(index * 1.57) * 0.1, 0.22, Math.sin(index * 1.57) * 0.1]}>
          <sphereGeometry args={[0.16, 16, 16]} />
          <meshStandardMaterial color={index % 2 ? "#5c8a4c" : "#6a9b56"} roughness={0.7} />
        </mesh>
      ))}
    </group>
  );
}

function StripedRug() {
  return (
    <group position={[0.1, 0.085, 0.02]}>
      <mesh receiveShadow>
        <boxGeometry args={[2.2, 0.025, 1.25]} />
        <meshStandardMaterial color="#efe7dc" roughness={0.8} />
      </mesh>
      {[-0.42, 0, 0.42].map((x) => (
        <mesh key={x} position={[x, 0.018, 0]}>
          <boxGeometry args={[0.18, 0.018, 1.18]} />
          <meshStandardMaterial color="#7a5134" roughness={0.8} />
        </mesh>
      ))}
    </group>
  );
}

function Corridor({ active }: { active: boolean }) {
  return (
    <group>
      {active && (
        <>
          <mesh position={[-0.7, 0.11, 2.95]}>
            <boxGeometry args={[6.0, 0.02, 0.5]} />
            <meshBasicMaterial color="#61b58f" transparent opacity={0.18} depthWrite={false} />
          </mesh>
        </>
      )}
      <mesh receiveShadow position={[-0.7, 0.055, 2.95]}>
        <boxGeometry args={[6.0, 0.045, 0.5]} />
        <meshStandardMaterial color="#e5ded2" />
      </mesh>
      {[-2.4, -0.9, 0.6, 2.1].map((x, index) => (
        <mesh key={`south-hall-${index}`} receiveShadow position={[x, 0.085, 2.95]}>
          <boxGeometry args={[1.0, 0.018, 0.08]} />
          <meshStandardMaterial color={index % 2 ? "#c6b49c" : "#f4efe5"} />
        </mesh>
      ))}
    </group>
  );
}

function Avatar({ position }: { position: { x: number; z: number } }) {
  return (
    <group position={[position.x, 0.12, position.z]}>
      <mesh castShadow position={[0, 0.18, 0]}>
        <cylinderGeometry args={[0.16, 0.18, 0.32, 28]} />
        <meshStandardMaterial color="#2f74c0" roughness={0.42} />
      </mesh>
      <mesh castShadow position={[0, 0.45, 0]}>
        <sphereGeometry args={[0.16, 28, 28]} />
        <meshStandardMaterial color="#f1c7a5" roughness={0.45} />
      </mesh>
      <mesh position={[0, 0.68, 0]}>
        <planeGeometry args={[0.82, 0.24]} />
        <meshBasicMaterial color="#12313c" transparent opacity={0.88} depthTest={false} />
      </mesh>
      <Text
        position={[0, 0.68, 0.014]}
        fontSize={0.14}
        color="#ffffff"
        anchorX="center"
        anchorY="middle"
        renderOrder={30}
      >
        我
      </Text>
      <pointLight position={[0, 0.85, 0]} intensity={0.32} color="#b6dcff" />
    </group>
  );
}

function RoomLabel({ label, size }: { label: string; size: [number, number] }) {
  return (
    <group position={[0, 1.12, 0]}>
      <mesh renderOrder={20}>
        <planeGeometry args={[Math.min(1.35, size[0] * 0.48), 0.38]} />
        <meshBasicMaterial color="#fffdf7" transparent opacity={0.92} depthTest={false} />
      </mesh>
      <Text
        position={[0, 0, 0.012]}
        fontSize={0.24}
        color="#203136"
        anchorX="center"
        anchorY="middle"
        renderOrder={21}
      >
        {label}
      </Text>
    </group>
  );
}

function EnvironmentBadge({ room, size }: { room: RoomState; size: [number, number] }) {
  return (
    <group position={[size[0] / 2 - 0.7, 1.06, size[1] / 2 - 0.34]}>
      <mesh renderOrder={18}>
        <planeGeometry args={[1.1, 0.24]} />
        <meshBasicMaterial color="#edf6f2" transparent opacity={0.86} depthTest={false} />
      </mesh>
      <Text
        position={[0, 0, 0.012]}
        fontSize={0.12}
        color="#31584d"
        anchorX="center"
        anchorY="middle"
        renderOrder={19}
      >
        {`${room.indoor_temperature_c.toFixed(1)}C  ${room.indoor_illuminance_lux.toFixed(0)}lx`}
      </Text>
    </group>
  );
}

function getRoom(state: SmartHomeState, roomId: RoomId) {
  return state.rooms.find((room) => room.room_id === roomId);
}

function findDevice<T extends DeviceState>(devices: DeviceState[], type: T["device_type"]) {
  return devices.find((device) => device.device_type === type) as T | undefined;
}

function getDaylight(weather: WeatherType, curtainOpeningPct: number) {
  const weatherFactor = {
    sunny: 1,
    cloudy: 0.62,
    overcast: 0.38,
    rainy: 0.22,
  }[weather];
  return weatherFactor * curtainOpeningPct / 100;
}

function getSkyColor(weather: WeatherType) {
  return {
    sunny: "#bde3ff",
    cloudy: "#cfdde5",
    overcast: "#aab3b9",
    rainy: "#879ba8",
  }[weather];
}

function getSceneBackground(weather: WeatherType) {
  return {
    sunny: "#eef6fb",
    cloudy: "#e7ecea",
    overcast: "#d8dddc",
    rainy: "#d3dbdd",
  }[weather];
}
