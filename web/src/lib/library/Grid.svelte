<script lang="ts">
  import VirtualGrid from "../ui/VirtualGrid.svelte";
  import EmptyState from "../ui/EmptyState.svelte";
  import Button from "../ui/Button.svelte";
  import Tile from "./Tile.svelte";
  import { library } from "../stores/library.svelte";
  import { ui } from "../stores/settings.svelte";
  import { viewport } from "../stores/viewport.svelte";

  interface Props {
    onopen: (index: number) => void;
    oncontext?: (index: number, e: MouseEvent) => void;
    onaddfolder?: () => void;
  }
  let { onopen, oncontext, onaddfolder }: Props = $props();

  let grid: VirtualGrid | undefined = $state();
  /* on a phone the tile setting is capped so three fit across */
  const size = $derived(viewport.phone ? Math.min(ui("grid_size"), 118) : ui("grid_size"));
  const gap = $derived(ui("density") === "compact" ? 4 : 8);

  function onclick(index: number, e: MouseEvent) {
    const row = library.rows[index];
    if (!row) return;
    if (e.shiftKey && library.anchor >= 0) {
      if (!e.ctrlKey && !e.metaKey) library.selected.clear();
      library.selectRange(library.anchor, index);
    } else if (e.ctrlKey || e.metaKey) {
      library.toggleSelect(row.path);
      library.anchor = index;
    } else {
      // plain click: focus it and make it the only selection, like a file manager
      if (library.selected.size === 1 && library.selected.has(row.path)) {
        library.selected.clear();
      } else {
        library.selectOnly(row.path);
      }
      library.anchor = index;
    }
    library.setFocus(index, false);
  }

  export function columns() { return grid?.getColumns() ?? 1; }
</script>

<div class="grid-wrap" role="listbox" aria-multiselectable="true" aria-label="Images">
  {#if library.total === 0 && !library.loading}
    {#if library.scope.type === "all" && library.folderPaths().length === 0}
      <EmptyState icon="folderPlus" title="Add a folder to get started" text="Point Ariadne at the folder your generator writes to, or any folder of images. Nothing in it is changed.">
        <Button variant="primary" icon="folderPlus" onclick={onaddfolder}>Add a folder</Button>
      </EmptyState>
    {:else}
      <EmptyState icon="search" title="Nothing matches" text="Try clearing a filter, or open a different folder." />
    {/if}
  {:else}
    <VirtualGrid
      bind:this={grid}
      total={library.total}
      minItemWidth={size}
      {gap}
      aspect={1}
      item={cell}
      onrange={(s, e) => library.ensureRange(s, e)}
      scrollToIndex={library.focus >= 0 ? library.focus : null}
    />
  {/if}
</div>

{#snippet cell(i: number)}
  <Tile index={i} row={library.rows[i]} {onopen} {onclick} {oncontext} />
{/snippet}

<style>
  .grid-wrap { height: 100%; min-height: 0; }
</style>
