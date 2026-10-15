<script lang="ts">
  import { thumbUrl } from "../api";

  /* ``lazy`` is for long lists; the grid turns it off, since it only mounts
     the tiles in view and a deferred load is a tile that shows up late */
  interface Props { path: string; alt?: string; fit?: "cover" | "contain"; class?: string; lazy?: boolean }
  let { path, alt = "", fit = "cover", class: cls = "", lazy = true }: Props = $props();
  let img: HTMLImageElement | undefined = $state();
  let loaded = $state(false);
  let failed = $state(false);
  /* an image the browser already holds is complete as soon as it is
     mounted: shown as it is, no fade, so scrolling back is instant */
  let instant = $state(false);
  $effect(() => {
    if (img && img.complete && img.naturalWidth > 0) { instant = true; loaded = true; }
  });
</script>

<div class={`thumb ${cls}`} class:loaded class:failed class:instant>
  <img
    bind:this={img}
    src={thumbUrl(path)}
    {alt}
    loading={lazy ? "lazy" : "eager"}
    decoding="async"
    draggable="false"
    style={`object-fit:${fit}`}
    onload={() => (loaded = true)}
    onerror={() => (failed = true)}
  />
</div>

<style>
  .thumb { position: relative; width: 100%; height: 100%; background: var(--surface-2); overflow: hidden; }
  img { width: 100%; height: 100%; display: block; opacity: 0; transition: opacity .25s var(--ease); }
  .loaded img { opacity: 1; }
  .instant img { transition: none; }
  .failed { background: repeating-linear-gradient(45deg, var(--surface-2), var(--surface-2) 6px, var(--surface) 6px, var(--surface) 12px); }
</style>
