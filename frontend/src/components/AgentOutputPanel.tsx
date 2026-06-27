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
  prompt: "Prompt",
  memory: "Memory",
  semantic: "Semantic",
  planning: "Planning",
  rag: "RAG",
  agents: "Agents",
  safety: "Safety",
  actions: "Actions",
  feedback: "Feedback",
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
        <label htmlFor="command">Natural language command</label>
        <textarea
          id="command"
          rows={5}
          value={command}
          onChange={(event) => onCommandChange(event.target.value)}
          onKeyDown={handleCommandKeyDown}
        />
        <button type="button" disabled={!canSubmit} onClick={onSubmit}>
          {isLoading ? "Running..." : "Submit task"}
        </button>
      </div>

      <div className="agent-process-panel">
        <div className="process-header">
          <h2>LLM multi-agent workflow</h2>
          <span>{formatLlmStatus(semantic.llm_mode, llmMetrics)}</span>
        </div>
        <div className="agent-flow">
          <FlowNode
            label="Perceive"
            active={Boolean(output)}
            detail={
              output
                ? `${String(getNested(promptPayload, "room_count") ?? "-")} rooms / ${String(
                    getNested(promptPayload, "device_count") ?? "-",
                  )} devices`
                : "waiting"
            }
          />
          <FlowNode
            label="RAG"
            active={ragMatches > 0}
            detail={ragMatches > 0 ? `${ragMatches} chunks retrieved` : "waiting"}
          />
          <FlowNode
            label="Memory"
            active={Boolean(semantic.memory_context)}
            detail={semantic.memory_context ? String(getNested(memoryContext, "day_summary") ?? "context loaded") : "waiting"}
          />
          <FlowNode
            label="Intent"
            active={Boolean(semantic.intent)}
            detail={
              semantic.intent
                ? `${String(semantic.intent)} / ${String(semantic.room)} / ${String(semantic.control_goal ?? "set_target")}`
                : "waiting"
            }
          />
          <FlowNode
            label="Plan"
            active={actions.length > 0}
            detail={actions.length > 0 ? `${actions.length} device actions` : "waiting"}
          />
          <FlowNode
            label="Safety"
            active={Object.keys(safetyReview).length > 0}
            detail={safetyIssues > 0 ? `${safetyIssues} findings` : Object.keys(safetyReview).length > 0 ? "passed" : "waiting"}
          />
          <FlowNode
            label="Execute"
            active={executedCount > 0}
            detail={executedCount > 0 ? `${executedCount} actions executed` : "waiting"}
          />
          <FlowNode
            label="Feedback"
            active={Boolean(output?.feedback_result)}
            detail={completed ? "target reached" : output ? "needs correction or convergence" : "waiting"}
          />
        </div>
      </div>

      <div className="agent-inspector">
        <div className="inspector-tabs" role="tablist" aria-label="Agent output inspector">
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
          {activeTab === "actions" && <span>{actions.length} actions</span>}
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
  return parts.join(" / ");
}
