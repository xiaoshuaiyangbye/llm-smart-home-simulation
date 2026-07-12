import type { DeviceState, EnergyState, RoomId, SmartHomeState } from "../types/state";

interface StatePanelProps {
  state: SmartHomeState | null;
  lastMessage: string;
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

export function StatePanel({ state, lastMessage }: StatePanelProps) {
  if (!state) {
    return (
      <section className="panel state-panel">
        <h2>状态面板</h2>
        <p>暂无状态数据</p>
        {lastMessage && <div className="last-message" role="alert">{lastMessage}</div>}
      </section>
    );
  }

  return (
    <section className="panel state-panel">
      <h2>状态面板</h2>
      <div className="summary-grid">
        <Metric label="天气" value={state.outdoor_environment.weather} />
        <Metric label="时间" value={`${state.outdoor_environment.time_hour}:00`} />
        <Metric label="室外照度" value={`${state.outdoor_environment.outdoor_illuminance_lux.toFixed(0)} lx`} />
        <Metric label="太阳辐射" value={`${state.outdoor_environment.solar_radiation_w_m2.toFixed(0)} W/m2`} />
        <Metric label="室外温度" value={`${state.outdoor_environment.outdoor_temperature_c.toFixed(1)} C`} />
        <Metric label="室外湿度" value={`${state.outdoor_environment.outdoor_humidity_percent.toFixed(0)}%`} />
        <Metric label="数据源" value={formatOutdoorDataSource(state.outdoor_environment.outdoor_data_source)} />
        <Metric label="照度来源" value={formatIlluminanceDataSource(state.outdoor_environment.illuminance_data_source)} />
        <Metric label="更新时间" value={formatDataUpdatedAt(state.outdoor_environment.data_updated_at)} />
      </div>
      <ComfortPanel state={state} />
      <EnergyPanel energy={state.energy_metrics} />
      {lastMessage && <div className="last-message">{lastMessage}</div>}
      <div className="room-state-list">
        {state.rooms.map((room) => (
          <div className="state-card" key={room.room_id}>
            <strong>{ROOM_LABELS[room.room_id]} · {room.activity}</strong>
            <span>照度 {room.indoor_illuminance_lux.toFixed(1)} lx</span>
            <span>温度 {room.indoor_temperature_c.toFixed(1)} C</span>
            <span>湿度 {room.indoor_humidity_percent.toFixed(0)}%</span>
            <span>{room.occupancy ? "有人" : "无人"}</span>
          </div>
        ))}
      </div>
      <div className="device-list">
        {state.devices.filter((device) => device.device_type !== "sensor").map((device) => (
          <DeviceLine key={device.entity_id} device={device} />
        ))}
      </div>
    </section>
  );
}

function EnergyPanel({ energy }: { energy: EnergyState }) {
  const savingText = `${energy.energy_saving_rate_percent.toFixed(1)}%`;
  return (
    <div className="energy-panel">
      <div className="energy-header">
        <h3>实时家庭能耗</h3>
        <span>相对固定策略节能率 {savingText}</span>
      </div>
      <div className="summary-grid">
        <Metric label="当前总功率" value={`${energy.current_power_w.toFixed(1)} W`} />
        <Metric label="运行功率" value={`${energy.operating_power_w.toFixed(1)} W`} />
        <Metric label="待机功率" value={`${energy.standby_power_w.toFixed(1)} W`} />
        <Metric label="累计耗电" value={`${energy.cumulative_energy_kwh.toFixed(3)} kWh`} />
        <Metric label="基线功率" value={`${energy.baseline_power_w.toFixed(1)} W`} />
        <Metric label="估算电费" value={`¥${energy.estimated_cost_cny.toFixed(3)}`} />
        <Metric label="小时耗电" value={`${energy.projected_hourly_energy_kwh.toFixed(3)} kWh`} />
        <Metric label="舒适能效" value={`${energy.comfort_adjusted_efficiency_score.toFixed(1)}`} />
      </div>
      <div className="energy-breakdown">
        {Object.entries(energy.by_device_type_w).map(([type, power]) => (
          <EnergyBar
            key={type}
            label={deviceTypeLabel(type)}
            value={power}
            max={Math.max(energy.current_power_w, 1)}
            detail={powerBreakdownText(energy, type)}
          />
        ))}
      </div>
      <p className="standard-note">
        功率组成：总功率 = 运行功率 + 待机功率。关闭状态下智能灯按 0.2 W、空调按 1.5 W、风扇按 0.3 W 计入待机功耗；窗帘和窗户仅在动作瞬间耗电，当前静态状态按 0 W 计。
      </p>
      <p className="standard-note">对照说明：{energy.baseline_definition}</p>
    </div>
  );
}

function ComfortPanel({ state }: { state: SmartHomeState }) {
  const comfort = state.comfort_metrics;
  const occupiedRoom = state.rooms.find((room) => room.occupancy && room.activity !== "away");
  const occupiedComfort = occupiedRoom
    ? comfort.rooms.find((room) => room.room_id === occupiedRoom.room_id)
    : undefined;
  return (
    <div className="energy-panel">
      <div className="energy-header">
        <h3>实时舒适度评价</h3>
        <span>{comfort.comfortable_room_count} 个房间舒适</span>
      </div>
      <div className="summary-grid">
        <Metric label="综合舒适度" value={`${comfort.average_overall_score.toFixed(1)}`} />
        <Metric label="热舒适度" value={`${comfort.average_thermal_score.toFixed(1)}`} />
        <Metric label="光舒适度" value={`${comfort.average_lighting_score.toFixed(1)}`} />
        <Metric label="湿度舒适度" value={`${comfort.average_humidity_score.toFixed(1)}`} />
        <Metric label="评价工况" value={seasonLabel(comfort.evaluation_season)} />
        <Metric
          label="居住舒适度"
          value={occupiedComfort ? `${occupiedComfort.overall_comfort_score.toFixed(1)}` : "离家不计入"}
        />
      </div>
      <p className="standard-note">{comfort.standard_basis.join("；")}</p>
      <p className="standard-note">全屋平均舒适度会随空房间自然升温/降温变化；生活仿真报告优先看“居住舒适度”和满意度。</p>
    </div>
  );
}

function EnergyBar({ label, value, max, detail }: { label: string; value: number; max: number; detail: string }) {
  const width = `${Math.min(100, Math.max(2, (value / max) * 100))}%`;
  return (
    <div className="energy-bar-row">
      <span>{label}</span>
      <div className="energy-bar-track">
        <i style={{ width }} />
      </div>
      <strong title={detail}>{value.toFixed(1)} W</strong>
      <small>{detail}</small>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DeviceLine({ device }: { device: DeviceState }) {
  let value = "";
  if (device.device_type === "light") value = `${device.is_on ? "on" : "off"} · ${device.brightness_pct.toFixed(0)}%`;
  if (device.device_type === "curtain") value = `${device.opening_pct.toFixed(0)}%`;
  if (device.device_type === "ac") value = `${device.is_on ? device.mode : "off"} · ${device.setpoint_c.toFixed(0)} C`;
  if (device.device_type === "fan") value = `${device.is_on ? "on" : "off"} · ${device.speed_pct.toFixed(0)}%`;
  if (device.device_type === "window") value = `${device.opening_pct.toFixed(0)}%`;

  return (
    <div className="device-line">
      <span>{device.name}</span>
      <strong>{value}</strong>
    </div>
  );
}

function deviceTypeLabel(type: string): string {
  if (type === "light") return "照明";
  if (type === "ac") return "空调";
  if (type === "fan") return "风扇";
  if (type === "curtain") return "窗帘";
  if (type === "window") return "窗户";
  return type;
}

function powerBreakdownText(energy: EnergyState, type: string): string {
  const devices = energy.devices.filter((device) => device.device_type === type);
  const operating = devices.reduce((sum, device) => sum + device.operating_power_w, 0);
  const standby = devices.reduce((sum, device) => sum + device.standby_power_w, 0);
  return `运行 ${operating.toFixed(1)} W / 待机 ${standby.toFixed(1)} W`;
}

function formatOutdoorDataSource(source: string): string {
  if (source === "realtime_open_meteo") return "实时天气";
  return "仿真公式";
}

function formatIlluminanceDataSource(source: string): string {
  if (source === "estimated_from_realtime_solar_radiation") return "实时辐射估算";
  return "仿真公式";
}

function formatDataUpdatedAt(value: string | null): string {
  if (!value) return "未同步";
  const date = new Date(value);
  if (!Number.isNaN(date.getTime())) {
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }
  return value.replace("T", " ");
}

function seasonLabel(value: string): string {
  if (value === "summer") return "夏季";
  if (value === "winter") return "冬季";
  return "过渡季";
}
