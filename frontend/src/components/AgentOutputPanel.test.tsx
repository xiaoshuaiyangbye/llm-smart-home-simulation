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

  fireEvent.click(screen.getByRole("tab", { name: "A2A 对话" }));

  expect(screen.getByText("反思未持久化；控制结果保持成功，未更新经验。")).toBeVisible();
});
