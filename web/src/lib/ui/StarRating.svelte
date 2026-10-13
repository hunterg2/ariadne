<script lang="ts">
  import Icon from "./Icon.svelte";

  interface Props {
    value: number;
    rejected?: boolean;
    size?: number;
    onchange?: (stars: number) => void;
    onreject?: () => void;
    showReject?: boolean;
    compact?: boolean;
  }
  let { value, rejected = false, size = 16, onchange, onreject, showReject = true, compact = false }: Props = $props();
  let hover = $state(0);
</script>

<div class="stars" class:compact class:readonly={!onchange} role="group" aria-label="Rating" onmouseleave={() => (hover = 0)}>
  {#if showReject}
    <button
      type="button"
      class="reject"
      class:on={rejected}
      title="Reject (X)"
      aria-label="Reject"
      onclick={(e) => { e.stopPropagation(); onreject?.(); }}
      disabled={!onreject}
    ><Icon name="x" size={size - 2} stroke={2.4} /></button>
  {/if}
  {#each [1, 2, 3, 4, 5] as n}
    <button
      type="button"
      class="star"
      class:lit={(hover ? n <= hover : n <= value)}
      class:dim={rejected}
      aria-label={`${n} star${n === 1 ? "" : "s"}`}
      title={`${n} star${n === 1 ? "" : "s"} (${n})`}
      onmouseenter={() => (hover = n)}
      onclick={(e) => { e.stopPropagation(); onchange?.(value === n ? 0 : n); }}
      disabled={!onchange}
    ><Icon name="star" {size} fill={(hover ? n <= hover : n <= value)} stroke={1.6} /></button>
  {/each}
</div>

<style>
  .stars { display: inline-flex; align-items: center; gap: 1px; }
  .stars.compact { gap: 0; }
  button { border: 0; background: transparent; padding: 1px; cursor: pointer; color: var(--muted); display: flex; border-radius: 4px; line-height: 0; }
  button:disabled { cursor: default; }
  .readonly button { pointer-events: none; }
  .star.lit { color: var(--star); }
  .star.dim { opacity: .35; }
  .star:not(:disabled):hover { color: var(--star); }
  .reject { margin-right: 2px; }
  .reject.on { color: var(--danger); }
  .reject:not(:disabled):hover { color: var(--danger); background: var(--danger-soft); }
</style>
