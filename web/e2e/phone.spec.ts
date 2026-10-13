import { expect, test } from "@playwright/test";
import { openLibrary, seed } from "./helpers";

/* a phone: narrow, touch, and no hover */
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test.describe("phone layout", () => {
  test.beforeAll(async ({ request }) => { await seed(request); });

  test("tab bar, folder drawer, two or more columns, info sheet, swipe in the viewer", async ({ page }) => {
    await openLibrary(page);

    // the rail is a tab bar along the bottom
    const rail = (await page.locator(".rail").boundingBox())!;
    expect(rail.y).toBeGreaterThan(700);
    expect(rail.width).toBeGreaterThan(300);

    // the sidebar is a drawer: hidden until asked for, gone once a scope is picked
    await expect(page.locator(".side")).toHaveCount(0);
    await page.getByRole("button", { name: "Folders" }).click();
    await expect(page.locator(".side.drawer")).toBeVisible();
    await page.locator(".side.drawer .entry.all").click();
    await expect(page.locator(".side.drawer")).toHaveCount(0);
    await expect(page.locator(".bar .title h2")).toHaveText("Whole library");

    // tiles share rows and are phone-sized
    const tiles = page.locator(".tile");
    await expect(tiles.nth(1)).toBeVisible();
    const a = (await tiles.nth(0).boundingBox())!;
    const b = (await tiles.nth(1).boundingBox())!;
    expect(Math.abs(a.y - b.y)).toBeLessThan(2);
    expect(a.width).toBeLessThan(200);

    // tapping a tile brings the info sheet up; its close button puts it away
    await tiles.first().tap();
    const sheet = page.locator(".info-sheet");
    await expect(sheet).toBeVisible();
    await sheet.getByRole("button", { name: "Close info" }).click();
    await expect(sheet).toHaveCount(0);

    // the viewer: a swipe to the left moves to the next image
    await page.keyboard.press("Enter");
    const viewer = page.getByRole("dialog", { name: "Image viewer" });
    await expect(viewer).toBeVisible();
    await expect(viewer.locator(".pos")).toContainText("1 /");
    const stage = (await viewer.locator(".stage").boundingBox())!;
    const y = stage.y + stage.height / 2;
    await page.mouse.move(stage.x + stage.width * 0.8, y);
    await page.mouse.down();
    await page.mouse.move(stage.x + stage.width * 0.2, y, { steps: 6 });
    await page.mouse.up();
    await expect(viewer.locator(".pos")).toContainText("2 /");
    await expect(viewer.locator(".strip")).toBeHidden();
  });
});
