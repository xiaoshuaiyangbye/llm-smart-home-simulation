import { useEffect, useMemo, useState, type KeyboardEvent } from "react";

import type { AgentOutput, AgentTraceStage } from "../types/state";
import { DecisionTracePanel } from "./DecisionTracePanel";

interface AgentOutputPanelProps {
  command: string;
  onCommandChange: (command: string) => void;
  onSubmit: () => Promise<void>;
  output: AgentOutput | null;
  liveStages: AgentTraceStage[];
  isLoading: boolean;
}

type InspectorTab =
  | "prompt"
  | "memory"
  | "semantic"
  | "planning"
  | "rag"
  | "harness"
  | "agents"
  | "a2a"
  | "safety"
  | "actions"
  | "feedback";

const TAB_LABELS: Record<InspectorTab, string> = {
  prompt: "提示词",
  memory: "记忆",
  semantic: "语义",
  planning: "规划",
  rag: "RAG",
  harness: "Graph Harness",
  agents: "协同",
  a2a: "A2A 对话",
  safety: "安全",
  actions: "动作",
  feedback: "反馈",
};

export function AgentOutputPanel({
  command,
  onCommandChange,
  onSubmit,
  output,
  liveStages,
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
  const traceBlackboard = liveStages.length > 0 ? { stages: liveStages } : blackboard;
  const a2aMessages = useMemo(() => buildA2AMessages(traceBlackboard), [traceBlackboard]);
  const workflowGraph = asRecord(asRecord(blackboard).workflow_graph);
  const workflowStages = Array.isArray(asRecord(blackboard).stages) ? (asRecord(blackboard).stages as AgentTraceStage[]) : [];
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
  const safetyIssuesValue = safetyReview.issues;
  const safetyIssues = Array.isArray(safetyIssuesValue) ? safetyIssuesValue.length : 0;
  const canSubmit = command.trim().length > 0 && !isLoading;

  useEffect(() => {
    if (isLoading && liveStages.length === 0) setActiveTab("a2a");
  }, [isLoading, liveStages.length]);

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
    if (activeTab === "harness") return workflowGraph;
    if (activeTab === "agents") return blackboard;
    if (activeTab === "a2a") return a2aMessages;
    if (activeTab === "safety") return Object.keys(safetyReview).length > 0 ? safetyReview : { status: "waiting" };
    if (activeTab === "actions") return actions;
    return output?.feedback_result ?? { status: "waiting" };
  }, [
    activeTab,
    actions,
    a2aMessages,
    blackboard,
    memoryContext,
    output,
    promptPayload,
    promptTemplate,
    ragContext,
    safetyReview,
    semanticForDisplay,
    workflowGraph,
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
        <span className="section-kicker">家庭助手</span>
        <h2>想让家做什么？</h2>
        <label htmlFor="command">指令输入</label>
        <textarea
          id="command"
          rows={3}
          value={command}
          onChange={(event) => onCommandChange(event.target.value)}
          onKeyDown={handleCommandKeyDown}
          placeholder="例如：今晚十一点后卧室保持安静，温度不要低于 26 度"
        />
        <button type="button" disabled={!canSubmit} onClick={onSubmit}>
          {isLoading ? "执行中..." : "发送指令"}
        </button>
      </div>

      <div className="agent-process-panel">
        <div className="process-header">
          <div>
            <span className="section-kicker">执行过程</span>
            <h2>助手正在这样处理</h2>
          </div>
          <span>{formatLlmStatus(semantic.llm_mode, llmMetrics)}</span>
        </div>
        <div className="agent-flow">
          <FlowNode label="理解需求" active={Boolean(semantic.intent)} detail={semantic.intent ? "已识别房间与控制需求" : "等待一条指令"} />
          <FlowNode label="拟定动作" active={actions.length > 0} detail={actions.length > 0 ? `${actions.length} 个设备动作` : "等待规划"} />
          <FlowNode label="检查风险" active={Object.keys(safetyReview).length > 0} detail={safetyIssues > 0 ? `${safetyIssues} 个风险需处理` : Object.keys(safetyReview).length > 0 ? "检查已通过" : "等待检查"} />
          <FlowNode label="执行与反馈" active={executedCount > 0} detail={completed ? "反馈报告目标已达成" : executedCount > 0 ? `已执行 ${executedCount} 个动作` : "等待执行"} />
        </div>
      </div>

      <details className="agent-inspector"><summary>查看推理、协作与执行详情</summary>
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
          <h3>{activeTab === "a2a" ? "A2A 风格消息轨迹" : activeTab === "harness" ? "Graph-Governed Agent Harness" : `${TAB_LABELS[activeTab]} JSON`}</h3>
          {activeTab === "actions" && <span>{actions.length} 个动作</span>}
        </div>
        {activeTab === "a2a" ? (
          <A2ADialog messages={a2aMessages} isLive={isLoading} />
        ) : activeTab === "harness" ? (
          <>
            <GraphHarnessPanel graph={workflowGraph} stages={workflowStages} />
            <DecisionTracePanel trace={planning.decision_trace} />
          </>
        ) : (
          <pre>{JSON.stringify(inspectorValue, null, 2)}</pre>
        )}
      </details>
    </section>
  );
}

interface A2AMessage {
  id: string;
  sender: string;
  recipient: string;
  summary: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

function A2ADialog({ messages, isLive }: { messages: A2AMessage[]; isLive: boolean }) {
  if (messages.length === 0) {
    return <p className="a2a-empty">等待一次任务执行后生成协作消息轨迹。</p>;
  }

  return (
    <div className="a2a-dialog" aria-label="中心编排的 A2A 风格消息轨迹">
      <p className="a2a-disclaimer">中心编排消息记录，不代表去中心化 A2A 协议。</p>
      {isLive && <p className="a2a-live" role="status">正在实时接收 agent 消息…</p>}
      {messages.map((message) => (
        <details className="a2a-message" key={message.id}>
          <summary>
            <span className="a2a-route">{message.sender} → {message.recipient}</span>
            <span>{message.summary}</span>
          </summary>
          <div className="a2a-message-meta">{message.timestamp || "当前任务"}</div>
          <pre>{JSON.stringify(message.payload, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function GraphHarnessPanel({ graph, stages }: { graph: Record<string, unknown>; stages: AgentTraceStage[] }) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes.filter((node): node is string => typeof node === "string") : [];
  const observed = new Set(stages.map((stage) => stage.agent));
  const validation = asRecord(graph.trace_validation);
  const isValid = validation.valid === true;
  const isInvalid = validation.valid === false;
  const version = typeof graph.version === "string" ? graph.version : "等待完整命令结果";

  return (
    <section className="graph-harness" aria-label="Graph-Governed Agent Harness">
      <div className="graph-harness-summary">
        <div>
          <span className="section-kicker">中心化图约束控制</span>
          <strong>{version}</strong>
        </div>
        <span className={isValid ? "graph-status valid" : isInvalid ? "graph-status invalid" : "graph-status pending"}>
          {isValid ? "轨迹校验通过" : isInvalid ? "轨迹校验异常" : "等待校验"}
        </span>
      </div>
      {nodes.length > 0 ? (
        <ol className="graph-node-track" aria-label="本次声明工作流节点">
          {nodes.map((node) => (
            <li key={node} className={observed.has(node) ? "observed" : "declared"}>
              <i aria-hidden="true" />
              <span>{displayAgentName(node)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="graph-empty">发送一次命令后，可查看该次执行的版本化图与节点轨迹。</p>
      )}
      <p className="graph-boundary">本次软件 trace 用于展示中心化编排与可审计路径；不代表模型优劣、真实设备安全或真实家庭效果。</p>
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

function buildA2AMessages(blackboard: unknown): A2AMessage[] {
  const stages = asRecord(blackboard).stages;
  if (!Array.isArray(stages)) return [];

  return stages.flatMap((stage, index) => {
    const stageRecord = asRecord(stage);
    const sender = typeof stageRecord.agent === "string" ? stageRecord.agent : "unknown_agent";
    const payload = asRecord(stageRecord.output);
    if (!sender || Object.keys(payload).length === 0) return [];
    return [{
      id: `${sender}-${index}`,
      sender: displayAgentName(sender),
      recipient: displayAgentName(nextRecipient(sender)),
      summary: summarizeAgentMessage(sender, payload),
      timestamp: typeof stageRecord.recorded_at === "string" ? stageRecord.recorded_at : "",
      payload,
    }];
  });
}

function nextRecipient(agent: string): string {
  const recipients: Record<string, string> = {
    orchestrator: "context_agent",
    context_agent: "semantic_agent",
    knowledge_agent: "semantic_agent",
    semantic_agent: "planning_agent",
    comfort_agent: "collaboration_agent",
    energy_agent: "collaboration_agent",
    planning_agent: "collaboration_agent",
    collaboration_agent: "safety_agent",
    safety_agent: "critic_agent",
    critic_agent: "execution_agent",
    execution_agent: "feedback_agent",
    feedback_agent: "reflection_agent",
    reflection_agent: "orchestrator",
  };
  return recipients[agent] ?? "orchestrator";
}

function displayAgentName(agent: string): string {
  const names: Record<string, string> = {
    orchestrator: "编排器",
    context_agent: "上下文 Agent",
    knowledge_agent: "知识 Agent",
    semantic_agent: "语义 Agent",
    comfort_agent: "舒适度 Agent",
    energy_agent: "能耗 Agent",
    planning_agent: "规划 Agent",
    collaboration_agent: "协作 Agent",
    safety_agent: "安全 Agent",
    critic_agent: "批评 Agent",
    execution_agent: "执行 Agent",
    feedback_agent: "反馈 Agent",
    reflection_agent: "反思 Agent",
  };
  return names[agent] ?? agent;
}

function summarizeAgentMessage(agent: string, payload: Record<string, unknown>): string {
  if (agent === "orchestrator") {
    return `已加载 ${String(payload.room_count ?? "-")} 个房间与 ${String(payload.device_count ?? "-")} 台设备`;
  }
  if (agent === "semantic_agent") {
    return `识别意图：${String(payload.intent ?? "未知")}；房间：${String(payload.room ?? "未知")}`;
  }
  if (agent === "knowledge_agent") {
    return `检索到 ${String(getNested(payload.rag_context, "match_count") ?? 0)} 条知识匹配`;
  }
  if (agent === "comfort_agent") {
    return `完成 ${String(payload.target_room_count ?? 0)} 个目标房间的舒适度审查`;
  }
  if (agent === "energy_agent") {
    return `发现 ${Array.isArray(payload.waste_candidates) ? payload.waste_candidates.length : 0} 个潜在能耗项`;
  }
  if (agent === "planning_agent") {
    return `生成 ${Array.isArray(payload.actions) ? payload.actions.length : 0} 个候选动作`;
  }
  if (agent === "collaboration_agent") {
    return payload.phase === "critic_revision" ? "处理批评 Agent 的修订请求" : "整合专长 Agent 的计划建议";
  }
  if (agent === "safety_agent") {
    return `安全审查：${Array.isArray(payload.issues) ? payload.issues.length : 0} 个风险，${payload.actions_changed ? "已调整动作" : "无需调整"}`;
  }
  if (agent === "critic_agent") {
    return `批评审查：${payload.approved ? "通过" : "需要关注"}，${Array.isArray(payload.revision_requests) ? payload.revision_requests.length : 0} 个修订请求`;
  }
  if (agent === "execution_agent") {
    return `已执行 ${String(payload.executed_count ?? 0)} 个动作`;
  }
  if (agent === "feedback_agent") {
    return payload.completed ? "目标已达成" : "反馈要求继续校正或收敛";
  }
  if (agent === "reflection_agent") {
    if (payload.recorded === false && payload.reason === "persistence_failed") {
      return "反思未持久化；控制结果保持成功，未更新经验。";
    }
    return `形成经验：${String(payload.conclusion ?? "已记录本次执行结果")}`;
  }
  return "已记录阶段输出";
}
