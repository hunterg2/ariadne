<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  interface Props {
    open: boolean;
    title?: string;
    width?: number;
    onclose: () => void;
    children?: Snippet;
    actions?: Snippet;
    tall?: boolean;
  }
  let { open, title, width = 520, onclose, children, actions, tall = false }: Props = $props();
  let sheet: HTMLDivElement | undefined = $state();

  function onkeydown(e: KeyboardEvent) {
    if (e.key === "Escape") { e.stopPropagation(); onclose(); }
  }

  /* Escape must reach the sheet even when nothing inside took focus, and
     the keys must not fall through to the screen underneath. */
  $effect(() => {
    if (open && sheet && !sheet.contains(document.activeElement)) sheet.focus();
  });
</script>

{#if open}
  <div class="overlay" role="presentation" onmousedown={(e) => { if (e.target === e.currentTarget) onclose(); }}>
    <div bind:this={sheet} class="sheet" class:tall role="dialog" aria-modal="true" aria-label={title} style={`width:min(${width}px, calc(100vw - 32px))`} tabindex="-1" {onkeydown}>
      {#if title}
        <header>
          <h3>{title}</h3>
          <button class="close" type="button" onclick={onclose} aria-label="Close"><Icon name="x" size={16} /></button>
        </header>
      {/if}
      <div class="body">{@render children?.()}</div>
      {#if actions}<footer>{@render actions()}</footer>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; z-index: 200; background: rgba(0, 0, 0, .55);
    display: flex; align-items: center; justify-content: center; padding: var(--sp4);
    animation: fade var(--dur) var(--ease);
  }
  .sheet {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg);
    box-shadow: var(--shadow-2); max-height: calc(100vh - 32px); display: flex; flex-direction: column;
    animation: rise .2s var(--ease); outline: none;
  }
  .sheet.tall { height: calc(100vh - 32px); }
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: var(--sp4) var(--sp5) var(--sp3); border-bottom: 1px solid var(--border);
  }
  h3 { margin: 0; font-size: 15px; font-weight: 600; }
  .close { border: 0; background: transparent; color: var(--muted); cursor: pointer; padding: 4px; border-radius: var(--r-sm); display: flex; }
  .close:hover { background: var(--hover); color: var(--text); }
  .body { padding: var(--sp4) var(--sp5); overflow: auto; flex: 1; min-height: 0; }
  footer {
    display: flex; justify-content: flex-end; gap: var(--sp2);
    padding: var(--sp3) var(--sp5) var(--sp4); border-top: 1px solid var(--border);
  }
  /* phones: a sheet from the bottom, full width */
  @media (max-width: 760px) {
    .overlay { padding: var(--sp2); align-items: flex-end; }
    .sheet { width: 100% !important; max-height: calc(100vh - 16px); border-radius: var(--r-lg) var(--r-lg) var(--r-sm) var(--r-sm); }
    .sheet.tall { height: calc(100vh - 16px); }
    header, .body, footer { padding-left: var(--sp4); padding-right: var(--sp4); }
    footer { flex-wrap: wrap; }
  }
  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
  @keyframes rise { from { transform: translateY(8px); opacity: 0; } to { transform: none; opacity: 1; } }
</style>
