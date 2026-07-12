import { useEffect, useState } from "react";

import type { RobustnessConfig, UserPreferenceProfile } from "../types/state";

interface ResearchControlPanelProps {
  profile: UserPreferenceProfile | null;
  robustness: RobustnessConfig | null;
  isLoading: boolean;
  onSaveProfile: (profile: Partial<UserPreferenceProfile>) => Promise<void>;
  onSaveRobustness: (config: RobustnessConfig) => Promise<void>;
  onFeedback: (satisfaction: number) => Promise<void>;
}

export function ResearchControlPanel({
  profile,
  robustness,
  isLoading,
  onSaveProfile,
  onSaveRobustness,
  onFeedback,
}: ResearchControlPanelProps) {
  const [temperature, setTemperature] = useState(profile?.preferred_temperature_c ?? 25);
  const [illuminance, setIlluminance] = useState(profile?.preferred_illuminance_lux ?? 500);
  const [energyPreference, setEnergyPreference] = useState(profile?.energy_saving_preference ?? 0.5);
  const [draftRobustness, setDraftRobustness] = useState<RobustnessConfig>(robustness ?? emptyRobustness());

  useEffect(() => {
    if (!profile) return;
    setTemperature(profile.preferred_temperature_c);
    setIlluminance(profile.preferred_illuminance_lux);
    setEnergyPreference(profile.energy_saving_preference);
  }, [profile]);

  useEffect(() => {
    if (robustness) setDraftRobustness(robustness);
  }, [robustness]);

  return (
    <section className="panel research-control-panel">
      <h2>论文实验控制</h2>
      <p className="research-subtitle">个性化多目标闭环：偏好、反馈与扰动均会进入智能体决策过程。</p>
      <div className="research-grid">
        <label>
          偏好温度 {temperature.toFixed(1)}°C
          <input type="range" min={16} max={30} step={0.5} value={temperature} disabled={isLoading} onChange={(event) => setTemperature(Number(event.target.value))} />
        </label>
        <label>
          偏好照度 {illuminance.toFixed(0)} lx
          <input type="range" min={100} max={1000} step={50} value={illuminance} disabled={isLoading} onChange={(event) => setIlluminance(Number(event.target.value))} />
        </label>
        <label>
          节能偏好 {Math.round(energyPreference * 100)}%
          <input type="range" min={0} max={1} step={0.1} value={energyPreference} disabled={isLoading} onChange={(event) => setEnergyPreference(Number(event.target.value))} />
        </label>
      </div>
      <button
        type="button"
        disabled={isLoading || !profile}
        onClick={() => onSaveProfile({ preferred_temperature_c: temperature, preferred_illuminance_lux: illuminance, energy_saving_preference: energyPreference })}
      >保存用户偏好</button>
      <div className="research-feedback">
        <span>本次控制体验：</span>
        {[1, 2, 3, 4, 5].map((satisfaction) => (
          <button key={satisfaction} type="button" disabled={isLoading || !profile} onClick={() => onFeedback(satisfaction)} aria-label={`提交 ${satisfaction} 分满意度`}>
            {satisfaction}★
          </button>
        ))}
        <small>已学习 {profile?.feedback_count ?? 0} 次，满意度 EMA：{profile?.satisfaction_ema.toFixed(1) ?? "--"}</small>
      </div>
      <div className="robustness-control">
        <label className="checkbox-row">
          <input type="checkbox" checked={draftRobustness.enabled} disabled={isLoading} onChange={(event) => setDraftRobustness({ ...draftRobustness, enabled: event.target.checked })} />
          启用鲁棒性扰动实验
        </label>
        <label>
          温度传感器噪声 ±{draftRobustness.temperature_sensor_noise_c.toFixed(1)}°C
          <input type="range" min={0} max={2} step={0.1} value={draftRobustness.temperature_sensor_noise_c} disabled={isLoading} onChange={(event) => setDraftRobustness({ ...draftRobustness, temperature_sensor_noise_c: Number(event.target.value) })} />
        </label>
        <label>
          执行失败率 {Math.round(draftRobustness.actuator_failure_probability * 100)}%
          <input type="range" min={0} max={0.3} step={0.05} value={draftRobustness.actuator_failure_probability} disabled={isLoading} onChange={(event) => setDraftRobustness({ ...draftRobustness, actuator_failure_probability: Number(event.target.value) })} />
        </label>
        <button type="button" className="secondary-button" disabled={isLoading} onClick={() => onSaveRobustness(draftRobustness)}>保存扰动配置</button>
      </div>
    </section>
  );
}

function emptyRobustness(): RobustnessConfig {
  return { enabled: false, seed: 42, temperature_sensor_noise_c: 0, illuminance_sensor_noise_lux: 0, actuator_failure_probability: 0 };
}
