<script lang="ts">
  import { toasts, dismiss } from "../stores/toasts.svelte";
  import Icon from "./Icon.svelte";
</script>

<div class="toasts" aria-live="polite">
  {#each toasts as t (t.id)}
    <div class="toast" class:error={t.error}>
      <Icon name={t.error ? "alert" : "check"} size={15} />
      <span class="msg">{t.message}</span>
      {#if t.action}
        <button class="act" type="button" onclick={() => { t.action?.run(); dismiss(t.id); }}>{t.action.label}</button>
      {/if}
      <button class="x" type="button" onclick={() => dismiss(t.id)} aria-label="Dismiss"><Icon name="x" size={13} /></button>
    </div>
  {/each}
</div>

<style>
  .toasts {
    position: fixed; right: var(--sp4); bottom: var(--sp4); z-index: 400;
    display: flex; flex-direction: column; gap: var(--sp2); max-width: min(420px, calc(100vw - 32px));
  }
  @media (max-width: 760px) {
    .toasts { left: var(--sp3); right: var(--sp3); bottom: calc(62px + env(safe-area-inset-bottom)); max-width: none; }
  }
  .toast {
    display: flex; align-items: center; gap: var(--sp2); padding: 10px 12px;
    background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--select);
    border-radius: var(--r); box-shadow: var(--shadow-2); font-size: 13px;
    animation: rise .2s var(--ease);
  }
  .toast.error { border-left-color: var(--danger); }
  .toast.error :global(.icon) { color: var(--danger); }
  .toast :global(.icon) { color: var(--select); }
  .msg { flex: 1; }
  .act { border: 0; background: var(--accent-soft); color: var(--text); font: inherit; font-weight: 600; padding: 4px 8px; border-radius: var(--r-sm); cursor: pointer; }
  .x { border: 0; background: transparent; color: var(--muted); cursor: pointer; display: flex; padding: 2px; }
  @keyframes rise { from { transform: translateY(6px); opacity: 0; } to { transform: none; opacity: 1; } }
</style>
