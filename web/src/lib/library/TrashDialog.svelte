<script lang="ts">
  import * as api from "../api";
  import type { TrashItem } from "../api";
  import Modal from "../ui/Modal.svelte";
  import Button from "../ui/Button.svelte";
  import Thumb from "../ui/Thumb.svelte";
  import { library } from "../stores/library.svelte";
  import { toast, reportError } from "../stores/toasts.svelte";
  import { count, relative } from "../format";

  interface Props { open: boolean; onclose: () => void }
  let { open, onclose }: Props = $props();

  let items: TrashItem[] = $state([]);
  let picked = $state(new Set<number>());
  let loading = $state(false);

  async function load() {
    loading = true;
    try { items = (await api.listTrash()).items; picked = new Set(); }
    catch (e) { reportError(e); }
    finally { loading = false; }
  }
  $effect(() => { if (open) load(); });

  function toggle(id: number) {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id); else next.add(id);
    picked = next;
  }
  async function restore(ids: number[]) {
    try {
      const res = await api.restoreTrash(ids);
      toast(`Restored ${count(res.restored.length)}.`);
      await load();
      if (library.folder) library.open({ type: "folder", path: library.folder }); else library.reload();
    } catch (e) { reportError(e); }
  }
  async function purge(ids: number[] | "all") {
    const n = ids === "all" ? items.length : ids.length;
    if (!confirm(`Permanently delete ${count(n)} file${n === 1 ? "" : "s"}? This cannot be undone.`)) return;
    try {
      await api.purgeTrash(ids);
      toast("Deleted.");
      await load();
    } catch (e) { reportError(e); }
  }
</script>

<Modal {open} {onclose} title="Trash" width={720} tall>
  <div class="stack full">
    <div class="row">
      <span class="hint">{count(items.length)} item{items.length === 1 ? "" : "s"}. Soft-deleted files sit in a trash/ subfolder beside their originals until purged.</span>
      <span class="spacer"></span>
      <Button size="sm" disabled={!picked.size} onclick={() => restore(Array.from(picked))}>Restore selected</Button>
      <Button size="sm" variant="danger" disabled={!picked.size} onclick={() => purge(Array.from(picked))}>Delete selected</Button>
      <Button size="sm" variant="danger" disabled={!items.length} onclick={() => purge("all")}>Empty trash</Button>
    </div>
    <div class="grid">
      {#each items as it (it.id)}
        <button class="item" class:on={picked.has(it.id)} type="button" onclick={() => toggle(it.id)} title={it.original_path}>
          <div class="t"><Thumb path={it.trash_path} /></div>
          <div class="meta">
            <span class="n">{it.name}</span>
            <span class="faint">{relative(it.deleted_at)}{#if it.tags.length} · {it.tags.join(", ")}{/if}</span>
          </div>
        </button>
      {:else}
        {#if !loading}<p class="hint pad">Trash is empty.</p>{/if}
      {/each}
    </div>
  </div>
  {#snippet actions()}<Button onclick={onclose}>Close</Button>{/snippet}
</Modal>

<style>
  .full { height: 100%; }
  .grid { flex: 1; overflow: auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--sp2); align-content: start; }
  .item { border: 2px solid var(--border); border-radius: var(--r-sm); background: var(--surface-2); padding: 0; cursor: pointer; overflow: hidden; text-align: left; color: var(--text); font: inherit; }
  .item.on { border-color: var(--accent); }
  .t { aspect-ratio: 1; }
  .meta { display: flex; flex-direction: column; padding: 6px 8px; font-size: 12px; }
  .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pad { padding: var(--sp4); grid-column: 1 / -1; }
</style>
