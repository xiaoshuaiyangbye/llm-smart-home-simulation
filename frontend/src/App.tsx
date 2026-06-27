import { useEffect, useMemo, useRef, useState } from "react";

import {
  backToToday,
  controlDevice,
  fetchLifeSimulationStatus,
  fetchSmartHomeState,
  resetSimulation,
  stepSimulation,
  startLifeSimulation,
  stopLifeSimulation,
  submitTask,
  tickLifeSimulation,
  updateEnvironment,
} from "./api/client";
import { AgentOutputPanel } from "./components/AgentOutputPanel";
import { ChartPanel } from "./components/ChartPanel";
import { ControlPanel } from "./components/ControlPanel";
import { LifeSimulationPanel } from "./components/LifeSimulationPanel";
import { StatePanel } from "./components/StatePanel";
import { HouseScene } from "./scene/HouseScene";
import type { ActivityType, AgentOutput, DeviceActionRequest, HistoryPoint, LifeSimulationDuration, LifeSimulationStatus, RoomId, SmartHomeState, WeatherType } from "./types/state";
import "./styles.css";

const ROOM_LABELS: Record<RoomId, string> = {
  living_room: "客厅",
  bedroom: "卧室",
  study_room: "书房",
  dining_room: "餐厅",
  kitchen: "厨房",
  bathroom: "卫生间",
  laundry: "洗衣区",
  balcony: "阳台",
  corridor: "走廊",
};

const ROOM_AREAS: Array<{ id: RoomId; x: number; z: number; w: number; d: number }> = [
  { id: "bedroom", x: -4.4, z: -2.22, w: 4.2, d: 3.36 },
  { id: "study_room", x: -0.35, z: -2.22, w: 3.9, d: 3.36 },
  { id: "bathroom", x: 3.05, z: -2.22, w: 2.9, d: 3.36 },
  { id: "living_room", x: -3.95, z: 1.08, w: 5.1, d: 3.24 },
  { id: "dining_room", x: 0.55, z: 1.08, w: 3.9, d: 3.24 },
  { id: "kitchen", x: 4.0, z: 1.08, w: 3.0, d: 3.24 },
  { id: "laundry", x: 1.4, z: 3.9, w: 2.4, d: 2.4 },
  { id: "balcony", x: -6.35, z: 3.45, w: 1.75, d: 2.35 },
  { id: "corridor", x: -0.7, z: 2.95, w: 6.0, d: 0.5 },
];

const ROOM_AVATAR_POSITIONS: Record<RoomId, { x: number; z: number }> = {
  living_room: { x: -3.85, z: 1.25 },
  bedroom: { x: -4.35, z: -2.1 },
  study_room: { x: -0.35, z: -2.12 },
  dining_room: { x: 0.55, z: 1.05 },
  kitchen: { x: 4.0, z: 1.02 },
  bathroom: { x: 3.05, z: -2.12 },
  laundry: { x: 1.4, z: 3.9 },
  balcony: { x: -6.35, z: 3.45 },
  corridor: { x: -0.7, z: 2.95 },
};

export default function App() {
  const [state, setState] = useState<SmartHomeState | null>(null);
  const [agentOutput, setAgentOutput] = useState<AgentOutput | null>(null);
  const [command, setCommand] = useState("");
  const [avatarPosition, setAvatarPosition] = useState({ x: -3.85, z: 1.25 });
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [lifeSimulation, setLifeSimulation] = useState<LifeSimulationStatus | null>(null);
  const tickInFlightRef = useRef(false);
  const isScreenshotMode = new URLSearchParams(window.location.search).get("screenshot") === "1";

  useEffect(() => {
    fetchSmartHomeState()
      .then((nextState) => applyState(nextState))
      .catch(() => setMessage("无法连接后端服务，请确认 FastAPI 已启动。"));
    fetchLifeSimulationStatus()
      .then((status) => {
        setLifeSimulation(status);
        if (status.active) applyLifeSimulationStatus(status);
      })
      .catch(() => undefined);
  }, []);

  const sceneTitle = useMemo(() => {
    if (!state) return "智能家居仿真实验平台";
    return `智能家居仿真实验平台 · ${state.outdoor_environment.weather} · ${state.outdoor_environment.time_hour}:00`;
  }, [state]);

  const currentRoomId = useMemo(() => getRoomAtPosition(avatarPosition), [avatarPosition]);
  const currentRoomName = ROOM_LABELS[currentRoomId];
  const isLifeSimulationActive = Boolean(lifeSimulation?.active);
  const sceneCurrentRoomId = isLifeSimulationActive ? (lifeSimulation?.current_room_id ?? "corridor") : currentRoomId;
  const sceneCurrentRoomName = isLifeSimulationActive ? (lifeSimulation?.current_room_name ?? "离家") : currentRoomName;
  const showAvatar = !isLifeSimulationActive || Boolean(lifeSimulation?.current_room_id);
  const displayedState = useMemo<SmartHomeState | null>(() => {
    if (!state) return null;
    if (isLifeSimulationActive) return state;
    return {
      ...state,
      rooms: state.rooms.map((room) => ({
        ...room,
        occupancy: room.room_id === currentRoomId,
        activity: getDisplayedActivity(room.activity, room.room_id === currentRoomId),
      })),
    };
  }, [isLifeSimulationActive, state, currentRoomId]);
  const llmModeLabel = getLlmModeLabel(agentOutput?.semantic_result?.llm_mode);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (isEditableTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (!["w", "a", "s", "d"].includes(key)) return;
      event.preventDefault();
      setAvatarPosition((position) => {
        const speed = event.shiftKey ? 0.42 : 0.28;
        const next = { ...position };
        if (key === "w") next.z -= speed;
        if (key === "s") next.z += speed;
        if (key === "a") next.x -= speed;
        if (key === "d") next.x += speed;
        return clampToHome(next);
      });
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    if (!isLifeSimulationActive) return;
    const timer = window.setInterval(() => {
      if (tickInFlightRef.current) return;
      tickInFlightRef.current = true;
      tickLifeSimulation()
        .then((status) => {
          applyLifeSimulationStatus(status);
          if (!status.active && status.total_minutes > 0) {
            setMessage("生活快速仿真已完成，日志和分析报告已生成。");
          }
        })
        .catch((error: unknown) => {
          setMessage(error instanceof Error ? error.message : "生活仿真推进失败。");
        })
        .finally(() => {
          tickInFlightRef.current = false;
        });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isLifeSimulationActive]);

  function applyState(nextState: SmartHomeState) {
    setState(nextState);
    const livingRoom = nextState.rooms.find((room) => room.room_id === "living_room");
    if (livingRoom) {
      setHistory((previous) => [
        ...previous.slice(-19),
        {
          step: nextState.current_time_step,
          livingRoomIlluminance: livingRoom.indoor_illuminance_lux,
          livingRoomTemperature: livingRoom.indoor_temperature_c,
          currentPowerW: nextState.energy_metrics.current_power_w,
        },
      ]);
    }
  }

  function applyLifeSimulationStatus(status: LifeSimulationStatus) {
    setLifeSimulation(status);
    applyState(status.state);
    if (status.current_room_id) {
      setAvatarPosition(ROOM_AVATAR_POSITIONS[status.current_room_id]);
    }
    if (status.last_agent_output) {
      setAgentOutput(status.last_agent_output);
    }
  }

  async function runWithLoading(work: () => Promise<void>) {
    setIsLoading(true);
    setMessage("");
    try {
      await work();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败，请检查后端接口状态。");
    } finally {
      setIsLoading(false);
    }
  }

  function handleStep() {
    return runWithLoading(async () => {
      const nextState = await stepSimulation(1);
      applyState(nextState);
      setMessage("已推进 1 分钟仿真。");
    });
  }

  function handleReset() {
    return runWithLoading(async () => {
      const nextState = await resetSimulation();
      setAgentOutput(null);
      setHistory([]);
      setLifeSimulation(null);
      applyState(nextState);
      setMessage("系统已重置。");
    });
  }

  function handleStartLifeSimulation(duration: LifeSimulationDuration) {
    return runWithLoading(async () => {
      const status = await startLifeSimulation(duration);
      applyLifeSimulationStatus(status);
      setMessage(`已启动${durationLabel(duration)}生活快速仿真，24 小时仿真约 24 分钟。`);
    });
  }

  function handleStopLifeSimulation() {
    return runWithLoading(async () => {
      const status = await stopLifeSimulation();
      applyLifeSimulationStatus(status);
      setMessage("生活仿真已停止，已保留当前日志与分析。");
    });
  }

  function handleBackToToday() {
    return runWithLoading(async () => {
      const nextState = await backToToday();
      setLifeSimulation(null);
      setAgentOutput(null);
      setHistory([]);
      applyState(nextState);
      const currentRoom = nextState.rooms.find((room) => room.occupancy)?.room_id ?? "living_room";
      setAvatarPosition(ROOM_AVATAR_POSITIONS[currentRoom]);
      setMessage("已回到今天的实时环境。");
    });
  }

  function handleEnvironmentChange(payload: Partial<{ weather: WeatherType; time_hour: number }>) {
    return runWithLoading(async () => {
      const nextState = await updateEnvironment(payload);
      applyState(nextState);
      setMessage("室外环境已更新。");
    });
  }

  function handleDeviceAction(request: DeviceActionRequest) {
    return runWithLoading(async () => {
      const response = await controlDevice(request);
      applyState(response.after_state);
      setMessage(response.message);
    });
  }

  function handleTaskSubmit() {
    return runWithLoading(async () => {
      const scopedCommand = withCurrentRoomContext(command, currentRoomName);
      const response = await submitTask(scopedCommand, currentRoomId);
      applyState(response.state);
      setAgentOutput(response.agent_output);
      setMessage(`智能体已感知你在${currentRoomName}，并完成任务规划与控制。`);
    });
  }

  return (
    <main className={`app-shell${isScreenshotMode ? " screenshot-mode" : ""}`}>
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">⌂</span>
          <strong>智能家居仿真实验平台</strong>
        </div>
        <div className="topbar-meta" aria-label="simulation status">
          <span>{state?.outdoor_environment.weather ?? "cloudy"}</span>
          <span>{state ? `${state.outdoor_environment.outdoor_temperature_c.toFixed(0)}°C` : "--"}</span>
          <span>{state ? `${state.outdoor_environment.time_hour}:00:00` : "--"}</span>
        </div>
        <div className="topbar-actions">
          <span className="status-pill">{llmModeLabel}</span>
          <span className="avatar-dot" aria-hidden="true" />
        </div>
      </header>
      <section className="workspace-panel">
        <div className="workspace-heading">
          <div className="breadcrumb-line">
            <span>实验场景</span>
            <i aria-hidden="true" />
            <h1>{sceneTitle}</h1>
            <span className={isLifeSimulationActive ? "live-badge active" : "live-badge"}>
              {isLifeSimulationActive ? "运行中" : "待启动"}
            </span>
          </div>
        </div>
      <div className="dashboard">
        <section className="scene-panel">
          <HouseScene
            state={displayedState}
            avatarPosition={avatarPosition}
            currentRoomId={sceneCurrentRoomId}
            avatarVisible={showAvatar}
          />
          <button className="scene-fullscreen" type="button" aria-label="fullscreen">全屏</button>
          <div className="scene-rail" aria-hidden="true">
            <span>测温</span>
            <span>设备</span>
            <span>结构</span>
          </div>
          <div className="scene-toolbar" aria-hidden="true">
            <span>视角控制</span>
            <span>鸟瞰</span>
            <span>漫游</span>
            <span>复位</span>
          </div>
          <div className="movement-hint">
            {isLifeSimulationActive ? `生活仿真：${sceneCurrentRoomName}` : `W/A/S/D 移动“我”：当前在 ${currentRoomName}`}
          </div>
        </section>
        <aside className="side-panel">
          <LifeSimulationPanel
            status={lifeSimulation}
            isLoading={isLoading}
            onStart={handleStartLifeSimulation}
            onStop={handleStopLifeSimulation}
            onBackToToday={handleBackToToday}
          />
          <StatePanel state={displayedState} lastMessage={message} />
          <ControlPanel
            state={displayedState}
            isLoading={isLoading || isLifeSimulationActive}
            onStep={handleStep}
            onReset={handleReset}
            onEnvironmentChange={handleEnvironmentChange}
            onDeviceAction={handleDeviceAction}
          />
          <ChartPanel history={history} />
        </aside>
      </div>
      <AgentOutputPanel
        command={command}
        onCommandChange={setCommand}
        onSubmit={handleTaskSubmit}
        output={agentOutput}
        isLoading={isLoading || isLifeSimulationActive}
      />
      </section>
    </main>
  );
}

function getRoomAtPosition(position: { x: number; z: number }): RoomId {
  const area = ROOM_AREAS.find(
    (room) =>
      position.x >= room.x - room.w / 2 &&
      position.x <= room.x + room.w / 2 &&
      position.z >= room.z - room.d / 2 &&
      position.z <= room.z + room.d / 2,
  );
  return area?.id ?? "corridor";
}

function clampToHome(position: { x: number; z: number }) {
  return {
    x: Math.max(-7.25, Math.min(5.55, position.x)),
    z: Math.max(-3.9, Math.min(5.08, position.z)),
  };
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return target.isContentEditable || ["input", "textarea", "select", "button"].includes(tagName);
}

function withCurrentRoomContext(command: string, roomName: string) {
  const hasRoom = ["客厅", "卧室", "书房", "餐厅", "厨房", "卫生间", "洗衣区", "阳台", "走廊"].some((name) =>
    command.includes(name),
  );
  if (hasRoom) return command;
  return `我现在在${roomName}。${command}`;
}

function getDisplayedActivity(activity: ActivityType, isCurrentRoom: boolean): ActivityType {
  if (!isCurrentRoom) return "away";
  return activity === "away" ? "idle" : activity;
}

function getLlmModeLabel(mode: unknown): string {
  if (mode === "real") return "Real LLM";
  return "LLM Agent";
}

function durationLabel(duration: LifeSimulationDuration): string {
  if (duration === "day") return "一天";
  if (duration === "week") return "一周";
  return "一个月";
}
