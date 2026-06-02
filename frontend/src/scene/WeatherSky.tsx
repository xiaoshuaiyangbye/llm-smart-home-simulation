import type { WeatherType } from "../types/state";

interface WeatherSkyProps {
  weather: WeatherType;
}

const WEATHER_STYLE: Record<WeatherType, { color: string; label: string; symbol: string }> = {
  sunny: { color: "#b9dcff", label: "sunny", symbol: "SUN" },
  cloudy: { color: "#c7d3dc", label: "cloudy", symbol: "CLD" },
  overcast: { color: "#aeb8bf", label: "overcast", symbol: "OVC" },
  rainy: { color: "#879ba8", label: "rainy", symbol: "RAN" },
};

export function WeatherSky({ weather }: WeatherSkyProps) {
  const style = WEATHER_STYLE[weather];
  return (
    <group position={[0, 2.95, -2.25]}>
      <mesh>
        <planeGeometry args={[13.8, 1.2]} />
        <meshStandardMaterial color={style.color} emissive={style.color} emissiveIntensity={0.22} />
      </mesh>
      <WeatherMarker weather={weather} />
    </group>
  );
}

function WeatherMarker({ weather }: { weather: WeatherType }) {
  const isRainy = weather === "rainy";
  const isSunny = weather === "sunny";
  return (
    <group position={[-5.8, 0.12, 0.08]}>
      <mesh>
        <sphereGeometry args={[0.22, 24, 24]} />
        <meshStandardMaterial color={isSunny ? "#ffd55a" : "#e9edf0"} />
      </mesh>
      {!isSunny && (
        <>
          <mesh position={[0.22, 0, 0]}>
            <sphereGeometry args={[0.2, 24, 24]} />
            <meshStandardMaterial color="#eef2f4" />
          </mesh>
          <mesh position={[0.43, -0.04, 0]}>
            <sphereGeometry args={[0.15, 24, 24]} />
            <meshStandardMaterial color="#dce3e7" />
          </mesh>
        </>
      )}
      {isRainy && [0, 1, 2].map((index) => (
        <mesh key={index} position={[0.08 + index * 0.16, -0.42, 0]} rotation={[0, 0, -0.28]}>
          <boxGeometry args={[0.025, 0.26, 0.025]} />
          <meshStandardMaterial color="#4d7f9f" />
        </mesh>
      ))}
    </group>
  );
}

