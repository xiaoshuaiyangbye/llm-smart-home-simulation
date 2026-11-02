import { useEffect, useId, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";

import "./DecisionTracePanel.css";

type JsonRecord = Record<string, unknown>;
interface TraceAction { entity_id: string; action: string; parameters: JsonRecord; reason?: string }
interface DeviceSnapshot { devices: (JsonRecord & { entity_id: string })[] }
interface TraceEvent {
  event_id: string;
  stage: string;
  before_actions: TraceAction[];
  after_actions: TraceAction[];
  actions_changed: boolean;
  before_state: DeviceSnapshot | null;
  after_state: DeviceSnapshot | null;
  duration_ms: number;
  details: JsonRecord;
}
interface DecisionTrace {
  schema_version: "decision_trace_v1";
  semantic_mode: "mock" | "real" | "unknown";
  evidence_class: "observed_software_simulation";
  boundary: string;
  events: TraceEvent[];
}
interface Demo { id: string; title: string; description: string; trace: DecisionTrace }

const STAGES: Record<string, string> = {
  planning_agent: "原始规划", collaboration_agent: "协作整合", safety_agent: "安全审查",
  critic_agent: "批评审查", execution_agent: "执行", feedback_correction: "反馈校正",
  outcome: "最终结果", error: "执行异常", user_feedback: "住户反馈",
  snapshot_prepare: "保存计划快照", state_changed: "环境变化", commit_guard: "提交前校验",
  planning_context: "后续规划上下文", knowledge_agent: "知识检索", confirmed_experience: "确认经验",
};
const LABELS: Record<string, string> = {
  brightness_pct: "亮度", opening_pct: "开度", color_temperature_k: "色温", setpoint_c: "设定温度",
  speed_pct: "转速", is_on: "开关", mode: "模式", value: "读数", status: "状态",
  executed_count: "已执行动作数", issues: "审查问题", approved: "审查同意", revision_requests: "修订请求",
  confirmed_before: "反馈前已确认", confirmed_after: "反馈后已确认", sample_count: "反馈样本数",
  feedback_completed: "反馈目标达成", reason: "依据", confirmed_experience: "已确认经验",
  completion_rate: "完成比例", evidence_boundary: "证据边界", error: "异常信息",
  command: "原始指令", message: "阶段说明", enabled: "审查已启用", review_round: "审查轮次",
  findings: "批评意见", revision_decisions: "修订决定", targets: "规划目标", experiment_fault: "实验故障注入",
  correction_round: "本次校正轮次", correction_rounds: "校正总轮次", results: "执行明细",
  turn: "反馈次数", reflection_input: "反思重放输入", feedback_input: "明确反馈输入", semantic_input: "语义输入",
  used_sources: "检索来源", rag_context: "检索上下文", guard_inputs: "提交校验输入", guard_result: "提交校验结果",
  allowed: "允许提交", state_changed: "环境已变化", preference_changed: "偏好已变化", duplicate_commit: "重复提交",
  snapshot_revision: "快照环境版本", current_revision: "当前环境版本", commit_id: "提交标识", committed_action_ids: "已提交动作标识",
  snapshot_preference_fingerprint: "快照偏好指纹", current_preference_fingerprint: "当前偏好指纹",
};
const ACTIONS: Record<string, string> = { turn_on: "开启", turn_off: "关闭", open: "打开", close: "关闭", set_brightness: "设置亮度", set_opening: "设置开度", set_temperature: "设置温度", set_mode: "设置模式", set_speed: "设置转速" };
const VALUES: Record<string, string> = { stale_snapshot_replan_required: "快照已过期，需要重新规划", cool: "制冷", heat: "制热", fan: "送风", dry: "除湿", off: "关闭" };

export function DecisionTracePanel({ trace }: { trace: unknown }) {
  const id = useId();
  const liveTrace = useMemo(() => parseTrace(trace), [trace]);
  const [demos, setDemos] = useState<Demo[]>([]);
  const [loadState, setLoadState] = useState("正在加载历史演示…");
  const [source, setSource] = useState("live");
  const [imported, setImported] = useState<{ name: string; trace: DecisionTrace } | null>(null);
  const [importMessage, setImportMessage] = useState("");
  const [exportError, setExportError] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const stageButtons = useRef<(HTMLButtonElement | null)[]>([]);
  const selectedDemo = demos.find((demo) => demo.id === source);
  const selectedTrace = source === "live" ? liveTrace : source === "imported" ? imported?.trace : selectedDemo?.trace;
  const events = selectedTrace?.events ?? [];
  const activeIndex = Math.min(selectedIndex, Math.max(0, events.length - 1));
  const event = events[activeIndex];
  const changed = event ? actionsChanged(event) : false;

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/decision-demos/evidence.json", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("load");
        const parsed = parseBundle(await response.json());
        if (!parsed) throw new Error("format");
        if (!controller.signal.aborted) { setDemos(parsed); setLoadState(""); }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoadState(error instanceof Error && error.message === "format"
          ? "演示记录格式不完整，仍可查看当前执行或导入其他记录。"
          : "演示记录加载失败，可重新打开本页签重试，或导入已保存的轨迹。");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => { setSelectedIndex(0); setExportError(""); }, [selectedTrace]);

  function navigateStage(keyEvent: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (keyEvent.key === "ArrowRight" || keyEvent.key === "ArrowDown") next = Math.min(index + 1, events.length - 1);
    else if (keyEvent.key === "ArrowLeft" || keyEvent.key === "ArrowUp") next = Math.max(index - 1, 0);
    else if (keyEvent.key === "Home") next = 0;
    else if (keyEvent.key === "End") next = events.length - 1;
    else return;
    keyEvent.preventDefault();
    setSelectedIndex(next);
    stageButtons.current[next]?.focus();
  }

  async function importTrace(change: ChangeEvent<HTMLInputElement>) {
    const file = change.currentTarget.files?.[0];
    change.currentTarget.value = "";
    if (!file) return;
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error("文件超过 5 MB");
      const content = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("无法读取文件"));
        reader.readAsText(file);
      });
      const parsed = parseTrace(JSON.parse(content));
      if (!parsed) throw new Error("轨迹结构不完整，请使用 decision_trace_v1 的 JSON 文件");
      setImported({ name: file.name, trace: parsed });
      setSource("imported");
      setSelectedIndex(0);
      setImportMessage(`已导入 ${file.name}；仅完成格式检查，未复核来源与结果。`);
    } catch (error) {
      setImportMessage(`导入失败：${error instanceof SyntaxError ? "文件不是有效 JSON" : error instanceof Error ? error.message : "无法读取文件"}。`);
    }
  }

  function exportTrace() {
    if (!selectedTrace) return;
    try {
      const url = URL.createObjectURL(new Blob([JSON.stringify(selectedTrace, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `decision-trace-${source}.json`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setExportError("");
    } catch { setExportError("导出失败，请检查浏览器是否允许下载。"); }
  }

  return (
    <section className="decision-replay" aria-labelledby={`${id}-heading`}>
      <div className="decision-replay-header">
        <div><span className="decision-replay-kicker">从计划到住宅状态</span><h3 id={`${id}-heading`}>决策对照与回放</h3></div>
        <button type="button" className="decision-replay-export" onClick={exportTrace} disabled={!selectedTrace}>导出当前轨迹</button>
      </div>
      <div className="decision-replay-source">
        <label htmlFor={`${id}-source`}>回放来源</label>
        <select id={`${id}-source`} value={source} onChange={(change) => { setSource(change.target.value); setSelectedIndex(0); }}>
          <option value="live">当前执行轨迹</option>
          {demos.map((demo) => <option key={demo.id} value={demo.id}>{demo.title}</option>)}
          {imported && <option value="imported">导入：{imported.name}</option>}
        </select>
        <label className="decision-replay-import">导入轨迹 JSON<input type="file" accept=".json,application/json" aria-label="导入轨迹 JSON" onChange={(change) => void importTrace(change)} /></label>
      </div>
      {loadState && <p className="decision-replay-notice" role="status">{loadState}</p>}
      {importMessage && <p className="decision-replay-notice" role="status">{importMessage}</p>}
      {exportError && <p className="decision-replay-notice" role="alert">{exportError}</p>}
      {selectedDemo && <p className="decision-replay-description">{selectedDemo.description}</p>}
      <p className="decision-replay-boundary">
        <strong>{source === "live" ? "当前执行记录" : "历史回放，不会执行设备动作"}</strong>
        {selectedTrace && <span>{selectedTrace.semantic_mode === "mock" ? "Mock 语义 · 软件仿真" : selectedTrace.semantic_mode === "real" ? "真实模型语义 · 软件仿真" : "语义模式未知 · 软件仿真"}</span>}
        <span>动作变化不等于效果改善；这些记录不验证真实设备或真实家庭效果。</span>
      </p>
      {!selectedTrace ? <p className="decision-replay-empty">{source === "live" && trace != null ? "当前轨迹格式不完整，无法进行可靠对照。可切换历史演示或导入有效记录。" : "完成一次指令后可查看当前轨迹，也可选择历史演示或导入保存的记录。"}</p>
        : !event ? <p className="decision-replay-empty">这份记录没有可回放的阶段。</p>
          : <>
            <ol className="decision-replay-timeline" aria-label="选择决策阶段">
              {events.map((item, index) => <li key={item.event_id}>
                <button type="button" ref={(element) => { stageButtons.current[index] = element; }} aria-pressed={index === activeIndex} aria-controls={`${id}-stage`} tabIndex={index === activeIndex ? 0 : -1} onClick={() => setSelectedIndex(index)} onKeyDown={(keyEvent) => navigateStage(keyEvent, index)}>
                  <span className="decision-replay-step">{index + 1}</span><span>{STAGES[item.stage] ?? item.stage}<small>{actionsChanged(item) ? "动作有变化" : "动作未改动"}</small></span>
                </button>
              </li>)}
            </ol>
            <div className="decision-replay-stage" id={`${id}-stage`}>
              <div className="decision-replay-stage-heading"><h4>{STAGES[event.stage] ?? event.stage}</h4><span>{event.duration_ms.toFixed(2)} ms · {changed ? "动作有变化" : "动作未改动"}</span></div>
              {changed !== event.actions_changed && <p className="decision-replay-notice" role="status">记录的变更标记与动作内容不一致，以下以动作内容对照为准。</p>}
              <div className="decision-replay-actions">
                <ActionList title="原动作" actions={event.before_actions} />
                <ActionList title="修改后动作" actions={event.after_actions} />
              </div>
              <StateChanges before={event.before_state} after={event.after_state} />
              {Object.keys(event.details).length > 0 && <div className="decision-replay-evidence"><h5>阶段依据与结果</h5><EvidenceFields record={event.details} /></div>}
            </div>
            <details className="decision-replay-provenance"><summary>记录说明与证据边界</summary><p>{selectedTrace.boundary}</p><p>{source === "live" ? "来自本次命令返回的轨迹。" : source === "imported" ? "导入文件只做结构检查，未复核来源与结果。" : "来自保存的软件仿真记录；此处没有重新运行实验或验证记录自报的结果。"}</p></details>
          </>}
    </section>
  );
}

function ActionList({ title, actions }: { title: string; actions: TraceAction[] }) {
  const id = useId();
  return <section className="decision-replay-action-list" aria-labelledby={id}><h5 id={id}>{title}<span>{actions.length} 个</span></h5>
    {actions.length === 0 ? <p className="decision-replay-empty">未记录动作</p> : <ul>{actions.map((action, index) => <li key={`${action.entity_id}-${index}`}>
      <strong>{ACTIONS[action.action] ?? action.action}</strong><code>{action.entity_id}</code>
      <div>{Object.entries(action.parameters).map(([key, value]) => <span className="decision-replay-parameter" key={key}>{LABELS[key] ?? key}：{formatValue(value, key)}</span>)}</div>
      {action.reason && <p>{action.reason}</p>}
    </li>)}</ul>}
  </section>;
}

function StateChanges({ before, after }: { before: DeviceSnapshot | null; after: DeviceSnapshot | null }) {
  if (!before || !after) return <div className="decision-replay-state"><h5>设备状态变化</h5><p className="decision-replay-empty">本阶段未同时记录前后设备快照，无法判断设备是否变化。</p></div>;
  const beforeDevices = new Map(before.devices.map((device) => [device.entity_id, device]));
  const afterDevices = new Map(after.devices.map((device) => [device.entity_id, device]));
  const rows = [...new Set([...beforeDevices.keys(), ...afterDevices.keys()])].flatMap((entityId) => {
    const oldDevice = beforeDevices.get(entityId);
    const newDevice = afterDevices.get(entityId);
    const name = typeof newDevice?.name === "string" ? newDevice.name : typeof oldDevice?.name === "string" ? oldDevice.name : entityId;
    if (!oldDevice || !newDevice) return [{ entityId, name, key: "设备记录", oldValue: oldDevice ? "存在" : "未记录", newValue: newDevice ? "存在" : "未记录" }];
    return [...new Set([...Object.keys(oldDevice), ...Object.keys(newDevice)])].filter((key) => key !== "entity_id" && comparable(oldDevice[key]) !== comparable(newDevice[key])).map((key) => ({ entityId, name, key, oldValue: formatValue(oldDevice[key], key), newValue: formatValue(newDevice[key], key) }));
  });
  return <div className="decision-replay-state"><h5>设备状态变化</h5>{rows.length === 0 ? <p className="decision-replay-empty">已记录的前后快照中，设备状态未变化。</p> : <div className="decision-replay-table-scroll"><table aria-label="设备状态变化"><thead><tr><th>设备</th><th>属性</th><th>变化前</th><th>变化后</th></tr></thead><tbody>{rows.map((row) => <tr key={`${row.entityId}-${row.key}`}><th scope="row">{row.name}<small>{row.entityId}</small></th><td>{LABELS[row.key] ?? row.key}</td><td>{row.oldValue}</td><td>{row.newValue}</td></tr>)}</tbody></table></div>}</div>;
}

function EvidenceFields({ record }: { record: JsonRecord }) {
  return <dl>{Object.entries(record).map(([key, value]) => <div key={key}><dt>{LABELS[key] ?? key}</dt><dd>{formatValue(value, key)}</dd></div>)}</dl>;
}

function formatValue(value: unknown, key = ""): string {
  if (value == null) return "未记录";
  if (typeof value === "boolean") return key === "is_on" ? (value ? "开启" : "关闭") : (value ? "是" : "否");
  if (typeof value === "number") return `${value}${key.endsWith("_pct") ? "%" : key.endsWith("_c") ? " °C" : key.endsWith("_k") ? " K" : ""}`;
  if (typeof value === "string") return VALUES[value] ?? value;
  if (Array.isArray(value)) return value.length ? value.map((entry) => formatValue(entry)).join("；") : "无";
  return Object.entries(value as JsonRecord).map(([nestedKey, entry]) => `${LABELS[nestedKey] ?? nestedKey}：${formatValue(entry, nestedKey)}`).join("；") || "无";
}

function isRecord(value: unknown): value is JsonRecord { return value !== null && typeof value === "object" && !Array.isArray(value); }
function isJson(value: unknown, depth = 0): boolean {
  if (depth > 12) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.length <= 2000 && value.every((entry) => isJson(entry, depth + 1));
  return isRecord(value) && Object.keys(value).length <= 2000 && Object.values(value).every((entry) => isJson(entry, depth + 1));
}
function validState(value: unknown): boolean {
  if (value === null) return true;
  if (!isRecord(value) || !Array.isArray(value.devices) || !isJson(value)) return false;
  const ids = new Set<string>();
  return value.devices.every((device) => {
    if (!isRecord(device) || typeof device.entity_id !== "string" || !device.entity_id || ids.has(device.entity_id)) return false;
    ids.add(device.entity_id);
    return true;
  });
}
function validActions(value: unknown): boolean {
  return Array.isArray(value) && value.length <= 2000 && value.every((action) => isRecord(action) && typeof action.entity_id === "string" && action.entity_id.length > 0 && typeof action.action === "string" && action.action.length > 0 && isRecord(action.parameters) && isJson(action.parameters) && (action.reason === undefined || typeof action.reason === "string"));
}
function parseTrace(value: unknown): DecisionTrace | null {
  if (!isRecord(value) || value.schema_version !== "decision_trace_v1" || value.evidence_class !== "observed_software_simulation" || !["mock", "real", "unknown"].includes(String(value.semantic_mode)) || typeof value.boundary !== "string" || !Array.isArray(value.events) || value.events.length > 1000) return null;
  const ids = new Set<string>();
  for (const event of value.events) {
    if (!isRecord(event) || typeof event.event_id !== "string" || !event.event_id || ids.has(event.event_id) || typeof event.stage !== "string" || !event.stage || typeof event.actions_changed !== "boolean" || typeof event.duration_ms !== "number" || !Number.isFinite(event.duration_ms) || event.duration_ms < 0 || !validActions(event.before_actions) || !validActions(event.after_actions) || !validState(event.before_state) || !validState(event.after_state) || !isRecord(event.details) || !isJson(event.details)) return null;
    ids.add(event.event_id);
  }
  return { schema_version: "decision_trace_v1", semantic_mode: value.semantic_mode as DecisionTrace["semantic_mode"], evidence_class: "observed_software_simulation", boundary: value.boundary, events: value.events as TraceEvent[] };
}
function parseBundle(value: unknown): Demo[] | null {
  if (!isRecord(value) || value.schema_version !== "decision_demo_bundle_v1" || typeof value.generated_at !== "string" || !Array.isArray(value.examples) || value.examples.length > 20) return null;
  const demos: Demo[] = [];
  for (const example of value.examples) {
    if (!isRecord(example) || typeof example.id !== "string" || !example.id || ["live", "imported"].includes(example.id) || demos.some((demo) => demo.id === example.id) || typeof example.title !== "string" || typeof example.description !== "string") return null;
    const parsed = parseTrace(example.trace);
    if (!parsed) return null;
    demos.push({ id: example.id, title: example.title, description: example.description, trace: parsed });
  }
  return demos;
}
function comparable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(comparable).join(",")}]`;
  if (isRecord(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${comparable(value[key])}`).join(",")}}`;
  return JSON.stringify(value) ?? "undefined";
}
function actionsChanged(event: TraceEvent): boolean {
  const executable = (actions: TraceAction[]) => actions.map(({ entity_id, action, parameters }) => ({ entity_id, action, parameters }));
  return comparable(executable(event.before_actions)) !== comparable(executable(event.after_actions));
}
