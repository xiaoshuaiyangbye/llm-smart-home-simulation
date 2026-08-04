export type RoomId =
  | "living_room"
  | "bedroom"
  | "study_room"
  | "dining_room"
  | "kitchen"
  | "bathroom"
  | "laundry"
  | "balcony"
  | "corridor";
export type ActivityType = "idle" | "study" | "movie" | "sleep" | "away";
export type WeatherType = "sunny" | "cloudy" | "overcast" | "rainy";
export type OutdoorDataSource = "simulation_formula" | "realtime_open_meteo" | "historical_week_log";
export type IlluminanceDataSource =
  | "simulation_formula"
  | "estimated_from_realtime_solar_radiation"
  | "historical_week_log";
export type DeviceType = "light" | "curtain" | "ac" | "fan" | "window" | "sensor";
export type AcMode = "cool" | "heat" | "fan" | "dry" | "off";
export type SensorType = "illuminance" | "temperature" | "humidity" | "occupancy";

export interface RoomState {
  room_id: RoomId;
  name: string;
  indoor_illuminance_lux: number;
  indoor_temperature_c: number;
  indoor_humidity_percent: number;
  occupancy: boolean;
  activity: ActivityType;
}

export interface OutdoorEnvironmentState {
  weather: WeatherType;
  time_hour: number;
  time_minute: number;
  outdoor_illuminance_lux: number;
  solar_radiation_w_m2: number;
  outdoor_temperature_c: number;
  outdoor_humidity_percent: number;
  outdoor_data_source: OutdoorDataSource;
  illuminance_data_source: IlluminanceDataSource;
  data_updated_at: string | null;
}

interface BaseDeviceState {
  entity_id: string;
  room: RoomId;
  name: string;
  device_type: DeviceType;
}

export interface LightDeviceState extends BaseDeviceState {
  device_type: "light";
  is_on: boolean;
  brightness_pct: number;
  color_temperature_k: number;
  max_lux_contribution: number;
}

export interface CurtainDeviceState extends BaseDeviceState {
  device_type: "curtain";
  opening_pct: number;
}

export interface AcDeviceState extends BaseDeviceState {
  device_type: "ac";
  is_on: boolean;
  mode: AcMode;
  setpoint_c: number;
}

export interface FanDeviceState extends BaseDeviceState {
  device_type: "fan";
  is_on: boolean;
  speed_pct: number;
}

export interface WindowDeviceState extends BaseDeviceState {
  device_type: "window";
  opening_pct: number;
}

export interface SensorDeviceState extends BaseDeviceState {
  device_type: "sensor";
  sensor_type: SensorType;
  value: number | boolean;
}

export type DeviceState =
  | LightDeviceState
  | CurtainDeviceState
  | AcDeviceState
  | FanDeviceState
  | WindowDeviceState
  | SensorDeviceState;

export interface SmartHomeState {
  current_time_step: number;
  rooms: RoomState[];
  outdoor_environment: OutdoorEnvironmentState;
  devices: DeviceState[];
  energy_metrics: EnergyState;
  comfort_metrics: ComfortState;
}

export interface DeviceEnergySnapshot {
  entity_id: string;
  room: RoomId;
  device_type: DeviceType;
  current_power_w: number;
  operating_power_w: number;
  standby_power_w: number;
  power_state: string;
}

export interface RoomEnergySnapshot {
  room_id: RoomId;
  current_power_w: number;
}

export interface EnergyState {
  current_power_w: number;
  operating_power_w: number;
  standby_power_w: number;
  cumulative_energy_kwh: number;
  baseline_power_w: number;
  energy_saving_rate_percent: number;
  baseline_definition: string;
  estimated_cost_cny: number;
  estimated_carbon_kg: number;
  projected_hourly_energy_kwh: number;
  baseline_projected_hourly_energy_kwh: number;
  comfort_adjusted_efficiency_score: number;
  by_device_type_w: Record<string, number>;
  by_room_w: RoomEnergySnapshot[];
  devices: DeviceEnergySnapshot[];
}

export interface RoomComfortSnapshot {
  room_id: RoomId;
  apparent_temperature_c: number;
  thermal_comfort_score: number;
  lighting_comfort_score: number;
  humidity_comfort_score: number;
  overall_comfort_score: number;
  comfort_level: "comfortable" | "acceptable" | "uncomfortable";
  thermal_standard_range_c: number[];
  lighting_standard_range_lux: number[];
  humidity_standard_range_percent: number[];
}

export interface ComfortState {
  average_overall_score: number;
  average_thermal_score: number;
  average_lighting_score: number;
  average_humidity_score: number;
  comfortable_room_count: number;
  evaluation_season: "summer" | "winter" | "transition";
  standard_basis: string[];
  rooms: RoomComfortSnapshot[];
}

export interface AgentAction {
  entity_id: string;
  action: string;
  parameters: Record<string, unknown>;
  reason: string;
}

export interface AgentOutput {
  semantic_result: Record<string, unknown>;
  planning_result: Record<string, unknown>;
  execution_result: Record<string, unknown>;
  feedback_result: Record<string, unknown>;
  actions: AgentAction[];
  multi_agent_blackboard?: Record<string, unknown>;
}

export interface AgentTraceStage {
  agent: string;
  recorded_at: string;
  output: Record<string, unknown>;
}

export interface TaskResponse {
  experiment_id: string;
  user_command: string;
  success: boolean;
  agent_output: AgentOutput;
  state: SmartHomeState;
  error: string | null;
}

export interface AgentCommandResponse {
  success: boolean;
  semantic_result: Record<string, unknown>;
  plan_result: Record<string, unknown>;
  execution_result: Record<string, unknown>;
  feedback_result: Record<string, unknown>;
  multi_agent_blackboard: Record<string, unknown>;
  final_state: SmartHomeState | null;
  error: string | null;
}

export interface DeviceActionRequest {
  entity_id: string;
  action: string;
  parameters: Record<string, number | string | boolean>;
}

export interface DeviceActionResponse {
  success: boolean;
  message: string;
  before_state: SmartHomeState;
  after_state: SmartHomeState;
  action: DeviceActionRequest;
  timestamp: string;
}

export interface HistoryPoint {
  step: number;
  livingRoomIlluminance: number;
  livingRoomTemperature: number;
  currentPowerW: number;
}

export type LifeSimulationDuration = "day" | "week" | "month";

export interface LifeSimulationStatus {
  active: boolean;
  duration: LifeSimulationDuration | null;
  total_days: number;
  simulated_minute: number;
  total_minutes: number;
  day: number;
  time: string;
  progress_percent: number;
  speed_label: string;
  current_activity: string;
  current_room_id: RoomId | null;
  current_room_name: string;
  weather_source: string;
  event_count: number;
  completed_event_count: number;
  error_count: number;
  last_event: Record<string, unknown> | null;
  last_agent_output: AgentOutput | null;
  summary: Record<string, unknown>;
  output_paths: Record<string, string>;
  state: SmartHomeState;
}

export interface AgentHealth {
  success: boolean;
  llm_mode: "mock" | "real" | string;
  error?: string | null;
}

export interface AuthStatus {
  requires_auth: boolean;
}

export interface ObjectiveWeights {
  comfort: number;
  energy: number;
  safety: number;
  stability: number;
}

export interface UserPreferenceProfile {
  profile_id: string;
  display_name: string;
  preferred_temperature_c: number;
  temperature_tolerance_c: number;
  preferred_illuminance_lux: number;
  preferred_humidity_percent: number;
  energy_saving_preference: number;
  objective_weights: ObjectiveWeights;
  feedback_count: number;
  satisfaction_ema: number;
  updated_at: string;
}

export interface PrivateMemoryReflection {
  reflection_id: string;
  recorded_at: string;
  trigger: string;
  intent: string;
  room: string;
  completed: boolean;
  conclusion: string;
  pattern_confidence: number;
}

export interface PrivateUserMemory {
  schema_version: string;
  scope: string;
  persistence_enabled: boolean;
  profile: UserPreferenceProfile;
  private_attributes: Record<string, string>;
  feedback_history: Array<Record<string, unknown>>;
  reflections: PrivateMemoryReflection[];
  learned_patterns: Record<string, Record<string, unknown>>;
  reflection_policy: Record<string, string>;
}

export interface AutonomousTickResult {
  mode: "backend_autonomous_runtime_v1";
  cycle_at: string;
  decision: {
    triggered: boolean;
    trigger_type: string;
    room_id: RoomId | null;
    reason: string;
    command: string | null;
    observed_value: unknown;
    target: unknown;
    suppressed?: boolean;
    suppression_reason?: string;
    cooldown_remaining_seconds?: number;
  } | null;
  agent_response: AgentCommandResponse | null;
  state: SmartHomeState;
  reflection_count: number;
  success: boolean;
  error: string | null;
}

export interface AutonomousRuntimeConfig {
  interval_seconds: number;
  simulation_minutes_per_cycle: number;
  repeated_trigger_cooldown_seconds: number;
  max_consecutive_failures: number;
}

export interface AutonomousRuntimeStatus {
  architecture: "backend_owned_autonomous_loop";
  active: boolean;
  stopping: boolean;
  config: AutonomousRuntimeConfig;
  started_at: string | null;
  stopped_at: string | null;
  stop_reason: string;
  cycle_count: number;
  decision_count: number;
  suppressed_count: number;
  failure_count: number;
  consecutive_failures: number;
  last_cycle_at: string | null;
  last_result: AutonomousTickResult | null;
  last_reflex: {
    policy: string;
    trigger_type: string;
    room_id: RoomId;
    action: DeviceActionRequest;
    success: boolean;
    message: string;
  } | null;
  settings_persisted: boolean;
  auto_resume_after_restart: boolean;
  worker_alive: boolean;
}

export interface PresenceUpdateResult {
  state: SmartHomeState;
  reflex_action: AutonomousRuntimeStatus["last_reflex"];
  autonomy_woken: boolean;
}

export interface RobustnessConfig {
  enabled: boolean;
  seed: number;
  temperature_sensor_noise_c: number;
  illuminance_sensor_noise_lux: number;
  actuator_failure_probability: number;
}
