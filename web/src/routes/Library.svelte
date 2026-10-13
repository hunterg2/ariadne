<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { HistoryItem } from "../lib/api";
  import * as api from "../lib/api";
  import Sidebar from "../lib/library/Sidebar.svelte";
  import FilterBar from "../lib/library/FilterBar.svelte";
  import SelectionBar from "../lib/library/SelectionBar.svelte";
  import Grid from "../lib/library/Grid.svelte";
  import Inspector from "../lib/library/Inspector.svelte";
  import Viewer from "../lib/library/Viewer.svelte";
  import TagEditor from "../lib/library/TagEditor.svelte";
  import BrowseDialog from "../lib/library/BrowseDialog.svelte";
  import CollectionDialog from "../lib/library/CollectionDialog.svelte";
  import TrashDialog from "../lib/library/TrashDialog.svelte";
  import DuplicateReview from "../lib/library/DuplicateReview.svelte";
  import CompareDialog from "../lib/library/CompareDialog.svelte";
  import TagRun from "../lib/library/TagRun.svelte";
  import PromptsDialog from "../lib/library/PromptsDialog.svelte";
  import ImageEditor from "../lib/library/ImageEditor.svelte";
  import Icon from "../lib/ui/Icon.svelte";
  import { library } from "../lib/stores/library.svelte";
  import { settings, ui, patchUi } from "../lib/stores/settings.svelte";
  import { viewport } from "../lib/stores/viewport.svelte";
  import { toast, reportError } from "../lib/stores/toasts.svelte";
  import { useHotkeys } from "../lib/hotkeys";
  import { route, replace } from "../lib/router.svelte";
  import { count } from "../lib/format";

  interface Props { searchInput?: HTMLInputElement }
  let { searchInput = $bindable() }: Props = $props();

  let grid: Grid | undefined = $state();
  let viewer: { index: number; cull: boolean } | null = $state(null);
  let tagFor: string[] | null = $state(null);
  let collectFor: string[] | null = $state(null);
  let trashOpen = $state(false);
  let browse: { purpose: "add" | "fix" | "copy" | "move"; item?: HistoryItem; paths?: string[] } | null = $state(null);
  let ctx: { x: number; y: number; index: number } | null = $state(null);
  let dupes: { folder: string | null } | null = $state(null);
  let compareRows: api.ImageRow[] | null = $state(null);
  let tagRunPaths: string[] | null = $state(null);
  let promptsOpen = $state(false);
  let editPath: string | null = $state(null);

  function onePath(): string | null {
    const t = library.targets();
    if (t.length === 1) return t[0];
    toast(t.length ? "Pick one image for this." : "Pick an image first.", { error: true });
    return null;
  }

  function compare(paths: string[]) {
    const rows = paths.map((p) => library.rows.find((r) => r?.path === p)).filter(Boolean) as api.ImageRow[];
    if (rows.length < 2) { toast("Select at least two images to compare.", { error: true }); return; }
    if (rows.length > 6) toast("Comparing the first 6.");
    compareRows = rows.slice(0, 6);
  }

  const inspectorOpen = $derived(ui("inspector_open"));
  const sidebarWidth = $derived(ui("sidebar_width"));
  /* phones: the sidebar is a drawer that closes once a folder is picked, and
     the inspector is a sheet over the grid for the focused image */
  let drawer = $state(false);
  $effect(() => { library.scope; drawer = false; });
  const infoSheet = $derived(viewport.phone && inspectorOpen && !!library.focused);

  onMount(async () => {
    await library.loadSidebar();
    applyRoute();
  });

  /* The URL names the scope; the scope writes the URL. Only one direction
     runs at a time, guarded by comparing before writing. */
  function applyRoute() {
    const folder = route.query.get("folder");
    const collection = route.query.get("collection");
    const tool = route.query.get("tool");
    if (tool) {
      setTimeout(() => {
        if (tool === "dupes") dupes = { folder: folder || library.folder };
        else if (tool === "prompts") promptsOpen = true;
        else if (tool === "compare") compare(Array.from(library.selected));
        else if (tool === "autotag") tagRunPaths = library.targets();
        else if (tool === "edit") editPath = onePath();
      }, 50);
    }
    if (folder) {
      if (!(library.scope.type === "folder" && library.scope.path === folder)) library.open({ type: "folder", path: folder });
    } else if (collection) {
      if (!(library.scope.type === "collection" && library.scope.id === collection)) library.open({ type: "collection", id: collection });
    } else if (library.rows.length === 0 && library.total === 0 && !library.loading) {
      const last = settings.data.last_folder;
      if (last && library.findFolder(last)) library.open({ type: "folder", path: last });
      else library.open({ type: "all" });
    }
  }
  $effect(() => {
    route.query;            // re-run on navigation
    untrack(applyRoute);
  });
  $effect(() => {
    const s = library.scope;
    const want = s.type === "folder" ? { folder: s.path } : s.type === "collection" ? { collection: s.id } : {};
    const have = { folder: route.query.get("folder") ?? undefined, collection: route.query.get("collection") ?? undefined };
    if ((want as any).folder !== have.folder || (want as any).collection !== have.collection || route.query.get("tool")) replace("/library", want);
  });

  function openViewer(index: number, cull = false) {
    if (index < 0 || index >= library.total) return;
    library.setFocus(index);
    viewer = { index, cull };
  }

  function moveFocus(delta: number) {
    const next = library.focus < 0 ? 0 : library.focus + delta;
    if (next >= 0 && next < library.total) library.setFocus(next);
  }

  $effect(() => useHotkeys("library", {
    star1: () => library.rate(library.targets(), { stars: 1 }),
    star2: () => library.rate(library.targets(), { stars: 2 }),
    star3: () => library.rate(library.targets(), { stars: 3 }),
    star4: () => library.rate(library.targets(), { stars: 4 }),
    star5: () => library.rate(library.targets(), { stars: 5 }),
    star0: () => library.rate(library.targets(), { stars: 0 }),
    reject: () => {
      const t = library.targets();
      const f = library.focused;
      library.rate(t, { rejected: t.length === 1 && f ? !f.rejected : true });
    },
    tag: () => { const t = library.targets(); if (t.length) tagFor = t; },
    select: () => { const f = library.focused; if (f) { library.toggleSelect(f.path); library.anchor = library.focus; } },
    info: () => patchUi({ inspector_open: !ui("inspector_open") }),
    open: () => openViewer(library.focus < 0 ? 0 : library.focus),
    cull: () => openViewer(library.focus < 0 ? 0 : library.focus, true),
    trash: () => library.trash(library.targets()),
    reveal: () => { const f = library.focused; if (f) api.reveal(f.path); },
    prev: () => moveFocus(-1),
    next: () => moveFocus(1),
    up: () => moveFocus(-(grid?.columns() ?? 1)),
    down: () => moveFocus(grid?.columns() ?? 1),
    selectAll: () => library.selectAllLoaded(),
    escape: () => {
      if (ctx) { ctx = null; return; }
      if (dupes) { dupes = null; return; }
      if (library.selected.size) { library.clearSelection(); return; }
      return false;
    },
  }));

  async function pickFolder(path: string) {
    const b = browse;
    browse = null;
    if (!b) return;
    try {
      if (b.purpose === "add") {
        const res = await api.addFolder(path);
        library.history = res.history;
        library.refreshFolderStatus();
        library.open({ type: "folder", path });
      } else if (b.purpose === "fix" && b.item?.path) {
        const res = await api.repathFolder(b.item.path, path);
        library.history = res.history;
        library.refreshFolderStatus();
        toast(`Moved ${count(res.moved)} records to the new location.`);
        library.open({ type: "folder", path: res.path });
      } else if ((b.purpose === "copy" || b.purpose === "move") && b.paths) {
        const res = await api.exportFiles(b.paths, path, b.purpose);
        toast(`${b.purpose === "move" ? "Moved" : "Copied"} ${count(res.count)} file${res.count === 1 ? "" : "s"}.`);
        if (b.purpose === "move") { library.removeRows(b.paths); library.clearSelection(); }
      }
    } catch (e) { reportError(e); }
  }

  function onContext(index: number, e: MouseEvent) {
    library.setFocus(index, false);
    const row = library.rows[index];
    if (row && !library.selected.has(row.path)) library.selectOnly(row.path);
    ctx = { x: e.clientX, y: e.clientY, index };
  }
</script>

<div class="library" style={`--sidebar:${sidebarWidth}px`}>
  {#if !viewport.phone || drawer}
    {#if viewport.phone}<div class="drawer-scrim" role="presentation" onmousedown={() => (drawer = false)}></div>{/if}
    <div class="side" class:drawer={viewport.phone}>
      <Sidebar
        onaddfolder={() => (browse = { purpose: "add" })}
        onfixfolder={(item) => (browse = { purpose: "fix", item })}
        onnewcollection={() => (collectFor = [])}
        ontrash={() => (trashOpen = true)}
        ondupes={(folder) => (dupes = { folder })}
      />
    </div>
  {/if}
  <div class="main">
    <FilterBar bind:searchInput ondupes={() => (dupes = { folder: library.folder })} onprompts={() => (promptsOpen = true)} onfolders={() => (drawer = true)} />
    <SelectionBar
      ontag={(p) => (tagFor = p)}
      oncollect={(p) => (collectFor = p)}
      onexport={(paths, mode) => (browse = { purpose: mode, paths })}
      oncompare={compare}
      onsuggest={(p) => (tagRunPaths = p)}
    />
    <div class="grid-area">
      <Grid bind:this={grid} onopen={(i) => openViewer(i)} oncontext={onContext} onaddfolder={() => (browse = { purpose: "add" })} />
    </div>
  </div>
  {#if infoSheet}
    <div class="info-sheet">
      <button class="sheet-close" type="button" onclick={() => patchUi({ inspector_open: false })} aria-label="Close info"><Icon name="x" size={16} /></button>
      <Inspector row={library.focused} onopen={(path) => openViewer(library.indexOf(path))} ontag={(p) => (tagFor = p)} oncollect={(p) => (collectFor = p)} onedit={(p) => (editPath = p)} />
    </div>
  {:else if inspectorOpen && !viewport.phone}
    <Inspector row={library.focused} onopen={(path) => openViewer(library.indexOf(path))} ontag={(p) => (tagFor = p)} oncollect={(p) => (collectFor = p)} onedit={(p) => (editPath = p)} />
  {/if}
</div>

{#if viewer}
  <Viewer bind:index={viewer.index} bind:cull={viewer.cull} onclose={() => (viewer = null)} ontag={(p) => (tagFor = p)} oncollect={(p) => (collectFor = p)} onedit={(p) => (editPath = p)} />
{/if}

{#if ctx}
  {@const row = library.rows[ctx.index]}
  <div class="scrim" role="presentation" onmousedown={() => (ctx = null)} oncontextmenu={(e) => { e.preventDefault(); ctx = null; }}></div>
  <div class="ctx" style={`left:${Math.min(ctx.x, innerWidth - 220)}px; top:${Math.min(ctx.y, innerHeight - 320)}px`} role="menu">
    <button class="menu-item" onclick={() => { openViewer(ctx!.index); ctx = null; }}><Icon name="maximize" size={14} />Open<span class="hint">Enter</span></button>
    <button class="menu-item" onclick={() => { tagFor = library.targets(); ctx = null; }}><Icon name="tag" size={14} />Tag<span class="hint">T</span></button>
    <button class="menu-item" onclick={() => { collectFor = library.targets(); ctx = null; }}><Icon name="layers" size={14} />Add to collection</button>
    <div class="menu-sep"></div>
    <div class="stars-row">
      {#each [1, 2, 3, 4, 5] as n}<button class="s" onclick={() => { library.rate(library.targets(), { stars: n }); ctx = null; }}>{n}★</button>{/each}
      <button class="s" onclick={() => { library.rate(library.targets(), { stars: 0 }); ctx = null; }}>0</button>
    </div>
    <button class="menu-item" onclick={() => { library.rate(library.targets(), { rejected: !(row?.rejected) }); ctx = null; }}><Icon name="x" size={14} />{row?.rejected ? "Un-reject" : "Reject"}<span class="hint">X</span></button>
    <div class="menu-sep"></div>
    {#if row}
      <button class="menu-item" onclick={() => { editPath = row.path; ctx = null; }}><Icon name="edit" size={14} />Edit</button>
        <button class="menu-item" onclick={() => { api.reveal(row.path); ctx = null; }}><Icon name="folder" size={14} />Reveal<span class="hint">R</span></button>
    {/if}
    <div class="menu-sep"></div>
    <button class="menu-item" onclick={() => { library.trash(library.targets()); ctx = null; }}><Icon name="trash" size={14} />Trash<span class="hint">Del</span></button>
  </div>
{/if}

<DuplicateReview open={!!dupes} folder={dupes?.folder ?? null} onclose={() => (dupes = null)} />
<CompareDialog open={!!compareRows} rows={compareRows ?? []} onclose={() => (compareRows = null)} />
<TagRun open={!!tagRunPaths} paths={tagRunPaths ?? []} onclose={() => (tagRunPaths = null)} />
<PromptsDialog open={promptsOpen && !!library.folder} folder={library.folder ?? ""} onclose={() => (promptsOpen = false)} />
<ImageEditor open={!!editPath} path={editPath ?? ""} onclose={() => (editPath = null)} onsaved={(p) => library.afterWrite(p)} />
<TagEditor open={!!tagFor} paths={tagFor ?? []} onclose={() => (tagFor = null)} />
<CollectionDialog open={!!collectFor} paths={collectFor ?? []} onclose={() => (collectFor = null)} />
<TrashDialog open={trashOpen} onclose={() => (trashOpen = false)} />
<BrowseDialog
  open={!!browse}
  title={browse?.purpose === "add" ? "Add a folder" : browse?.purpose === "fix" ? "Where did the folder go?" : browse?.purpose === "move" ? "Move to…" : "Copy to…"}
  confirmLabel={browse?.purpose === "add" ? "Add this folder" : browse?.purpose === "fix" ? "Use this location" : browse?.purpose === "move" ? "Move here" : "Copy here"}
  start={browse?.item?.path ?? library.folder ?? ""}
  onpick={pickFolder}
  onclose={() => (browse = null)}
/>

<style>
  .library { display: flex; height: 100%; min-height: 0; }
  .side { width: var(--sidebar); flex: none; min-width: 180px; max-width: 420px; }
  .main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .grid-area { flex: 1; min-height: 0; }
  .drawer-scrim { position: fixed; inset: 0; z-index: 170; background: var(--scrim); }
  .side.drawer { position: fixed; top: 0; bottom: 0; left: 0; width: min(85vw, 320px); max-width: none; z-index: 171; box-shadow: var(--shadow-2); animation: slide .18s var(--ease); }
  .info-sheet { position: fixed; left: 0; right: 0; bottom: calc(54px + env(safe-area-inset-bottom)); height: 52vh; z-index: 140; background: var(--surface); border-top: 1px solid var(--border-strong); border-radius: var(--r-lg) var(--r-lg) 0 0; box-shadow: var(--shadow-2); overflow: hidden; animation: up .18s var(--ease); }
  .info-sheet :global(.inspector) { width: 100%; height: 100%; border-left: 0; }
  .sheet-close { position: absolute; top: 6px; right: 6px; z-index: 1; border: 0; border-radius: 50%; width: 30px; height: 30px; display: grid; place-items: center; background: var(--scrim); color: #fff; cursor: pointer; }
  @keyframes slide { from { transform: translateX(-24px); opacity: 0; } to { transform: none; opacity: 1; } }
  @keyframes up { from { transform: translateY(24px); opacity: 0; } to { transform: none; opacity: 1; } }
  .scrim { position: fixed; inset: 0; z-index: 160; }
  .ctx { position: fixed; z-index: 161; min-width: 200px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); box-shadow: var(--shadow-2); padding: var(--sp1); animation: rise .12s var(--ease); }
  .stars-row { display: flex; gap: 2px; padding: 2px 4px; }
  .stars-row .s { flex: 1; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); font: inherit; font-size: 12px; padding: 4px 0; border-radius: 4px; cursor: pointer; }
  .stars-row .s:hover { background: var(--accent-soft); border-color: var(--accent); }
  @keyframes rise { from { transform: translateY(-4px); opacity: 0; } to { transform: none; opacity: 1; } }
</style>
