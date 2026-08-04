import type {
  DeviceActionRequest,
  DeviceActionResponse,
  AgentCommandResponse,
  AgentTraceStage,
  AgentHealth,
  AuthStatus,
  EnergyState,
  LifeSimulationDuration,
  LifeSimulationStatus,
  SmartHomeState,
  TaskResponse,
  WeatherType,
  RobustnessConfig,
  PrivateUserMemory,
  PresenceUpdateResult,
  AutonomousTickResult,
  AutonomousRuntimeConfig,
  AutonomousRuntimeStatus,
  UserPreferenceProfile,
} from "../types/state";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "http://localhost:8000" : "");
const REQUEST_TIMEOUT_MS = 20_000;
const RESIDENT_STORAGE_KEY = "smart-home-resident-workspace-id";
const LEGACY_SESSION_STORAGE_KEY = "smart-home-simulation-session";

function getSessionId(): string {
  const stored = window.localStorage.getItem(RESIDENT_STORAGE_KEY);
  if (stored) return stored;
  const legacy = window.sessionStorage.getItem(LEGACY_SESSION_STORAGE_KEY);
  const residentId = legacy ?? crypto.randomUUID().replace(/-/g, "");
  window.localStorage.setItem(RESIDENT_STORAGE_KEY, residentId);
  return residentId;
}

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const canRetry = !options?.method || options.method === "GET";
  let response: Response | undefined;
  for (let attempt = 0; attempt < (canRetry ? 2 : 1); attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        ...options,
        signal: controller.signal,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Simulation-Session": getSessionId(),
          ...(options?.headers ?? {}),
        },
      });
      break;
    } catch (error) {
      if (attempt + 1 < (canRetry ? 2 : 1)) {
        await new Promise((resolve) => window.setTimeout(resolve, 250));
        continue;
      }
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new Error("请求超时，请检查后端或模型服务后重试。");
      }
      throw new Error("网络连接失败，请检查后端服务后重试。");
    } finally {
      window.clearTimeout(timeout);
    }
  }
  if (!response) throw new Error("网络连接失败，请检查后端服务后重试。");
  if (!response.ok) {
    let detail = `Request failed: ${path}`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      detail = `Request failed: ${path}`;
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export function fetchSmartHomeState(): Promise<SmartHomeState> {
  return requestJson<SmartHomeState>("/api/state");
}

export function fetchEnergyMetrics(): Promise<EnergyState> {
  return requestJson<EnergyState>("/api/energy");
}

export function updateCurrentRoom(currentRoomId: SmartHomeState["rooms"][number]["room_id"]): Promise<PresenceUpdateResult> {
  return requestJson<PresenceUpdateResult>("/api/presence/current-room", {
    method: "PUT",
    body: JSON.stringify({ current_room_id: currentRoomId }),
  });
}

export function stepSimulation(minutes = 1): Promise<SmartHomeState> {
  return requestJson<SmartHomeState>("/api/simulation/step", {
    method: "POST",
    body: JSON.stringify({ minutes }),
  });
}

export function resetSimulation(): Promise<SmartHomeState> {
  return requestJson<SmartHomeState>("/api/state/reset", { method: "POST" });
}

export function startLifeSimulation(duration: LifeSimulationDuration): Promise<LifeSimulationStatus> {
  return requestJson<LifeSimulationStatus>("/api/life-simulation/start", {
    method: "POST",
    body: JSON.stringify({ duration }),
  });
}

export function tickLifeSimulation(): Promise<LifeSimulationStatus> {
  return requestJson<LifeSimulationStatus>("/api/life-simulation/tick", { method: "POST" });
}

export function stopLifeSimulation(): Promise<LifeSimulationStatus> {
  return requestJson<LifeSimulationStatus>("/api/life-simulation/stop", { method: "POST" });
}

export function backToToday(): Promise<SmartHomeState> {
  return requestJson<SmartHomeState>("/api/life-simulation/today", { method: "POST" });
}

export function fetchLifeSimulationStatus(): Promise<LifeSimulationStatus> {
  return requestJson<LifeSimulationStatus>("/api/life-simulation/status");
}

export function fetchAgentHealth(): Promise<AgentHealth> {
  return requestJson<AgentHealth>("/api/agent/health");
}

export function fetchAuthStatus(): Promise<AuthStatus> {
  return requestJson<AuthStatus>("/api/auth/status");
}

export function createAuthSession(accessToken: string): Promise<void> {
  return requestJson<void>("/api/auth/session", {
    method: "POST",
    body: JSON.stringify({ access_token: accessToken }),
  });
}

export function fetchResearchProfile(): Promise<UserPreferenceProfile> {
  return requestJson<UserPreferenceProfile>("/api/research/profile");
}

export function updateResearchProfile(payload: Partial<UserPreferenceProfile>): Promise<UserPreferenceProfile> {
  return requestJson<UserPreferenceProfile>("/api/research/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function submitResearchFeedback(payload: {
  satisfaction: number;
  desired_temperature_c?: number;
  desired_illuminance_lux?: number;
  note?: string;
}): Promise<UserPreferenceProfile> {
  return requestJson<UserPreferenceProfile>("/api/research/profile/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchPrivateUserMemory(): Promise<PrivateUserMemory> {
  return requestJson<PrivateUserMemory>("/api/research/private-memory");
}

export function updatePrivateUserAttributes(attributes: Record<string, string | null>): Promise<PrivateUserMemory> {
  return requestJson<PrivateUserMemory>("/api/research/private-memory/attributes", {
    method: "PUT",
    body: JSON.stringify({ attributes }),
  });
}

export function runAutonomousTick(minutes = 5): Promise<AutonomousTickResult> {
  return requestJson<AutonomousTickResult>("/api/autonomy/tick", {
    method: "POST",
    body: JSON.stringify({ minutes }),
  });
}

export function startAutonomousRuntime(
  config: AutonomousRuntimeConfig,
): Promise<AutonomousRuntimeStatus> {
  return requestJson<AutonomousRuntimeStatus>("/api/autonomy/start", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export function stopAutonomousRuntime(): Promise<AutonomousRuntimeStatus> {
  return requestJson<AutonomousRuntimeStatus>("/api/autonomy/stop", { method: "POST" });
}

export function fetchAutonomousRuntimeStatus(): Promise<AutonomousRuntimeStatus> {
  return requestJson<AutonomousRuntimeStatus>("/api/autonomy/status");
}

export function resetPrivateUserMemory(): Promise<PrivateUserMemory> {
  return requestJson<PrivateUserMemory>("/api/research/private-memory", {
    method: "DELETE",
    body: JSON.stringify({ confirmation: "RESET_PRIVATE_MEMORY" }),
  });
}

export function fetchRobustnessConfig(): Promise<RobustnessConfig> {
  return requestJson<RobustnessConfig>("/api/research/robustness");
}

export function updateRobustnessConfig(payload: RobustnessConfig): Promise<RobustnessConfig> {
  return requestJson<RobustnessConfig>("/api/research/robustness", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function updateEnvironment(
  payload: Partial<{ weather: WeatherType; time_hour: number }>,
): Promise<SmartHomeState> {
  return requestJson<SmartHomeState>("/api/environment", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function controlDevice(
  request: DeviceActionRequest,
): Promise<DeviceActionResponse> {
  return requestJson<DeviceActionResponse>("/api/device/action", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function submitTask(userCommand: string, currentRoomId?: string): Promise<TaskResponse> {
  const response = await requestJson<AgentCommandResponse>("/api/agent/command", {
    method: "POST",
    body: JSON.stringify({
      user_command: userCommand,
      current_room_id: currentRoomId,
    }),
  });
  if (!response.success || !response.final_state) {
    throw new Error(response.error ?? "Agent command failed.");
  }
  return {
    experiment_id: "local-demo",
    user_command: userCommand,
    success: true,
    agent_output: {
      semantic_result: response.semantic_result,
      planning_result: response.plan_result,
      execution_result: response.execution_result,
      feedback_result: response.feedback_result,
      actions: Array.isArray(response.plan_result.actions) ? response.plan_result.actions : [],
      multi_agent_blackboard: response.multi_agent_blackboard,
    },
    state: response.final_state,
    error: null,
  };
}

export async function submitTaskWithTrace(
  userCommand: string,
  currentRoomId: string | undefined,
  onStage: (stage: AgentTraceStage) => void,
): Promise<TaskResponse> {
  const response = await fetch(`${API_BASE_URL}/api/agent/command/stream`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Simulation-Session": getSessionId(),
    },
    body: JSON.stringify({ user_command: userCommand, current_room_id: currentRoomId }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`Unable to open live agent trace (${response.status}).`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed: AgentCommandResponse | null = null;
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const event = frame.match(/^event: (.+)$/m)?.[1];
      const data = frame.match(/^data: (.+)$/m)?.[1];
      if (!event || !data) continue;
      const payload = JSON.parse(data) as unknown;
      if (event === "stage") onStage(payload as AgentTraceStage);
      if (event === "complete") completed = payload as AgentCommandResponse;
      if (event === "error") {
        const message = typeof payload === "object" && payload ? (payload as { message?: unknown }).message : undefined;
        throw new Error(typeof message === "string" ? message : "Live agent trace failed.");
      }
    }
    if (done) break;
  }
  if (!completed || !completed.success || !completed.final_state) {
    throw new Error(completed?.error ?? "Live agent trace ended without a successful result.");
  }
  return {
    experiment_id: "local-demo",
    user_command: userCommand,
    success: true,
    agent_output: {
      semantic_result: completed.semantic_result,
      planning_result: completed.plan_result,
      execution_result: completed.execution_result,
      feedback_result: completed.feedback_result,
      actions: Array.isArray(completed.plan_result.actions) ? completed.plan_result.actions : [],
      multi_agent_blackboard: completed.multi_agent_blackboard,
    },
    state: completed.final_state,
    error: null,
  };
}

export function getLogExportUrl(): string {
  return `${API_BASE_URL}/api/logs/export`;
}
