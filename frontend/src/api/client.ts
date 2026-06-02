import type {
  DeviceActionRequest,
  DeviceActionResponse,
  AgentCommandResponse,
  EnergyState,
  LifeSimulationDuration,
  LifeSimulationStatus,
  SmartHomeState,
  TaskResponse,
  WeatherType,
} from "../types/state";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options,
  });
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
  return response.json();
}

export function fetchSmartHomeState(): Promise<SmartHomeState> {
  return requestJson<SmartHomeState>("/api/state");
}

export function fetchEnergyMetrics(): Promise<EnergyState> {
  return requestJson<EnergyState>("/api/energy");
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
    },
    state: response.final_state,
    error: null,
  };
}

export function getLogExportUrl(): string {
  return `${API_BASE_URL}/api/logs/export`;
}
