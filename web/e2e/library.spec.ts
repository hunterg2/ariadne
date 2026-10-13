import { expect, test, type APIRequestContext } from "@playwright/test";
import { LIBRARY, openLibrary, seed, SAMPLE_COUNT } from "./helpers";

/* what the index says, so the spec does not care what earlier specs added */
async function count(request: APIRequestContext, q = "") {
  const res = await request.get(`/api/images?folder=${encodeURIComponent(LIBRARY)}&q=${encodeURIComponent(q)}`);
  return (await res.json()).total as number;
}

test.describe("library", () => {
  test.beforeAll(async ({ request }) => { await seed(request); });

  test("shows the folder, rates with a key, filters by stars and searches prompts", async ({ page, request }) => {
    await openLibrary(page);
    const tiles = page.locator(".tile");
    const total = await count(request);
    expect(total).toBeGreaterThanOrEqual(SAMPLE_COUNT);
    await expect(page.locator(".bar .title")).toContainText(`${total} images`);
    // the grid is virtual: it draws what fits, never nothing
    expect(await tiles.count()).toBeGreaterThanOrEqual(8);

    // click a tile, press 5: the star row on that tile lights up
    await tiles.first().click();
    await page.keyboard.press("5");
    await expect(tiles.first().locator(".star.lit")).toHaveCount(5);

    // the rating filter leaves only that one
    await page.locator(".chip", { hasText: "Rating" }).click();
    await page.locator(".menu-item", { hasText: "5+ stars" }).click();
    await expect(page.locator(".bar .title")).toContainText("1 image");
    await expect(tiles).toHaveCount(1);
    await page.locator(".filters").getByRole("button", { name: "Clear" }).click();   // the selection bar has one too
    await expect(page.locator(".bar .title")).toContainText(`${total} images`);

    // a prompt search through the query language
    const foxes = await count(request, 'prompt: ...red fox...');   // ... means contains; a bare phrase must match whole
    expect(foxes).toBeGreaterThanOrEqual(2);
    const search = page.locator(".search input");
    await search.fill('prompt: ...red fox...');
    await search.press("Enter");
    await expect(page.locator(".bar .title")).toContainText(`${foxes} images`);
    await expect(tiles).toHaveCount(foxes);

    // the helper under the box offers fields and, for tag:, nothing yet
    await search.fill("");
    await search.pressSequentially("mo");
    await expect(page.locator(".help .item .l").first()).toHaveText("model:");
  });
});
