import type { SmartHomeState } from "../types/state";

interface LightingProps {
  state: SmartHomeState;
}

export function Lighting({ state }: LightingProps) {
  const weatherAmbient = {
    sunny: 0.62,
    cloudy: 0.45,
    overcast: 0.34,
    rainy: 0.28,
  }[state.outdoor_environment.weather];

  return (
    <>
      <ambientLight intensity={weatherAmbient} />
      <directionalLight
        castShadow
        position={[4, 7, 4]}
        intensity={weatherAmbient * 1.2}
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
    </>
  );
}

