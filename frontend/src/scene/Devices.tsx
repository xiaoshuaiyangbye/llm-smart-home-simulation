import type { AcDeviceState, FanDeviceState, LightDeviceState, RoomState } from "../types/state";

interface DevicesProps {
  room: RoomState;
  light?: LightDeviceState;
  ac?: AcDeviceState;
  fan?: FanDeviceState;
}

export function Devices({ room, light, ac, fan }: DevicesProps) {
  const lampGlow = light?.is_on ? light.brightness_pct / 100 : 0.05;
  const acColor = ac?.is_on ? "#5aa7d8" : "#8b9495";
  const fanColor = fan?.is_on ? "#4f776b" : "#7b817f";

  return (
    <group>
      <mesh castShadow position={[0, 2.35, -0.05]}>
        <sphereGeometry args={[0.18, 24, 24]} />
        <meshStandardMaterial color="#fff4bf" emissive="#ffd36a" emissiveIntensity={lampGlow} />
      </mesh>
      <mesh castShadow position={[1.55, 1.85, -1.62]}>
        <boxGeometry args={[0.68, 0.28, 0.12]} />
        <meshStandardMaterial color={acColor} />
      </mesh>
      <mesh castShadow position={[-1.45, 0.48, 1.05]}>
        <cylinderGeometry args={[0.22, 0.22, 0.08, 24]} />
        <meshStandardMaterial color={fanColor} />
      </mesh>
      <mesh castShadow position={[-1.45, 0.72, 1.05]}>
        <cylinderGeometry args={[0.03, 0.03, 0.45, 16]} />
        <meshStandardMaterial color="#67706e" />
      </mesh>
      <mesh castShadow position={[-1.45, 0.98, 1.05]} rotation={[0, 0, (fan?.speed_pct ?? 0) / 30]}>
        <boxGeometry args={[0.75, 0.04, 0.08]} />
        <meshStandardMaterial color={fanColor} />
      </mesh>
      <mesh position={[1.96, 0.52, 1.18]}>
        <boxGeometry args={[0.04, 0.22, 0.22]} />
        <meshStandardMaterial color={room.occupancy ? "#4a7c59" : "#b8bbb6"} />
      </mesh>
    </group>
  );
}

