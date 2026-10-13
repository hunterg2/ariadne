<script lang="ts">
  import { onMount } from "svelte";
  import * as api from "./lib/api";
  import Icon from "./lib/ui/Icon.svelte";
  import Menu from "./lib/ui/Menu.svelte";
  import Toasts from "./lib/ui/Toasts.svelte";
  import Kbd from "./lib/ui/Kbd.svelte";
  import CommandPalette from "./lib/ui/CommandPalette.svelte";
  import PinGate from "./lib/ui/PinGate.svelte";
  import Library from "./routes/Library.svelte";
  import Tools from "./routes/Tools.svelte";
  import Settings from "./routes/Settings.svelte";
  import Placeholder from "./routes/Placeholder.svelte";
  import { route, go, href, section } from "./lib/router.svelte";
  import { loadSettings, ui, patchUi } from "./lib/stores/settings.svelte";
  import { reportError } from "./lib/stores/toasts.svelte";
  import { useHotkeys, keysFor } from "./lib/hotkeys";

  const NAV = [
    { id: "library", label: "Library", icon: "grid", key: "goLibrary" },
    { id: "tools", label: "Tools", icon: "tool", key: "goTools" },
    { id: "settings", label: "Settings", icon: "settings", key: "goSettings" },
  ];

  let projects: api.Project[] = $state([]);
  let searchInput: HTMLInputElement | undefined = $state();
  let paletteOpen = $state(false);
  /* another device that has not entered the PIN sees the gate instead */
  let gate: { need: api.PinNeed; message: string } | null = $state(null);
  const active = $derived(section());
  const activeProject = $derived(projects.find((p) => p.active));
  const theme = $derived(ui("theme"));

  onMount(async () => {
    api.onPinNeeded((need, message) => { if (!gate) gate = { need, message }; });
    await loadSettings();
    try { projects = (await api.projects()).projects; } catch { /* ignore */ }
    document.title = "Ariadne";
  });

  $effect(() => useHotkeys("global", {
    goLibrary: () => go("/library"), goTools: () => go("/tools"), goSettings: () => go("/settings"),
    search: () => { if (active !== "library") go("/library"); setTimeout(() => searchInput?.focus(), 50); },
    palette: () => (paletteOpen = !paletteOpen),
    escape: () => false,
  }));

  function cycleTheme() {
    const next = theme === "dark" ? "light" : theme === "light" ? "system" : "dark";
    patchUi({ theme: next });
  }
  async function switchProject(id: string) {
    try { await api.switchProject(id); location.reload(); } catch (e) { reportError(e); }
  }
</script>

<div class="app">
  <nav class="rail" aria-label="Sections">
    <a class="brand" href={href("/library")} title="Ariadne">
      <img src="/icon.png" alt="" width="26" height="26" />
    </a>
    {#each NAV as n (n.id)}
      <a class="nav" class:on={active === n.id} href={href("/" + n.id)} title={`${n.label} (${keysFor(n.key)[0] ?? ""})`}>
        <Icon name={n.icon} size={19} />
        <span>{n.label}</span>
      </a>
    {/each}
    <span class="spacer"></span>
    <button class="nav" onclick={cycleTheme} title={`Theme: ${theme}`}>
      <Icon name={theme === "light" ? "sun" : theme === "dark" ? "moon" : "palette"} size={19} /><span>Theme</span>
    </button>
  </nav>

  <div class="frame">
    <header class="topbar">
      <Menu>
        {#snippet trigger({ toggle })}
          <button class="project" onclick={toggle}>
            <Icon name="archive" size={15} /><span>{activeProject?.name ?? "Library"}</span><Icon name="chevronDown" size={13} />
          </button>
        {/snippet}
        {#snippet children({ close })}
          <div class="menu-title">Libraries</div>
          {#each projects as p (p.id)}
            <button class="menu-item" class:active={p.active} onclick={() => { if (!p.active) switchProject(p.id); close(); }}>{p.name}</button>
          {/each}
          <div class="menu-sep"></div>
          <button class="menu-item" onclick={() => { go("/settings"); close(); }}>Manage libraries…</button>
        {/snippet}
      </Menu>
      <span class="spacer"></span>
      {#if active !== "library"}
        <button class="search-hint" onclick={() => { go("/library"); setTimeout(() => searchInput?.focus(), 50); }} title="Search the library">
          <Icon name="search" size={14} /> <span class="lbl">Search the library</span> <Kbd combo="/" />
        </button>
      {/if}
      <button class="search-hint" onclick={() => (paletteOpen = true)} title="Command palette">
        <Icon name="command" size={14} /> <span class="lbl">Commands</span> <Kbd combo={keysFor("palette")[0] ?? "ctrl+k"} />
      </button>
    </header>

    <main class="content">
      {#if active === "library"}
        <Library bind:searchInput />
      {:else if active === "tools"}
        <Tools />
      {:else if active === "settings"}
        <Settings />
      {:else}
        <Placeholder icon="alert" title="Not found" text={`There is nothing at ${route.path}.`} />
      {/if}
    </main>
  </div>
</div>

<Toasts />
<CommandPalette open={paletteOpen} onclose={() => (paletteOpen = false)} />
{#if gate}<PinGate need={gate.need} message={gate.message} />{/if}

<style>
  .app { display: flex; height: 100%; }
  .rail { width: 64px; flex: none; display: flex; flex-direction: column; align-items: stretch; padding: var(--sp2) 0; background: var(--rail); border-right: 1px solid var(--border); gap: 2px; }
  .brand { display: grid; place-items: center; height: 44px; margin-bottom: var(--sp2); }
  .nav { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 8px 0; margin: 0 6px; border-radius: var(--r-sm); color: var(--muted); font-size: 10.5px; text-decoration: none; border: 0; background: transparent; cursor: pointer; font-family: inherit; }
  .nav:hover { background: var(--hover); color: var(--text); text-decoration: none; }
  .nav.on { background: var(--accent-soft); color: var(--accent); }
  .frame { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .topbar { display: flex; align-items: center; gap: var(--sp3); height: 44px; padding: 0 var(--sp4); background: var(--surface); border-bottom: 1px solid var(--border); }
  .project { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; color: var(--text); font: inherit; font-weight: 600; cursor: pointer; padding: 4px 8px; border-radius: var(--r-sm); }
  .project:hover { background: var(--hover); }
  .search-hint { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--muted); font: inherit; font-size: 12.5px; padding: 4px 10px; border-radius: var(--r-pill); cursor: pointer; }
  .search-hint:hover { color: var(--text); }
  .content { flex: 1; min-height: 0; }

  /* phones: the rail becomes a tab bar along the bottom, the top bar keeps
     only icons, and screens get the full width */
  @media (max-width: 760px) {
    .app { flex-direction: column; }
    .rail {
      position: fixed; left: 0; right: 0; bottom: 0; width: auto; z-index: 150;
      height: calc(54px + env(safe-area-inset-bottom)); padding: 0 0 env(safe-area-inset-bottom);
      flex-direction: row; justify-content: space-around; align-items: stretch;
      border-right: 0; border-top: 1px solid var(--border);
    }
    .brand, .rail .spacer, .rail button.nav { display: none; }
    .nav { flex: 1; margin: 0; padding: 7px 0 4px; border-radius: 0; font-size: 10px; gap: 2px; }
    .frame { padding-bottom: calc(54px + env(safe-area-inset-bottom)); }
    .topbar { padding: 0 var(--sp2); gap: var(--sp2); }
    .search-hint .lbl, .search-hint :global(kbd) { display: none; }
    .search-hint { padding: 5px 9px; }
  }
</style>
