<script lang="ts">
  import type { ImageRow } from "../api";
  import Icon from "../ui/Icon.svelte";
  import StarRating from "../ui/StarRating.svelte";
  import Thumb from "../ui/Thumb.svelte";
  import { library } from "../stores/library.svelte";
  import { ui } from "../stores/settings.svelte";

  interface Props {
    index: number;
    row: ImageRow | undefined;
    onopen: (index: number) => void;
    onclick: (index: number, e: MouseEvent) => void;
    oncontext?: (index: number, e: MouseEvent) => void;
  }
  let { index, row, onopen, onclick, oncontext }: Props = $props();

  const selected = $derived(!!row && library.selected.has(row.path));
  const focused = $derived(library.focus === index);
  const starsAlways = $derived(ui("stars_always"));
  const natural = $derived(ui("layout") === "natural");
  const compact = $derived(ui("density") === "compact");
  /* in a folder that includes its subfolders, say which one this came from */
  const sub = $derived.by(() => {
    if (!row || !library.recursive || library.scope.type !== "folder") return "";
    const root = library.scope.path;
    return row.folder.length > root.length && row.folder.startsWith(root) ? row.folder.slice(root.length + 1) : "";
  });
</script>

<div
  class="tile"
  class:selected
  class:focused
  class:rejected={!!row?.rejected}
  class:compact
  role="option"
  aria-selected={selected}
  tabindex="-1"
  onclick={(e) => onclick(index, e)}
  ondblclick={() => onopen(index)}
  oncontextmenu={(e) => { if (oncontext) { e.preventDefault(); oncontext(index, e); } }}
  title={row ? `${row.name}\n${row.width}×${row.height}` : ""}
>
  {#if row}
    <Thumb path={row.path} fit={natural ? "contain" : "cover"} lazy={false} />
    <div class="top" class:always={!!sub}>
      {#if row.kind === "generated"}
        <span class="kind" title="Generated"><Icon name="sparkles" size={12} /></span>
      {:else if row.kind === "photo"}
        <span class="kind" title="Photo"><Icon name="camera" size={12} /></span>
      {/if}
      {#if sub}<span class="kind sub" title={row.folder}><Icon name="folderTree" size={11} />{sub}</span>{/if}
      {#if row.label}<span class="label" style={`background:${row.label}`}></span>{/if}
      <span class="spacer"></span>
      {#if row.user_tags.length}
        <span class="count" title={row.user_tags.join(", ")}><Icon name="tag" size={10} />{row.user_tags.length}</span>
      {/if}
      <button
        class="check"
        class:on={selected}
        type="button"
        aria-label={selected ? "Deselect" : "Select"}
        onclick={(e) => { e.stopPropagation(); library.toggleSelect(row.path); library.setFocus(index, false); }}
      ><Icon name="check" size={12} stroke={3} /></button>
    </div>
    {#if row.rejected}
      <div class="reject-mark"><Icon name="x" size={28} stroke={2.5} /></div>
    {/if}
    <div class="bottom" class:always={starsAlways || row.stars > 0}>
      <span class="name">{row.name}</span>
      <StarRating
        value={row.stars}
        rejected={!!row.rejected}
        size={compact ? 12 : 14}
        compact
        showReject={false}
        onchange={(n) => library.rate([row.path], { stars: n })}
      />
    </div>
  {:else}
    <div class="skeleton"></div>
  {/if}
</div>

<style>
  .tile {
    position: relative; width: 100%; height: 100%; border-radius: var(--r-sm); overflow: hidden;
    background: var(--surface-2); cursor: pointer; outline: 2px solid transparent; outline-offset: -2px;
    transition: outline-color var(--dur) var(--ease), transform var(--dur) var(--ease);
    user-select: none;
  }
  .tile:hover { outline-color: var(--border-strong); }
  .tile.focused { outline-color: var(--accent); }
  .tile.selected { outline-color: var(--select); }
  .tile.selected.focused { outline-color: var(--accent); box-shadow: inset 0 0 0 4px var(--select); }
  .tile.rejected :global(.thumb) { filter: grayscale(.7) brightness(.55); }
  .skeleton { width: 100%; height: 100%; background: linear-gradient(100deg, var(--surface-2) 40%, var(--hover) 50%, var(--surface-2) 60%); background-size: 200% 100%; animation: shimmer 1.4s infinite; }
  @keyframes shimmer { to { background-position: -200% 0; } }

  .top, .bottom {
    position: absolute; left: 0; right: 0; display: flex; align-items: center; gap: 4px; padding: 6px;
    opacity: 0; transition: opacity var(--dur) var(--ease); pointer-events: none;
  }
  .top { top: 0; background: linear-gradient(rgba(0, 0, 0, .55), transparent); }
  .bottom { bottom: 0; background: linear-gradient(transparent, rgba(0, 0, 0, .65)); justify-content: space-between; }
  .tile:hover .top, .tile:hover .bottom, .tile.selected .top, .top.always, .bottom.always, .tile.focused .bottom { opacity: 1; }
  .sub { max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
  .compact .sub { display: none; }
  .top > *, .bottom > * { pointer-events: auto; }
  .bottom.always:not(:hover) .name { opacity: 0; }
  .tile:hover .bottom .name { opacity: 1; }
  .name { font-size: 11px; color: #fff; text-shadow: 0 1px 2px rgba(0, 0, 0, .8); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
  .compact .name { display: none; }
  .kind, .count {
    display: inline-flex; align-items: center; gap: 2px; height: 18px; padding: 0 5px; border-radius: 9px;
    background: rgba(0, 0, 0, .5); color: #fff; font-size: 10.5px; font-weight: 600;
  }
  .label { width: 10px; height: 10px; border-radius: 50%; border: 1px solid rgba(255, 255, 255, .6); }
  .check {
    width: 20px; height: 20px; border-radius: 50%; border: 1.5px solid rgba(255, 255, 255, .8);
    background: rgba(0, 0, 0, .35); color: transparent; display: grid; place-items: center; cursor: pointer; padding: 0;
  }
  .check:hover { background: rgba(255, 255, 255, .25); }
  .check.on { background: var(--select); border-color: var(--select); color: #11111b; }
  .reject-mark { position: absolute; inset: 0; display: grid; place-items: center; color: var(--danger); pointer-events: none; opacity: .9; }
  /* no hover on a touch screen: the star row and the check are always there */
  @media (pointer: coarse) {
    .top, .bottom { opacity: 1; }
    .bottom .name { opacity: 0; }
    .check { width: 24px; height: 24px; }
  }
  .bottom :global(.stars) { filter: drop-shadow(0 1px 1px rgba(0, 0, 0, .8)); }
  .bottom :global(.stars button) { color: rgba(255, 255, 255, .55); }
  .bottom :global(.stars .star.lit) { color: var(--star); }
</style>
