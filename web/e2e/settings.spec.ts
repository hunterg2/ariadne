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

  test("drafts a bug report as a prefilled GitHub issue", async ({ page }) => {
    await page.goto("/#/settings");
    // the new tab would be github.com; catch the address instead of opening it
    await page.evaluate(() => {
      (window as any).__opened = [] as string[];
      window.open = ((url: string | URL) => { (window as any).__opened.push(String(url)); return window; }) as typeof window.open;
    });
    await page.getByRole("button", { name: "Report a bug" }).click();
    const sheet = page.locator(".sheet");
    await sheet.locator("#bug-summary").fill("The grid froze after a sort");
    await sheet.locator("#bug-steps").fill("Sorted by name, then scrolled");
    const preview = sheet.locator("#bug-preview");
    await expect(preview).toContainText("The grid froze after a sort");
    await expect(preview).toContainText("Sorted by name, then scrolled");
    await expect(preview).toContainText(/Images indexed: \d+/);
    await sheet.getByRole("button", { name: "Open on GitHub" }).click();
    const opened = await page.evaluate(() => (window as any).__opened as string[]);
    expect(opened).toHaveLength(1);
    const url = new URL(opened[0]);
    expect(url.origin + url.pathname).toBe("https://github.com/hunterg2/ariadne/issues/new");
    expect(url.searchParams.get("title")).toBe("The grid froze after a sort");
    expect(url.searchParams.get("body")).toContain("Sorted by name, then scrolled");
    expect(url.searchParams.get("labels")).toBe("bug");
    await expect(sheet).toHaveCount(0);                                   // the dialog closed
  });
});
