<script lang="ts">
  import { prettyCombo } from "../hotkeys";
  interface Props { combo: string }
  let { combo }: Props = $props();
</script>

<kbd>{prettyCombo(combo)}</kbd>

<style>
  kbd {
    display: inline-block; padding: 1px 6px; min-width: 18px; text-align: center;
    border: 1px solid var(--border-strong); border-bottom-width: 2px; border-radius: 4px;
    background: var(--surface-2); color: var(--muted); font: 11px/1.5 var(--mono);
  }
</style>
