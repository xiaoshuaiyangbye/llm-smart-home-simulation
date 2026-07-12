import type {
  AcDeviceState,
  CurtainDeviceState,
  DeviceActionRequest,
  FanDeviceState,
  LightDeviceState,
  RoomId,
  SmartHomeState,
  WeatherType,
} from "../types/state";
import { DebouncedRange } from "./DebouncedRange";

interface ControlPanelProps {
  state: SmartHomeState | null;
  isLoading: boolean;
  onStep: () => Promise<void>;
  onReset: () => Promise<void>;
  onEnvironmentChange: (payload: Partial<{ weather: WeatherType; time_hour: number }>) => Promise<void>;
  onDeviceAction: (request: DeviceActionRequest) => Promise<void>;
}

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

export function ControlPanel({
  state,
  isLoading,
  onStep,
  onReset,
  onEnvironmentChange,
  onDeviceAction,
}: ControlPanelProps) {
  const weather = state?.outdoor_environment.weather ?? "sunny";
  const timeHour = state?.outdoor_environment.time_hour ?? 14;

  return (
    <section className="panel control-panel">
      <h2>控制面板</h2>
      <div className="control-grid">
        <label>
          天气
          <select
            value={weather}
            disabled={isLoading}
            onChange={(event) => onEnvironmentChange({ weather: event.target.value as WeatherType })}
          >
            <option value="sunny">sunny</option>
            <option value="cloudy">cloudy</option>
            <option value="overcast">overcast</option>
            <option value="rainy">rainy</option>
          </select>
        </label>
        <label>
          时间
          <input
            type="number"
            min={0}
            max={23}
            value={timeHour}
            disabled={isLoading}
            onChange={(event) => onEnvironmentChange({ time_hour: Number(event.target.value) })}
          />
        </label>
        <button type="button" disabled={isLoading} onClick={onStep}>单步仿真</button>
        <button type="button" disabled={isLoading} className="secondary-button" onClick={onReset}>重置系统</button>
      </div>
      <div className="device-controls">
        {state?.rooms.map((room) => (
          <RoomControl
            key={room.room_id}
            roomId={room.room_id}
            state={state}
            disabled={isLoading}
            onDeviceAction={onDeviceAction}
          />
        ))}
      </div>
    </section>
  );
}

function RoomControl({
  roomId,
  state,
  disabled,
  onDeviceAction,
}: {
  roomId: RoomId;
  state: SmartHomeState;
  disabled: boolean;
  onDeviceAction: (request: DeviceActionRequest) => Promise<void>;
}) {
  const light = state.devices.find((device) => device.room === roomId && device.device_type === "light") as LightDeviceState | undefined;
  const curtain = state.devices.find((device) => device.room === roomId && device.device_type === "curtain") as CurtainDeviceState | undefined;
  const ac = state.devices.find((device) => device.room === roomId && device.device_type === "ac") as AcDeviceState | undefined;
  const fan = state.devices.find((device) => device.room === roomId && device.device_type === "fan") as FanDeviceState | undefined;

  return (
    <div className="room-control">
      <strong>{ROOM_LABELS[roomId]}</strong>
      {light && (
        <div className="control-row">
          <span>灯光</span>
          <button disabled={disabled} onClick={() => onDeviceAction({ entity_id: light.entity_id, action: light.is_on ? "turn_off" : "turn_on", parameters: { brightness_pct: light.brightness_pct || 80 } })}>
            {light.is_on ? "关闭" : "开启"}
          </button>
          <DebouncedRange
            ariaLabel={`${ROOM_LABELS[roomId]} 灯光亮度`}
            min={0}
            max={100}
            value={light.brightness_pct}
            disabled={disabled}
            onCommit={(brightness_pct) => onDeviceAction({ entity_id: light.entity_id, action: "set_brightness", parameters: { brightness_pct } })}
          />
        </div>
      )}
      {curtain && (
        <div className="control-row">
          <span>窗帘</span>
          <button disabled={disabled} onClick={() => onDeviceAction({ entity_id: curtain.entity_id, action: "open", parameters: {} })}>打开</button>
          <button disabled={disabled} onClick={() => onDeviceAction({ entity_id: curtain.entity_id, action: "close", parameters: {} })}>关闭</button>
          <DebouncedRange
            ariaLabel={`${ROOM_LABELS[roomId]} 窗帘开合`}
            min={0}
            max={100}
            value={curtain.opening_pct}
            disabled={disabled}
            onCommit={(opening_pct) => onDeviceAction({ entity_id: curtain.entity_id, action: "set_opening", parameters: { opening_pct } })}
          />
        </div>
      )}
      {ac && (
        <div className="control-row">
          <span>空调</span>
          <button disabled={disabled} onClick={() => onDeviceAction({ entity_id: ac.entity_id, action: ac.is_on ? "turn_off" : "turn_on", parameters: { mode: "cool" } })}>
            {ac.is_on ? "关闭" : "开启"}
          </button>
          <input
            type="number"
            min={16}
            max={30}
            value={ac.setpoint_c}
            disabled={disabled}
            onChange={(event) => onDeviceAction({ entity_id: ac.entity_id, action: "set_temperature", parameters: { setpoint_c: Number(event.target.value) } })}
          />
        </div>
      )}
      {fan && (
        <div className="control-row">
          <span>风扇</span>
          <button disabled={disabled} onClick={() => onDeviceAction({ entity_id: fan.entity_id, action: fan.is_on ? "turn_off" : "turn_on", parameters: { speed_pct: fan.speed_pct || 60 } })}>
            {fan.is_on ? "关闭" : "开启"}
          </button>
          <DebouncedRange
            ariaLabel={`${ROOM_LABELS[roomId]} 风扇风速`}
            min={0}
            max={100}
            value={fan.speed_pct}
            disabled={disabled}
            onCommit={(speed_pct) => onDeviceAction({ entity_id: fan.entity_id, action: "set_speed", parameters: { speed_pct } })}
          />
        </div>
      )}
    </div>
  );
}
