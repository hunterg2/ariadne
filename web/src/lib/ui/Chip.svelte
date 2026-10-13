<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  interface Props {
    active?: boolean;
    color?: string;
    icon?: string;
    onclick?: (e: MouseEvent) => void;
    onremove?: () => void;
    title?: string;
    small?: boolean;
    children?: Snippet;
    class?: string;
  }
  let { active = false, color, icon, onclick, onremove, title, small = false, children, class: cls = "" }: Props = $props();
</script>

<span
  class={`chip ${cls}`}
  class:active
  class:small
  class:clickable={!!onclick}
  style={color ? `--chip: ${color}` : ""}
  {title}
  role={onclick ? "button" : undefined}
  tabindex={onclick ? 0 : undefined}
  {onclick}
  onkeydown={(e) => { if (onclick && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onclick(e as unknown as MouseEvent); } }}
>
  {#if color}<i class="dot"></i>{/if}
  {#if icon}<Icon name={icon} size={small ? 12 : 14} />{/if}
  {#if children}{@render children()}{/if}
  {#if onremove}
    <button class="rm" type="button" onclick={(e) => { e.stopPropagation(); onremove(); }} aria-label="Remove">
      <Icon name="x" size={11} stroke={2.4} />
    </button>
  {/if}
</span>

<style>
  .chip {
    display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 9px;
    border-radius: var(--r-pill); border: 1px solid var(--border); background: var(--surface-2);
    font-size: 12.5px; line-height: 1; color: var(--text); white-space: nowrap; user-select: none;
    transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
  }
  .chip.small { height: 20px; padding: 0 7px; font-size: 11.5px; }
  .chip.clickable { cursor: pointer; }
  .chip.clickable:hover { background: var(--hover); border-color: var(--border-strong); }
  .chip.active { background: var(--accent-soft); border-color: var(--accent); }
  .chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--chip, var(--muted)); }
  .rm {
    display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px;
    margin-right: -4px; border: 0; border-radius: 50%; background: transparent; color: var(--muted); cursor: pointer;
  }
  .rm:hover { background: var(--hover-strong); color: var(--text); }
</style>
