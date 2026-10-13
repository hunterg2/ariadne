<script lang="ts">
  import * as api from "../api";
  import Modal from "../ui/Modal.svelte";
  import Button from "../ui/Button.svelte";
  import Icon from "../ui/Icon.svelte";
  import { reportError } from "../stores/toasts.svelte";

  interface Props {
    open: boolean;
    title?: string;
    confirmLabel?: string;
    start?: string;
    onpick: (path: string) => void;
    onclose: () => void;
  }
  let { open, title = "Choose a folder", confirmLabel = "Choose this folder", start = "", onpick, onclose }: Props = $props();

  let current = $state("root");
  let parent = $state("");
  let dirs: { name: string; path: string }[] = $state([]);
  let typed = $state("");
  let loading = $state(false);

  async function load(path: string) {
    loading = true;
    try {
      const res = await api.browse(path);
      current = res.current_path;
      parent = res.parent_path;
      dirs = res.directories;
      typed = current === "root" ? "" : current;
    } catch (e) {
      reportError(e, "Could not open that folder.");
    } finally {
      loading = false;
    }
  }

  $effect(() => { if (open) load(start || "root"); });

  function submitTyped(e: Event) {
    e.preventDefault();
    if (typed.trim()) load(typed.trim());
  }
</script>

<Modal {open} {onclose} {title} width={560} tall>
  <div class="stack full">
    <form class="row" onsubmit={submitTyped}>
      <Button size="sm" square icon="chevronLeft" title="Up one level" disabled={!parent && current === "root"} onclick={() => load(parent || "root")} />
      <input bind:value={typed} placeholder="Type or paste a path and press Enter" spellcheck="false" />
      <Button size="sm" type="submit" icon="chevronRight" square title="Go" />
    </form>
    <div class="list">
      {#if loading}
        <p class="hint pad"><Icon name="loader" size={13} class="spin" /> Reading…</p>
      {:else}
        {#each dirs as d (d.path)}
          <button class="dir" type="button" ondblclick={() => load(d.path)} onclick={() => (typed = d.path)} class:picked={typed === d.path}>
            <Icon name="folder" size={15} /><span>{d.name}</span>
            <span class="spacer"></span>
            <span class="enter" onclick={(e) => { e.stopPropagation(); load(d.path); }} role="button" tabindex="-1" title="Open"><Icon name="chevronRight" size={14} /></span>
          </button>
        {:else}
          <p class="hint pad">No subfolders here.</p>
        {/each}
      {/if}
    </div>
    <p class="hint">Double-click a folder to open it; single-click picks it. The current folder is chosen when nothing is picked.</p>
  </div>
  {#snippet actions()}
    <Button onclick={onclose}>Cancel</Button>
    <Button variant="primary" disabled={!typed || typed === "root"} onclick={() => onpick(typed)}>{confirmLabel}</Button>
  {/snippet}
</Modal>

<style>
  .full { height: 100%; }
  .row input { flex: 1; font-family: var(--mono); font-size: 12.5px; }
  .list { flex: 1; min-height: 240px; overflow: auto; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface-2); }
  .dir { display: flex; align-items: center; gap: var(--sp2); width: 100%; padding: 7px 10px; border: 0; background: transparent; color: var(--text); font: inherit; text-align: left; cursor: pointer; }
  .dir:hover { background: var(--hover); }
  .dir.picked { background: var(--accent-soft); }
  .enter { color: var(--muted); display: inline-flex; padding: 2px; border-radius: 4px; }
  .enter:hover { background: var(--hover-strong); color: var(--text); }
  .pad { padding: var(--sp3); }
</style>
