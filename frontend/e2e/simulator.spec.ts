import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("group", { name: "可交互户型图" })).toBeVisible();
});

test("默认 2D 视图可推进仿真并切换到延迟加载的 3D 视图", async ({ page }) => {
  const twoDimensional = page.getByRole("button", { name: /2D/ });
  await expect(twoDimensional).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".home-plan-2d svg")).toBeVisible();

  const step = page.getByRole("button", { name: "单步仿真" });
  await expect(step).toBeEnabled();
  const stepResponse = page.waitForResponse((response) => (
    response.url().endsWith("/api/simulation/step") && response.request().method() === "POST"
  ));
  await step.click();
  expect((await stepResponse).ok()).toBe(true);
  await expect(page.getByText(/已推进 1 分钟仿真/)).toBeVisible();

  const threeDimensional = page.getByRole("button", { name: /3D/ });
  await threeDimensional.click();
  await expect(threeDimensional).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("canvas")).toBeVisible({ timeout: 10_000 });
});

test("关键房间与视图控件可通过键盘获得并暴露语义状态", async ({ page }) => {
  const room = page.getByRole("button", { name: "选择客厅" });
  await room.focus();
  await expect(room).toBeFocused();
  await room.press("Enter");

  const twoDimensional = page.getByRole("button", { name: /2D/ });
  const threeDimensional = page.getByRole("button", { name: /3D/ });
  await expect(twoDimensional).toHaveAttribute("aria-pressed", "true");
  await expect(threeDimensional).toHaveAttribute("aria-pressed", "false");
});

test("人物进入卫生间时将真实占用事件同步给后端", async ({ page }) => {
  const bathroomPresence = page.waitForResponse((response) => {
    if (!response.url().endsWith("/api/presence/current-room") || response.request().method() !== "PUT") {
      return false;
    }
    return response.request().postDataJSON().current_room_id === "bathroom";
  });
  for (let step = 0; step < 25; step += 1) await page.keyboard.press("d");
  for (let step = 0; step < 12; step += 1) await page.keyboard.press("w");

  const response = await bathroomPresence;
  expect(response.ok()).toBe(true);
  expect((await response.json()).state.rooms.filter((room: { occupancy: boolean }) => room.occupancy)).toEqual([
    expect.objectContaining({ room_id: "bathroom" }),
  ]);
});

test("页面刷新后保留后端已确认的所在房间", async ({ page }) => {
  const sessionId = await page.evaluate(() => localStorage.getItem("smart-home-resident-workspace-id"));
  expect(sessionId).toBeTruthy();
  await page.evaluate(async (residentId) => {
    const response = await fetch("http://127.0.0.1:8000/api/presence/current-room", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-Simulation-Session": residentId ?? "",
      },
      body: JSON.stringify({ current_room_id: "bathroom" }),
    });
    if (!response.ok) throw new Error(`presence setup failed: ${response.status}`);
  }, sessionId);

  await page.reload();
  await expect(page.getByText("W/A/S/D 移动“我”：当前在 卫生间")).toBeVisible();
  const occupiedRooms = await page.evaluate(async (residentId) => {
    const response = await fetch("http://127.0.0.1:8000/api/state", {
      headers: { "X-Simulation-Session": residentId ?? "" },
    });
    const state = await response.json();
    return state.rooms.filter((room: { occupancy: boolean }) => room.occupancy).map((room: { room_id: string }) => room.room_id);
  }, sessionId);
  expect(occupiedRooms).toEqual(["bathroom"]);
});

test("人员位置同步失败时回滚界面位置", async ({ page }) => {
  await page.route("**/api/presence/current-room", async (route) => {
    const payload = route.request().postDataJSON();
    if (payload.current_room_id === "bathroom") {
      await route.abort("connectionfailed");
      return;
    }
    await route.continue();
  });
  for (let step = 0; step < 25; step += 1) await page.keyboard.press("d");
  for (let step = 0; step < 12; step += 1) await page.keyboard.press("w");

  await expect(page.getByText(/网络连接失败|无法同步当前房间/)).toBeVisible();
  await expect(page.getByText("W/A/S/D 移动“我”：当前在 客厅")).toBeVisible();
});

test("默认交互页面没有 WCAG A/AA 自动化违规", async ({ page }) => {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
});

test("后端状态请求失败时向用户显示连接错误", async ({ page }) => {
  await page.route("**/api/state", (route) => route.abort("connectionfailed"));
  await page.reload();
  await expect(page.getByText(/无法连接后端服务/)).toBeVisible();
});

test("提交指令时展示中心编排的实时协作轨迹", async ({ page }) => {
  await page.getByLabel("指令输入").fill("打开客厅灯光");
  const streamResponse = page.waitForResponse((response) => (
    response.url().endsWith("/api/agent/command/stream") && response.request().method() === "POST"
  ));
  await page.getByRole("button", { name: "发送指令" }).click();
  expect((await streamResponse).ok()).toBe(true);
  await expect(page.getByRole("button", { name: "发送指令" })).toBeEnabled({ timeout: 20_000 });

  await page.getByRole("tab", { name: "A2A 对话" }).click();
  await expect(page.getByText("中心编排消息记录，不代表去中心化 A2A 协议。")).toBeVisible();
  await expect(page.getByText(/编排器 → 上下文 Agent/)).toBeVisible();
  await expect(page.getByText(/协作 Agent → 安全 Agent/)).toBeVisible();
  await expect(page.getByText(/反思 Agent → 编排器/)).toBeVisible();
});

test("私有知识库与持续自治循环可在界面启用并产生反思", async ({ page }) => {
  await page.getByText("家庭成员习惯与隐私设置", { exact: true }).click();
  await page.getByLabel("健康与安全约束").fill("怕风，睡眠时避免直吹");
  await page.getByLabel("睡眠与生活习惯").fill("夜间浅睡，23:00 入睡");
  const memoryResponse = page.waitForResponse((response) => (
    response.url().endsWith("/api/research/private-memory/attributes")
      && response.request().method() === "PUT"
  ));
  await page.getByRole("button", { name: "保存到私有知识库" }).click();
  expect((await memoryResponse).ok()).toBe(true);
  await expect(page.getByText(/结构化长期属性已保存/)).toBeVisible();
  await expect(page.getByRole("button", { name: "已保存到私有知识库" })).toBeDisabled();

  const temperature = page.locator("label").filter({ hasText: "偏好温度" }).locator("input");
  await temperature.fill("16");
  await page.getByRole("button", { name: "保存用户偏好" }).click();
  await expect(page.getByText(/用户偏好已更新/)).toBeVisible();

  const autonomousStart = page.waitForResponse(
    (response) => response.url().endsWith("/api/autonomy/start") && response.request().method() === "POST",
    { timeout: 15_000 },
  );
  const autonomyToggle = page.getByRole("checkbox", { name: "启用持续感知与自主决策" });
  await autonomyToggle.check();
  const response = await autonomousStart;
  expect(response.ok()).toBe(true);
  expect((await response.json()).architecture).toBe("backend_owned_autonomous_loop");
  await expect(page.getByText(/后端自治决策：/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/已反思 1 次/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("main")).toBeVisible();
  const restoredToggle = page.getByRole("checkbox", { name: "启用持续感知与自主决策" });
  await expect(restoredToggle).toBeChecked();
  await page.getByText("家庭成员习惯与隐私设置", { exact: true }).click();
  await expect(page.getByLabel("健康与安全约束")).toHaveValue("怕风，睡眠时避免直吹");
  await restoredToggle.uncheck();
  await expect(page.getByText("后端自治服务已停止。")).toBeVisible();
});
