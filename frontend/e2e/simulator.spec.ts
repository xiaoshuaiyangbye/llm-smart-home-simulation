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
  await expect(page.locator("canvas")).toBeVisible();
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

test("默认交互页面没有 WCAG A/AA 自动化违规", async ({ page }) => {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
});

test("后端状态请求失败时向用户显示连接错误", async ({ page }) => {
  await page.route("**/api/state", (route) => route.abort("connectionfailed"));
  await page.reload();
  await expect(page.getByText(/无法连接后端服务/)).toBeVisible();
});
