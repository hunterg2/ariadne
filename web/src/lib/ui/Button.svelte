<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  interface Props {
    variant?: "default" | "primary" | "ghost" | "danger" | "subtle";
    size?: "sm" | "md" | "lg";
    icon?: string;
    iconRight?: string;
    disabled?: boolean;
    active?: boolean;
    title?: string;
    type?: "button" | "submit";
    onclick?: (e: MouseEvent) => void;
    class?: string;
    children?: Snippet;
    square?: boolean;
  }
  let {
    variant = "default", size = "md", icon, iconRight, disabled = false, active = false,
    title, type = "button", onclick, class: cls = "", children, square = false,
  }: Props = $props();
</script>

<button
  class={`btn ${variant} ${size} ${cls}`}
  class:active
  class:square
  {type}
  {title}
  {disabled}
  aria-label={title}
  {onclick}
>
  {#if icon}<Icon name={icon} size={size === "sm" ? 15 : 17} />{/if}
  {#if children}<span class="label">{@render children()}</span>{/if}
  {#if iconRight}<Icon name={iconRight} size={size === "sm" ? 14 : 16} />{/if}
</button>

<style>
  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: var(--sp2);
    border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
    border-radius: var(--r-sm); font: inherit; font-weight: 500; cursor: pointer;
    padding: 0 var(--sp3); height: 32px; line-height: 1; white-space: nowrap;
    transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease),
                color var(--dur) var(--ease), transform var(--dur) var(--ease);
    user-select: none;
  }
  .btn:hover:not(:disabled) { background: var(--hover); border-color: var(--border-strong); }
  .btn:active:not(:disabled) { transform: translateY(1px); }
  .btn:disabled { opacity: .45; cursor: default; }
  .btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .btn.sm { height: 26px; padding: 0 var(--sp2); font-size: 12.5px; }
  @media (pointer: coarse) { .btn.sm { height: 32px; } .btn.square.sm { width: 32px; } }
  .btn.lg { height: 38px; padding: 0 var(--sp4); font-size: 15px; }
  .btn.square { padding: 0; width: 32px; }
  .btn.square.sm { width: 26px; }
  .btn.primary { background: var(--accent); color: var(--on-accent); border-color: transparent; }
  .btn.primary:hover:not(:disabled) { background: var(--accent-strong); border-color: transparent; }
  .btn.ghost, .btn.subtle { background: transparent; border-color: transparent; }
  .btn.subtle { color: var(--muted); }
  .btn.ghost:hover:not(:disabled), .btn.subtle:hover:not(:disabled) { background: var(--hover); color: var(--text); }
  .btn.danger { color: var(--danger); }
  .btn.danger:hover:not(:disabled) { background: var(--danger-soft); border-color: var(--danger); }
  .btn.active { background: var(--accent-soft); border-color: var(--accent); color: var(--text); }
  .label { display: inline-flex; align-items: center; }
</style>
