/* Keyboard shortcuts. Every frequent action has a key; Settings, Keyboard
   lists them and lets the user rebind any of them. */

import { settings } from "./stores/settings.svelte";

export interface Action {
  id: string;
  label: string;
  keys: string[];          // default combos, e.g. "1", "shift+x", "ctrl+k"
  scope: Scope;
}

export type Scope = "global" | "library" | "viewer" | "editor";

export const ACTIONS: Action[] = [
  { id: "star1", label: "Rate 1 star", keys: ["1"], scope: "library" },
  { id: "star2", label: "Rate 2 stars", keys: ["2"], scope: "library" },
  { id: "star3", label: "Rate 3 stars", keys: ["3"], scope: "library" },
  { id: "star4", label: "Rate 4 stars", keys: ["4"], scope: "library" },
  { id: "star5", label: "Rate 5 stars", keys: ["5"], scope: "library" },
  { id: "star0", label: "Clear rating", keys: ["0"], scope: "library" },
  { id: "reject", label: "Toggle reject", keys: ["x"], scope: "library" },
  { id: "tag", label: "Tag", keys: ["t"], scope: "library" },
  { id: "select", label: "Toggle selection", keys: ["s"], scope: "library" },
  { id: "info", label: "Info panel", keys: ["space"], scope: "library" },
  { id: "open", label: "Open viewer", keys: ["enter"], scope: "library" },
  { id: "cull", label: "Cull mode", keys: ["f"], scope: "library" },
  { id: "trash", label: "Trash", keys: ["delete", "backspace"], scope: "library" },
  { id: "reveal", label: "Reveal in file manager", keys: ["r"], scope: "library" },
  { id: "prev", label: "Previous image", keys: ["arrowleft", "a"], scope: "library" },
  { id: "next", label: "Next image", keys: ["arrowright", "d"], scope: "library" },
  { id: "up", label: "Row up", keys: ["arrowup", "w"], scope: "library" },
  { id: "down", label: "Row down", keys: ["arrowdown"], scope: "library" },
  { id: "selectAll", label: "Select all", keys: ["ctrl+a"], scope: "library" },
  { id: "escape", label: "Close / clear", keys: ["escape"], scope: "global" },
  { id: "palette", label: "Command palette", keys: ["ctrl+k"], scope: "global" },
  { id: "search", label: "Focus search", keys: ["/"], scope: "global" },
  { id: "goLibrary", label: "Library", keys: ["alt+1"], scope: "global" },
  { id: "goTools", label: "Tools", keys: ["alt+2"], scope: "global" },
  { id: "goSettings", label: "Settings", keys: ["alt+3"], scope: "global" },
  { id: "write", label: "Save the copy", keys: ["ctrl+enter"], scope: "editor" },
  { id: "undo", label: "Undo", keys: ["ctrl+z"], scope: "editor" },
  { id: "redo", label: "Redo", keys: ["ctrl+shift+z", "ctrl+y"], scope: "editor" },
  { id: "zoomIn", label: "Zoom in", keys: ["+", "="], scope: "editor" },
  { id: "zoomOut", label: "Zoom out", keys: ["-"], scope: "editor" },
  { id: "zoomFit", label: "Fit", keys: ["0"], scope: "editor" },
  { id: "zoomActual", label: "Actual size", keys: ["1"], scope: "editor" },
];

export function keysFor(id: string): string[] {
  const override = settings.data.ui?.hotkeys?.[id];
  if (Array.isArray(override) && override.length) return override.filter(Boolean);
  return ACTIONS.find((a) => a.id === id)?.keys ?? [];
}

export function comboOf(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey) parts.push("shift");
  let key = e.key.toLowerCase();
  if (key === " ") key = "space";
  parts.push(key);
  return parts.join("+");
}

export function prettyCombo(combo: string): string {
  return combo
    .split("+")
    .map((p) => ({ ctrl: "Ctrl", alt: "Alt", shift: "Shift", space: "Space", escape: "Esc",
                   arrowleft: "←", arrowright: "→", arrowup: "↑", arrowdown: "↓",
                   delete: "Del", backspace: "⌫", enter: "Enter" }[p] ?? p.toUpperCase()))
    .join(" + ");
}

/* Return false to let the key fall through to the next layer; anything else
   (including a promise from an async handler) counts as handled. */
type Handler = (e: KeyboardEvent) => unknown;

const layers: { scope: Scope; handlers: Map<string, Handler> }[] = [];

/* Push a layer of handlers for a scope; returns a function that removes it.
   The topmost layer that handles an action wins, so a viewer over the
   library takes the keys while it is open. */
export function useHotkeys(scope: Scope, handlers: Record<string, Handler>) {
  const layer = { scope, handlers: new Map(Object.entries(handlers)) };
  layers.push(layer);
  return () => {
    const i = layers.indexOf(layer);
    if (i >= 0) layers.splice(i, 1);
  };
}

/* A full-screen editor takes every library and viewer key while it is open,
   so a stray "1" edits the picture rather than rating it. */
export function useModalHotkeys(handlers: Record<string, Handler>) {
  const swallow: Record<string, Handler> = {};
  for (const a of ACTIONS) if (a.scope !== "global") swallow[a.id] = () => undefined;
  return useHotkeys("editor", { ...swallow, ...handlers });
}

function isTyping(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

window.addEventListener("keydown", (e) => {
  const combo = comboOf(e);
  const typing = isTyping(e);
  for (let i = layers.length - 1; i >= 0; i--) {
    const layer = layers[i];
    for (const [id, handler] of layer.handlers) {
      if (!keysFor(id).includes(combo)) continue;
      // while typing, only modified combos and Escape get through
      if (typing && !combo.includes("+") && combo !== "escape") continue;
      const result = handler(e);
      if (result !== false) {
        e.preventDefault();
        return;
      }
    }
  }
});
