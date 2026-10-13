import { expect, test } from "@playwright/test";
import { seed } from "./helpers";

test.describe("command palette", () => {
  test.beforeAll(async ({ request }) => { await seed(request); });

  test("opens with Ctrl+K and jumps to a screen", async ({ page }) => {
    await page.goto("/#/library");
    await expect(page.locator(".rail")).toBeVisible();
    await page.keyboard.press("Control+k");
    const input = page.getByPlaceholder(/Go to a screen/);
    await expect(input).toBeVisible();
    await input.fill("settings");
    await expect(page.locator(".item.on")).toContainText("Settings");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#\/settings/);
    await expect(page.getByRole("heading", { name: "Settings", level: 2 })).toBeVisible();
    await expect(input).toBeHidden();
  });
});
