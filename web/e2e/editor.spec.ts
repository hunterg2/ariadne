import { expect, test } from "@playwright/test";
import { LIBRARY, openLibrary, seed } from "./helpers";

async function total(request: Parameters<typeof seed>[0]) {
  const page = await (await request.get("/api/images?folder=" + encodeURIComponent(LIBRARY))).json();
  return page.total as number;
}

test.describe("image editor", () => {
  test.beforeAll(async ({ request }) => { await seed(request); });

  test("draws a stroke and saves a copy beside the original", async ({ page, request }) => {
    await openLibrary(page);
    const before = await total(request);
    await page.locator(".tile").nth(3).click();
    // the tool query opens the editor on the focused image, as the palette does
    await page.evaluate((folder) => { location.hash = "#/library?folder=" + encodeURIComponent(folder) + "&tool=edit"; }, LIBRARY);
    const editor = page.getByRole("dialog", { name: "Image editor" });
    await expect(editor).toBeVisible();
    const canvas = editor.locator("canvas");
    await expect(canvas).toBeVisible();
    const box = (await canvas.boundingBox())!;
    expect(box.width).toBeGreaterThan(50);

    // the marker is the default tool: one stroke across the middle
    await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.5, { steps: 12 });
    await page.mouse.up();
    await expect(editor.getByRole("button", { name: /^Undo/ })).toBeEnabled();

    await page.keyboard.press("Control+Enter");
    const warn = page.getByRole("button", { name: "Save anyway" });
    if (await warn.isVisible({ timeout: 2000 }).catch(() => false)) await warn.click();
    await expect(page.getByText(/^Saved /)).toBeVisible();
    await expect(editor).toBeHidden();
    await expect.poll(() => total(request)).toBe(before + 1);
  });
});
