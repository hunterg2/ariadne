/* Shared by the specs: where the sample library is, how to seed the
   server (idempotent, so every spec can call it) and how to open the
   Library on it. */
import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { join } from "node:path";

export const APP_DIR = process.env.ARIADNE_E2E_DIR!;
export const LIBRARY = join(APP_DIR, "library");
export const SAMPLE_COUNT = 16;

/* Register the sample folder and index it. */
export async function seed(request: APIRequestContext) {
  await request.post("/api/history", { data: { folder: LIBRARY } });
  await request.post("/api/images/scan", { data: { folder: LIBRARY, wait: true } });
}

export async function openLibrary(page: Page) {
  await page.goto("/#/library?folder=" + encodeURIComponent(LIBRARY));
  await expect(page.locator(".tile").first()).toBeVisible();
}
