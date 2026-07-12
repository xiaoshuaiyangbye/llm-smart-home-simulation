import { useMemo, useState, type KeyboardEvent } from "react";

import type { AgentOutput } from "../types/state";

interface AgentOutputPanelProps {
  command: string;
  onCommandChange: (command: string) => void;
  onSubmit: () => Promise<void>;
  output: AgentOutput | null;
  isLoading: boolean;
}

type InspectorTab =
  | "prompt"
  | "memory"
  | "semantic"
  | "planning"
  | "rag"
  | "agents"
  | "safety"
  | "actions"
  | "feedback";

const TAB_LABELS: Record<InspectorTab, string> = {
  prompt: "提示词",
  memory: "记忆",
  semantic: "语义",
  planning: "规划",
  rag: "RAG",
  agents: "协同",
  safety: "安全",
  actions: "动作",
  feedback: "反馈",
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
  const multiAgentContext = asRecord(planning.multi_agent_context);
  const knowledgeResult = asRecord(multiAgentContext.knowledge_result);
  const safetyReview = asRecord(multiAgentContext.safety_result);
  const blackboard =
    output?.multi_agent_blackboard ??
    semantic.multi_agent_blackboard ??
    planning.multi_agent_blackboard ??
    { status: "waiting" };
  const ragContext = semantic.rag_context ?? knowledgeResult.rag_context ?? { status: "waiting" };
  const llmMetrics = asRecord(semantic.llm_metrics);
  const promptTemplate = semantic.prompt_template ?? { status: "waiting" };
  const promptPayload = semantic.prompt_payload_summary ?? { status: "waiting" };
  const memoryContext = semantic.memory_context ?? { status: "waiting" };
  const semanticForDisplay = useMemo(() => {
    const rest = { ...semantic };
    delete rest.prompt_template;
    delete rest.prompt_payload_summary;
    delete rest.memory_context;
    delete rest.multi_agent_blackboard;
    return Object.keys(rest).length > 0 ? rest : { status: "waiting" };
  }, [semantic]);
  const completed = Boolean(feedback.completed);
  const actions = Array.isArray(output?.actions) ? output.actions : [];
  const executedCount = Number(execution.executed_count ?? 0);
  const ragRecord = asRecord(ragContext);
  const ragMatchesValue = ragRecord.matches;
  const safetyIssuesValue = safetyReview.issues;
  const ragMatches = Array.isArray(ragMatchesValue) ? ragMatchesValue.length : 0;
  const safetyIssues = Array.isArray(safetyIssuesValue) ? safetyIssuesValue.length : 0;
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
    if (activeTab === "rag") return ragContext;
    if (activeTab === "agents") return blackboard;
    if (activeTab === "safety") return Object.keys(safetyReview).length > 0 ? safetyReview : { status: "waiting" };
    if (activeTab === "actions") return actions;
    return output?.feedback_result ?? { status: "waiting" };
  }, [
    activeTab,
    actions,
    blackboard,
    memoryContext,
    output,
    promptPayload,
    promptTemplate,
    ragContext,
    safetyReview,
    semanticForDisplay,
  ]);

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
        <label htmlFor="command">指令输入</label>
        <textarea
          id="command"
          rows={5}
          value={command}
          onChange={(event) => onCommandChange(event.target.value)}
          onKeyDown={handleCommandKeyDown}
          placeholder="请输入自然语言指令，例如：晚上7点，打开客厅灯和空调，温度设置为24度"
        />
        <button type="button" disabled={!canSubmit} onClick={onSubmit}>
          {isLoading ? "执行中..." : "发送指令"}
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
            detail={
              output
                ? `${String(getNested(promptPayload, "room_count") ?? "-")} rooms / ${String(
                    getNested(promptPayload, "device_count") ?? "-",
                  )} devices`
                : "等待输入"
            }
          />
          <FlowNode
            label="RAG"
            active={ragMatches > 0}
            detail={ragMatches > 0 ? `检索 ${ragMatches} 段知识` : "等待检索"}
          />
          <FlowNode
            label="记忆"
            active={Boolean(semantic.memory_context)}
            detail={semantic.memory_context ? String(getNested(memoryContext, "day_summary") ?? "上下文已载入") : "等待上下文"}
          />
          <FlowNode
            label="意图"
            active={Boolean(semantic.intent)}
            detail={
              semantic.intent
                ? `${String(semantic.intent)} / ${String(semantic.room)} / ${String(semantic.control_goal ?? "set_target")}`
                : "等待识别"
            }
          />
          <FlowNode
            label="规划"
            active={actions.length > 0}
            detail={actions.length > 0 ? `${actions.length} 个设备动作` : "等待规划"}
          />
          <FlowNode
            label="安全"
            active={Object.keys(safetyReview).length > 0}
            detail={safetyIssues > 0 ? `${safetyIssues} 个风险` : Object.keys(safetyReview).length > 0 ? "已通过" : "等待检查"}
          />
          <FlowNode
            label="执行"
            active={executedCount > 0}
            detail={executedCount > 0 ? `已执行 ${executedCount} 个动作` : "等待执行"}
          />
          <FlowNode
            label="反馈"
            active={Boolean(output?.feedback_result)}
            detail={completed ? "目标已达成" : output ? "等待修正或收敛" : "等待反馈"}
          />
        </div>
      </div>

      <div className="agent-inspector">
        <div className="inspector-tabs" role="tablist" aria-label="Agent output inspector">
          {(Object.keys(TAB_LABELS) as InspectorTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={tab === activeTab}
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
  if (!mode) return "等待中";
  const requestMs = metrics.request_ms;
  const stream = metrics.stream;
  const cacheHit = metrics.cache_hit;
  const parts = [String(mode)];
  if (typeof requestMs === "number") parts.push(`${(requestMs / 1000).toFixed(1)}s`);
  if (stream === true) parts.push("stream");
  if (cacheHit === true) parts.push("cache");
  return parts.join(" / ");
}
