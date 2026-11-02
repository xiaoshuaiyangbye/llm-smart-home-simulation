import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { AgentOutputPanel } from "./AgentOutputPanel";

test("labels a reflection persistence failure without misrepresenting the control result", () => {
  render(
    <AgentOutputPanel
      command="打开客厅灯"
      onCommandChange={vi.fn()}
      onSubmit={vi.fn().mockResolvedValue(undefined)}
      isLoading={false}
      liveStages={[]}
      output={{
        semantic_result: {},
        planning_result: {},
        execution_result: {},
        feedback_result: {},
        actions: [],
        multi_agent_blackboard: {
          stages: [
            {
              agent: "reflection_agent",
              recorded_at: "2026-07-15T10:00:00",
              output: { recorded: false, reason: "persistence_failed" },
            },
          ],
        },
      }}
    />,
  );

  fireEvent.click(screen.getByText("查看推理、协作与执行详情"));
  fireEvent.click(screen.getByRole("tab", { name: "A2A 对话" }));

  expect(screen.getByText("反思未持久化；控制结果保持成功，未更新经验。")).toBeVisible();
});

test("shows a graph-governed harness trace without overstating its evidence", () => {
  render(
    <AgentOutputPanel
      command="打开客厅灯"
      onCommandChange={vi.fn()}
      onSubmit={vi.fn().mockResolvedValue(undefined)}
      isLoading={false}
      liveStages={[]}
      output={{
        semantic_result: {},
        planning_result: {},
        execution_result: {},
        feedback_result: {},
        actions: [],
        multi_agent_blackboard: {
          stages: [
            { agent: "orchestrator", recorded_at: "2026-08-26T10:00:00", output: {} },
            { agent: "semantic_agent", recorded_at: "2026-08-26T10:00:01", output: {} },
            { agent: "execution_agent", recorded_at: "2026-08-26T10:00:02", output: {} },
          ],
          workflow_graph: {
            version: "multi_agent_workflow_v1",
            nodes: ["orchestrator", "semantic_agent", "execution_agent"],
            edges: [],
            trace_validation: { valid: true, violations: [] },
          },
        },
      }}
    />,
  );

  const inspectors = screen.getAllByText("查看推理、协作与执行详情");
  fireEvent.click(inspectors[inspectors.length - 1]);
  const harnessTabs = screen.getAllByRole("tab", { name: "Graph Harness" });
  fireEvent.click(harnessTabs[harnessTabs.length - 1]);

  expect(screen.getByRole("heading", { name: "Graph-Governed Agent Harness" })).toBeVisible();
  expect(screen.getByText("multi_agent_workflow_v1")).toBeVisible();
  expect(screen.getByText("轨迹校验通过")).toBeVisible();
  expect(screen.getByText(/本次软件 trace/)).toBeVisible();
  expect(screen.getByText("编排器")).toBeVisible();
  expect(screen.getByText("语义 Agent")).toBeVisible();
});
