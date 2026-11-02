# Graph Harness Demo Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use task-by-task TDD execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a demo audience inspect the versioned graph, completed node trace, and evidence boundary of one smart-home multi-agent command.

**Architecture:** Reuse `multi_agent_blackboard.workflow_graph` from the completed command response. Add a dedicated `Graph Harness` inspector tab in `AgentOutputPanel`; it renders declared nodes as an ordered control trace, shows the trace validator result, and labels the evidence as local software trace rather than autonomy or field validation.

**Tech Stack:** React, TypeScript, existing Vitest/Testing Library, existing CSS tokens.

## Global Constraints

- Preserve the `TaskRunner`, API contract, task fixtures, experiments, and current agent behavior.
- Use only trace data actually returned by `multi_agent_workflow_v1`; do not fabricate a running node or intervention result.
- Describe the system as center-orchestrated and graph-governed, not decentralized.
- Keep the panel responsive, keyboard reachable, and usable without animation.
- Do not commit, push, deploy, or change external systems.

---

### Task 1: Graph Harness inspector

**Files:**
- Modify: `frontend/src/components/AgentOutputPanel.tsx`
- Modify: `frontend/src/components/AgentOutputPanel.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: `output.multi_agent_blackboard.workflow_graph` with `version`, `nodes`, `edges`, and `trace_validation`.
- Produces: a `Graph Harness` tab labelled `Graph-Governed Agent Harness` and a valid/invalid/pending trace status.

- [x] **Step 1: Write the failing UI test**

```tsx
fireEvent.click(screen.getByRole("tab", { name: "Graph Harness" }));
expect(screen.getByRole("heading", { name: "Graph-Governed Agent Harness" })).toBeVisible();
expect(screen.getByText("multi_agent_workflow_v1")).toBeVisible();
expect(screen.getByText("轨迹校验通过")).toBeVisible();
expect(screen.getByText(/本次软件 trace/)).toBeVisible();
```

- [x] **Step 2: Run the test to verify it fails**

Run: `npm test -- --run src/components/AgentOutputPanel.test.tsx`

Expected: FAIL because the tab does not exist.

- [x] **Step 3: Implement the minimal panel**

```tsx
function GraphHarnessPanel({ graph, stages }: { graph: Record<string, unknown>; stages: AgentTraceStage[] }) {
  const validation = asRecord(graph.trace_validation);
  const valid = validation.valid === true;
  return <section aria-label="Graph-Governed Agent Harness">...</section>;
}
```

Render only declared graph nodes, mark a node completed only when its agent appears in the returned stage trace, and show the explicit evidence boundary.

- [x] **Step 4: Add scoped styles and run the UI test**

Run: `npm test -- --run src/components/AgentOutputPanel.test.tsx`

Expected: PASS for the graph tab and the existing reflection-degradation assertion.

### Task 2: Demo-quality validation

**Files:**
- Modify: `docs/improvement_backlog.md`

**Interfaces:**
- Consumes: Task 1 UI and test evidence.
- Produces: a concise evidence-led record of the display change and its research boundary.

- [x] **Step 1: Run frontend validation**

Run: `npm test -- --run src/components/AgentOutputPanel.test.tsx`; `npm run build`

Expected: PASS.

- [ ] **Step 2: Perform browser verification**

Start the local application through the repository entrypoint when necessary, submit one mock command, and verify the `Graph Harness` tab visibly shows the graph version and trace status. Record a screenshot only if the current local service starts successfully.

- [x] **Step 3: Record the evidence boundary**

Append a backlog entry stating that the view improves trace comprehension for a local software simulation and does not validate model quality, real-device safety, or real-home outcomes.
