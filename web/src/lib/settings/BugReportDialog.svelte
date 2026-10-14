<script lang="ts">
  /* A bug report: what went wrong and what came before, with the
     diagnostics, drafted by the server (services/system.report) and
     handed to GitHub as a prefilled new issue in the public repository.
     The user reads it there and submits it; nothing leaves this computer
     before that. Copy and Download are for people without an account. */
  import { untrack } from "svelte";
  import * as api from "../api";
  import Modal from "../ui/Modal.svelte";
  import Button from "../ui/Button.svelte";
  import { toast, reportError } from "../stores/toasts.svelte";

  interface Props { open: boolean; onclose: () => void }
  let { open, onclose }: Props = $props();

  let summary = $state("");
  let steps = $state("");
  let includeDiag = $state(true);
  let report: api.BugReport | null = $state(null);
  let busy = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    if (open) untrack(() => { summary = ""; steps = ""; includeDiag = true; report = null; refresh(); });
  });

  /* the preview follows the typing, a moment behind */
  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(refresh, 300);
  }
  async function refresh() {
    busy = true;
    try { report = await api.bugReport(summary, steps, includeDiag); }
    catch (e) { reportError(e, "Could not put the report together."); }
    finally { busy = false; }
  }

  function openIssue() {
    if (!report) return;
    const tab = window.open(report.url, "_blank");
    if (!tab) { toast("The browser blocked the new tab. Copy the report and open the issues page yourself.", { error: true }); return; }
    toast("Read it over on GitHub and press Submit there.");
    onclose();
  }
  async function copy() {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report.text);
      toast("Report copied.");
    } catch {
      // a browser that refuses the clipboard still gets the text, as a file
      location.href = api.bugReportDownloadUrl(summary, steps, includeDiag);
      toast("The browser refused the clipboard, so the report is downloading as a file instead.");
    }
  }
  function download() {
    location.href = api.bugReportDownloadUrl(summary, steps, includeDiag);
  }
</script>

<Modal {open} {onclose} title="Report a bug" width={640}>
  <div class="stack">
    <div>
      <label class="field" for="bug-summary">What went wrong?</label>
      <textarea id="bug-summary" bind:value={summary} oninput={schedule} rows="3"
        placeholder="e.g. Dragging a photo onto a collection does nothing while the grid is sorted by name."></textarea>
    </div>
    <div>
      <label class="field" for="bug-steps">What did you do just before? (optional)</label>
      <textarea id="bug-steps" bind:value={steps} oninput={schedule} rows="3"
        placeholder="The screen you were on, what you pressed, the file if one is involved."></textarea>
    </div>
    <label class="check">
      <input type="checkbox" bind:checked={includeDiag} onchange={refresh} />
      <span>Include the diagnostics: versions, settings, folder paths and account names (never a password or a key), and the last lines of the log.</span>
    </label>
    <div>
      <label class="field" for="bug-preview">What will be sent</label>
      <pre id="bug-preview" class="preview">{report?.body ?? (busy ? "Putting it together…" : "")}</pre>
      {#if report?.cut}
        <p class="hint">Older log lines were left out so the address fits; the downloaded report has all of them. Attach it to the issue if the log matters.</p>
      {/if}
    </div>
    <p class="hint">
      "Open on GitHub" opens a new issue at github.com/{report?.repo ?? "hunterg2/ariadne"} with this filled in. You read it there and press Submit yourself; nothing is sent before that.
      It needs a GitHub account; without one, copy or download the report and send it another way.
    </p>
  </div>
  {#snippet actions()}
    <Button variant="ghost" icon="copy" disabled={!report} onclick={copy}>Copy</Button>
    <Button variant="ghost" icon="download" disabled={!report} onclick={download}>Download</Button>
    <span class="spacer"></span>
    <Button onclick={onclose}>Cancel</Button>
    <Button variant="primary" icon="send" disabled={!report || !summary.trim()} onclick={openIssue}>Open on GitHub</Button>
  {/snippet}
</Modal>

<style>
  .preview {
    max-height: 200px; overflow: auto; margin: 0; padding: var(--sp2) var(--sp3);
    border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--bg);
    font-size: 11.5px; line-height: 1.4; white-space: pre-wrap; word-break: break-word; color: var(--muted);
  }
  .check { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; }
  .check input { margin-top: 3px; }
  .spacer { flex: 1; }
</style>
