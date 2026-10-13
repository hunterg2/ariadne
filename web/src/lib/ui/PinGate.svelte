<script lang="ts">
  /* Shown on another device until it has entered the PIN. Covers the whole
     app: nothing underneath can load anyway, every request answers 401. */
  import * as api from "../api";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  interface Props { need: api.PinNeed; message: string }
  let { need, message }: Props = $props();

  let pin = $state("");
  let error = $state("");
  let busy = $state(false);
  let input: HTMLInputElement | undefined = $state();

  $effect(() => { input?.focus(); });

  async function submit(e: Event) {
    e.preventDefault();
    if (!pin.trim() || busy) return;
    busy = true;
    error = "";
    try {
      await api.enterPin(pin);
      location.reload();           // every screen refetches with the cookie
    } catch (err) {
      error = err instanceof Error ? err.message : "That did not work.";
      pin = "";
      busy = false;
      input?.focus();
    }
  }
</script>

<div class="gate" role="dialog" aria-modal="true" aria-labelledby="gate-title">
  <form class="sheet" onsubmit={submit}>
    <div class="brand"><img src="/icon.png" alt="" width="36" height="36" /><span>Ariadne</span></div>
    {#if need === "unset"}
      <h2 id="gate-title"><Icon name="lock" size={18} /> No PIN set yet</h2>
      <p>{message || "Ariadne can be reached from other devices but has no PIN. Set one in Settings, under Other devices, on the computer running it."}</p>
      <Button variant="primary" onclick={() => location.reload()}>Try again</Button>
    {:else}
      <h2 id="gate-title"><Icon name="lock" size={18} /> Enter the PIN</h2>
      <p class="hint">It is set on the computer running Ariadne, under Settings, Other devices.</p>
      <input bind:this={input} bind:value={pin} type="password" inputmode="numeric" autocomplete="current-password" placeholder="PIN" aria-label="PIN" />
      {#if error}<p class="err">{error}</p>{/if}
      <Button variant="primary" type="submit" disabled={busy || !pin.trim()}>Unlock</Button>
    {/if}
  </form>
</div>

<style>
  .gate { position: fixed; inset: 0; z-index: 200; display: grid; place-items: center; padding: 16px; background: var(--bg); }
  .sheet { width: min(360px, 100%); display: flex; flex-direction: column; gap: var(--sp3); padding: var(--sp5); background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; }
  h2 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 18px; }
  p { margin: 0; }
  input { font-size: 20px; letter-spacing: .2em; text-align: center; padding: 10px; }
  .err { color: var(--danger); font-size: 13px; }
</style>
