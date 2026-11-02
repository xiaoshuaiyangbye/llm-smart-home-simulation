import { useEffect, useState } from "react";
import { downloadEnergyPlusArtifact, requestJson } from "../api/client";
import "./EnergyPlusPanel.css";

type Controller = "rule" | "manual" | "harness_real";
type Space = { room_id: string; name: string; area_m2: number; polygon: number[][] };
type Status = { available: boolean; version: string; weather: string; deepseek: { ready: boolean; status: string }; calibration_status: string; rooms?: Space[]; height_m?: number };
type RoomSummary = Record<string, number | string | null>;
type Run = { run_id: string; status: string; phase?: string; error?: string; samples?: number; summary?: Record<string, unknown> & { room_summaries?: Record<string, RoomSummary> } };
type Observation = { minute: number; temperature_c: number; relative_humidity_pct: number; co2_ppm: number; total_illuminance_lux: number; electricity_step_j: number; rooms?: Record<string, Observation> };
type Calibration = { calibration_id: string; fit: { illuminance: { holdout_mae: number }; power: { holdout_mae: number } } };

const names: Record<Controller, string> = {
  rule: "规则基线", manual: "手动设定", harness_real: "助手 · 本地 DeepSeek",
};
const number = (value: unknown, digits = 2) => typeof value === "number" ? value.toFixed(digits) : "—";

function Sparkline({ rows, keyName, title, unit, color, scale = 1 }: { rows: Observation[]; keyName: keyof Observation; title: string; unit: string; color: string; scale?: number }) {
  const sampled = rows.filter((_, index) => index % Math.max(1, Math.floor(rows.length / 150)) === 0);
  const values = sampled.map((row) => Number(row[keyName]) * scale).filter(Number.isFinite);
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values), span = Math.max(0.01, max - min);
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 100},${35 - ((value - min) / span) * 30}`).join(" ");
  return <div className="eplus-chart"><div><strong>{title}</strong><span>{number(values[values.length - 1])} {unit}</span></div><svg role="img" aria-label={`${title}时间序列`} viewBox="0 0 100 40" preserveAspectRatio="none"><polyline fill="none" stroke={color} strokeWidth="1.4" vectorEffect="non-scaling-stroke" points={points} /></svg><small>范围 {number(min)}–{number(max)} {unit} · {rows.length} 个 5 分钟采样</small></div>;
}

export default function EnergyPlusPanel() {
  const [view, setView] = useState<"setup" | "results" | "spaces">("setup");
  const [status, setStatus] = useState<Status | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<Run | null>(null);
  const [rows, setRows] = useState<Observation[]>([]);
  const [viewRoom, setViewRoom] = useState("living_room");
  const [currentRoom, setCurrentRoom] = useState("living_room");
  const [controller, setController] = useState<Controller>("rule");
  const [season, setSeason] = useState("summer");
  const [days, setDays] = useState(1);
  const [command, setCommand] = useState("客厅看书，保持舒适，注意通风并节约能源");
  const [temperature, setTemperature] = useState(25);
  const [lux, setLux] = useState(500);
  const [co2, setCo2] = useState(1000);
  const [light, setLight] = useState(0.5);
  const [ventilation, setVentilation] = useState(0.3);
  const [windowOpening, setWindowOpening] = useState(0);
  const [hvacEnabled, setHvacEnabled] = useState(true);
  const [heatingSetpoint, setHeatingSetpoint] = useState(20);
  const [controlInterval, setControlInterval] = useState(30);
  const [calibrationId, setCalibrationId] = useState("");
  const [measurements, setMeasurements] = useState("");
  const [source, setSource] = useState("");
  const [sensor, setSensor] = useState("");
  const [ambientSubtracted, setAmbientSubtracted] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const [nextStatus, history] = await Promise.all([
      requestJson<Status>("/api/energyplus/status"),
      requestJson<{ runs: Run[] }>("/api/energyplus/runs"),
    ]);
    setStatus(nextStatus);
    setRuns(history.runs);
  }
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const [nextStatus, history] = await Promise.all([
          requestJson<Status>("/api/energyplus/status"),
          requestJson<{ runs: Run[] }>("/api/energyplus/runs"),
        ]);
        if (!alive) return;
        setStatus(nextStatus); setRuns(history.runs);
        const currentId = selected?.run_id ?? history.runs[0]?.run_id;
        if (currentId) {
          const current = await requestJson<Run>(`/api/energyplus/runs/${currentId}`);
          if (!alive) return;
          setSelected(current);
          if (current.status === "completed" && rows.length === 0) {
            const data = await requestJson<{ observations: Observation[] }>(`/api/energyplus/runs/${currentId}/observations`);
            if (alive) setRows(data.observations);
          }
        }
      } catch (error) { if (alive) setNotice(String(error)); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2500);
    return () => { alive = false; window.clearInterval(timer); };
  }, [selected?.run_id, rows.length]);

  async function createRun() {
    setBusy(true); setNotice("");
    try {
      const created = await requestJson<Run>("/api/energyplus/runs", { method: "POST", body: JSON.stringify({
        spatial_scope: "whole_home", current_room_id: currentRoom,
        controller, season, days, control_interval_minutes: controlInterval, user_command: command, temperature_target_c: temperature,
        illuminance_target_lux: lux, co2_limit_ppm: co2, calibration_id: calibrationId || null,
        manual_controls: { light_fraction: light, cooling_setpoint_c: temperature, heating_setpoint_c: heatingSetpoint, hvac_enabled: hvacEnabled, ventilation_fraction: ventilation, window_fraction: windowOpening },
      }) });
      setRows([]); setSelected(created); setView("results"); await refresh();
    } catch (error) { setNotice(String(error)); }
    finally { setBusy(false); }
  }
  async function calibrate() {
    setBusy(true); setNotice("");
    try {
      const points = JSON.parse(measurements);
      if (!Array.isArray(points)) throw new Error("测量数据必须是 JSON 数组");
      const result = await requestJson<Calibration>("/api/energyplus/calibrations", { method: "POST", body: JSON.stringify({ source_description: source, sensor_location: sensor, ambient_subtracted: ambientSubtracted, points }) });
      setCalibrationId(result.calibration_id);
      setNotice(`校准已保存：${result.calibration_id}。留出集照度 MAE ${number(result.fit.illuminance.holdout_mae)} lx，功率 MAE ${number(result.fit.power.holdout_mae)} W。`);
    } catch (error) { setNotice(String(error)); }
    finally { setBusy(false); }
  }
  const summary = selected?.summary;
  const chartRows = rows.map((row) => row.rooms?.[viewRoom] ?? row);
  const roomSummaries = summary?.room_summaries;
  const statusText = (value: string) => ({ queued: "排队中", running: "运行中", completed: "已完成", failed: "运行失败", cancelled: "已停止" }[value] ?? value);
  return <div className="eplus-panel eplus-redesigned">
    <div className="experiment-toolbar"><div className="experiment-tabs" role="group" aria-label="物理实验页面">
      {([ ["setup", "新建实验"], ["results", "实验结果"], ["spaces", "空间与假设"] ] as const).map(([key, label]) => <button type="button" key={key} aria-pressed={view === key} onClick={() => setView(key)}>{label}</button>)}
    </div><span className={status?.available ? "eplus-pill ok" : "eplus-pill"}>{status?.available ? "引擎可用" : "引擎未就绪"}</span></div>
    <p className="experiment-source">{status?.rooms?.length ?? "—"} 个设计空间 · EnergyPlus {status?.version ?? ""} · 未校准软件仿真</p>

    <div hidden={view !== "setup"} className="experiment-setup">
      <section className="eplus-card experiment-form"><div className="form-section-heading"><span>实验设置</span><h2>这次想怎样控制住宅？</h2><p>选择控制方式和场景，再开始一次独立仿真。</p></div>
        <label>控制方式<select value={controller} onChange={(e) => setController(e.target.value as Controller)}>{(Object.keys(names) as Controller[]).map((key) => <option key={key} value={key} disabled={key === "harness_real" && !status?.deepseek.ready}>{names[key]}</option>)}</select></label>
        {controller === "rule" && <p className="eplus-hint">规则基线会根据房间占用、照度和 CO₂ 自动调节已有设备。</p>}
        {!status?.deepseek.ready && <p className="eplus-hint">本地 DeepSeek 未就绪，暂不可选。</p>}
        <div className="eplus-two"><label>天气场景<select value={season} onChange={(e) => setSeason(e.target.value)}><option value="summer">夏季 · 7 月 21 日</option><option value="winter">冬季 · 1 月 21 日</option></select></label><label>有人活动的房间<select value={currentRoom} onChange={(e) => setCurrentRoom(e.target.value)}>{status?.rooms?.map((r) => <option key={r.room_id} value={r.room_id}>{r.name}</option>)}</select></label></div>
        <p className="eplus-hint">所选房间每天 08:00–18:00 为 2 人，其余空间无人。9 个空间始终参与计算。</p>
        {controller.startsWith("harness") && <label>希望助手完成什么？<textarea value={command} rows={3} onChange={(e) => setCommand(e.target.value)} /></label>}
        <h3 className="form-subheading">环境目标</h3><div className="eplus-three"><label>温度 °C<input type="number" min="20" max="28" value={temperature} onChange={(e) => { const next = Number(e.target.value); setTemperature(next); if (heatingSetpoint >= next) setHeatingSetpoint(next - 1); }} /></label><label>照度 lx<input type="number" min="100" max="1000" value={lux} onChange={(e) => setLux(Number(e.target.value))} /></label><label>CO₂ 上限 ppm<input type="number" min="600" max="2000" value={co2} onChange={(e) => setCo2(Number(e.target.value))} /></label></div>
        {controller === "manual" && <details open className="experiment-options"><summary>手动设备设定</summary><p className="eplus-hint">作用于各房间已有设备；没有空调或外窗的空间不会添加虚构设备。</p><div className="eplus-two"><label>灯光比例 {light}<input type="range" min="0" max="1" step="0.05" value={light} onChange={(e) => setLight(Number(e.target.value))} /></label><label>机械通风比例 {ventilation}<input type="range" min="0" max="1" step="0.05" value={ventilation} onChange={(e) => setVentilation(Number(e.target.value))} /></label><label>开窗比例 {windowOpening}<input type="range" min="0" max="1" step="0.05" value={windowOpening} onChange={(e) => setWindowOpening(Number(e.target.value))} /></label><label>HVAC 运行<input type="checkbox" checked={hvacEnabled} onChange={(e) => setHvacEnabled(e.target.checked)} /></label><label>制热设定 °C<input type="number" min="12" max={Math.min(24, temperature - 1)} value={heatingSetpoint} onChange={(e) => setHeatingSetpoint(Number(e.target.value))} /></label></div></details>}
        <details className="experiment-options"><summary>时长、控制周期与灯具校准</summary><div className="eplus-two"><label>仿真天数<input type="number" min="1" max="7" value={days} onChange={(e) => setDays(Number(e.target.value))} /></label><label>控制周期<select value={controlInterval} onChange={(e) => setControlInterval(Number(e.target.value))}>{[5,10,15,20,30,60,120].map((v) => <option key={v} value={v}>{v} 分钟</option>)}</select></label></div><label>当前房间的灯具校准编号（可选）<input value={calibrationId} onChange={(e) => setCalibrationId(e.target.value)} placeholder="留空使用未校准默认值" /></label></details>
        <button type="button" className="eplus-primary" disabled={busy || !status?.available || (controller === "harness_real" && !status.deepseek.ready)} onClick={() => void createRun()}>{busy ? "正在创建…" : "开始全屋实验"} <span aria-hidden="true">→</span></button>
      </section>
      <aside className="experiment-brief"><span className="section-kicker">本次实验</span><h3>{season === "summer" ? "夏季" : "冬季"}全屋控制</h3><dl><div><dt>空间范围</dt><dd>全部 {status?.rooms?.length ?? 9} 个空间</dd></div><div><dt>仿真时长</dt><dd>{days} 天</dd></div><div><dt>控制方式</dt><dd>{names[controller]}</dd></div><div><dt>控制周期</dt><dd>{controlInterval} 分钟</dd></div></dl><p>结果会单独保存在“实验结果”中，不会改变首页的生活模拟状态。</p><div className="experiment-caveat">模拟电量不等于实测电量。建筑与设备参数尚未校准。</div><button type="button" onClick={() => setView("spaces")}>查看空间与建模假设 →</button></aside>
    </div>

    <div hidden={view !== "results"}>
      {runs.length === 0 && !selected ? <div className="experiment-empty"><span aria-hidden="true">⌁</span><h2>还没有实验结果</h2><p>先创建一次实验，再查看全屋电量和各房间的环境变化。</p><button type="button" onClick={() => setView("setup")}>创建第一个实验</button></div> : <>
      <div className="experiment-results"><aside className="eplus-card experiment-history"><h3>运行记录</h3><div className="eplus-history">{runs.map((run) => <button type="button" key={run.run_id} className={selected?.run_id === run.run_id ? "active" : ""} onClick={() => { setRows([]); setSelected(run); }}><span>实验 {run.run_id.slice(0,8)}</span><strong>{statusText(run.status)}</strong></button>)}</div></aside>
      <section className="eplus-card"><h3>本次运行</h3>{selected && <><p className="run-status">{statusText(selected.status)} · {selected.samples ?? 0} 个时间点</p><details className="run-identifier"><summary>运行编号</summary><code>{selected.run_id}</code></details>{selected.error && <p className="eplus-error">{selected.error}</p>}{["queued","running"].includes(selected.status) && <button type="button" onClick={() => void requestJson(`/api/energyplus/runs/${selected.run_id}/cancel`,{ method:"POST" }).then(refresh).catch((e) => setNotice(String(e)))}>停止实验</button>}</>}
      {summary && <><p className="result-scope">{summary.spatial_scope === "whole_home" ? `全屋结果 · ${summary.room_count} 个空间` : "历史单房间结果 · 不代表全屋"}</p><div className="eplus-metrics"><div><strong>{number(summary.modeled_electricity_kwh,3)}<small> kWh</small></strong><span>全屋模拟电量</span></div><div><strong>{typeof summary.occupied_target_satisfaction_rate === "number" ? `${number(summary.occupied_target_satisfaction_rate * 100,1)}%` : "不适用"}</strong><span>占用期目标满足率</span></div><div><strong>{number(summary.max_co2_ppm,0)}<small> ppm</small></strong><span>CO₂ 峰值</span></div><div><strong>{number(summary.control_latency_ms_mean,1)}<small> ms</small></strong><span>平均控制耗时</span></div></div><p className="eplus-hint">制冷热负荷 {number(summary.cooling_thermal_load_kwh,3)} kWh（热量），制冷模拟用电 {number(summary.modeled_cooling_electricity_kwh,3)} kWh（电量）。</p></>}
      </section></div>
      {roomSummaries && <section className="eplus-card room-results"><h3>各空间结果</h3><div className="result-table-scroll"><table><thead><tr><th>空间</th><th>时间点</th><th>模拟电量 kWh</th><th>占用期目标满足率</th></tr></thead><tbody>{Object.entries(roomSummaries).map(([rid,r]) => <tr key={rid}><td>{r.name}</td><td>{r.sample_count}</td><td>{number(r.modeled_electricity_kwh,3)}</td><td>{typeof r.occupied_target_satisfaction_rate === "number" ? `${number(r.occupied_target_satisfaction_rate * 100,1)}%` : "无人，不适用"}</td></tr>)}</tbody></table></div></section>}
      {rows.length > 0 && <section className="eplus-card room-results"><div className="chart-heading"><h3>房间环境变化</h3>{roomSummaries && <label>查看空间<select value={viewRoom} onChange={(e) => setViewRoom(e.target.value)}>{Object.entries(roomSummaries).map(([rid,r]) => <option key={rid} value={rid}>{r.name}</option>)}</select></label>}</div><div className="eplus-charts"><Sparkline rows={chartRows} keyName="temperature_c" title="室温" unit="°C" color="#315bdb" /><Sparkline rows={chartRows} keyName="relative_humidity_pct" title="相对湿度" unit="%" color="#528f9f" /><Sparkline rows={chartRows} keyName="co2_ppm" title="CO₂" unit="ppm" color="#458361" /><Sparkline rows={chartRows} keyName="total_illuminance_lux" title="桌面照度" unit="lx" color="#a97b2b" /><Sparkline rows={chartRows} keyName="electricity_step_j" title="每 5 分钟电量" unit="kWh" scale={1/3600000} color="#7869a6" /></div></section>}
      {summary && selected && <details className="eplus-card room-results"><summary>下载结果与复现文件</summary><p className="eplus-hint">包含原始回调、SQL 对账、控制记录和模型来源，供复查与复现。</p><div className="eplus-downloads">{["summary.json","observations.csv","observations.jsonl","raw_callback_observations.jsonl","control_trace.jsonl","provenance.json","accounting_audit.json",...(roomSummaries ? ["whole_home.epJSON","spatial_bindings.json"] : []),"engine/eplusout.err","engine/eplusout.sql"].map((file) => <button type="button" key={file} onClick={() => void downloadEnergyPlusArtifact(selected.run_id,file).catch((e) => setNotice(String(e)))}>{file.split("/").pop()} ↓</button>)}</div></details>}
      </>}
    </div>

    <div hidden={view !== "spaces"} className="experiment-spaces">
      {status?.rooms && <section className="eplus-card"><h3>设计户型 · {status.rooms.length} 个独立热区</h3><svg viewBox="-6.7 -4.5 11.6 9.6" role="img" aria-label="全屋九空间热区边界" className="thermal-plan">{status.rooms.map((r) => <g key={r.room_id}><polygon points={r.polygon.map((p) => p.join(",")).join(" ")} fill="#edf2ff" stroke="#6d85b4" strokeWidth="0.025" /><text x={r.polygon.reduce((s,p) => s+p[0],0)/r.polygon.length} y={r.polygon.reduce((s,p) => s+p[1],0)/r.polygon.length} textAnchor="middle" fontSize="0.28" fill="#243956">{r.name}</text></g>)}</svg><div className="space-areas">{status.rooms.map((r) => <span key={r.room_id}>{r.name}<strong>{number(r.area_m2,1)} m²</strong></span>)}</div></section>}
      <section className="eplus-card"><h3>如何理解这些结果</h3><ul className="assumption-list"><li>这是未校准的建筑物理仿真，模拟电量与 CO₂ 不是住宅实测。</li><li>全部空间在同一个引擎中计算；层高暂定 {status?.height_m ?? 3} m，墙体、设备、天气与气流参数仍含假设。</li><li>自然采光来自 EnergyPlus；电灯照度使用经验响应，或所选房间的测量拟合。</li><li>窗帘尚无物理执行器。餐厅与走廊没有设计外窗，其窗户动作会明确拒绝。</li><li>固定合成占用、封闭阳台与固定跨区换气不等于真实住户行为。无人空间的占用期指标不适用。</li></ul></section>
      <details className="eplus-card eplus-cal"><summary>录入灯具测量数据</summary><p>至少 6 条、3 个调光档位；先扣除自然光。拟合仅对应当前测量点，不代表全屋照度分布。</p><div className="eplus-two"><label>测量来源<input value={source} onChange={(e) => setSource(e.target.value)} placeholder="实验日期、灯具与仪器" /></label><label>传感器位置<input value={sensor} onChange={(e) => setSensor(e.target.value)} placeholder="桌面中心，离地 0.8 m" /></label></div><label>测量数组 JSON<textarea rows={6} value={measurements} onChange={(e) => setMeasurements(e.target.value)} placeholder='[{"dimming_fraction":0,"electric_illuminance_lux":0,"power_w":0}]' /></label><label className="eplus-check"><input type="checkbox" checked={ambientSubtracted} onChange={(e) => setAmbientSubtracted(e.target.checked)} />已对每条照度读数扣除环境光</label><button type="button" disabled={busy || !ambientSubtracted} onClick={() => void calibrate()}>拟合并保存校准</button></details>
    </div>
    {notice && <p role="alert" className="eplus-error">{notice}</p>}
  </div>;
}
