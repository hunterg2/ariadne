<script lang="ts">
  /* Suggest tags for a set of images, one event per image, review, apply. */
  import * as api from "../api";
  import Modal from "../ui/Modal.svelte";
  import Button from "../ui/Button.svelte";
  import Thumb from "../ui/Thumb.svelte";
  import { library } from "../stores/library.svelte";
  import { settings } from "../stores/settings.svelte";
  import { toast, reportError } from "../stores/toasts.svelte";
  import { count } from "../format";

  interface Item { path: string; name: string; tags: string[]; already: string[]; error: string | null; chosen: Set<string> }
  interface Props { open: boolean; paths: string[]; onclose: () => void }
  let { open, paths, onclose }: Props = $props();

  let items: Item[] = $state([]);
  let done = $state(0);
  let title = $state("");
  let source: EventSource | null = null;
  let applying = $state(false);

  const backend = $derived((settings.data.tagger?.backend as string) || "prompt");
  const total = $derived(items.reduce((n, i) => n + i.chosen.size, 0));

  function start() {
    items = []; done = 0;
    if (backend !== "prompt" && paths.length > 40 &&
        !confirm(`Send ${paths.length} images to ${backend}?\n\nEach one is uploaded separately, so this takes a while and, on a paid service, costs per image.`)) {
      onclose(); return;
    }
    title = `Suggesting tags for ${count(paths.length)} image${paths.length === 1 ? "" : "s"}`;
    source?.close();
    source = api.tagAutoStream(paths);
    source.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === "image") {
        done = data.current;
        items = [...items, { path: data.path, name: data.name, tags: data.tags ?? [], already: data.existing ?? [],
                             error: data.error ?? null, chosen: new Set(data.tags ?? []) }];
      } else if (data.type === "done") {
        source?.close(); source = null;
        const failed = items.filter((i) => i.error).length;
        title = failed ? `Finished, though ${failed} did not work` : "Finished. Untick anything you do not want, then apply.";
      }
    };
    source.onerror = () => { source?.close(); source = null; title = "The connection dropped part way through."; };
  }
  $effect(() => { if (open) start(); else { source?.close(); source = null; } });

  function toggle(item: Item, tag: string) {
    const next = new Set(item.chosen);
    if (next.has(tag)) next.delete(tag); else next.add(tag);
    item.chosen = next;
    items = [...items];
  }
  function all(on: boolean) {
    for (const i of items) i.chosen = on ? new Set(i.tags) : new Set();
    items = [...items];
  }
  async function apply() {
    const jobs = items.filter((i) => i.chosen.size);
    if (!jobs.length) return;
    applying = true;
    try {
      let written = 0;
      for (const item of jobs) { await library.addTags([item.path], Array.from(item.chosen)); written += item.chosen.size; }
      toast(`Added ${count(written)} tag${written === 1 ? "" : "s"} across ${count(jobs.length)} image${jobs.length === 1 ? "" : "s"}.`);
      onclose();
    } catch (e) { reportError(e); }
    finally { applying = false; }
  }
</script>

<Modal {open} {onclose} {title} width={720} tall>
  <div class="stack full">
    <div class="row">
      <div class="bar"><div class="fill" style={`width:${paths.length ? Math.round((done / paths.length) * 100) : 0}%`}></div></div>
      <span class="hint">{done} of {paths.length} · {backend === "prompt" ? "from the prompts" : backend}</span>
      <span class="spacer"></span>
      <Button size="sm" variant="ghost" onclick={() => all(true)}>Tick all</Button>
      <Button size="sm" variant="ghost" onclick={() => all(false)}>Untick all</Button>
    </div>
    <div class="list">
      {#each items as item (item.path)}
        <div class="item">
          <span class="t"><Thumb path={item.path} /></span>
          <div class="body">
            <div class="n">{item.name}</div>
            {#if item.error}<div class="err">{item.error}</div>
            {:else if !item.tags.length}<div class="hint">{item.already.length ? "Nothing new to add." : "No suggestions for this one."}</div>
            {:else}
              <div class="chips">
                {#each item.tags as tag (tag)}<button class="chip" class:off={!item.chosen.has(tag)} onclick={() => toggle(item, tag)}>{tag}</button>{/each}
                {#each item.already.slice(0, 6) as tag (tag)}<span class="chip had" title="Already on this image">{tag}</span>{/each}
              </div>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  </div>
  {#snippet actions()}
    <Button onclick={onclose}>Close</Button>
    <Button variant="primary" disabled={!total || applying} onclick={apply}>{applying ? "Applying…" : total ? `Apply ${count(total)} tag${total === 1 ? "" : "s"}` : "Nothing ticked"}</Button>
  {/snippet}
</Modal>

<style>
  .full { height: 100%; }
  .bar { width: 160px; height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width .2s; }
  .list { flex: 1; overflow: auto; display: flex; flex-direction: column; gap: var(--sp2); }
  .item { display: flex; gap: var(--sp3); padding: var(--sp2); border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface-2); }
  .t { width: 64px; height: 64px; flex: none; border-radius: 4px; overflow: hidden; }
  .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .n { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .err { color: var(--danger); font-size: 12px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { border: 1px solid var(--accent); background: var(--accent-soft); color: var(--text); font: inherit; font-size: 12px; padding: 2px 8px; border-radius: var(--r-pill); cursor: pointer; }
  .chip.off { border-color: var(--border); background: transparent; color: var(--muted); text-decoration: line-through; }
  .chip.had { border-color: transparent; background: var(--surface); color: var(--faint); cursor: default; }
</style>
