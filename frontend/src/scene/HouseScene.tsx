import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls as ThreeOrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { useEffect, useMemo, useState } from "react";

import type { RoomId, SmartHomeState, WeatherType } from "../types/state";
import { HomeScene2D } from "./HomeScene2D";
import { HomeScene3D } from "./HomeScene3D";
import { floorPlanBounds } from "../data/floorPlan";

interface HouseSceneProps {
  state: SmartHomeState | null;
  avatarPosition: { x: number; z: number };
  currentRoomId: RoomId;
  avatarVisible?: boolean;
  cameraMode?: "3d" | "2d";
  sceneLayer?: "sensors" | "devices" | "structure";
  resetKey?: number;
}

export function HouseScene({
  state,
  avatarPosition,
  currentRoomId,
  avatarVisible = true,
  cameraMode = "3d",
  sceneLayer = "sensors",
  resetKey = 0,
}: HouseSceneProps) {
  const [selection, setSelection] = useState("");

  if (!state) {
    return <div className="scene-placeholder">正在加载户型场景...</div>;
  }

  const is2D = cameraMode === "2d";
  const camera = is2D
    ? { position: [floorPlanBounds.center[0], 13.5, floorPlanBounds.center[1] + 0.01] as [number, number, number], zoom: 62 }
    : {
        position: [floorPlanBounds.center[0], 12.5, floorPlanBounds.center[1] + 9] as [number, number, number],
        zoom: 34,
      };
  const target = [floorPlanBounds.center[0], 0.08, floorPlanBounds.center[1]] as [number, number, number];

  return (
    <>
      <Canvas
        key={`${cameraMode}-${resetKey}`}
        orthographic
        shadows={!is2D}
        dpr={[1, 2]}
        camera={camera}
        gl={{ antialias: true, alpha: true }}
        onPointerMissed={() => setSelection("")}
      >
        <color attach="background" args={[is2D ? "#f9f6ef" : getSceneBackground(state.outdoor_environment.weather)]} />
        <SceneLighting weather={state.outdoor_environment.weather} flat={is2D} />
        {is2D ? (
          <HomeScene2D
            state={state}
            avatarPosition={avatarPosition}
            currentRoomId={currentRoomId}
            avatarVisible={avatarVisible}
            sceneLayer={sceneLayer}
            onSelect={setSelection}
          />
        ) : (
          <HomeScene3D
            state={state}
            avatarPosition={avatarPosition}
            currentRoomId={currentRoomId}
            avatarVisible={avatarVisible}
            sceneLayer={sceneLayer}
            onSelect={setSelection}
          />
        )}
        {!is2D && <GroundShadow />}
        <SceneControls is2D={is2D} target={target} />
      </Canvas>
      {selection && <div className="scene-selection-card">{selection}</div>}
    </>
  );
}

function GroundShadow() {
  return (
    <mesh position={[floorPlanBounds.center[0], -0.165, floorPlanBounds.center[1]]} rotation={[-Math.PI / 2, 0, 0]} scale={[7.3, 4.2, 1]}>
      <circleGeometry args={[1, 48]} />
      <meshBasicMaterial color="#74695b" transparent opacity={0.12} depthWrite={false} />
    </mesh>
  );
}

function SceneControls({ is2D, target }: { is2D: boolean; target: [number, number, number] }) {
  const { camera, gl, invalidate } = useThree();
  const controls = useMemo(() => new ThreeOrbitControls(camera, gl.domElement), [camera, gl]);

  useEffect(() => {
    controls.enableDamping = true;
    controls.enableRotate = !is2D;
    controls.enablePan = true;
    controls.enableZoom = true;
    controls.minZoom = is2D ? 46 : 28;
    controls.maxZoom = is2D ? 112 : 80;
    controls.minPolarAngle = is2D ? 0 : Math.PI / 9;
    controls.maxPolarAngle = is2D ? 0 : Math.PI / 2.35;
    controls.target.set(...target);
    const onChange = () => invalidate();
    controls.addEventListener("change", onChange);
    controls.update();
    return () => {
      controls.removeEventListener("change", onChange);
      controls.dispose();
    };
  }, [controls, invalidate, is2D, target]);

  useFrame(() => controls.update());
  return null;
}

function SceneLighting({ weather, flat }: { weather: WeatherType; flat: boolean }) {
  const ambient = {
    sunny: 0.82,
    cloudy: 0.7,
    overcast: 0.58,
    rainy: 0.5,
  }[weather];

  if (flat) {
    return (
      <>
      <ambientLight intensity={1.18} />
      <directionalLight position={[0, 8, 2]} intensity={0.42} />
      </>
    );
  }

  return (
    <>
      <hemisphereLight args={["#fffdfa", "#d8cbb9", ambient * 1.08]} />
      <ambientLight intensity={ambient * 0.64} />
      <directionalLight
        castShadow
        position={[5.8, 9.2, 6.4]}
        intensity={ambient * 1.7}
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-left={-8}
        shadow-camera-right={8}
        shadow-camera-top={7}
        shadow-camera-bottom={-7}
      />
      <directionalLight position={[-5.2, 4.6, -3.6]} intensity={ambient * 0.28} color="#fff2dd" />
    </>
  );
}

function getSceneBackground(weather: WeatherType) {
  return {
    sunny: "#f2f0e9",
    cloudy: "#efeee8",
    overcast: "#e8e6df",
    rainy: "#e4e7e4",
  }[weather];
}
