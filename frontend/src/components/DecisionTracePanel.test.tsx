import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { DecisionTracePanel } from "./DecisionTracePanel";
import savedBundle from "../../public/decision-demos/evidence.json";

const action = (brightness: number) => ({ entity_id: "light.living_room", action: "turn_on", parameters: { brightness_pct: brightness }, reason: "住户明确要求" });
const state = (brightness: number) => ({ devices: [{ entity_id: "light.living_room", name: "客厅灯", device_type: "light", is_on: true, brightness_pct: brightness }] });
const trace = {
  schema_version: "decision_trace_v1", semantic_mode: "mock", evidence_class: "observed_software_simulation", boundary: "Observed software only.",
  events: [
    { event_id: "review-1", stage: "safety_agent", before_actions: [action(100)], after_actions: [action(70)], actions_changed: true, before_state: null, after_state: null, duration_ms: 2.4, details: { issues: ["限制过高亮度"] } },
    { event_id: "execution-2", stage: "execution_agent", before_actions: [action(70)], after_actions: [action(70)], actions_changed: false, before_state: state(0), after_state: state(70), duration_ms: 4.5, details: { executed_count: 1 } },
  ],
};
const bundle = {
  schema_version: "decision_demo_bundle_v1", generated_at: "2026-09-07T10:00:00Z",
  examples: [
    { id: "stale-snapshot", title: "环境变化后拒绝过期计划", description: "计划期间住户离开房间。", trace, verification: { passed: true, checks: [] }, provenance: {} },
    { id: "confirmed-feedback", title: "住户确认经验", description: "观察显式反馈何时成为规划上下文。", trace: { ...trace, events: [{ ...trace.events[0], stage: "user_feedback", before_actions: [], after_actions: [], actions_changed: false, details: { confirmed_after: true, sample_count: 3 } }] }, verification: { passed: true, checks: [] }, provenance: {} },
    { id: "conflicting-knowledge", title: "冲突知识下的安全审查", description: "观察检索建议与安全限制的冲突。", trace, verification: { passed: true, checks: [] }, provenance: {} },
  ],
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => bundle }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("compares actual action parameters and switches stages to show device changes", async () => {
  render(<DecisionTracePanel trace={trace} />);
  expect(within(screen.getByRole("region", { name: "原动作1 个" })).getByText("亮度：100%" )).toBeVisible();
  expect(within(screen.getByRole("region", { name: "修改后动作1 个" })).getByText("亮度：70%" )).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /2.*执行/ }));
  expect(screen.getByRole("heading", { name: "执行" })).toBeVisible();
  expect(screen.getAllByText("动作未改动").length).toBeGreaterThan(0);
  const changes = screen.getByRole("table", { name: "设备状态变化" });
  expect(within(changes).getByText("客厅灯")).toBeVisible();
  expect(within(changes).getByText("0%")).toBeVisible();
  expect(within(changes).getByText("70%")).toBeVisible();
  await screen.findByRole("option", { name: "住户确认经验" });
});

test("supports keyboard stage navigation and selecting historical examples without execution", async () => {
  render(<DecisionTracePanel trace={trace} />);
  const first = screen.getByRole("button", { name: /1.*安全审查/ });
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowRight" });
  expect(screen.getByRole("button", { name: /2.*执行/ })).toHaveFocus();
  expect(screen.getByRole("heading", { name: "执行" })).toBeVisible();
  await screen.findByRole("option", { name: "住户确认经验" });
  fireEvent.change(screen.getByLabelText("回放来源"), { target: { value: "confirmed-feedback" } });
  expect(screen.getByRole("heading", { name: "住户反馈" })).toBeVisible();
  expect(screen.getByText("观察显式反馈何时成为规划上下文。")).toBeVisible();
  expect(screen.getByText(/历史回放，不会执行设备动作/)).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith("/decision-demos/evidence.json", expect.objectContaining({ signal: expect.any(AbortSignal) }));
});

test("does not trust a supplied change flag or passed marker", async () => {
  const deceptive = { ...trace, verification: { passed: true }, events: [{ ...trace.events[0], after_actions: [action(100)], actions_changed: true }] };
  render(<DecisionTracePanel trace={deceptive} />);
  expect(screen.getAllByText("动作未改动").length).toBeGreaterThan(0);
  expect(screen.getByText(/变更标记与动作内容不一致/)).toBeVisible();
  expect(screen.queryByText("验证通过")).not.toBeInTheDocument();
  await screen.findByRole("option", { name: "住户确认经验" });
});

test("handles malformed live trace and malformed demo bundle without crashing", async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ ...bundle, examples: [null] }) } as Response);
  render(<DecisionTracePanel trace={{ ...trace, events: [null] }} />);
  expect(screen.getByText(/当前轨迹格式不完整/)).toBeVisible();
  expect(await screen.findByText(/演示记录格式不完整/)).toBeVisible();
  expect(screen.getByRole("button", { name: "导出当前轨迹" })).toBeDisabled();
});

test("preserves live inspection when historical records fail to load", async () => {
  vi.mocked(fetch).mockRejectedValue(new Error("offline"));
  render(<DecisionTracePanel trace={trace} />);
  expect(await screen.findByText(/演示记录加载失败/)).toBeVisible();
  expect(screen.getByRole("heading", { name: "安全审查" })).toBeVisible();
});

test("handles an empty trace and missing state without claiming unchanged devices", async () => {
  const view = render(<DecisionTracePanel trace={{ ...trace, events: [] }} />);
  expect(screen.getByText(/这份记录没有可回放的阶段/)).toBeVisible();
  view.rerender(<DecisionTracePanel trace={trace} />);
  expect(screen.getByText(/本阶段未同时记录前后设备快照/)).toBeVisible();
  await screen.findByRole("option", { name: "住户确认经验" });
});

test("exports the selected historical trace instead of the current live result", async () => {
  const createObjectURL = vi.fn().mockReturnValue("blob:decision-trace");
  const revokeObjectURL = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<DecisionTracePanel trace={trace} />);
  await screen.findByRole("option", { name: "住户确认经验" });
  fireEvent.change(screen.getByLabelText("回放来源"), { target: { value: "confirmed-feedback" } });
  fireEvent.click(screen.getByRole("button", { name: "导出当前轨迹" }));
  const blob = createObjectURL.mock.calls[0][0] as Blob;
  const exported = await new Promise<string>((resolve) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob); });
  expect(JSON.parse(exported).events[0].stage).toBe("user_feedback");
  expect(click).toHaveBeenCalledOnce();
});

test("imports saved JSON as an unverified replay and rejects invalid device snapshots", async () => {
  render(<DecisionTracePanel trace={null} />);
  const file = new File([JSON.stringify(trace)], "saved.json", { type: "application/json" });
  fireEvent.change(screen.getByLabelText("导入轨迹 JSON"), { target: { files: [file] } });
  expect(await screen.findByText(/已导入 saved.json/)).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("已导入 saved.json；仅完成格式检查，未复核来源与结果。");
  const bad = new File([JSON.stringify({ ...trace, events: [{ ...trace.events[0], before_state: { devices: [null] } }] })], "invalid.json");
  fireEvent.change(screen.getByLabelText("导入轨迹 JSON"), { target: { files: [bad] } });
  await waitFor(() => expect(screen.getByText(/导入失败：轨迹结构不完整/)).toBeVisible());
  expect(screen.getByRole("heading", { name: "安全审查" })).toBeVisible();
});

test("loads the generated demo bundle and labels the actual state change and commit guard", async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => savedBundle } as Response);
  render(<DecisionTracePanel trace={null} />);
  await screen.findByRole("option", { name: savedBundle.examples[0].title });
  fireEvent.change(screen.getByLabelText("回放来源"), { target: { value: "stale-snapshot" } });
  fireEvent.click(screen.getByRole("button", { name: /2.*环境变化/ }));
  expect(screen.getByRole("heading", { name: "环境变化" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /3.*提交前校验/ }));
  expect(screen.getByRole("heading", { name: "提交前校验" })).toBeVisible();
  expect(screen.getByText("快照已过期，需要重新规划")).toBeVisible();
  expect(screen.getByText("提交校验结果")).toBeVisible();
  expect(screen.getByText(/本记录在拒绝处结束/)).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
});
