import type { HistoryPoint } from "../types/state";

interface ChartPanelProps {
  history: HistoryPoint[];
}

export function ChartPanel({ history }: ChartPanelProps) {
  const points = history.slice(-20);
  const maxIlluminance = Math.max(1, ...points.map((point) => point.livingRoomIlluminance));
  const maxTemperature = Math.max(1, ...points.map((point) => point.livingRoomTemperature));
  const maxPower = Math.max(1, ...points.map((point) => point.currentPowerW));

  return (
    <section className="panel chart-panel">
      <span className="section-kicker">家庭趋势</span>
      <h2>最近变化</h2>
      <div className="sparkline">
        {points.map((point, index) => (
          <div className="spark-column" key={`${point.step}-${index}`}>
            <i style={{ height: `${(point.livingRoomIlluminance / maxIlluminance) * 100}%` }} />
            <b style={{ height: `${(point.livingRoomTemperature / maxTemperature) * 100}%` }} />
            <em style={{ height: `${(point.currentPowerW / maxPower) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="legend-row">
        <span><i className="legend-lux" />客厅照度</span>
        <span><i className="legend-temp" />客厅温度</span>
        <span><i className="legend-energy" />家庭功率</span>
      </div>
    </section>
  );
}
