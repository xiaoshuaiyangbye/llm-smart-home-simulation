import { useMemo, useState, type KeyboardEvent } from "react";

import type { AgentOutput } from "../types/state";

interface AgentOutputPanelProps {
  command: string;
  onCommandChange: (command: string) => void;
  onSubmit: () => Promise<void>;
  output: AgentOutput | null;
  isLoading: boolean;
}

type InspectorTab = "prompt" | "memory" | "semantic" | "planning" | "actions" | "feedback";

const TAB_LABELS: Record<InspectorTab, string> = {
  prompt: "提示词模板",
  memory: "上下文记忆",
  semantic: "语义理解",
  planning: "任务规划",
  actions: "执行动作",
  feedback: "反馈判断",
};

export function AgentOutputPanel({
  command,
  onCommandChange,
  onSubmit,
  output,
  isLoading,
}: AgentOutputPanelProps) {
  const [activeTab, setActiveTab] = useState<InspectorTab>("semantic");
  const semantic = asRecord(output?.semantic_result);
  const planning = asRecord(output?.planning_result);
  const execution = asRecord(output?.execution_result);
  const feedback = asRecord(output?.feedback_result);
  const llmMetrics = asRecord(semantic.llm_metrics);
  const promptTemplate = semantic.prompt_template ?? { status: "waiting" };
  const promptPayload = semantic.prompt_payload_summary ?? { status: "waiting" };
  const memoryContext = semantic.memory_context ?? { status: "waiting" };
  const semanticForDisplay = useMemo(() => {
    const rest = { ...semantic };
    delete rest.prompt_template;
    delete rest.prompt_payload_summary;
    delete rest.memory_context;
    return Object.keys(rest).length > 0 ? rest : { status: "waiting" };
  }, [semantic]);
  const completed = Boolean(feedback.completed);
  const actions = Array.isArray(output?.actions) ? output.actions : [];
  const executedCount = Number(execution.executed_count ?? 0);
  const canSubmit = command.trim().length > 0 && !isLoading;

  const inspectorValue = useMemo(() => {
    if (activeTab === "prompt") {
      return {
        prompt_template: promptTemplate,
        prompt_payload_summary: promptPayload,
      };
    }
    if (activeTab === "memory") return memoryContext;
    if (activeTab === "semantic") return semanticForDisplay;
    if (activeTab === "planning") return output?.planning_result ?? { status: "waiting" };
    if (activeTab === "actions") return actions;
    return output?.feedback_result ?? { status: "waiting" };
  }, [activeTab, actions, memoryContext, output, promptPayload, promptTemplate, semanticForDisplay]);

  function handleCommandKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    if (canSubmit) {
      void onSubmit();
    }
  }

  return (
    <section className="agent-dock">
      <div className="command-box">
        <label htmlFor="command">自然语言指令</label>
        <textarea
          id="command"
          rows={5}
          value={command}
          onChange={(event) => onCommandChange(event.target.value)}
          onKeyDown={handleCommandKeyDown}
        />
        <button type="button" disabled={!canSubmit} onClick={onSubmit}>
          {isLoading ? "执行中..." : "提交任务"}
        </button>
      </div>

      <div className="agent-process-panel">
        <div className="process-header">
          <h2>大语言模型智能体流程</h2>
          <span>{formatLlmStatus(semantic.llm_mode, llmMetrics)}</span>
        </div>
        <div className="agent-flow">
          <FlowNode
            label="感知"
            active={Boolean(output)}
            detail={output ? `读取 ${String(getNested(promptPayload, "room_count") ?? "-")} 个房间与 ${String(getNested(promptPayload, "device_count") ?? "-")} 个虚拟设备状态` : "等待任务"}
          />
          <FlowNode
            label="提示词"
            active={Boolean(semantic.prompt_template)}
            detail={semantic.prompt_template ? "自动注入平台、户型、设备和 JSON 输出约束" : "等待生成"}
          />
          <FlowNode
            label="记忆"
            active={Boolean(semantic.memory_context)}
            detail={semantic.memory_context ? String(getNested(memoryContext, "day_summary") ?? "已读取当天上下文") : "等待上下文"}
          />
          <FlowNode
            label="理解"
            active={Boolean(semantic.intent)}
            detail={semantic.intent ? `${String(semantic.intent)} / ${String(semantic.room)} / ${String(semantic.control_goal ?? "set_target")}` : "等待语义解析"}
          />
          <FlowNode
            label="规划"
            active={actions.length > 0}
            detail={actions.length > 0 ? `生成 ${actions.length} 个设备动作` : "等待动作序列"}
          />
          <FlowNode
            label="执行"
            active={executedCount > 0}
            detail={executedCount > 0 ? `已联动 ${executedCount} 个虚拟设备` : "等待执行"}
          />
          <FlowNode
            label="反馈"
            active={Boolean(output?.feedback_result)}
            detail={completed ? "目标达成" : output ? "需要继续修正或等待结果" : "等待闭环判断"}
          />
        </div>
      </div>

      <div className="agent-inspector">
        <div className="inspector-tabs" role="tablist" aria-label="智能体输出检查器">
          {(Object.keys(TAB_LABELS) as InspectorTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              className={tab === activeTab ? "active" : ""}
              onClick={() => setActiveTab(tab)}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>
        <div className="inspector-title">
          <h3>{TAB_LABELS[activeTab]} JSON</h3>
          {activeTab === "actions" && <span>{actions.length} 个动作</span>}
        </div>
        <pre>{JSON.stringify(inspectorValue, null, 2)}</pre>
      </div>
    </section>
  );
}

function FlowNode({ label, active, detail }: { label: string; active: boolean; detail: string }) {
  return (
    <div className={active ? "flow-node active" : "flow-node"}>
      <strong>{label}</strong>
      <span>{detail}</span>
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function getNested(value: unknown, key: string): unknown {
  const record = asRecord(value);
  return record[key];
}

function formatLlmStatus(mode: unknown, metrics: Record<string, unknown>): string {
  if (!mode) return "waiting";
  const requestMs = metrics.request_ms;
  const stream = metrics.stream;
  const cacheHit = metrics.cache_hit;
  const parts = [String(mode)];
  if (typeof requestMs === "number") parts.push(`${(requestMs / 1000).toFixed(1)}s`);
  if (stream === true) parts.push("stream");
  if (cacheHit === true) parts.push("cache");
  return parts.join(" · ");
}
