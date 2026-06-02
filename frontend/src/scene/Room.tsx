import type {
  AcDeviceState,
  CurtainDeviceState,
  DeviceState,
  FanDeviceState,
  LightDeviceState,
  RoomState,
  WeatherType,
  WindowDeviceState,
} from "../types/state";
import { Devices } from "./Devices";

const ROOM_COLORS: Record<string, string> = {
  living_room: "#d8e4df",
  bedroom: "#e7ddd3",
  study_room: "#d9e0ea",
};

interface RoomProps {
  room: RoomState;
  devices: DeviceState[];
  position: [number, number, number];
  weather: WeatherType;
}

export function Room({ room, devices, position, weather }: RoomProps) {
  const light = findDevice<LightDeviceState>(devices, room.room_id, "light");
  const curtain = findDevice<CurtainDeviceState>(devices, room.room_id, "curtain");
  const ac = findDevice<AcDeviceState>(devices, room.room_id, "ac");
  const fan = findDevice<FanDeviceState>(devices, room.room_id, "fan");
  const windowDevice = findDevice<WindowDeviceState>(devices, room.room_id, "window");
  const lampIntensity = light?.is_on ? 0.3 + light.brightness_pct / 100 : 0.08;
  const daylightStrength = getDaylightStrength(weather) * ((curtain?.opening_pct ?? 60) / 100);

  return (
    <group position={position}>
      <mesh receiveShadow position={[0, -0.05, 0]}>
        <boxGeometry args={[4.2, 0.1, 3.4]} />
        <meshStandardMaterial color="#c8bda9" />
      </mesh>
      <mesh position={[0, 1.35, -1.7]}>
        <boxGeometry args={[4.2, 2.8, 0.1]} />
        <meshStandardMaterial color={ROOM_COLORS[room.room_id]} />
      </mesh>
      <mesh position={[-2.1, 1.35, 0]}>
        <boxGeometry args={[0.1, 2.8, 3.4]} />
        <meshStandardMaterial color="#edf0ea" />
      </mesh>
      <mesh position={[2.1, 1.35, 0]}>
        <boxGeometry args={[0.1, 2.8, 3.4]} />
        <meshStandardMaterial color="#edf0ea" />
      </mesh>

      <Window openingPct={windowDevice?.opening_pct ?? 20} curtainOpeningPct={curtain?.opening_pct ?? 60} daylightStrength={daylightStrength} />
      <Devices room={room} light={light} ac={ac} fan={fan} />
      <Furniture roomId={room.room_id} />

      <pointLight
        position={[0, 2.35, -0.1]}
        intensity={lampIntensity}
        color={light?.color_temperature_k && light.color_temperature_k < 3600 ? "#ffd6a0" : "#fff2d2"}
      />
      <pointLight position={[-1.5, 1.4, -1.25]} intensity={daylightStrength} color="#cfe8ff" />
    </group>
  );
}

function Window({
  openingPct,
  curtainOpeningPct,
  daylightStrength,
}: {
  openingPct: number;
  curtainOpeningPct: number;
  daylightStrength: number;
}) {
  const curtainWidth = 1.5 * (1 - curtainOpeningPct / 100);
  return (
    <group position={[-1.25, 1.35, -1.76]}>
      <mesh>
        <boxGeometry args={[1.55, 1, 0.04]} />
        <meshStandardMaterial color="#b8d9ef" emissive="#b8d9ef" emissiveIntensity={daylightStrength * 0.18} />
      </mesh>
      <mesh position={[-0.78 + curtainWidth / 2, 0, 0.04]}>
        <boxGeometry args={[Math.max(0.04, curtainWidth), 1.08, 0.04]} />
        <meshStandardMaterial color="#8d6f62" />
      </mesh>
      <mesh position={[0.78 - curtainWidth / 2, 0, 0.04]}>
        <boxGeometry args={[Math.max(0.04, curtainWidth), 1.08, 0.04]} />
        <meshStandardMaterial color="#8d6f62" />
      </mesh>
      <mesh position={[0, -0.64, 0.08]}>
        <boxGeometry args={[1.4 * (openingPct / 100), 0.06, 0.06]} />
        <meshStandardMaterial color="#8aa4b4" />
      </mesh>
    </group>
  );
}

function Furniture({ roomId }: { roomId: string }) {
  if (roomId === "bedroom") {
    return (
      <group>
        <mesh position={[0.55, 0.28, 0.35]}>
          <boxGeometry args={[1.65, 0.38, 1.25]} />
          <meshStandardMaterial color="#9f8d7a" />
        </mesh>
        <mesh position={[0.05, 0.58, -0.25]}>
          <boxGeometry args={[0.65, 0.2, 0.42]} />
          <meshStandardMaterial color="#e9e2d8" />
        </mesh>
      </group>
    );
  }
  if (roomId === "study_room") {
    return (
      <group>
        <mesh position={[0.55, 0.42, -0.85]}>
          <boxGeometry args={[1.55, 0.15, 0.72]} />
          <meshStandardMaterial color="#8c6e50" />
        </mesh>
        <mesh position={[0.55, 0.22, -0.85]}>
          <boxGeometry args={[0.12, 0.45, 0.12]} />
          <meshStandardMaterial color="#5c4a38" />
        </mesh>
        <mesh position={[1.25, 0.35, 0.25]}>
          <boxGeometry args={[0.55, 0.7, 0.55]} />
          <meshStandardMaterial color="#4e6865" />
        </mesh>
      </group>
    );
  }
  return (
    <group>
      <mesh position={[-0.15, 0.32, 0.55]}>
        <boxGeometry args={[1.75, 0.55, 0.75]} />
        <meshStandardMaterial color="#60776b" />
      </mesh>
      <mesh position={[1.25, 0.25, -0.15]}>
        <boxGeometry args={[0.82, 0.28, 0.62]} />
        <meshStandardMaterial color="#946b4e" />
      </mesh>
    </group>
  );
}

function findDevice<T extends DeviceState>(
  devices: DeviceState[],
  roomId: string,
  deviceType: T["device_type"],
) {
  return devices.find((device) => device.room === roomId && device.device_type === deviceType) as T | undefined;
}

function getDaylightStrength(weather: WeatherType) {
  return {
    sunny: 1.05,
    cloudy: 0.62,
    overcast: 0.35,
    rainy: 0.22,
  }[weather];
}

