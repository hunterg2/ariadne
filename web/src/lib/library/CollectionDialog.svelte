<script lang="ts">
  import * as api from "../api";
  import Modal from "../ui/Modal.svelte";
  import Button from "../ui/Button.svelte";
  import Icon from "../ui/Icon.svelte";
  import { library } from "../stores/library.svelte";
  import { toast, reportError } from "../stores/toasts.svelte";
  import { count } from "../format";

  interface Props { open: boolean; paths: string[]; onclose: () => void }
  let { open, paths, onclose }: Props = $props();

  let mode: "pick" | "new" = $state("pick");
  let name = $state("");
  let kind: "manual" | "smart" = $state("manual");
  let query = $state("");
  let color = $state("");
  const COLORS = ["", "#f38ba8", "#fab387", "#f9e2af", "#a6e3a1", "#89b4fa", "#cba6f7"];
  const manual = $derived(library.collections.filter((c) => c.kind === "manual"));

  $effect(() => {
    if (open) {
      mode = paths.length ? "pick" : "new";
      name = ""; kind = "manual"; color = "";
      query = library.filters.q || (library.filters.tag ? `tag: ${library.filters.tag}` : "");
      if (!manual.length && paths.length) mode = "new";
    }
  });

  async function addTo(id: string) {
    try {
      const res = await api.collectionItems(id, paths);
      toast(`Added ${count(res.added ?? 0)} to the collection.`);
      await library.refreshCollections();
      for (const p of paths) {
        const row = library.rows.find((r) => r?.path === p);
        if (row && !row.collections.includes(id)) library.patchRows([p], { collections: [...row.collections, id] });
      }
      onclose();
    } catch (e) { reportError(e); }
  }

  async function create(e: Event) {
    e.preventDefault();
    try {
      const res = await api.createCollection({
        name, kind, query: kind === "smart" ? query : "", color,
        paths: kind === "manual" ? paths : [],
      });
      await library.refreshCollections();
      toast(`Created "${res.collection.name}".`);
      if (kind === "manual" && paths.length) {
        for (const p of paths) {
          const row = library.rows.find((r) => r?.path === p);
          if (row) library.patchRows([p], { collections: [...row.collections, res.id] });
        }
      } else {
        library.open({ type: "collection", id: res.id });
      }
      onclose();
    } catch (err) { reportError(err); }
  }
</script>

<Modal {open} {onclose} title={paths.length ? `Add ${count(paths.length)} image${paths.length === 1 ? "" : "s"} to a collection` : "New collection"} width={460}>
  {#if mode === "pick"}
    <div class="list">
      {#each manual as c (c.id)}
        <button class="pick" type="button" onclick={() => addTo(c.id)}>
          <Icon name="layers" size={15} />{#if c.color}<i class="swatch" style={`background:${c.color}`}></i>{/if}
          <span>{c.name}</span><span class="spacer"></span><span class="faint">{count(c.count ?? 0)}</span>
        </button>
      {/each}
      <button class="pick new" type="button" onclick={() => (mode = "new")}><Icon name="plus" size={15} /><span>New collection…</span></button>
    </div>
  {:else}
    <form class="stack" onsubmit={create} id="newcol">
      <div>
        <label class="field" for="col-name">Name</label>
        <input id="col-name" bind:value={name} placeholder="e.g. Portfolio picks" required />
      </div>
      <div class="row">
        <label class="opt"><input type="radio" bind:group={kind} value="manual" /> Manual: images you add</label>
        <label class="opt"><input type="radio" bind:group={kind} value="smart" /> Smart: a saved search</label>
      </div>
      {#if kind === "smart"}
        <div>
          <label class="field" for="col-query">Query</label>
          <input id="col-query" bind:value={query} class="mono" placeholder={'stars: 4...; tag: portrait'} />
          <p class="hint">The same language as the search box. The collection shows whatever matches, library-wide.</p>
        </div>
      {/if}
      <div>
        <span class="field">Colour</span>
        <div class="row">
          {#each COLORS as c}
            <button type="button" class="swatch big" class:on={color === c} style={c ? `background:${c}` : ""} onclick={() => (color = c)} aria-label={c || "none"}>{#if !c}<Icon name="x" size={10} />{/if}</button>
          {/each}
        </div>
      </div>
    </form>
  {/if}
  {#snippet actions()}
    {#if mode === "new"}
      {#if manual.length && paths.length}<Button variant="ghost" onclick={() => (mode = "pick")}>Back</Button>{/if}
      <Button onclick={onclose}>Cancel</Button>
      <Button variant="primary" type="submit" onclick={(e) => { (document.getElementById("newcol") as HTMLFormElement)?.requestSubmit(); }}>Create</Button>
    {:else}
      <Button onclick={onclose}>Cancel</Button>
    {/if}
  {/snippet}
</Modal>

<style>
  .list { display: flex; flex-direction: column; gap: 2px; }
  .pick { display: flex; align-items: center; gap: var(--sp2); padding: 9px 10px; border: 1px solid transparent; border-radius: var(--r-sm); background: transparent; color: var(--text); font: inherit; text-align: left; cursor: pointer; }
  .pick:hover { background: var(--hover); }
  .pick.new { color: var(--accent); border-top: 1px solid var(--border); border-radius: 0; margin-top: 4px; }
  .opt { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
  .swatch { width: 9px; height: 9px; border-radius: 50%; }
  .swatch.big { width: 20px; height: 20px; border: 2px solid transparent; background: var(--surface-2); cursor: pointer; display: grid; place-items: center; color: var(--muted); padding: 0; }
  .swatch.big.on { border-color: var(--text); }
</style>
