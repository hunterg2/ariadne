<script lang="ts">
  /* A dropdown anchored under its trigger. The trigger is the `trigger`
     snippet; the items snippet gets a close() function. */
  import type { Snippet } from "svelte";

  interface Props {
    trigger: Snippet<[{ open: boolean; toggle: () => void }]>;
    children: Snippet<[{ close: () => void }]>;
    align?: "left" | "right";
    width?: number;
  }
  let { trigger, children, align = "left", width }: Props = $props();

  let open = $state(false);
  let root: HTMLElement | undefined = $state();

  function toggle() { open = !open; }
  function close() { open = false; }

  $effect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (root && !root.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey, true);
    };
  });
</script>

<span class="menu-root" bind:this={root}>
  {@render trigger({ open, toggle })}
  {#if open}
    <div class="popover" class:right={align === "right"} style={width ? `min-width:${width}px` : ""} role="menu">
      {@render children({ close })}
    </div>
  {/if}
</span>

<style>
  .menu-root { position: relative; display: inline-flex; }
  .popover {
    position: absolute; top: calc(100% + 4px); left: 0; z-index: 150; min-width: 180px;
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--r);
    box-shadow: var(--shadow-2); padding: var(--sp1); animation: rise .15s var(--ease);
  }
  .popover.right { left: auto; right: 0; }
  @keyframes rise { from { transform: translateY(-4px); opacity: 0; } to { transform: none; opacity: 1; } }
  :global(.menu-item) {
    display: flex; align-items: center; gap: var(--sp2); width: 100%; padding: 7px 10px;
    border: 0; background: transparent; color: var(--text); font: inherit; text-align: left;
    border-radius: var(--r-sm); cursor: pointer; white-space: nowrap;
  }
  :global(.menu-item:hover), :global(.menu-item.active) { background: var(--hover); }
  :global(.menu-item.active) { color: var(--accent); }
  :global(.menu-item .hint) { margin-left: auto; color: var(--muted); font-size: 12px; }
  :global(.menu-sep) { height: 1px; background: var(--border); margin: var(--sp1) 0; }
  :global(.menu-title) { padding: 6px 10px 2px; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
</style>
