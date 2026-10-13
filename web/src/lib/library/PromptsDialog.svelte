<script lang="ts">
  /* Every distinct prompt in the open folder, with counts. "Show" pins the
     grid to one prompt through the search language. */
  import * as api from "../api";
  import Modal from "../ui/Modal.svelte";
  import Button from "../ui/Button.svelte";
  import { library } from "../stores/library.svelte";
  import { toast, reportError } from "../stores/toasts.svelte";
  import { basename, count } from "../format";

  interface Props { open: boolean; folder: string; onclose: () => void }
  let { open, folder, onclose }: Props = $props();

  let prompts: { text: string; count: number; newest: number }[] = $state([]);
  let search = $state("");
  let sort = $state<"count" | "recent" | "alpha">("count");
  let expanded = $state(new Set<string>());

  async function load() {
    try { prompts = (await api.uniquePrompts(folder, library.isRecursive(folder))).prompts; } catch (e) { reportError(e); }
  }
  $effect(() => { if (open && folder) { search = ""; load(); } });

  const rows = $derived.by(() => {
    const needle = search.trim().toLowerCase();
    const list = prompts.filter((p) => !needle || p.text.toLowerCase().includes(needle));
    return [...list].sort(sort === "alpha" ? (a, b) => a.text.localeCompare(b.text)
      : sort === "recent" ? (a, b) => b.newest - a.newest : (a, b) => b.count - a.count);
  });
  const totalImages = $derived(prompts.reduce((n, p) => n + p.count, 0));

  function show(text: string) {
    const clean = text.replace(/"/g, "");
    library.setFilters({ q: text ? `prompt: "${clean}"` : "" });
    onclose();
  }
  function copy(text: string) {
    navigator.clipboard.writeText(text).then(() => toast("Prompt copied."), () => toast("Copy failed.", { error: true }));
  }
  function copyAll() {
    const text = rows.filter((p) => p.text).map((p) => `[${p.count}] ${p.text}`).join("\n\n");
    if (!text) { toast("Nothing to copy."); return; }
    navigator.clipboard.writeText(text).then(() => toast(`Copied ${count(rows.length)} prompts.`));
  }
  function toggle(text: string) {
    const next = new Set(expanded);
    if (next.has(text)) next.delete(text); else next.add(text);
    expanded = next;
  }
</script>

<Modal {open} {onclose} title={`${count(prompts.length)} unique prompt${prompts.length === 1 ? "" : "s"} across ${count(totalImages)} images in ${basename(folder)}`} width={820} tall>
  <div class="stack full">
    <div class="row">
      <input bind:value={search} placeholder="Find a prompt" />
      <select bind:value={sort}><option value="count">Most used</option><option value="recent">Most recent</option><option value="alpha">A to Z</option></select>
      <Button size="sm" variant="ghost" icon="copy" onclick={copyAll}>Copy all</Button>
    </div>
    <div class="list">
      {#each rows as p (p.text)}
        <div class="prow">
          <span class="pcount" title={`${p.count} image${p.count === 1 ? "" : "s"}`}>{p.count}</span>
          <button class="ptext" class:none={!p.text} class:open={expanded.has(p.text)} onclick={() => toggle(p.text)} title="Click to expand">{p.text || "(no prompt recorded)"}</button>
          <span class="pbtns">
            <Button size="sm" onclick={() => show(p.text)}>Show</Button>
            <Button size="sm" variant="ghost" icon="copy" square title="Copy" disabled={!p.text} onclick={() => copy(p.text)} />
          </span>
        </div>
      {:else}
        <p class="hint">{search ? "No prompt matches that." : "No prompts found in this folder."}</p>
      {/each}
    </div>
  </div>
  {#snippet actions()}<Button onclick={onclose}>Close</Button>{/snippet}
</Modal>

<style>
  .full { height: 100%; }
  .row input { flex: 1; }
  .list { flex: 1; overflow: auto; display: flex; flex-direction: column; gap: 4px; }
  .prow { display: flex; align-items: flex-start; gap: var(--sp2); padding: 6px 8px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface-2); }
  .pcount { flex: none; min-width: 28px; text-align: center; font-weight: 700; font-size: 12px; padding: 2px 6px; border-radius: var(--r-pill); background: var(--accent-soft); color: var(--accent); }
  .ptext { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--text); font: inherit; font-size: 12.5px; text-align: left; cursor: pointer; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; white-space: pre-wrap; }
  .ptext.open { -webkit-line-clamp: unset; }
  .ptext.none { color: var(--faint); font-style: italic; }
  .pbtns { display: flex; gap: 4px; flex: none; }
</style>
