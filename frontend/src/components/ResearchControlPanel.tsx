import { useEffect, useRef, useState } from "react";

import type { AutonomousRuntimeStatus, PrivateUserMemory, RobustnessConfig, UserPreferenceProfile } from "../types/state";

interface ResearchControlPanelProps {
  profile: UserPreferenceProfile | null;
  robustness: RobustnessConfig | null;
  privateMemory: PrivateUserMemory | null;
  autonomyStatus: AutonomousRuntimeStatus | null;
  isLoading: boolean;
  onSaveProfile: (profile: Partial<UserPreferenceProfile>) => Promise<void>;
  onSaveRobustness: (config: RobustnessConfig) => Promise<void>;
  onFeedback: (satisfaction: number) => Promise<void>;
  onSavePrivateAttributes: (attributes: Record<string, string | null>) => Promise<void>;
  onResetPrivateMemory: () => Promise<void>;
  onAutonomyChange: (enabled: boolean) => Promise<void>;
}

export function ResearchControlPanel({
  profile,
  robustness,
  privateMemory,
  autonomyStatus,
  isLoading,
  onSaveProfile,
  onSaveRobustness,
  onFeedback,
  onSavePrivateAttributes,
  onResetPrivateMemory,
  onAutonomyChange,
}: ResearchControlPanelProps) {
  const autonomyRunning = Boolean(autonomyStatus?.active);
  const autonomyStopping = Boolean(autonomyStatus?.stopping);
  const autonomyEnabled = autonomyRunning && !autonomyStopping;
  const [autonomyRequested, setAutonomyRequested] = useState(autonomyEnabled);
  const [temperature, setTemperature] = useState(profile?.preferred_temperature_c ?? 25);
  const [illuminance, setIlluminance] = useState(profile?.preferred_illuminance_lux ?? 500);
  const [energyPreference, setEnergyPreference] = useState(profile?.energy_saving_preference ?? 0.5);
  const [draftRobustness, setDraftRobustness] = useState<RobustnessConfig>(robustness ?? emptyRobustness());
  const [privateAttributes, setPrivateAttributes] = useState(() => privateAttributeDraft(privateMemory));
  const [privateAttributesDirty, setPrivateAttributesDirty] = useState(false);
  const [privateAttributesSaving, setPrivateAttributesSaving] = useState(false);
  const privateAttributesDirtyRef = useRef(false);

  useEffect(() => {
    if (!profile) return;
    setTemperature(profile.preferred_temperature_c);
    setIlluminance(profile.preferred_illuminance_lux);
    setEnergyPreference(profile.energy_saving_preference);
  }, [profile]);

  useEffect(() => {
    if (robustness) setDraftRobustness(robustness);
  }, [robustness]);

  useEffect(() => {
    if (!privateAttributesDirtyRef.current) {
      setPrivateAttributes(privateAttributeDraft(privateMemory));
    }
  }, [privateMemory]);

  useEffect(() => {
    setAutonomyRequested(autonomyEnabled);
  }, [autonomyEnabled]);

  const latestReflection = privateMemory?.reflections[privateMemory.reflections.length - 1];

  return (
    <section className="panel research-control-panel">
      <div className="research-heading">
        <div>
          <span className="section-kicker">家庭自动化</span>
          <h2>自动运行</h2>
        </div>
        <span className={autonomyRunning ? "autonomy-orb active" : "autonomy-orb"} aria-hidden="true" />
      </div>
      <p className="research-subtitle">根据家中状态自动执行，并在每次操作后学习你的习惯。</p>
      <label className="checkbox-row autonomy-toggle">
        <input
          type="checkbox"
          aria-label="启用持续感知与自主决策"
          checked={autonomyRequested}
          disabled={isLoading || autonomyStopping || !privateMemory}
          onChange={(event) => {
            const enabled = event.target.checked;
            setAutonomyRequested(enabled);
            void onAutonomyChange(enabled).catch(() => setAutonomyRequested(!enabled));
          }}
        />
        <span><strong>{autonomyStopping ? "正在安全停止" : autonomyRequested ? "全屋自动运行中" : "开启全屋自动化"}</strong><small>感知环境 · 自动决策 · 持续学习</small></span>
      </label>
      <div className="memory-glimpse" aria-label="私有记忆摘要">
        <span><small>住户记忆</small><strong>{privateMemory?.reflections.length ?? 0} 条反思</strong></span>
        <span><small>运行周期</small><strong>{autonomyStatus?.cycle_count ?? 0}</strong></span>
        <span><small>有效决策</small><strong>{autonomyStatus?.decision_count ?? 0}</strong></span>
      </div>
      <details className="memory-profile-details">
        <summary>家庭成员习惯与隐私设置</summary>
        <div className="private-memory-control">
        <label>
          健康与安全约束
          <textarea
            value={privateAttributes.health_constraints}
            maxLength={200}
            disabled={isLoading || !privateMemory}
            placeholder="例如：鼻炎、怕风、不能直吹"
            onChange={(event) => updatePrivateDraft("health_constraints", event.target.value)}
          />
        </label>
        <label>
          睡眠与生活习惯
          <textarea
            value={privateAttributes.sleep_and_routine}
            maxLength={200}
            disabled={isLoading || !privateMemory}
            placeholder="例如：夜间浅睡、23:00 入睡、早晨优先自然光"
            onChange={(event) => updatePrivateDraft("sleep_and_routine", event.target.value)}
          />
        </label>
        <label className="private-notes-field">
          其他长期属性
          <textarea
            value={privateAttributes.resident_notes}
            maxLength={200}
            disabled={isLoading}
            placeholder="例如：在家办公，更重视舒适度"
            onChange={(event) => updatePrivateDraft("resident_notes", event.target.value)}
          />
        </label>
        <button
          type="button"
          className="secondary-button"
          disabled={isLoading || privateAttributesSaving || !privateMemory || !privateAttributesDirty}
          onClick={() => {
            setPrivateAttributesSaving(true);
            void onSavePrivateAttributes({
              health_constraints: privateAttributes.health_constraints.trim() || null,
              sleep_and_routine: privateAttributes.sleep_and_routine.trim() || null,
              resident_notes: privateAttributes.resident_notes.trim() || null,
            })
              .then(() => {
                privateAttributesDirtyRef.current = false;
                setPrivateAttributesDirty(false);
              })
              .catch(() => undefined)
              .finally(() => setPrivateAttributesSaving(false));
          }}
        >
          {privateAttributesSaving
            ? "保存中…"
            : privateAttributesDirty
              ? "保存到私有知识库"
              : "已保存到私有知识库"}
        </button>
        <small>
          本地住户空间 · 已反思 {privateMemory?.reflections.length ?? 0} 次
          {latestReflection ? ` · 最近：${latestReflection.conclusion}` : ""}
        </small>
        <small>
          后端自治服务 · 周期 {autonomyStatus?.cycle_count ?? 0} · 决策 {autonomyStatus?.decision_count ?? 0}
          {autonomyStopping ? " · 当前周期结束后停止" : ""}
          {autonomyStatus?.suppressed_count ? ` · 冷却抑制 ${autonomyStatus.suppressed_count}` : ""}
          {autonomyStatus?.failure_count ? ` · 失败 ${autonomyStatus.failure_count}` : ""}
          {autonomyStatus && !autonomyStatus.active && autonomyStatus.stop_reason === "max_consecutive_failures"
            ? " · 已因连续失败自动停机"
            : ""}
        </small>
        <button
          type="button"
          className="secondary-button memory-reset-button"
          disabled={isLoading || autonomyRunning || !privateMemory}
          onClick={onResetPrivateMemory}
        >
          清除私有记忆
        </button>
        </div>
      </details>
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
      <details className="research-details">
        <summary>实验反馈与鲁棒性设置</summary>
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
      </details>
    </section>
  );

  function updatePrivateDraft(key: keyof PrivateAttributeDraft, value: string) {
    privateAttributesDirtyRef.current = true;
    setPrivateAttributesDirty(true);
    setPrivateAttributes((current) => ({ ...current, [key]: value }));
  }
}

interface PrivateAttributeDraft {
  health_constraints: string;
  sleep_and_routine: string;
  resident_notes: string;
}

function privateAttributeDraft(memory: PrivateUserMemory | null): PrivateAttributeDraft {
  return {
    health_constraints: memory?.private_attributes.health_constraints ?? "",
    sleep_and_routine: memory?.private_attributes.sleep_and_routine ?? "",
    resident_notes: memory?.private_attributes.resident_notes ?? "",
  };
}

function emptyRobustness(): RobustnessConfig {
  return { enabled: false, seed: 42, temperature_sensor_noise_c: 0, illuminance_sensor_noise_lux: 0, actuator_failure_probability: 0 };
}
