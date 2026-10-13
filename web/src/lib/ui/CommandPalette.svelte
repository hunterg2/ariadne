<script lang="ts">
  /* Ctrl+K: type a few letters, pick a screen, tool, folder or collection.
     Everything in here is reachable by other means; this is the fast lane. */
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  import Kbd from "./Kbd.svelte";
  import { library } from "../stores/library.svelte";
  import { settings, patchUi, ui } from "../stores/settings.svelte";
  import { go } from "../router.svelte";
  import { keysFor } from "../hotkeys";
  import { basename } from "../format";

  interface Command { id: string; label: string; group: string; icon: string; hint?: string; keys?: string; run: () => void }
  interface Props { open: boolean; onclose: () => void; children?: Snippet }
  let { open, onclose }: Props = $props();

  let query = $state("");
  let cursor = $state(0);
  let input: HTMLInputElement | undefined = $state();

  const commands = $derived.by((): Command[] => {
    const out: Command[] = [];
    const sections: [string, string, string, string][] = [
      ["library", "Library", "grid", "goLibrary"], ["tools", "Tools", "tool", "goTools"],
      ["settings", "Settings", "settings", "goSettings"],
    ];
    for (const [id, label, icon, key] of sections) {
      out.push({ id: "go:" + id, label, group: "Go to", icon, keys: keysFor(key)[0], run: () => go("/" + id) });
    }
    out.push({ id: "theme", label: `Theme: ${ui("theme")} (switch)`, group: "Do", icon: "palette", run: () => { const t = ui("theme"); patchUi({ theme: t === "dark" ? "light" : t === "light" ? "system" : "dark" }); } });
    out.push({ id: "inspector", label: ui("inspector_open") ? "Hide the info panel" : "Show the info panel", group: "Do", icon: "panelRight", keys: keysFor("info")[0], run: () => patchUi({ inspector_open: !ui("inspector_open") }) });
    const tools: [string, string, string, string?][] = [
      ["dupes", "Find duplicates", "dupes"], ["prompts", "Unique prompts in this folder", "hash"],
      ["compare", "Compare the selection", "compare", "needs 2+ selected"], ["autotag", "Suggest tags for the selection", "sparkles"],
      ["edit", "Edit the focused image", "edit"],
    ];
    for (const [tool, label, icon, hint] of tools) {
      out.push({ id: "tool:" + tool, label, group: "Tools", icon, hint, run: () => go("/library", { tool }) });
    }
    out.push({ id: "tool:trash", label: "Open the trash", group: "Tools", icon: "trash", run: () => go("/tools") });
    out.push({ id: "all", label: "Everything in the library", group: "Folders", icon: "globe", run: () => { go("/library"); library.open({ type: "all" }); } });
    for (const path of library.folderPaths()) {
      const item = library.findFolder(path);
      out.push({ id: "folder:" + path, label: item?.alias || basename(path), group: "Folders", icon: "folder", hint: path, run: () => go("/library", { folder: path }) });
    }
    for (const c of library.collections) {
      out.push({ id: "collection:" + c.id, label: c.name, group: "Collections", icon: c.kind === "smart" ? "wand" : "layers", run: () => go("/library", { collection: c.id }) });
    }
    return out;
  });

  /* Letters in order, anywhere in the label, earlier and tighter matches first. */
  function score(c: Command, q: string): number {
    if (!q) return 1;
    const hay = (c.label + " " + c.group + " " + (c.hint ?? "")).toLowerCase();
    if (hay.includes(q)) return 100 - hay.indexOf(q);
    let i = 0, last = -1, gaps = 0;
    for (const ch of q) {
      const at = hay.indexOf(ch, last + 1);
      if (at < 0) return 0;
      if (last >= 0) gaps += at - last - 1;
      last = at; i++;
    }
    return 50 - Math.min(40, gaps);
  }
  const matches = $derived.by(() => {
    const q = query.trim().toLowerCase();
    return commands.map((c) => ({ c, s: score(c, q) })).filter((m) => m.s > 0).sort((a, b) => b.s - a.s).map((m) => m.c).slice(0, 40);
  });

  $effect(() => {
    if (open) { query = ""; cursor = 0; setTimeout(() => input?.focus(), 0); }
  });
  $effect(() => { matches; cursor = 0; });

  function run(c: Command) {
    onclose();
    c.run();
  }
  function onkeydown(e: KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onclose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); cursor = Math.min(matches.length - 1, cursor + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); cursor = Math.max(0, cursor - 1); }
    else if (e.key === "Enter") { e.preventDefault(); const c = matches[cursor]; if (c) run(c); }
    else e.stopPropagation();
  }
  let lastGroup = "";
</script>

{#if open}
  <div class="overlay" role="presentation" onmousedown={(e) => { if (e.target === e.currentTarget) onclose(); }}>
    <div class="palette" role="dialog" aria-modal="true" aria-label="Command palette" onkeydown={onkeydown}>
      <div class="search">
        <Icon name="command" size={16} />
        <input bind:this={input} bind:value={query} placeholder="Go to a screen, open a tool, jump to a folder…" spellcheck="false" />
        <Kbd combo="escape" />
      </div>
      <div class="list" role="listbox">
        {#each matches as c, i (c.id)}
          {@const showGroup = i === 0 || matches[i - 1].group !== c.group}
          {#if showGroup}<div class="group">{c.group}</div>{/if}
          <button class="item" class:on={i === cursor} role="option" aria-selected={i === cursor} onmouseenter={() => (cursor = i)} onclick={() => run(c)}>
            <Icon name={c.icon} size={15} />
            <span class="label">{c.label}</span>
            {#if c.hint}<span class="hint">{c.hint}</span>{/if}
            {#if c.keys}<Kbd combo={c.keys} />{/if}
          </button>
        {:else}
          <p class="hint pad">Nothing matches "{query}".</p>
        {/each}
      </div>
      <div class="foot hint"><Kbd combo="arrowup" /><Kbd combo="arrowdown" /> move · <Kbd combo="enter" /> run · {settings.loaded ? `${commands.length} commands` : ""}</div>
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; z-index: 210; background: var(--scrim); display: flex; align-items: flex-start; justify-content: center; padding-top: 12vh; animation: fade var(--dur) var(--ease); }
  .palette { width: min(640px, calc(100vw - 32px)); max-height: 70vh; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); box-shadow: var(--shadow-2); overflow: hidden; animation: rise .18s var(--ease); }
  .search { display: flex; align-items: center; gap: var(--sp2); padding: var(--sp3) var(--sp4); border-bottom: 1px solid var(--border); color: var(--muted); }
  .search input { flex: 1; border: 0; background: transparent; font: inherit; font-size: 15px; color: var(--text); outline: none; padding: 4px 0; }
  .list { overflow: auto; padding: var(--sp2); flex: 1; min-height: 0; }
  .group { font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--faint); padding: var(--sp2) var(--sp2) 2px; }
  .item { display: flex; align-items: center; gap: var(--sp3); width: 100%; border: 0; background: transparent; color: var(--text); font: inherit; text-align: left; padding: 7px var(--sp2); border-radius: var(--r-sm); cursor: pointer; }
  .item.on { background: var(--accent-soft); }
  .item .label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item .hint { max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; }
  .foot { display: flex; align-items: center; gap: 6px; padding: var(--sp2) var(--sp4); border-top: 1px solid var(--border); font-size: 11.5px; }
  .pad { padding: var(--sp4); }
  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
  @keyframes rise { from { transform: translateY(-6px); opacity: 0; } to { transform: none; opacity: 1; } }
</style>
