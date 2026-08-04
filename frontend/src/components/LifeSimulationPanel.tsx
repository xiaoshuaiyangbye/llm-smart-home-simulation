import type { LifeSimulationDuration, LifeSimulationStatus } from "../types/state";

interface LifeSimulationPanelProps {
  status: LifeSimulationStatus | null;
  isLoading: boolean;
  canStart: boolean;
  unavailableReason?: string;
  onStart: (duration: LifeSimulationDuration) => Promise<void>;
  onStop: () => Promise<void>;
  onBackToToday: () => Promise<void>;
}

const DURATION_LABELS: Record<LifeSimulationDuration, string> = {
  day: "一天",
  week: "一周",
  month: "一个月",
};

const DURATION_BUTTON_LABELS: Record<LifeSimulationDuration, string> = {
  day: "模拟一天 (1天)",
  week: "模拟一周 (7天)",
  month: "模拟一个月 (30天)",
};

export function LifeSimulationPanel({
  status,
  isLoading,
  canStart,
  unavailableReason,
  onStart,
  onStop,
  onBackToToday,
}: LifeSimulationPanelProps) {
  const active = Boolean(status?.active);
  const summary = status?.summary ?? {};
  const progress = Math.min(100, Math.max(0, status?.progress_percent ?? 0));
  const responseTimeMs = status?.last_event?.response_time_ms;
  const duration = status?.duration ? DURATION_LABELS[status.duration] : "--";

  return (
    <section className="panel life-sim-panel">
      <div className="life-sim-header">
        <div>
          <span className="section-kicker">生活场景</span>
          <h2>生活模拟</h2>
          <p>{active ? `正在模拟 ${duration}` : "加速观察长期自治表现"}</p>
        </div>
        <span className={active ? "run-status active" : "run-status"}>{active ? "运行中" : "待启动"}</span>
      </div>
      <div className="life-sim-actions">
        {(Object.keys(DURATION_LABELS) as LifeSimulationDuration[]).map((duration) => (
          <button
            key={duration}
            type="button"
            disabled={isLoading || active || !canStart}
            onClick={() => onStart(duration)}
          >
            {DURATION_BUTTON_LABELS[duration]}
          </button>
        ))}
        <button type="button" className="secondary-button" disabled={isLoading || !active} onClick={onStop}>
          停止
        </button>
        <button type="button" className="secondary-button" disabled={isLoading} onClick={onBackToToday}>
          回到今天
        </button>
      </div>
      {!active && !canStart && <p className="panel-notice" role="status">{unavailableReason ?? "生活仿真需要可用的真实 LLM 配置。"}</p>}
      <div className="life-progress" role="progressbar" aria-label="生活仿真进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)}>
        <i style={{ width: `${progress}%` }} />
      </div>
      <div className="life-sim-kpis">
        <Metric label="节能率" value={`${formatNumber(summary.energy_saving_vs_baseline_percent)}%`} emphasis />
        <Metric label="居住舒适度" value={formatNumber(summary.average_occupied_comfort)} emphasis />
        <Metric label="智能体能耗" value={`${formatNumber(summary.agent_energy_kwh, 3)} kWh`} />
        <Metric label="固定策略能耗" value={`${formatNumber(summary.baseline_energy_kwh, 3)} kWh`} />
      </div>
      <details className="life-details">
        <summary>查看完整推演指标</summary>
        <div className="life-sim-meta">
          <Metric label="智能体均功率" value={`${formatNumber(summary.average_power_w)} W`} />
          <Metric label="基线均功率" value={`${formatNumber(summary.average_baseline_power_w)} W`} />
          <Metric label="完成率" value={`${formatNumber(summary.task_completion_rate_percent)}%`} />
          <Metric label="满意度" value={formatNumber(summary.average_satisfaction_score)} />
          <Metric label="仿真时间" value={status ? `第 ${status.day} 天 ${status.time}` : "--"} />
          <Metric label="速度" value={status?.speed_label ?? "24h sim = 24min real"} />
          <Metric label="所在房间" value={status?.current_room_name || "--"} />
          <Metric label="生活事件" value={status ? `${status.completed_event_count}/${status.event_count}` : "--"} />
          <Metric label="天气来源" value={formatWeatherSource(status?.weather_source)} />
          <Metric label="上次响应" value={typeof responseTimeMs === "number" ? `${(responseTimeMs / 1000).toFixed(1)} s` : "--"} />
        </div>
      </details>
      {status?.last_event && (
        <div className="life-last-event">
          <strong>{String(status.last_event.activity ?? "生活事件")}</strong>
          <span>{String(status.last_event.command ?? "")}</span>
        </div>
      )}
      {status?.output_paths && Object.keys(status.output_paths).length > 0 && (
        <div className="life-output-paths">
          <strong>分析日志</strong>
          <span>{status.output_paths.report_md}</span>
        </div>
      )}
    </section>
  );
}

function Metric({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className={emphasis ? "metric-tile emphasis" : "metric-tile"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatNumber(value: unknown, digits = 1): string {
  return typeof value === "number" ? value.toFixed(digits) : "--";
}

function formatWeatherSource(source: string | undefined): string {
  if (!source) return "--";
  if (source.startsWith("historical_week_log")) return "上周日志";
  if (source === "mild_may_typical_profile") return "温和五月";
  return "周天气模板";
}
