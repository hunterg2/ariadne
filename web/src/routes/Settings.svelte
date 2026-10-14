<script lang="ts">
  import { onMount } from "svelte";
  import * as api from "../lib/api";
  import Button from "../lib/ui/Button.svelte";
  import Kbd from "../lib/ui/Kbd.svelte";
  import Icon from "../lib/ui/Icon.svelte";
  import BrowseDialog from "../lib/library/BrowseDialog.svelte";
  import BugReportDialog from "../lib/settings/BugReportDialog.svelte";
  import { settings, ui, patchUi, patchSettings, flushSettings, UI_DEFAULTS } from "../lib/stores/settings.svelte";
  import { library } from "../lib/stores/library.svelte";
  import { ACTIONS, keysFor, comboOf } from "../lib/hotkeys";
  import { toast, reportError } from "../lib/stores/toasts.svelte";
  import { bytes, count, basename, relative } from "../lib/format";

  let cache: Awaited<ReturnType<typeof api.cacheStats>> | null = $state(null);
  let lib: Awaited<ReturnType<typeof api.libraryStats>> | null = $state(null);
  let projects: api.Project[] = $state([]);
  let recording: string | null = $state(null);
  let sys: api.SystemInfo | null = $state(null);
  let authSt: api.AuthStatus | null = $state(null);
  let pin = $state("");
  let pinBusy = $state(false);
  let upd: api.UpdateState | null = $state(null);
  let updBusy = $state(false);
  let diagBusy = $state(false);
  let reportOpen = $state(false);

  /* ---- updates and diagnostics ---- */
  async function checkUpdates() {
    updBusy = true;
    try {
      upd = await api.checkUpdates();
      toast(upd.error ? upd.error : upd.newer ? `Ariadne ${upd.latest} is out.` : "You have the newest release.", { error: !!upd.error });
    } catch (e) { reportError(e); } finally { updBusy = false; }
  }
  async function copyText(text: string) {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return; }
    // plain http from another device has no clipboard API; the old way still works
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  async function copyDiagnostics() {
    diagBusy = true;
    try {
      const d = await api.diagnostics();
      try {
        await copyText(d.text);
        toast("Diagnostics copied. Paste them into a bug report.");
      } catch {
        // a browser that refuses the clipboard still gets the text, as a file
        location.href = "/api/system/diagnostics?download=1";
        toast("The browser refused the clipboard, so the diagnostics are downloading as a file instead.");
      }
    } catch (e) { reportError(e, "Could not gather the diagnostics."); } finally { diagBusy = false; }
  }

  async function savePin(e: Event) {
    e.preventDefault();
    if (pin.trim().length < 4 || pinBusy) return;
    pinBusy = true;
    try {
      authSt = await api.setPin(pin);
      pin = "";
      toast("PIN saved. Other devices are asked for it from now on.");
    } catch (err) { reportError(err); } finally { pinBusy = false; }
  }
  async function removePin() {
    if (!confirm("Remove the PIN? Other devices are turned away until a new one is set.")) return;
    pinBusy = true;
    try { authSt = await api.clearPin(); toast("PIN removed."); } catch (err) { reportError(err); } finally { pinBusy = false; }
  }

  /* ---- AI tagger ---- */
  const TAGGER_ABOUT: Record<string, string> = {
    prompt: "Reads the generation prompt each image already carries. No model, nothing leaves this machine, and it is instant.",
    ollama: "Uses a vision model running on your own machine. Free and private, but Ollama has to be running with a vision model pulled, such as llava or qwen2-vl.",
    openai: "Any service speaking the OpenAI chat API: OpenAI itself, LM Studio, llama.cpp's server, OpenRouter. Your images are uploaded to it, and a paid service will charge per image.",
    anthropic: "Claude's API. Your images are uploaded to Anthropic, and it charges per image.",
  };
  const TAGGER_HINTS: Record<string, [string, string]> = {
    ollama: ["llava", "http://localhost:11434"], openai: ["gpt-4o-mini", "https://api.openai.com/v1"], anthropic: ["claude-haiku-5-5", "https://api.anthropic.com/v1"],
  };
  const tagger = $derived({ backend: "prompt", model: "", url: "", api_key: "", max_tags: 12, prefer_existing: true, include_model: false, include_loras: false, ...((settings.data.tagger as Record<string, any>) ?? {}) });
  let taggerStatus: { ok: boolean; message: string } | null = $state(null);
  function setTagger(patch: Record<string, unknown>) { patchSettings({ tagger: { ...tagger, ...patch } }); taggerStatus = null; }
  async function testTagger() {
    taggerStatus = { ok: true, message: "Checking…" };
    try { await flushSettings(); taggerStatus = await api.tagCheck(tagger); } catch (e) { taggerStatus = { ok: false, message: (e as Error).message }; }
  }

  /* ---- watched folders ---- */
  interface AutoFolder { id: string; path: string; name: string; include_root: boolean; enabled: boolean; excluded?: string[] }
  const autoFolders = $derived<AutoFolder[]>((settings.data.auto_folders as AutoFolder[] | undefined) ?? []);
  let watchOpen = $state(false);
  async function saveAutoFolders(next: AutoFolder[]) {
    patchSettings({ auto_folders: next });
    await flushSettings();
    await library.loadSidebar();
  }
  function patchAutoFolder(id: string, patch: Partial<AutoFolder>) {
    saveAutoFolders(autoFolders.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  }
  function addAutoFolder(path: string) {
    watchOpen = false;
    if (autoFolders.some((a) => a.path === path)) { toast("That folder is already being watched.", { error: true }); return; }
    saveAutoFolders([...autoFolders, { id: "auto_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), path, name: basename(path), include_root: false, enabled: true }]);
    toast("Watching it. Its subfolders appear as a group in the sidebar.");
  }

  /* ---- editor ---- */
  const editDefaults = $derived((settings.data.edit_defaults as Record<string, any> | undefined) ?? {});

  async function refresh() {
    try { cache = await api.cacheStats(); lib = await api.libraryStats(); projects = (await api.projects()).projects; } catch { /* ignore */ }
    try { sys = await api.systemInfo(); } catch { /* ignore */ }
    try { authSt = await api.authStatus(); } catch { /* ignore */ }
    try { upd = await api.updateState(); } catch { /* ignore */ }
  }
  onMount(refresh);

  async function toggleStartup(on: boolean) {
    try {
      const res = await api.setStartup(on);
      sys = res;
      toast(res.message, { error: !res.success });
    } catch (e) { reportError(e); }
  }

  function record(id: string) {
    recording = id;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      window.removeEventListener("keydown", onKey, true);
      if (e.key === "Escape") { recording = null; return; }
      const combo = comboOf(e);
      if (["control", "shift", "alt", "meta"].includes(e.key.toLowerCase())) { recording = null; return; }
      patchUi({ hotkeys: { ...(settings.data.ui?.hotkeys ?? {}), [id]: [combo] } });
      recording = null;
      toast(`${ACTIONS.find((a) => a.id === id)?.label}: ${combo}`);
    };
    window.addEventListener("keydown", onKey, true);
  }
  function resetKey(id: string) {
    const next = { ...(settings.data.ui?.hotkeys ?? {}) };
    delete next[id];
    patchUi({ hotkeys: next });
  }

  async function maintenance(what: "prune" | "thumbs" | "meta") {
    try {
      if (what === "prune") { const r = await api.pruneCache(); toast(`Removed ${count(r.removed)} stale thumbnails.`); }
      else if (what === "thumbs") { await api.clearCache("thumbs"); toast("Thumbnails will be rebuilt as you browse."); }
      else { await api.clearCache("meta"); toast("Metadata will be re-read as you browse."); }
      refresh();
    } catch (e) { reportError(e); }
  }

  async function switchProject(id: string) {
    try { await api.switchProject(id); location.reload(); } catch (e) { reportError(e); }
  }
  async function newProject() {
    const name = prompt("Name for the new library");
    if (!name) return;
    try { await api.createProject(name); location.reload(); } catch (e) { reportError(e); }
  }
</script>

<div class="settings">
  <h2>Settings</h2>

  <section>
    <h3>Appearance</h3>
    <div class="grid2">
      <label class="field" for="theme">Theme</label>
      <select id="theme" value={ui("theme")} onchange={(e) => patchUi({ theme: (e.currentTarget as HTMLSelectElement).value as any })}>
        <option value="system">Follow the system</option><option value="dark">Dark</option><option value="light">Light</option>
      </select>
      <label class="field" for="density">Density</label>
      <select id="density" value={ui("density")} onchange={(e) => patchUi({ density: (e.currentTarget as HTMLSelectElement).value as any })}>
        <option value="comfortable">Comfortable</option><option value="compact">Compact</option>
      </select>
      <label class="field" for="stars">Stars on tiles</label>
      <label class="check"><input id="stars" type="checkbox" checked={ui("stars_always")} onchange={(e) => patchUi({ stars_always: e.currentTarget.checked })} /> Always show the star row, not only on hover</label>
      <label class="field" for="gsize">Tile size</label>
      <input id="gsize" type="range" min="110" max="420" step="10" value={ui("grid_size")} oninput={(e) => patchUi({ grid_size: +e.currentTarget.value })} />
    </div>
  </section>

  <section>
    <h3>Keyboard</h3>
    <p class="hint">Click a key to change it, then press the new one. Escape cancels.</p>
    <div class="keys">
      {#each ACTIONS as a (a.id)}
        <div class="key-row">
          <span class="label">{a.label}</span>
          <span class="scope">{a.scope}</span>
          <button class="combo" class:rec={recording === a.id} onclick={() => record(a.id)}>
            {#if recording === a.id}press a key…{:else}{#each keysFor(a.id) as k}<Kbd combo={k} />{/each}{/if}
          </button>
          {#if settings.data.ui?.hotkeys?.[a.id]}<button class="reset" onclick={() => resetKey(a.id)} title="Reset"><Icon name="refresh" size={12} /></button>{/if}
        </div>
      {/each}
    </div>
  </section>

  <section>
    <h3>Library</h3>
    <div class="grid2">
      <label class="field" for="delmode">When deleting</label>
      <select id="delmode" value={settings.data.delete_mode} onchange={(e) => patchSettings({ delete_mode: e.currentTarget.value })}>
        <option value="soft">Move to a trash subfolder (can be restored)</option>
        <option value="hard">Recycle bin, or delete outright</option>
      </select>
      <label class="field" for="tq">Thumbnail quality</label>
      <input id="tq" type="number" min="50" max="100" value={settings.data.thumb_quality} onchange={(e) => patchSettings({ thumb_quality: +e.currentTarget.value })} />
      <label class="field" for="warm">Thumbnails</label>
      <label class="check"><input id="warm" type="checkbox" checked={settings.data.warm_thumbs !== false} onchange={(e) => patchSettings({ warm_thumbs: e.currentTarget.checked })} /> Build them while a folder is being read, so a big folder scrolls smoothly from the first visit</label>
      <label class="field" for="cull">Cull mode</label>
      <label class="check"><input id="cull" type="checkbox" checked={settings.data.cull_auto_advance !== false} onchange={(e) => patchSettings({ cull_auto_advance: e.currentTarget.checked })} /> Move to the next image after rating</label>
    </div>
    <div class="row wrap">
      <Button size="sm" icon="refresh" onclick={() => maintenance("prune")}>Clean up thumbnails</Button>
      <Button size="sm" onclick={() => maintenance("thumbs")}>Rebuild thumbnails</Button>
      <Button size="sm" onclick={() => maintenance("meta")}>Re-read metadata</Button>
    </div>
    {#if cache}<p class="hint">{count(cache.files)} thumbnails, {bytes(cache.bytes)}. Database {bytes(cache.db_bytes)}.{#if lib} {lib.backups} backups, latest {lib.latest_backup}.{/if}</p>{/if}
  </section>

  <section>
    <h3>Libraries</h3>
    <p class="hint">Each library has its own folders, ratings, tags and collections.</p>
    <div class="projects">
      {#each projects as p (p.id)}
        <div class="proj" class:on={p.active}>
          <Icon name="archive" size={15} /><span>{p.name}</span><span class="faint">{bytes(p.size)}</span><span class="spacer"></span>
          {#if !p.active}<Button size="sm" onclick={() => switchProject(p.id)}>Open</Button>{:else}<span class="badge accent">open</span>{/if}
        </div>
      {/each}
    </div>
    <div class="row"><Button size="sm" icon="plus" onclick={newProject}>New library</Button></div>
  </section>

  <section>
    <h3>Backup</h3>
    <p class="hint">The open library's database, settings and sidebar in one zip, together with the key file. Save it somewhere other than this computer now and then: your image folders are not in it, and everything else can be rebuilt.</p>
    {#if sys}
      <div class="grid2">
        <span class="field">Key file</span>
        <div class="stack">
          {#if sys.backup.key_exists}
            <span class="hint"><code>{sys.backup.key_path}</code> signs the cookie other devices get after the PIN. A new one only signs them out.</span>
          {:else}
            <span class="hint">None yet. It is made the first time another device enters the PIN, at <code>{sys.backup.key_path}</code>.</span>
          {/if}
        </div>
        <span class="field">Backup</span>
        <div class="row wrap">
          <Button size="sm" icon="download" onclick={() => (location.href = "/api/backup")}>Download a backup</Button>
          <span class="hint">{count(sys.backup.files.length)} files, {bytes(sys.backup.bytes)} before compression. Restoring is copying them back into the data folder; the zip says how.</span>
        </div>
      </div>
    {/if}
  </section>

  <section>
    <h3>Background service</h3>
    <p class="hint">Tray mode keeps Ariadne running without a console window, so a phone on the network can always reach it; start at logon makes that automatic.</p>
    {#if sys}
      <div class="grid2">
        <span class="field">Tray mode</span>
        <span>{#if sys.tray_available}Available: run <code>start.bat --tray</code> (or the startup shortcut below).{:else}Needs the pystray package: <code>py -m pip install pystray</code>, then run <code>start.bat --tray</code>.{/if}</span>
        <span class="field">Start at logon</span>
        <div class="row">
          {#if !sys.startup_supported}<span class="hint">Only wired up on Windows so far.</span>
          {:else}
            <Button size="sm" variant={sys.startup_enabled ? "default" : "primary"} icon={sys.startup_enabled ? "x" : "play"} onclick={() => toggleStartup(!sys!.startup_enabled)}>{sys.startup_enabled ? "Remove from startup" : "Start with Windows"}</Button>
            {#if sys.startup_enabled}<span class="hint">{sys.startup_path}</span>{/if}
          {/if}
        </div>
        <span class="field">Other devices</span>
        <div class="stack">
          {#if sys.urls.length}
            <span>Reachable on your network at {#each sys.urls as u, i (u)}{#if i}, {/if}<a href={u} target="_blank" rel="noopener">{u}</a>{/each}.</span>
            {#if authSt && !authSt.has_pin}
              <span class="bad">No PIN is set, so other devices are turned away. Set one below.</span>
            {:else}
              <span class="hint">Other devices are asked for the PIN below, then remembered for 30 days. Start without <code>--host</code> to go back to this computer only.</span>
            {/if}
          {:else}
            <span>Only this computer can open Ariadne right now.</span>
            <span class="hint">To use it from a phone or laptop on the same network, set a PIN below, then start it with <code>start.bat --lan</code> (or <code>--host 0.0.0.0</code>) and open the address it prints.</span>
          {/if}
        </div>
        <label class="field" for="pin">PIN</label>
        <div class="stack">
          <form class="row" onsubmit={savePin}>
            <input id="pin" type="password" inputmode="numeric" autocomplete="off" placeholder={authSt?.has_pin ? "New PIN" : "At least 4 characters"} bind:value={pin} style="width:170px" />
            <Button size="sm" variant="primary" type="submit" disabled={pin.trim().length < 4 || pinBusy}>{authSt?.has_pin ? "Change PIN" : "Set PIN"}</Button>
            {#if authSt?.has_pin}<Button size="sm" variant="ghost" disabled={pinBusy} onclick={removePin}>Remove</Button>{/if}
            {#if authSt}<span class={authSt.has_pin ? "ok" : "hint"}>{authSt.has_pin ? "A PIN is set." : "No PIN yet."}</span>{/if}
          </form>
          <span class="hint">Kept as a salted hash in the library database, never in settings.json. Changing or removing it signs every other device out; ten wrong guesses lock a device out for fifteen minutes.</span>
        </div>
      </div>
    {/if}
  </section>

  <section>
    <h3>Watched folders</h3>
    <p class="hint">A watched folder's subfolders appear as a group in the sidebar and stay in step as folders come and go. Point it at a generator's output directory.</p>
    <div class="list">
      {#each autoFolders as a (a.id)}
        <div class="auto" class:off={!a.enabled}>
          <div class="row">
            <input type="text" value={a.name} placeholder="Name shown in the sidebar" onchange={(e) => patchAutoFolder(a.id, { name: e.currentTarget.value.trim() || basename(a.path) })} />
            <Button size="sm" variant="ghost" square icon="x" title="Stop watching this folder" onclick={() => saveAutoFolders(autoFolders.filter((x) => x.id !== a.id))} />
          </div>
          <span class="mono faint" title={a.path}>{a.path}</span>
          <div class="row wrap">
            <label class="check"><input type="checkbox" checked={a.enabled} onchange={(e) => patchAutoFolder(a.id, { enabled: e.currentTarget.checked })} /> Keep this group in sync</label>
            <label class="check"><input type="checkbox" checked={!!a.include_root} onchange={(e) => patchAutoFolder(a.id, { include_root: e.currentTarget.checked })} /> Include images sitting loose in the folder, as their own entry</label>
          </div>
        </div>
      {:else}
        <p class="hint">None yet.</p>
      {/each}
    </div>
    <div class="row"><Button size="sm" icon="folderPlus" onclick={() => (watchOpen = true)}>Watch a folder…</Button></div>
  </section>

  <section>
    <h3>Suggesting tags</h3>
    <div class="grid2">
      <label class="field" for="tg-backend">Source</label>
      <select id="tg-backend" value={tagger.backend} onchange={(e) => setTagger({ backend: e.currentTarget.value })}>
        <option value="prompt">From the prompt already in the image</option>
        <option value="ollama">A model on this machine, through Ollama</option>
        <option value="openai">An OpenAI-compatible service</option>
        <option value="anthropic">Anthropic</option>
      </select>
      <span></span><p class="hint">{TAGGER_ABOUT[tagger.backend] ?? ""}</p>
      {#if tagger.backend !== "prompt"}
        <label class="field" for="tg-model">Model</label>
        <input id="tg-model" type="text" value={tagger.model} placeholder={TAGGER_HINTS[tagger.backend]?.[0] ?? ""} onchange={(e) => setTagger({ model: e.currentTarget.value.trim() })} />
        <label class="field" for="tg-url">Address</label>
        <input id="tg-url" type="text" value={tagger.url} placeholder={TAGGER_HINTS[tagger.backend]?.[1] ?? ""} onchange={(e) => setTagger({ url: e.currentTarget.value.trim() })} />
        {#if tagger.backend !== "ollama"}
          <label class="field" for="tg-key">API key</label>
          <div class="stack">
            <input id="tg-key" type="password" value={tagger.api_key} placeholder="sk-…" autocomplete="off" onchange={(e) => setTagger({ api_key: e.currentTarget.value })} />
            <span class="hint">Kept in settings.json in plain text, on this machine only. Anyone who can read that file can read the key.</span>
          </div>
        {/if}
      {/if}
      <label class="field" for="tg-max">At most</label>
      <div class="row">
        <input id="tg-max" type="number" min="3" max="30" value={tagger.max_tags} style="width:80px" onchange={(e) => setTagger({ max_tags: Math.max(3, Math.min(30, +e.currentTarget.value || 12)) })} />
        <span class="hint">tags per image</span>
        <span class="spacer"></span>
        <Button size="sm" onclick={testTagger}>Test it</Button>
      </div>
      {#if taggerStatus}<span></span><p class={taggerStatus.ok ? "ok" : "bad"}>{taggerStatus.message}</p>{/if}
      <span class="field">Vocabulary</span>
      <label class="check"><input type="checkbox" checked={tagger.prefer_existing !== false} onchange={(e) => setTagger({ prefer_existing: e.currentTarget.checked })} /> Reuse the tags I already have where they fit, so one thing keeps one spelling</label>
      {#if tagger.backend === "prompt"}
        <span class="field">Also tag with</span>
        <div class="stack">
          <label class="check"><input type="checkbox" checked={!!tagger.include_model} onchange={(e) => setTagger({ include_model: e.currentTarget.checked })} /> The checkpoint name</label>
          <label class="check"><input type="checkbox" checked={!!tagger.include_loras} onchange={(e) => setTagger({ include_loras: e.currentTarget.checked })} /> Each LoRA name</label>
        </div>
      {/if}
    </div>
  </section>

  <section>
    <h3>Editor</h3>
    <div class="grid2">
      <span class="field">Copies</span>
      <div class="stack">
        <label class="check"><input type="checkbox" checked={settings.data.tag_edits !== false} onchange={(e) => patchSettings({ tag_edits: e.currentTarget.checked })} /> Tag edited copies #edited</label>
        <label class="check"><input type="checkbox" checked={settings.data.warn_quality !== false} onchange={(e) => patchSettings({ warn_quality: e.currentTarget.checked })} /> Explain what a lossy save costs before writing it</label>
      </div>
      <span class="field">Editor defaults</span>
      <div class="row wrap">
        <span class="hint">{editDefaults.format ? `${String(editDefaults.format).toUpperCase()}${editDefaults.format !== "png" ? ` at ${editDefaults.quality ?? 92}` : ""}, ${editDefaults.metadata ?? "generation"} metadata, ${editDefaults.dest === "folder" ? "asks for a folder" : "_edit suffix"}.` : "Remembered from the last save."}</span>
        {#if editDefaults.format}<Button size="sm" variant="ghost" onclick={() => patchSettings({ edit_defaults: {} })}>Reset</Button>{/if}
      </div>
    </div>
  </section>

  <section>
    <h3>About</h3>
    {#if sys}
      <div class="grid2">
        <span class="field">Version</span>
        <div class="stack">
          <span>
            Ariadne {sys.version}.
            {#if upd?.newer}<a href={upd.url} target="_blank" rel="noopener">Ariadne {upd.latest} is out.</a> Download the zip from the release page and replace its app and python folders.
            {:else if upd?.error}<span class="hint">{upd.error}</span>
            {:else if upd?.latest}<span class="hint">You have the newest release.</span>
            {:else}<span class="hint">Not checked yet.</span>{/if}
          </span>
          <div class="row wrap">
            <Button size="sm" icon="refresh" disabled={updBusy} onclick={checkUpdates}>Check for a newer release</Button>
            <label class="check"><input type="checkbox" checked={settings.data.check_updates !== false} onchange={(e) => patchSettings({ check_updates: e.currentTarget.checked })} /> Check once a day</label>
            {#if upd?.checked_at}<span class="hint">Last checked {relative(upd.checked_at)}.</span>{/if}
          </div>
          <span class="hint">Asks GitHub for the newest release of {upd?.repo ?? "the public repository"}. Nothing is downloaded or installed by itself.</span>
        </div>
        <span class="field">Diagnostics</span>
        <div class="stack">
          <div class="row wrap">
            <Button size="sm" icon="alert" onclick={() => (reportOpen = true)}>Report a bug</Button>
            <Button size="sm" icon="copy" disabled={diagBusy} onclick={copyDiagnostics}>Copy diagnostics</Button>
            <Button size="sm" icon="download" onclick={() => (location.href = "/api/system/log")}>Download the log</Button>
          </div>
          <span class="hint">Report a bug drafts a GitHub issue from what you type and these diagnostics, shows you the text, and lets you submit it there. The diagnostics are versions, settings, accounts (never their secrets), what the scheduler last did and the end of the log. Everything Ariadne reports goes to <code>{sys.log_path}</code>, 1 MB with three older copies kept.</span>
        </div>
      </div>
    {/if}
  </section>
</div>

<BrowseDialog open={watchOpen} title="Watch a folder" confirmLabel="Watch this folder" start={library.folder ?? ""} onpick={addAutoFolder} onclose={() => (watchOpen = false)} />
<BugReportDialog open={reportOpen} onclose={() => (reportOpen = false)} />

<style>
  .settings { padding: var(--sp5); overflow: auto; height: 100%; display: flex; flex-direction: column; gap: var(--sp5); max-width: 860px; }
  section { display: flex; flex-direction: column; gap: var(--sp3); padding-bottom: var(--sp5); border-bottom: 1px solid var(--border); }
  .grid2 { display: grid; grid-template-columns: 160px 1fr; gap: var(--sp2) var(--sp4); align-items: center; }
  .grid2 .field { margin: 0; }
  @media (max-width: 760px) {
    .settings { padding: var(--sp3); gap: var(--sp4); }
    .grid2 { grid-template-columns: 1fr; gap: var(--sp1) var(--sp2); }
    .grid2 .field { margin-top: var(--sp2); font-weight: 600; }
  }
  .check { display: inline-flex; align-items: center; gap: 8px; }
  .keys { display: flex; flex-direction: column; }
  .key-row { display: flex; align-items: center; gap: var(--sp3); padding: 5px 0; border-bottom: 1px solid var(--border); }
  .key-row .label { flex: 1; }
  .key-row .scope { color: var(--faint); font-size: 11px; width: 60px; }
  .combo { display: inline-flex; gap: 4px; min-width: 120px; justify-content: flex-end; border: 0; background: transparent; cursor: pointer; font: inherit; color: var(--muted); }
  .combo.rec { color: var(--accent); }
  .reset { border: 0; background: transparent; color: var(--muted); cursor: pointer; display: flex; }
  .projects { display: flex; flex-direction: column; gap: 4px; }
  .proj { display: flex; align-items: center; gap: var(--sp2); padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--r-sm); }
  .proj.on { border-color: var(--accent); }
  .wrap { flex-wrap: wrap; }
  .list { display: flex; flex-direction: column; gap: var(--sp2); }
  .auto { display: flex; flex-direction: column; gap: 6px; padding: var(--sp3); border: 1px solid var(--border); border-radius: var(--r-sm); }
  .auto.off { opacity: .6; }
  .auto input[type=text] { flex: 1; }
  .auto .mono { font-size: 11.5px; word-break: break-all; }
  .ok { color: var(--select); font-size: 12.5px; }
  .bad { color: var(--danger); font-size: 12.5px; }
  .warn { color: var(--warn); font-size: 12.5px; }
</style>
