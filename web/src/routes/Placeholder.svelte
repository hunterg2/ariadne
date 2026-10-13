<script lang="ts">
  import EmptyState from "../lib/ui/EmptyState.svelte";
  interface Props { title: string; text: string; icon?: string }
  let { title, text, icon = "clock" }: Props = $props();
</script>

<div class="wrap"><EmptyState {icon} {title} {text} /></div>

<style>
  .wrap { height: 100%; display: grid; place-items: center; }
</style>
