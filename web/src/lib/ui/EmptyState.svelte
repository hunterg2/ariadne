<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  interface Props { icon?: string; title: string; text?: string; children?: Snippet }
  let { icon = "image", title, text, children }: Props = $props();
</script>

<div class="empty">
  <div class="ring"><Icon name={icon} size={26} stroke={1.5} /></div>
  <h3>{title}</h3>
  {#if text}<p>{text}</p>{/if}
  {#if children}<div class="actions">{@render children()}</div>{/if}
</div>

<style>
  .empty { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: var(--sp10) var(--sp4); color: var(--muted); gap: var(--sp2); min-height: 240px; }
  .ring { width: 56px; height: 56px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-2); color: var(--accent); margin-bottom: var(--sp2); }
  h3 { margin: 0; color: var(--text); font-size: 16px; font-weight: 600; }
  p { margin: 0; max-width: 360px; font-size: 13.5px; }
  .actions { display: flex; gap: var(--sp2); margin-top: var(--sp2); }
</style>
