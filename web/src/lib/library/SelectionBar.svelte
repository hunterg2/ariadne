<script lang="ts">
  import Button from "../ui/Button.svelte";
  import Menu from "../ui/Menu.svelte";
  import Icon from "../ui/Icon.svelte";
  import { library } from "../stores/library.svelte";
  import { toast } from "../stores/toasts.svelte";
  import * as api from "../api";
  import { count } from "../format";

  interface Props {
    ontag: (paths: string[]) => void;
    oncollect: (paths: string[]) => void;
    onexport: (paths: string[], mode: "copy" | "move") => void;
    oncompare: (paths: string[]) => void;
    onsuggest: (paths: string[]) => void;
  }
  let { ontag, oncollect, onexport, oncompare, onsuggest }: Props = $props();

  const paths = $derived(Array.from(library.selected));
  const n = $derived(library.selected.size);

  async function zip() {
    try { await api.downloadZip(paths); } catch (e) { toast((e as Error).message, { error: true }); }
  }
</script>

{#if n > 0}
  <div class="selbar">
    <span class="n"><b>{count(n)}</b> selected</span>
    <Menu>
      {#snippet trigger({ toggle })}<Button size="sm" icon="star" iconRight="chevronDown" onclick={toggle}>Rate</Button>{/snippet}
      {#snippet children({ close })}
        {#each [5, 4, 3, 2, 1] as s}
          <button class="menu-item" onclick={() => { library.rate(paths, { stars: s }); close(); }}>{"★".repeat(s)}<span class="hint">{s}</span></button>
        {/each}
        <div class="menu-sep"></div>
        <button class="menu-item" onclick={() => { library.rate(paths, { stars: 0 }); close(); }}>Clear rating<span class="hint">0</span></button>
        <button class="menu-item" onclick={() => { library.rate(paths, { rejected: true }); close(); }}><Icon name="x" size={14} />Reject<span class="hint">X</span></button>
        <button class="menu-item" onclick={() => { library.rate(paths, { rejected: false }); close(); }}>Un-reject</button>
      {/snippet}
    </Menu>
    <Button size="sm" icon="tag" onclick={() => ontag(paths)}>Tag</Button>
    <Button size="sm" icon="layers" onclick={() => oncollect(paths)}>Collection</Button>
    <span class="sep"></span>
    <Button size="sm" variant="ghost" icon="compare" onclick={() => oncompare(paths)} disabled={n < 2}>Compare</Button>
    <Button size="sm" variant="ghost" icon="sparkles" onclick={() => onsuggest(paths)}>Suggest tags</Button>
    <Menu>
      {#snippet trigger({ toggle })}<Button size="sm" variant="ghost" icon="more" onclick={toggle}>More</Button>{/snippet}
      {#snippet children({ close })}
        <button class="menu-item" onclick={() => { onexport(paths, "copy"); close(); }}><Icon name="copy" size={14} />Copy to…</button>
        <button class="menu-item" onclick={() => { onexport(paths, "move"); close(); }}><Icon name="move" size={14} />Move to…</button>
        <button class="menu-item" onclick={() => { zip(); close(); }}><Icon name="zip" size={14} />Download .zip</button>
        <div class="menu-sep"></div>
        <button class="menu-item" onclick={() => { library.selectAllLoaded(); close(); }}>Select all<span class="hint">Ctrl+A</span></button>
      {/snippet}
    </Menu>
    <span class="spacer"></span>
    <Button size="sm" variant="danger" icon="trash" onclick={() => library.trash(paths)}>Trash</Button>
    <Button size="sm" variant="subtle" icon="x" onclick={() => library.clearSelection()}>Clear</Button>
  </div>
{/if}

<style>
  .selbar {
    display: flex; align-items: center; gap: var(--sp2); flex-wrap: wrap;
    padding: var(--sp2) var(--sp4); background: var(--select-soft); border-bottom: 1px solid var(--border);
    animation: drop .15s var(--ease);
  }
  .n { font-size: 13px; margin-right: var(--sp2); }
  .sep { width: 1px; height: 20px; background: var(--border-strong); margin: 0 var(--sp1); }
  @keyframes drop { from { transform: translateY(-4px); opacity: 0; } to { transform: none; opacity: 1; } }
</style>
