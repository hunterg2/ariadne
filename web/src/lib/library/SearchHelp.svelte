<script lang="ts">
  /* The dropdown under the search box: the fields and their syntax, then
     values for the field being typed (tags, models, samplers...), recent
     searches when the box is empty, and the full reference behind "?".
     Arrows move, Enter or Tab inserts at the caret, Escape closes. The
     parent passes keydown events through handleKey() first. */
  import * as api from "../api";
  import Icon from "../ui/Icon.svelte";
  import Kbd from "../ui/Kbd.svelte";
  import { library } from "../stores/library.svelte";
  import { ui, patchUi } from "../stores/settings.svelte";

  interface Props { input: HTMLInputElement | undefined }
  let { input }: Props = $props();

  type Kind = "prompt" | "text" | "number" | "tag" | "facet" | "choice";
  interface Field { key: string; kind: Kind; hint: string; example: string; choices?: string[] }
  const FIELDS: Field[] = [
    { key: "prompt", kind: "prompt", hint: "words in the prompt", example: 'prompt: "red dress" & night' },
    { key: "negative", kind: "prompt", hint: "words in the negative prompt", example: "negative: ...blurry..." },
    { key: "tag", kind: "tag", hint: "one of your tags (#tag is a shortcut)", example: "tag: portrait" },
    { key: "model", kind: "facet", hint: "checkpoint", example: "model: ...xl..." },
    { key: "lora", kind: "facet", hint: "a LoRA that was used", example: "lora: ...detail..." },
    { key: "sampler", kind: "facet", hint: "sampler", example: "sampler: euler a" },
    { key: "scheduler", kind: "facet", hint: "scheduler", example: "scheduler: karras" },
    { key: "steps", kind: "number", hint: "steps, exact or a range", example: "steps: 20...30" },
    { key: "cfg", kind: "number", hint: "CFG scale", example: "cfg: 7" },
    { key: "seed", kind: "number", hint: "seed", example: "seed: 12345" },
    { key: "stars", kind: "number", hint: "rating, 0 to 5", example: "stars: 4...5" },
    { key: "width", kind: "number", hint: "pixels", example: "width: 1024..." },
    { key: "height", kind: "number", hint: "pixels", example: "height: ...768" },
    { key: "kind", kind: "choice", hint: "where it came from", example: "kind: photo", choices: ["generated", "photo", "other"] },
    { key: "camera", kind: "facet", hint: "camera model", example: "camera: ...canon..." },
    { key: "lens", kind: "facet", hint: "lens", example: "lens: ...50mm..." },
    { key: "iso", kind: "number", hint: "ISO", example: "iso: 100...400" },
    { key: "software", kind: "facet", hint: "software that wrote the file", example: "software: ...lightroom..." },
    { key: "title", kind: "text", hint: "file name", example: "title: portrait..." },
    { key: "folder", kind: "text", hint: "folder name", example: "folder: renders" },
    { key: "label", kind: "text", hint: "colour label", example: "label: red" },
    { key: "collection", kind: "text", hint: "collection name", example: 'collection: "best of"' },
    { key: "rejected", kind: "choice", hint: "rejected or not", example: "rejected: yes", choices: ["yes", "no"] },
  ];
  const OPERATORS: [string, string][] = [
    ['"two words"', "a phrase"], ["...word...", "contains"], ["word...", "starts with"], ["...word", "ends with"],
    ["a & b", "both"], ["a || b", "either"], ["20...30", "a range"], ["20...", "at least"], [";", "another field"],
  ];

  interface Item { label: string; insert: string; hint?: string; count?: number; whole?: boolean }

  let open = $state(false);
  let reference = $state(false);
  let highlight = $state(-1);
  let text = $state("");
  let caret = $state(0);
  let facetItems: Item[] = $state([]);
  let panel: HTMLDivElement | undefined = $state();
  let facetKey = "";
  let timer: ReturnType<typeof setTimeout> | null = null;

  /* where the caret sits: which field, the value typed so far, and where
     that value starts (what an insert replaces) */
  const ctx = $derived.by(() => {
    const before = text.slice(0, caret);
    const segStart = before.lastIndexOf(";") + 1;
    const seg = before.slice(segStart);
    const colon = seg.indexOf(":");
    if (colon < 0) {
      const lead = seg.length - seg.trimStart().length;
      const typed = seg.trimStart();
      if (typed.startsWith("#")) return { mode: "value" as const, field: FIELDS[2], needle: typed.slice(1), start: segStart + lead, shorthand: true };
      return { mode: "field" as const, field: null as Field | null, needle: typed.toLowerCase(), start: segStart + lead, shorthand: false };
    }
    const key = seg.slice(0, colon).trim().toLowerCase();
    const field = FIELDS.find((f) => f.key === key) ?? null;
    const rest = seg.slice(colon + 1);
    const amp = rest.lastIndexOf("&");
    const bar = rest.lastIndexOf("||");
    const cut = Math.max(amp >= 0 ? amp + 1 : 0, bar >= 0 ? bar + 2 : 0);
    const after = rest.slice(cut);
    const lead = after.length - after.trimStart().length;
    let needle = after.trimStart();
    if (needle.startsWith('"')) needle = needle.slice(1);
    return { mode: "value" as const, field, needle, start: segStart + colon + 1 + cut + lead, shorthand: false };
  });

  const recents = $derived(ui("search_history") ?? []);
  const items = $derived.by((): Item[] => {
    if (!open) return [];
    const c = ctx;
    if (c.mode === "field") {
      if (!text.trim() && recents.length) return recents.map((r) => ({ label: r, insert: r, hint: "recent", whole: true }));
      return FIELDS.filter((f) => !c.needle || f.key.startsWith(c.needle)).map((f) => ({ label: f.key + ":", insert: f.key + ": ", hint: f.hint }));
    }
    const f = c.field;
    if (!f) return [];
    const n = c.needle.toLowerCase();
    if (f.kind === "tag") return library.tags.filter((t) => !n || t.tag.toLowerCase().includes(n)).slice(0, 30).map((t) => ({ label: t.tag, insert: t.tag, count: t.count }));
    if (f.kind === "choice") return (f.choices ?? []).filter((v) => !n || v.startsWith(n)).map((v) => ({ label: v, insert: v }));
    if (f.kind === "facet") return facetItems;
    return [];
  });
  const tips = $derived.by((): [string, string][] | null => {
    const c = ctx;
    if (c.mode !== "value" || !c.field) return null;
    if (c.field.kind === "prompt" || c.field.kind === "text") return OPERATORS.slice(0, 6);
    if (c.field.kind === "number") return [["20", "exactly"], ["20...30", "between"], ["20...", "at least"], ["...30", "at most"]];
    return null;
  });
  const heading = $derived.by(() => {
    const c = ctx;
    if (c.mode === "field") return !text.trim() && recents.length ? "Recent searches" : "Fields";
    return c.field ? `${c.field.key}: ${c.field.hint}` : "Unknown field";
  });

  /* values for model/sampler/lora... come from the index, debounced */
  $effect(() => {
    const c = ctx;
    if (!open || c.mode !== "value" || !c.field || c.field.kind !== "facet") return;
    const key = c.field.key + "\u0000" + c.needle.toLowerCase();
    if (key === facetKey) return;
    facetKey = key;
    if (timer) clearTimeout(timer);
    const field = c.field.key, needle = c.needle;
    timer = setTimeout(async () => {
      try {
        const res = await api.facets(field, needle, 20);
        if (facetKey === key) facetItems = res.values.map((v) => ({ label: v.value, insert: v.value, count: v.count }));
      } catch { /* the list just stays as it was */ }
    }, 150);
  });

  function sync() {
    if (!input) return;
    text = input.value;
    caret = input.selectionStart ?? input.value.length;
  }
  $effect(() => {
    const el = input;
    if (!el) return;
    const onInput = () => { sync(); open = true; highlight = -1; };
    const onFocus = () => { sync(); open = true; };
    const onBlur = () => { open = false; };
    const onMove = () => sync();
    el.addEventListener("input", onInput);
    el.addEventListener("focus", onFocus);
    el.addEventListener("blur", onBlur);
    el.addEventListener("click", onMove);
    el.addEventListener("keyup", onMove);
    return () => {
      el.removeEventListener("input", onInput);
      el.removeEventListener("focus", onFocus);
      el.removeEventListener("blur", onBlur);
      el.removeEventListener("click", onMove);
      el.removeEventListener("keyup", onMove);
    };
  });
  $effect(() => {
    highlight;
    panel?.querySelector(".item.hl")?.scrollIntoView({ block: "nearest" });
  });
  /* the reference closes on a click anywhere else */
  $effect(() => {
    if (!reference) return;
    const onDown = (e: MouseEvent) => { if (panel && !panel.contains(e.target as Node)) reference = false; };
    const id = setTimeout(() => document.addEventListener("mousedown", onDown), 0);
    return () => { clearTimeout(id); document.removeEventListener("mousedown", onDown); };
  });

  export function pick(item: Item) {
    if (!input) return;
    const c = ctx;
    let next: string;
    let pos: number;
    if (item.whole) {
      next = item.insert;
      pos = next.length;
    } else {
      let ins = item.insert;
      const needsQuote = /[\s"&|;:]/.test(ins);
      if (c.mode === "value" && c.field) {
        if (c.shorthand) ins = needsQuote ? `tag: "${ins.replace(/"/g, "")}"` : "#" + ins;
        else if (needsQuote && c.field.kind !== "choice") ins = `"${ins.replace(/"/g, "")}"`;
      }
      next = text.slice(0, c.start) + ins + text.slice(caret);
      pos = c.start + ins.length;
    }
    input.value = next;
    input.setSelectionRange(pos, pos);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    highlight = -1;
    if (item.whole) open = false;
  }

  /* true when the key was used here and must not reach the input */
  export function handleKey(e: KeyboardEvent): boolean {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!open) { sync(); open = true; }
      const n = items.length;
      if (!n) return false;
      highlight = e.key === "ArrowDown" ? (highlight + 1) % n : (highlight - 1 + n) % n;
      return true;
    }
    if ((e.key === "Enter" || e.key === "Tab") && open && highlight >= 0 && items[highlight]) { pick(items[highlight]); return true; }
    if (e.key === "Tab" && open && items.length === 1 && !items[0].whole) { pick(items[0]); return true; }
    if (e.key === "Escape") {
      if (reference) { reference = false; return true; }
      if (open) { open = false; return true; }
    }
    return false;
  }
  export function close() { open = false; }
  export function toggleReference() { reference = !reference; open = false; }
</script>

{#if open && (items.length || tips)}
  <div class="help" bind:this={panel} role="listbox" aria-label="Search suggestions">
    <div class="title">
      <span>{heading}</span>
      {#if ctx.mode === "field" && !text.trim() && recents.length}
        <button type="button" class="link" onmousedown={(e) => { e.preventDefault(); patchUi({ search_history: [] }); }}>clear</button>
      {/if}
    </div>
    {#if tips}
      <div class="tips">{#each tips as [code, what] (code)}<span><code>{code}</code> {what}</span>{/each}</div>
    {/if}
    {#if items.length}
      <div class="items">
        {#each items as it, i (it.label)}
          <button type="button" class="item" class:hl={i === highlight} role="option" aria-selected={i === highlight}
            onmousedown={(e) => { e.preventDefault(); pick(it); }} onmouseenter={() => (highlight = i)}>
            <span class="l">{it.label}</span>
            {#if it.hint}<span class="h">{it.hint}</span>{/if}
            {#if it.count != null}<span class="c">{it.count}</span>{/if}
          </button>
        {/each}
      </div>
    {/if}
    <div class="foot"><Kbd combo="arrowdown" /><Kbd combo="arrowup" /> move <Kbd combo="enter" /> insert <Kbd combo="escape" /> close <span class="spacer"></span><code>;</code> starts another field</div>
  </div>
{/if}

{#if reference}
  <div class="help ref" bind:this={panel} role="dialog" aria-label="Search syntax">
    <div class="title"><span>Search syntax</span><button type="button" class="link" onclick={() => (reference = false)}>close</button></div>
    <p class="hint">Fields are separated by <code>;</code> and all of them must match. Text matches exactly unless you use <code>...</code>. <code>#tag</code> is short for <code>tag: tag</code>.</p>
    <div class="cols">
      <div>
        <h5>Fields</h5>
        {#each FIELDS as f (f.key)}<div class="r"><code>{f.example}</code><span class="h">{f.hint}</span></div>{/each}
      </div>
      <div>
        <h5>Operators</h5>
        {#each OPERATORS as [code, what] (code)}<div class="r"><code>{code}</code><span class="h">{what}</span></div>{/each}
        <h5>Examples</h5>
        <div class="r"><code>prompt: "red dress" & night; stars: 4...</code></div>
        <div class="r"><code>#portrait; kind: photo; camera: ...sony...</code></div>
        <div class="r"><code>model: ...xl...; steps: 20...30; rejected: no</code></div>
      </div>
    </div>
  </div>
{/if}

<style>
  .help { position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 30; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--r-sm); box-shadow: var(--shadow); display: flex; flex-direction: column; max-height: 360px; font-family: var(--font); color: var(--text); }
  .title { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; font-size: 11.5px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); }
  .link { border: 0; background: transparent; color: var(--accent); font: inherit; cursor: pointer; text-transform: none; letter-spacing: 0; }
  .tips { display: flex; flex-wrap: wrap; gap: 4px 14px; padding: 6px 10px; font-size: 12px; color: var(--muted); border-bottom: 1px solid var(--border); }
  code { font-family: var(--mono); font-size: 11.5px; color: var(--text); background: var(--surface-2); padding: 0 4px; border-radius: 3px; }
  .items { overflow: auto; padding: 4px; }
  .item { display: flex; align-items: center; gap: 8px; width: 100%; padding: 5px 8px; border: 0; background: transparent; color: var(--text); font: inherit; font-size: 12.5px; text-align: left; border-radius: var(--r-sm); cursor: pointer; }
  .item.hl { background: var(--accent-soft); }
  .item .l { font-family: var(--mono); }
  .item .h, .r .h { color: var(--muted); font-size: 11.5px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item .c { color: var(--faint); font-size: 11px; font-variant-numeric: tabular-nums; }
  .foot { display: flex; align-items: center; gap: 4px; padding: 5px 10px; font-size: 11px; color: var(--faint); border-top: 1px solid var(--border); }
  .ref { max-height: 70vh; overflow: auto; padding-bottom: var(--sp3); }
  .ref .hint { padding: 6px 10px 0; margin: 0; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp3); padding: 6px 10px; }
  h5 { margin: 6px 0 4px; font-size: 11.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  .r { display: flex; align-items: baseline; gap: 8px; padding: 2px 0; font-size: 12px; }
</style>
