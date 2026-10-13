<script lang="ts">
  /* A windowed grid: only the rows in view (plus overscan) are in the DOM.
     Items are laid out in fixed-height rows so the scroll height is known
     for the whole list without rendering it. */
  import type { Snippet } from "svelte";

  interface Props {
    total: number;
    minItemWidth: number;
    aspect?: number;             // height / width of a cell
    gap?: number;
    overscan?: number;
    padding?: number;
    item: Snippet<[number, number]>;   // (index, columnWidth)
    onrange?: (start: number, end: number) => void;
    scrollToIndex?: number | null;
    footer?: Snippet;
  }
  let {
    total, minItemWidth, aspect = 1, gap = 8, overscan = 2, padding = 12,
    item, onrange, scrollToIndex = null, footer,
  }: Props = $props();

  let viewport: HTMLDivElement | undefined = $state();
  let width = $state(0);
  let height = $state(0);
  let scrollTop = $state(0);

  const columns = $derived(Math.max(1, Math.floor((width - padding * 2 + gap) / (minItemWidth + gap))));
  const cellWidth = $derived(columns ? (width - padding * 2 - gap * (columns - 1)) / columns : minItemWidth);
  const cellHeight = $derived(cellWidth * aspect);
  const rowHeight = $derived(cellHeight + gap);
  const rowCount = $derived(Math.ceil(total / columns));
  const contentHeight = $derived(rowCount * rowHeight - gap + padding * 2);

  const firstRow = $derived(Math.max(0, Math.floor((scrollTop - padding) / rowHeight) - overscan));
  const lastRow = $derived(Math.min(rowCount - 1, Math.ceil((scrollTop - padding + height) / rowHeight) + overscan));
  const start = $derived(firstRow * columns);
  const end = $derived(Math.min(total, (lastRow + 1) * columns));

  $effect(() => {
    if (!viewport) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) { width = e.contentRect.width; height = e.contentRect.height; }
    });
    ro.observe(viewport);
    width = viewport.clientWidth;
    height = viewport.clientHeight;
    return () => ro.disconnect();
  });

  let lastRange = "";
  $effect(() => {
    const key = `${start}:${end}`;
    if (key !== lastRange && total > 0) { lastRange = key; onrange?.(start, end); }
  });

  $effect(() => {
    if (scrollToIndex == null || !viewport || !columns) return;
    const row = Math.floor(scrollToIndex / columns);
    const top = padding + row * rowHeight;
    const bottom = top + cellHeight;
    if (top < viewport.scrollTop) viewport.scrollTop = top - gap;
    else if (bottom > viewport.scrollTop + viewport.clientHeight) viewport.scrollTop = bottom - viewport.clientHeight + gap;
  });

  export function scrollTo(top: number) { if (viewport) viewport.scrollTop = top; }
  export function getColumns() { return columns; }
</script>

<div class="viewport" bind:this={viewport} onscroll={(e) => (scrollTop = (e.currentTarget as HTMLDivElement).scrollTop)}>
  <div class="content" style={`height:${contentHeight}px`}>
    {#if total > 0}
      {#each Array.from({ length: Math.max(0, end - start) }, (_, k) => start + k) as i (i)}
        {@const row = Math.floor(i / columns)}
        {@const col = i % columns}
        <div
          class="cell"
          style={`transform: translate(${padding + col * (cellWidth + gap)}px, ${padding + row * rowHeight}px); width:${cellWidth}px; height:${cellHeight}px`}
        >
          {@render item(i, cellWidth)}
        </div>
      {/each}
    {/if}
  </div>
  {#if footer}<div class="footer">{@render footer()}</div>{/if}
</div>

<style>
  .viewport { position: relative; height: 100%; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; }
  .content { position: relative; width: 100%; }
  .cell { position: absolute; top: 0; left: 0; will-change: transform; }
  .footer { padding: var(--sp4); }
</style>
