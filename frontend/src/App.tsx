import { WorkspaceNavigation, workspacePages, type WorkspacePage } from "./components/WorkspaceNavigation";
import { homeGeometry } from "./data/homeGeometry";
import { moveWithinHome, roomAtPosition } from "./data/homeMovement";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

import {
  backToToday,
  controlDevice,
  createAuthSession,
  fetchAgentHealth,
  fetchAutonomousRuntimeStatus,
  fetchAuthStatus,
  fetchResearchProfile,
  fetchPrivateUserMemory,
  fetchRobustnessConfig,
  fetchLifeSimulationStatus,
  fetchSmartHomeState,
  resetSimulation,
  resetPrivateUserMemory,
  startAutonomousRuntime,
  stepSimulation,
  startLifeSimulation,
  stopLifeSimulation,
  stopAutonomousRuntime,
  submitResearchFeedback,
  submitTaskWithTrace,
  tickLifeSimulation,
  updateCurrentRoom,
  updateEnvironment,
  updateResearchProfile,
  updatePrivateUserAttributes,
  updateRobustnessConfig,
} from "./api/client";
import { AgentOutputPanel } from "./components/AgentOutputPanel";
import { AccessGate } from "./components/AccessGate";
import { ChartPanel } from "./components/ChartPanel";
import { ControlPanel } from "./components/ControlPanel";
import { LifeSimulationPanel } from "./components/LifeSimulationPanel";
import { ResearchControlPanel } from "./components/ResearchControlPanel";
import { StatePanel } from "./components/StatePanel";
import { ViewModeToggle, type SceneViewMode } from "./components/ViewModeToggle";
import { HomePlan2D } from "./scene/HomePlan2D";
import type { AgentHealth, AgentOutput, AgentTraceStage, AutonomousRuntimeStatus, DeviceActionRequest, HistoryPoint, LifeSimulationDuration, LifeSimulationStatus, PrivateUserMemory, RobustnessConfig, RoomId, SmartHomeState, UserPreferenceProfile, WeatherType } from "./types/state";
import "./styles.css";
import "./styles-mi-home.css";
import "./styles-workspace.css";

const HouseScene = lazy(async () => {
  const module = await import("./scene/HouseScene");
  return { default: module.HouseScene };
});
const EnergyPlusPanel = lazy(() => import("./components/EnergyPlusPanel"));

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

const ROOM_AVATAR_POSITIONS = Object.fromEntries(homeGeometry.map((room) => [room.id, { x: room.x, z: room.z }])) as Record<RoomId, { x: number; z: number }>;

function formatClockTime(state: SmartHomeState): string {
  const { time_hour: hour, time_minute: minute } = state.outdoor_environment;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export default function App() {
  const [state, setState] = useState<SmartHomeState | null>(null);
  const [agentOutput, setAgentOutput] = useState<AgentOutput | null>(null);
  const [liveAgentStages, setLiveAgentStages] = useState<AgentTraceStage[]>([]);
  const [command, setCommand] = useState("");
  const [energyPlusOpen, setEnergyPlusOpen] = useState(false);
  const [activePage, setActivePage] = useState<WorkspacePage>(() => {
    const page = window.location.hash.slice(1);
    return page in workspacePages ? page as WorkspacePage : "overview";
  });
  function navigate(page: WorkspacePage) {
    setActivePage(page);
    window.history.pushState(null, "", `#${page}`);
    window.scrollTo({ top: 0 });
  }
  useEffect(() => {
    const syncPage = () => {
      const page = window.location.hash.slice(1);
      setActivePage(page in workspacePages ? page as WorkspacePage : "overview");
    };
    window.addEventListener("popstate", syncPage);
    window.addEventListener("hashchange", syncPage);
    return () => { window.removeEventListener("popstate", syncPage); window.removeEventListener("hashchange", syncPage); };
  }, []);
  const [avatarPosition, setAvatarPosition] = useState({ x: -3.85, z: 1.25 });
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [lifeSimulation, setLifeSimulation] = useState<LifeSimulationStatus | null>(null);
  const [agentHealth, setAgentHealth] = useState<AgentHealth | null>(null);
  const [researchProfile, setResearchProfile] = useState<UserPreferenceProfile | null>(null);
  const [robustnessConfig, setRobustnessConfig] = useState<RobustnessConfig | null>(null);
  const [privateMemory, setPrivateMemory] = useState<PrivateUserMemory | null>(null);
  const [autonomyStatus, setAutonomyStatus] = useState<AutonomousRuntimeStatus | null>(null);
  const [presenceHydrated, setPresenceHydrated] = useState(false);
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authError, setAuthError] = useState("");
  const [sceneView, setSceneView] = useState<SceneViewMode>(
    new URLSearchParams(window.location.search).get("view") === "3d" ? "3d" : "2d",
  );
  const [sceneLayer, setSceneLayer] = useState<"sensors" | "devices" | "structure">("sensors");
  const [sceneResetKey, setSceneResetKey] = useState(0);
  const scenePanelRef = useRef<HTMLElement | null>(null);
  const tickInFlightRef = useRef(false);
  const lastAutonomyCycleRef = useRef<string | null>(null);
  const lastSyncedRoomRef = useRef<RoomId | null>(null);
  const isScreenshotMode = new URLSearchParams(window.location.search).get("screenshot") === "1";

  useEffect(() => {
    fetchAuthStatus()
      .then(({ requires_auth }) => {
        setAuthRequired(requires_auth);
        setIsAuthenticated(!requires_auth);
      })
      .catch((error: unknown) => {
        setAuthRequired(true);
        setAuthError(error instanceof Error ? error.message : "无法确认访问权限。");
      });
  }, []);

  useEffect(() => {
    if (authRequired === null || !isAuthenticated) return;
    fetchSmartHomeState()
      .then((nextState) => {
        applyState(nextState);
        const occupiedRoom = nextState.rooms.find((room) => room.occupancy)?.room_id ?? "living_room";
        setAvatarPosition(ROOM_AVATAR_POSITIONS[occupiedRoom]);
        lastSyncedRoomRef.current = occupiedRoom;
        setPresenceHydrated(true);
      })
      .catch(() => setMessage("无法连接后端服务，请确认 FastAPI 已启动。"));
    fetchLifeSimulationStatus()
      .then((status) => {
        setLifeSimulation(status);
        if (status.active) applyLifeSimulationStatus(status);
      })
      .catch(() => undefined);
    fetchAgentHealth().then(setAgentHealth).catch(() => setAgentHealth(null));
    fetchResearchProfile().then(setResearchProfile).catch(() => setResearchProfile(null));
    fetchPrivateUserMemory().then(setPrivateMemory).catch(() => setPrivateMemory(null));
    fetchAutonomousRuntimeStatus().then(setAutonomyStatus).catch(() => setAutonomyStatus(null));
    fetchRobustnessConfig().then(setRobustnessConfig).catch(() => setRobustnessConfig(null));
  }, [authRequired, isAuthenticated]);


  const currentRoomId = useMemo(() => roomAtPosition(avatarPosition) ?? "living_room", [avatarPosition]);
  const currentRoomName = ROOM_LABELS[currentRoomId];
  const isLifeSimulationActive = Boolean(lifeSimulation?.active);
  const isAutonomyActive = Boolean(autonomyStatus?.active);
  const confirmedRoomId = state?.rooms.find((room) => room.occupancy)?.room_id ?? currentRoomId;
  const canStartLifeSimulation = agentHealth?.success === true && agentHealth.llm_mode === "real" && !isAutonomyActive;
  const lifeSimulationUnavailableReason = isAutonomyActive
    ? "请先停止后端自治服务，再启动生活快速仿真。"
    : agentHealth?.llm_mode === "mock"
    ? "生活推演需要已连接的真实模型。当前可使用手动控制、家庭助手的模拟语义或物理实验。"
    : agentHealth
    ? agentHealth.error ?? "生活仿真需要已验证的真实 LLM 服务。"
    : "正在检查真实 LLM 服务，请稍后重试。";
  const sceneCurrentRoomId = isLifeSimulationActive ? (lifeSimulation?.current_room_id ?? "corridor") : confirmedRoomId;
  const sceneCurrentRoomName = isLifeSimulationActive ? (lifeSimulation?.current_room_name ?? "离家") : ROOM_LABELS[confirmedRoomId];
  const showAvatar = !isLifeSimulationActive || Boolean(lifeSimulation?.current_room_id);
  const displayedState = state;
  const focusedRoom = displayedState?.rooms.find((room) => room.room_id === sceneCurrentRoomId);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (activePage !== "overview" || !presenceHydrated) return;
      if (isLifeSimulationActive) return;
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
        return moveWithinHome(position, next);
      });
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isLifeSimulationActive, activePage, presenceHydrated]);

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

  useEffect(() => {
    if (!isAuthenticated || !presenceHydrated || isLifeSimulationActive) return;
    if (lastSyncedRoomRef.current === currentRoomId) return;
    const previousRoom = lastSyncedRoomRef.current;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      lastSyncedRoomRef.current = currentRoomId;
      updateCurrentRoom(currentRoomId)
        .then((result) => {
          if (!cancelled) applyState(result.state);
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          lastSyncedRoomRef.current = previousRoom;
          if (previousRoom) setAvatarPosition(ROOM_AVATAR_POSITIONS[previousRoom]);
          setMessage(error instanceof Error ? error.message : "无法同步当前房间感知状态。");
        });
    }, 120);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [currentRoomId, isAuthenticated, isLifeSimulationActive, presenceHydrated]);

  useEffect(() => {
    if (!isAutonomyActive) return;
    const timer = window.setInterval(() => {
      fetchAutonomousRuntimeStatus()
        .then((status) => {
          setAutonomyStatus(status);
          const result = status.last_result;
          if (!result || result.cycle_at === lastAutonomyCycleRef.current) return;
          lastAutonomyCycleRef.current = result.cycle_at;
          applyState(result.state);
          if (result.agent_response?.success && result.agent_response.final_state) {
            const response = result.agent_response;
            setAgentOutput({
              semantic_result: response.semantic_result,
              planning_result: response.plan_result,
              execution_result: response.execution_result,
              feedback_result: response.feedback_result,
              actions: Array.isArray(response.plan_result.actions) ? response.plan_result.actions : [],
              multi_agent_blackboard: response.multi_agent_blackboard,
            });
            setMessage(`后端自治决策：${result.decision?.reason ?? "已完成一次自主控制"}`);
            fetchPrivateUserMemory().then(setPrivateMemory).catch(() => undefined);
          } else if (result.decision?.suppression_reason === "repeated_trigger_cooldown") {
            setMessage("后端自治服务持续感知中；同类动作处于冷却期，本周期未重复执行。");
          }
        })
        .catch((error: unknown) => {
          setMessage(error instanceof Error ? error.message : "无法读取后端自治服务状态。");
        });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [isAutonomyActive]);

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
      lastSyncedRoomRef.current = status.current_room_id;
    }
    if (status.last_agent_output) {
      setAgentOutput(status.last_agent_output);
    }
  }

  async function runWithLoading(work: () => Promise<void>, rethrow = false) {
    setIsLoading(true);
    setMessage("");
    try {
      await work();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败，请检查后端接口状态。");
      if (rethrow) throw error;
    } finally {
      setIsLoading(false);
    }
  }

  async function handleAuthentication(accessToken: string) {
    setIsLoading(true);
    setAuthError("");
    try {
      await createAuthSession(accessToken);
      setIsAuthenticated(true);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "访问验证失败。");
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
      if (isAutonomyActive) {
        const status = await stopAutonomousRuntime();
        setAutonomyStatus(status);
        if (status.active) {
          setMessage("自治服务正在结束当前周期；完全停止后请再次执行重置。");
          return;
        }
      }
      const nextState = await resetSimulation();
      setAgentOutput(null);
      setHistory([]);
      setLifeSimulation(null);
      setAvatarPosition(ROOM_AVATAR_POSITIONS.living_room);
      lastSyncedRoomRef.current = "living_room";
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
      lastSyncedRoomRef.current = currentRoom;
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

  function handleSaveResearchProfile(profile: Partial<UserPreferenceProfile>) {
    return runWithLoading(async () => {
      const nextProfile = await updateResearchProfile(profile);
      setResearchProfile(nextProfile);
      setMessage("用户偏好已更新，后续智能体规划将使用新的个性化目标。");
    });
  }

  function handleResearchFeedback(satisfaction: number) {
    return runWithLoading(async () => {
      const nextProfile = await submitResearchFeedback({
        satisfaction,
        desired_temperature_c: researchProfile?.preferred_temperature_c,
        desired_illuminance_lux: researchProfile?.preferred_illuminance_lux,
      });
      setResearchProfile(nextProfile);
      setPrivateMemory(await fetchPrivateUserMemory());
      setMessage(`已记录 ${satisfaction} 星反馈，并更新长期用户偏好模型。`);
    });
  }

  function handleSavePrivateAttributes(attributes: Record<string, string | null>) {
    return runWithLoading(async () => {
      const memory = await updatePrivateUserAttributes(attributes);
      setPrivateMemory(memory);
      setMessage("结构化长期属性已保存到当前住户的私有知识库。");
    }, true);
  }

  function handleAutonomyChange(enabled: boolean) {
    return runWithLoading(async () => {
      if (enabled) {
        const status = await startAutonomousRuntime({
          interval_seconds: 5,
          simulation_minutes_per_cycle: 5,
          repeated_trigger_cooldown_seconds: 30,
          max_consecutive_failures: 3,
        });
        lastAutonomyCycleRef.current = null;
        setAutonomyStatus(status);
        setMessage("后端常驻自治服务已启动；关闭页面后服务仍会继续运行。");
      } else {
        const status = await stopAutonomousRuntime();
        setAutonomyStatus(status);
        setMessage(
          status.stopping
            ? "已请求停止；系统会在当前决策周期安全结束后释放控制权。"
            : "后端自治服务已停止。",
        );
      }
    }, true);
  }

  function handleResetPrivateMemory() {
    return runWithLoading(async () => {
      if (!window.confirm("确认清除当前住户的画像、属性、反馈、反思和学习经验？")) return;
      const memory = await resetPrivateUserMemory();
      setPrivateMemory(memory);
      setResearchProfile(memory.profile);
      setMessage("当前住户的私有记忆已清除并恢复默认画像。");
    });
  }

  function handleSaveRobustness(config: RobustnessConfig) {
    return runWithLoading(async () => {
      const nextConfig = await updateRobustnessConfig(config);
      setRobustnessConfig(nextConfig);
      setMessage(nextConfig.enabled ? "鲁棒性扰动实验已启用。" : "鲁棒性扰动实验已关闭。");
    });
  }

  function handleTaskSubmit() {
    return runWithLoading(async () => {
      const scopedCommand = withCurrentRoomContext(command, currentRoomName);
      setLiveAgentStages([]);
      const response = await submitTaskWithTrace(scopedCommand, currentRoomId, (stage) => {
        setLiveAgentStages((current) => [...current, stage]);
      });
      applyState(response.state);
      setAgentOutput(response.agent_output);
      setPrivateMemory(await fetchPrivateUserMemory());
      setMessage(`智能体已感知你在${currentRoomName}，并完成任务规划与控制。`);
    });
  }

  async function handleSceneFullscreen() {
    const element = scenePanelRef.current;
    if (!element) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }
    await element.requestFullscreen();
  }

  if (authRequired === null || (authRequired && !isAuthenticated)) {
    return <AccessGate error={authError} isLoading={isLoading} onSubmit={handleAuthentication} />;
  }

  return (
    <main className={`app-shell workspace-mode${isScreenshotMode ? " screenshot-mode" : ""}`}>
      <WorkspaceNavigation active={activePage} onNavigate={navigate} />
      <div className="app-content">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true"><i /></span>
          <span className="brand-copy">
            <strong>{workspacePages[activePage].label}</strong>
            <small>{activePage === "experiments" ? "EnergyPlus 建筑物理仿真" : "生活模拟工作空间"}</small>
          </span>
        </div>
        <div className="topbar-meta" aria-label="simulation status">
          <span><small>天气</small>{{ sunny: "晴天", cloudy: "多云", overcast: "阴天", rainy: "雨天" }[state?.outdoor_environment.weather ?? "cloudy"]}</span>
          <span><small>室外</small>{state ? `${state.outdoor_environment.outdoor_temperature_c.toFixed(0)}°C` : "--"}</span>
          <span><small>住宅时间</small>{state ? formatClockTime(state) : "--"}</span>
          <span><small>感知</small>{focusedRoom?.occupancy ? "有人" : "空闲"}</span>
        </div>
        <div className="topbar-actions">
          <span className="status-pill"><i />{state ? "本地服务已连接" : "正在连接服务"}</span>
          <span className="resident-badge" aria-label="本地住户空间">R1</span>
        </div>
      </header>
      <section className="workspace-panel" id="home-overview">
        <div className="page-intro">
          <div><p className="page-eyebrow">{activePage === "experiments" ? "建筑物理仿真" : "住宅生活模拟"}</p><h1>{activePage === "overview" ? "我的住宅" : workspacePages[activePage].label}</h1><p>{workspacePages[activePage].description}</p></div>
          <span className="source-badge">{activePage === "experiments" ? "EnergyPlus · 9 个热区" : "生活模拟 · 简化环境模型"}</span>
        </div>
        <div className="overview-metrics" hidden={activePage !== "overview"} aria-label="住宅关键状态">
          <span><small>当前所在</small><strong>{sceneCurrentRoomName}</strong></span>
          <span><small>房间温度</small><strong>{focusedRoom ? `${focusedRoom.indoor_temperature_c.toFixed(1)}°C` : "—"}</strong></span>
          <span><small>房间照度</small><strong>{focusedRoom ? `${focusedRoom.indoor_illuminance_lux.toFixed(0)} lx` : "—"}</strong></span>
          <span><small>全屋模拟功率</small><strong>{displayedState ? `${displayedState.energy_metrics.current_power_w.toFixed(0)} W` : "—"}</strong></span>
        </div>
      <div className="dashboard" hidden={activePage !== "overview"}>
        <section className="scene-panel" ref={scenePanelRef} data-avatar-x={avatarPosition.x} data-avatar-z={avatarPosition.z}>
          <div className="scene-kicker"><span>全屋空间</span><strong>{sceneCurrentRoomName}</strong></div>
          {sceneView === "2d" ? (
            <HomePlan2D
              disabled={!presenceHydrated}
              state={displayedState}
              currentRoomId={sceneCurrentRoomId}
              onRoomSelect={(roomId) => {
                if (!presenceHydrated) return;
                if (isLifeSimulationActive) {
                  setMessage("生活仿真运行中，人员位置由生活轨迹统一控制。");
                  return;
                }
                setAvatarPosition(ROOM_AVATAR_POSITIONS[roomId]);
                setMessage(`已定位到${ROOM_LABELS[roomId]}。`);
              }}
            />
          ) : (
            <Suspense fallback={<div className="scene-loading" role="status">正在加载 3D 户型场景…</div>}>
              <HouseScene
                state={displayedState}
                avatarPosition={avatarPosition}
                currentRoomId={sceneCurrentRoomId}
                avatarVisible={showAvatar}
                sceneLayer={sceneLayer}
                resetKey={sceneResetKey}
              />
            </Suspense>
          )}
          <button className="scene-fullscreen" type="button" aria-label="全屏显示户型" onClick={handleSceneFullscreen}>全屏</button>
          <div className="scene-rail" aria-label="户型图层">
            <button
              type="button"
              className={sceneLayer === "sensors" ? "active" : ""}
              onClick={() => setSceneLayer("sensors")}
            >
              测温点
            </button>
            <button
              type="button"
              className={sceneLayer === "devices" ? "active" : ""}
              onClick={() => setSceneLayer("devices")}
            >
              设备层
            </button>
            <button
              type="button"
              className={sceneLayer === "structure" ? "active" : ""}
              onClick={() => setSceneLayer("structure")}
            >
              结构层
            </button>
          </div>
          <div className="scene-toolbar" aria-label="户型视角控制">
            <ViewModeToggle
              value={sceneView}
              onChange={setSceneView}
              onReset={() => setSceneResetKey((key) => key + 1)}
            />
          </div>
          <div className="movement-hint">
            {isLifeSimulationActive ? `生活仿真：${sceneCurrentRoomName}` : `W/A/S/D 移动“我”：当前在 ${currentRoomName}`}
          </div>
        </section>
        <aside className="overview-context">
          <span className="section-kicker">当前房间</span><h2>{sceneCurrentRoomName}</h2><p>在户型中选择房间，切换你的所在位置。</p>
          <div className="room-status-line"><span>人员状态</span><strong>{focusedRoom?.occupancy ? "有人" : "无人"}</strong></div>
          <div className="room-status-line"><span>自动运行</span><strong>{isAutonomyActive ? "运行中" : "未开启"}</strong></div>
          <button type="button" onClick={() => navigate("devices")}>调节房间设备 <span aria-hidden="true">→</span></button>
          <button type="button" className="secondary-button" onClick={() => navigate("assistant")}>让家庭助手帮忙 <span aria-hidden="true">→</span></button>
          <div className="overview-experiment"><span>想比较控制策略？</span><p>全屋物理实验有独立的输入、运行记录和结果。</p><button type="button" onClick={() => navigate("experiments")}>前往物理实验 →</button></div>
        </aside>
      </div>
      <div hidden={activePage !== "automation"} className="automation-page">
        <aside className="side-panel" id="autonomy">
          <ResearchControlPanel
            profile={researchProfile}
            robustness={robustnessConfig}
            privateMemory={privateMemory}
            autonomyStatus={autonomyStatus}
            isLoading={isLoading || isLifeSimulationActive}
            onSaveProfile={handleSaveResearchProfile}
            onSaveRobustness={handleSaveRobustness}
            onFeedback={handleResearchFeedback}
            onSavePrivateAttributes={handleSavePrivateAttributes}
            onResetPrivateMemory={handleResetPrivateMemory}
            onAutonomyChange={handleAutonomyChange}
          />
          <LifeSimulationPanel
            status={lifeSimulation}
            isLoading={isLoading}
            canStart={canStartLifeSimulation}
            unavailableReason={lifeSimulationUnavailableReason}
            onStart={handleStartLifeSimulation}
            onStop={handleStopLifeSimulation}
            onBackToToday={handleBackToToday}
          />
        </aside>
      </div>
      <div id="home-agent" hidden={activePage !== "assistant"}>
        <AgentOutputPanel
          command={command}
          onCommandChange={setCommand}
          onSubmit={handleTaskSubmit}
          output={agentOutput}
          liveStages={liveAgentStages}
          isLoading={isLoading || isLifeSimulationActive}
        />
      </div>
      <div className="devices-page" hidden={activePage !== "devices"}>
        <ControlPanel
          state={displayedState}
          isLoading={isLoading || isLifeSimulationActive}
          onStep={handleStep}
          onReset={handleReset}
          onEnvironmentChange={handleEnvironmentChange}
          onDeviceAction={handleDeviceAction}
        />
      </div>
      <div className="operations-grid" id="telemetry" hidden={activePage !== "data"}>
        <StatePanel state={displayedState} lastMessage="" />
        <ChartPanel history={history} />
      </div>
      <div hidden={activePage !== "experiments"}>
      <details open={activePage === "experiments"} id="energyplus" className="eplus-shell" onToggle={(event) => { if (event.currentTarget.open) setEnergyPlusOpen(true); }}>
        <summary>EnergyPlus 全屋物理仿真实验 <span>本地 · 可复现</span></summary>
        {energyPlusOpen && <Suspense fallback={<p>正在加载实验工作台…</p>}><EnergyPlusPanel /></Suspense>}
      </details>
      </div>
      {message && <p className="workspace-message" role="status">{message}</p>}
      </section>
      </div>
    </main>
  );
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return target.isContentEditable || ["input", "textarea", "select"].includes(tagName);
}

function withCurrentRoomContext(command: string, roomName: string) {
  const hasRoom = ["客厅", "卧室", "书房", "餐厅", "厨房", "卫生间", "洗衣区", "阳台", "走廊"].some((name) =>
    command.includes(name),
  );
  if (hasRoom) return command;
  return `我现在在${roomName}。${command}`;
}

function durationLabel(duration: LifeSimulationDuration): string {
  if (duration === "day") return "一天";
  if (duration === "week") return "一周";
  return "一个月";
}
