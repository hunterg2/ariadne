<script lang="ts">
  import { thumbUrl } from "../api";

  interface Props { path: string; alt?: string; fit?: "cover" | "contain"; class?: string }
  let { path, alt = "", fit = "cover", class: cls = "" }: Props = $props();
  let loaded = $state(false);
  let failed = $state(false);
</script>

<div class={`thumb ${cls}`} class:loaded class:failed>
  <img
    src={thumbUrl(path)}
    {alt}
    loading="lazy"
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
  .failed { background: repeating-linear-gradient(45deg, var(--surface-2), var(--surface-2) 6px, var(--surface) 6px, var(--surface) 12px); }
</style>
