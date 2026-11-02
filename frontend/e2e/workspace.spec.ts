import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("人物键盘移动响应按钮焦点，阻挡外墙和隔墙并允许门洞通行", async ({ page }) => {
  await page.goto("/#overview");
  await expect(page.getByRole("button", { name: "选择客厅", exact: true })).toHaveAttribute("aria-disabled", "false");
  const scene = page.locator(".scene-panel");
  const initialX = Number(await scene.getAttribute("data-avatar-x"));
  await page.getByRole("button", { name: "复位", exact: true }).click();
  await page.keyboard.press("a");
  await expect.poll(async () => Number(await scene.getAttribute("data-avatar-x"))).toBeLessThan(initialX);
  for (let i = 0; i < 40; i++) await page.keyboard.press("Shift+A");
  expect(Number(await scene.getAttribute("data-avatar-x"))).toBeGreaterThan(-6.45);
  for (let i = 0; i < 20; i++) await page.keyboard.press("w");
  expect(Number(await scene.getAttribute("data-avatar-z"))).toBeGreaterThan(-1.3);
  await page.getByRole("button", { name: "选择客厅", exact: true }).click();
  for (let i = 0; i < 5; i++) await page.keyboard.press("d");
  for (let i = 0; i < 8; i++) await page.keyboard.press("w");
  await expect(page.locator(".overview-metrics strong").first()).toHaveText("卧室");
});

test("首页状态卡片在桌面和手机均完整容纳标签与数值", async ({ page }) => {
  await page.goto("/#overview");
  await expect(page.locator(".overview-metrics strong").first()).not.toHaveText("—");
  for (const width of [2048, 1440, 1024, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    const visible = await page.locator(".overview-metrics > span").evaluateAll((cards) => cards.every((card) => {
      const bounds = card.getBoundingClientRect();
      return [...card.children].every((child) => {
        const rect = child.getBoundingClientRect();
        return rect.top >= bounds.top && rect.bottom <= bounds.bottom && rect.left >= bounds.left && rect.right <= bounds.right;
      });
    }));
    expect(visible, `width=${width}`).toBe(true);
  }
});

test("初始状态读取完成前不接受会被覆盖的房间选择", async ({ page }) => {
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/state", async (route) => { await gate; await route.continue(); });
  await page.goto("/");
  const bathroom = page.getByRole("button", { name: "选择卫生间", exact: true });
  await expect(bathroom).toHaveAttribute("aria-disabled", "true");
  await bathroom.dispatchEvent("click");
  release();
  await expect(bathroom).toHaveAttribute("aria-disabled", "false");
  const response = page.waitForResponse((r) => r.url().endsWith("/api/presence/current-room") && r.request().method() === "PUT");
  await bathroom.click();
  expect((await response).ok()).toBe(true);
  await expect(page.locator(".overview-metrics strong").first()).toHaveText("卫生间");
});

test("功能页面隔离、草稿保留与浏览器后退", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "功能页面" });
  await expect(page.getByRole("heading", { name: "我的住宅", exact: true })).toBeVisible();
  await expect(page.getByLabel("指令输入")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "开始全屋实验" })).not.toBeVisible();
  await nav.getByRole("button", { name: "家庭助手", exact: true }).click();
  await page.getByLabel("指令输入").fill("把书房的灯调到适合阅读");
  await nav.getByRole("button", { name: "设备控制", exact: true }).click();
  await page.getByLabel("选择要控制的房间").selectOption("bedroom");
  await expect(page.getByLabel("卧室 灯光亮度")).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("指令输入")).toHaveValue("把书房的灯调到适合阅读");
  await expect(nav.getByRole("button", { name: "家庭助手", exact: true })).toHaveAttribute("aria-current", "page");
});

test("物理实验按设置、结果、空间分组并完成真实引擎运行", async ({ page }) => {
  await page.goto("/#experiments");
  await expect(page.getByText("引擎可用", { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("img", { name: "全屋九空间热区边界" })).not.toBeVisible();
  await page.getByLabel("有人活动的房间").selectOption("bedroom");
  await page.getByRole("navigation", { name: "功能页面" }).getByRole("button", { name: "住宅总览", exact: true }).click();
  await page.getByRole("navigation", { name: "功能页面" }).getByRole("button", { name: "物理实验", exact: true }).click();
  await expect(page.getByLabel("有人活动的房间")).toHaveValue("bedroom");
  await page.getByRole("button", { name: "开始全屋实验" }).click();
  await expect(page.getByRole("button", { name: "实验结果", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("全屋结果 · 9 个空间", { exact: true })).toBeVisible({ timeout: 60000 });
  await expect(page.locator(".room-results tbody tr")).toHaveCount(9);
  await page.getByLabel("查看空间").selectOption("bedroom");
  await expect(page.getByRole("img", { name: "室温时间序列" })).toBeVisible();
  await expect(page.getByRole("button", { name: "summary.json ↓", exact: true })).not.toBeVisible();
  await page.getByText("下载结果与复现文件", { exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "summary.json ↓", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("summary.json");
  await page.getByRole("button", { name: "空间与假设", exact: true }).click();
  await expect(page.getByRole("img", { name: "全屋九空间热区边界" }).locator("polygon")).toHaveCount(9);
  await expect(page.getByText(/窗帘尚无物理执行器/)).toBeVisible();
});

test("六个页面在手机宽度均可导航且没有自动化无障碍违规", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const labels = ["住宅总览", "设备控制", "家庭助手", "自动运行", "物理实验", "状态与趋势"];
  for (const label of labels) {
    const nav = page.getByRole("navigation", { name: "功能页面" });
    await nav.getByRole("button", { name: label, exact: true }).click();
    await expect(nav.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-current", "page");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations, label).toEqual([]);
  }
});
