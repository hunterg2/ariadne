import { expect, test } from "@playwright/test";
import { LIBRARY, seed } from "./helpers";

test.describe("settings", () => {
  test.beforeAll(async ({ request }) => { await seed(request); });

  test("watches a folder and sets, then removes, the PIN", async ({ page, request }) => {
    await page.goto("/#/settings");
    await expect(page.getByRole("heading", { name: "Settings", level: 2 })).toBeVisible();

    // watched folders: type the path into the browse dialog
    await page.getByRole("button", { name: /Watch a folder/ }).click();
    const sheet = page.locator(".sheet");
    await expect(sheet.locator(".list .dir").first()).toBeVisible();     // the drive or root listing is in
    const typed = sheet.getByPlaceholder(/Type or paste a path/);
    await typed.fill(LIBRARY);
    await typed.press("Enter");                                           // open it, so the dialog holds that path
    await expect(sheet.locator(".list")).toContainText("No subfolders");
    await sheet.getByRole("button", { name: "Watch this folder" }).click();
    await expect(page.locator(".auto .mono")).toContainText("library");
    const settings = await (await request.get("/api/settings")).json();
    expect(settings.auto_folders.some((f: { path: string }) => f.path === LIBRARY)).toBe(true);

    // the PIN other devices enter
    await page.locator("#pin").fill("2468");
    await page.getByRole("button", { name: "Set PIN" }).click();
    await expect(page.getByText("A PIN is set.")).toBeVisible();
    expect((await (await request.get("/api/auth/status")).json()).has_pin).toBe(true);
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "Remove", exact: true }).click();
    await expect(page.getByText("No PIN yet.")).toBeVisible();
    expect((await (await request.get("/api/auth/status")).json()).has_pin).toBe(false);
  });
});
