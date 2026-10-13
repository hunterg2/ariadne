import * as api from "../api";
import { reportError } from "./toasts.svelte";

export type Theme = "dark" | "light" | "system";

export const UI_DEFAULTS = {
  theme: "system" as Theme,
  grid_size: 220,
  layout: "square" as "square" | "natural",
  sort: "date_desc",
  density: "comfortable" as "comfortable" | "compact",
  stars_always: false,
  inspector_open: true,
  sidebar_width: 240,
  hotkeys: {} as Record<string, string[]>,
  search_history: [] as string[],     // the last searches, newest first
};

/* remember a search for the helper's "recent" list */
export function rememberSearch(q: string) {
  const text = q.trim();
  if (!text) return;
  const rest = (ui("search_history") ?? []).filter((x) => x !== text);
  patchUi({ search_history: [text, ...rest].slice(0, 10) });
}

export const settings = $state({
  loaded: false,
  data: {} as api.Settings,
});

export function ui<K extends keyof typeof UI_DEFAULTS>(key: K): (typeof UI_DEFAULTS)[K] {
  const value = settings.data.ui?.[key];
  return (value === undefined || value === null ? UI_DEFAULTS[key] : value) as (typeof UI_DEFAULTS)[K];
}

export function applyTheme(theme: Theme = ui("theme")) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

export async function loadSettings() {
  try {
    settings.data = await api.getSettings();
    settings.data.ui = { ...UI_DEFAULTS, ...(settings.data.ui ?? {}) };
    settings.loaded = true;
    applyTheme();
  } catch (e) {
    reportError(e, "Could not load settings.");
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

/* Writes go through here so a burst of slider moves becomes one request. */
export function patchUi(patch: Partial<typeof UI_DEFAULTS>) {
  settings.data.ui = { ...settings.data.ui, ...patch };
  if ("theme" in patch) applyTheme(patch.theme);
  scheduleSave();
}

export function patchSettings(patch: Record<string, unknown>) {
  Object.assign(settings.data, patch);
  scheduleSave();
}

export function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(flushSettings, 400);
}

export async function flushSettings() {
  saveTimer = null;
  try {
    await api.saveSettings($state.snapshot(settings.data) as api.Settings);
  } catch (e) {
    reportError(e, "Could not save settings.");
  }
}
