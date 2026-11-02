import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { LifeSimulationPanel } from "./LifeSimulationPanel";

test("未运行时显示结果占位，不将缺少实验结果呈现为零收益", () => {
  render(<LifeSimulationPanel status={null} isLoading={false} canStart={false} onStart={vi.fn()} onStop={vi.fn()} onBackToToday={vi.fn()} />);
  expect(screen.getByText("开始生活模拟后，这里会显示模拟能耗、舒适度和完成情况。")).toBeVisible();
  expect(screen.queryByText("模拟节能率")).not.toBeInTheDocument();
  expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
});
