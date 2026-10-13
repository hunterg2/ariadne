<script lang="ts">
  import type { HistoryItem } from "../api";
  import * as api from "../api";
  import Button from "../ui/Button.svelte";
  import Icon from "../ui/Icon.svelte";
  import Menu from "../ui/Menu.svelte";
  import { library } from "../stores/library.svelte";
  import { toast, reportError } from "../stores/toasts.svelte";
  import { basename, count } from "../format";

  interface Props {
    onaddfolder: () => void;
    onfixfolder: (item: HistoryItem) => void;
    onnewcollection: () => void;
    ontrash: () => void;
    ondupes: (folder: string) => void;
  }
  let { onaddfolder, onfixfolder, onnewcollection, ontrash, ondupes }: Props = $props();

  let collapsed: Record<string, boolean> = $state({});

  function isOpenFolder(path: string) {
    return library.scope.type === "folder" && library.scope.path === path;
  }
  function label(item: HistoryItem) {
    return item.alias || basename(item.path ?? "");
  }
  function summary(path: string) {
    return library.summaries[path];
  }
  function status(path: string) {
    return library.status[path];
  }

  async function rename(item: HistoryItem) {
    const name = prompt("New name for this folder in the sidebar", label(item));
    if (name === null) return;
    try {
      const res = await api.updateHistory(item.path!, "rename", name.trim());
      library.history = res.history;
    } catch (e) { reportError(e); }
  }
  async function pin(item: HistoryItem, where: "top" | "bottom" | null) {
    try {
      const res = await api.updateHistory(item.path!, "pin", where);
      library.history = res.history;
    } catch (e) { reportError(e); }
  }
  async function remove(item: HistoryItem) {
    if (!confirm(`Remove "${label(item)}" from the sidebar?\n\nRatings and tags are kept; the folder on disk is untouched.`)) return;
    try {
      const res = await api.updateHistory(item.path!, "delete");
      library.history = res.history;
      if (isOpenFolder(item.path!)) library.open({ type: "all" });
    } catch (e) { reportError(e); }
  }
  async function rescan(item: HistoryItem) {
    try {
      const res = await api.scanFolder(item.path!, false, !!item.recursive);
      toast(`${res.added} new, ${res.updated} changed, ${res.missing} gone.`);
      library.refreshFolderStatus();
      if (isOpenFolder(item.path!)) library.reload();
    } catch (e) { reportError(e); }
  }

  const sortedPinned = (items: HistoryItem[]) => {
    const top = items.filter((i) => i.pinned === "top" || i.pinned === true);
    const bottom = items.filter((i) => i.pinned === "bottom");
    const rest = items.filter((i) => !i.pinned);
    return [...top, ...rest, ...bottom];
  };
</script>

<nav class="sidebar">
  <div class="head">
    <h4>Library</h4>
    <span class="spacer"></span>
    <Button size="sm" variant="subtle" square icon="refresh" title="Re-check folders" onclick={() => library.refreshFolderStatus()} />
    <Button size="sm" variant="subtle" square icon="folderPlus" title="Add a folder" onclick={onaddfolder} />
  </div>

  <button class="entry all" class:on={library.scope.type === "all"} onclick={() => library.open({ type: "all" })}>
    <Icon name="globe" size={15} /><span class="name">Everything</span>
  </button>

  <div class="tree">
    {#each sortedPinned(library.history) as item (item.path ?? item.id)}
      {@render node(item, 0)}
    {:else}
      <p class="hint pad">No folders yet. Add one to begin.</p>
    {/each}
  </div>

  <div class="head">
    <h4>Collections</h4>
    <span class="spacer"></span>
    <Button size="sm" variant="subtle" square icon="plus" title="New collection" onclick={onnewcollection} />
  </div>
  <div class="tree">
    {#each library.collections as c (c.id)}
      <button class="entry" class:on={library.scope.type === "collection" && library.scope.id === c.id} onclick={() => library.open({ type: "collection", id: c.id })}>
        <Icon name={c.kind === "smart" ? "wand" : "layers"} size={14} />
        {#if c.color}<i class="swatch" style={`background:${c.color}`}></i>{/if}
        <span class="name">{c.name}</span>
        {#if c.count != null}<span class="n">{count(c.count)}</span>{/if}
      </button>
    {:else}
      <p class="hint pad">Collections gather images from anywhere. Smart ones are saved searches.</p>
    {/each}
  </div>

  <div class="foot">
    <button class="entry" onclick={ontrash}><Icon name="trash" size={14} /><span class="name">Trash</span></button>
  </div>
</nav>

{#snippet node(item: HistoryItem, depth: number)}
  {#if item.type === "group"}
    {@const key = item.id ?? item.name ?? ""}
    {@const open = collapsed[key] === undefined ? item.isOpen !== false : !collapsed[key]}
    <button class="entry group" style={`padding-left:${10 + depth * 12}px`} onclick={() => (collapsed[key] = open)}>
      <Icon name={open ? "chevronDown" : "chevronRight"} size={13} />
      <span class="name">{item.name}</span>
      {#if item.status}<span class="status">{item.status}</span>{/if}
      <span class="n">{count((item.items ?? []).length)}</span>
    </button>
    {#if open}
      {#each sortedPinned(item.items ?? []) as child (child.path ?? child.id)}
        {@render node(child, depth + 1)}
      {/each}
    {/if}
  {:else if item.path}
    {@const st = status(item.path)}
    {@const sm = summary(item.path)}
    {@const broken = st && !st.ok}
    <div class="folder-row" class:on={isOpenFolder(item.path)} class:broken style={`padding-left:${10 + depth * 12}px`}>
      <button class="entry inner" onclick={() => (broken ? onfixfolder(item) : library.open({ type: "folder", path: item.path! }))} title={item.path}>
        <Icon name={broken ? "alert" : "folder"} size={14} />
        <span class="name">{label(item)}</span>
        {#if item.recursive}<Icon name="folderTree" size={12} class="pin" />{/if}
        {#if item.pinned}<Icon name="pin" size={11} class="pin" />{/if}
        {#if sm?.unrated}<span class="unrated" title={`${count(sm.unrated)} unrated`}>{count(sm.unrated)}</span>{/if}
        <span class="n">{sm?.total != null ? count(sm.total) : st?.count != null ? count(st.count) : ""}</span>
      </button>
      <Menu align="right">
        {#snippet trigger({ toggle })}
          <button class="more" onclick={(e) => { e.stopPropagation(); toggle(); }} aria-label="Folder actions"><Icon name="more" size={14} /></button>
        {/snippet}
        {#snippet children({ close })}
          <button class="menu-item" onclick={() => { rescan(item); close(); }}><Icon name="refresh" size={14} />Rescan</button>
          <button class="menu-item" class:active={!!item.recursive} onclick={() => { library.setRecursive(item.path!, !item.recursive); close(); }} title="Show the images in this folder's subfolders too (trash and dot-folders are skipped)">
            <Icon name={item.recursive ? "check" : "folderTree"} size={14} />Include subfolders
          </button>
          <button class="menu-item" onclick={() => { rename(item); close(); }}><Icon name="edit" size={14} />Rename</button>
          {#if item.pinned}
            <button class="menu-item" onclick={() => { pin(item, null); close(); }}><Icon name="pin" size={14} />Unpin</button>
          {:else}
            <button class="menu-item" onclick={() => { pin(item, "top"); close(); }}><Icon name="pin" size={14} />Pin to top</button>
          {/if}
          <button class="menu-item" onclick={() => { api.reveal(item.path!); close(); }}><Icon name="external" size={14} />Reveal</button>
          <button class="menu-item" onclick={() => { ondupes(item.path!); close(); }}><Icon name="dupes" size={14} />Find duplicates</button>
          <div class="menu-sep"></div>
          <button class="menu-item" onclick={() => { onfixfolder(item); close(); }}><Icon name="move" size={14} />Fix path…</button>
          <button class="menu-item" onclick={() => { remove(item); close(); }}><Icon name="x" size={14} />Remove from list</button>
        {/snippet}
      </Menu>
    </div>
  {/if}
{/snippet}

<style>
  .sidebar { width: 100%; height: 100%; overflow-y: auto; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; padding-bottom: var(--sp4); }
  .head { display: flex; align-items: center; gap: 2px; padding: var(--sp3) var(--sp3) var(--sp1) var(--sp4); }
  .tree { display: flex; flex-direction: column; padding: 0 var(--sp2); }
  .pad { padding: var(--sp2) var(--sp2); font-size: 12px; }
  .entry {
    display: flex; align-items: center; gap: 7px; width: 100%; min-height: 30px; padding: 0 var(--sp2);
    border: 0; background: transparent; color: var(--text); font: inherit; text-align: left; cursor: pointer;
    border-radius: var(--r-sm); white-space: nowrap;
  }
  .entry:hover { background: var(--hover); }
  .entry.on { background: var(--accent-soft); color: var(--text); }
  .entry.all { margin: 0 var(--sp2); width: auto; }
  .entry.group { color: var(--muted); font-size: 12.5px; font-weight: 600; }
  .entry .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .entry .n { color: var(--faint); font-size: 11.5px; font-variant-numeric: tabular-nums; }
  .status { font-size: 11px; }
  .folder-row { display: flex; align-items: center; border-radius: var(--r-sm); }
  .folder-row:hover { background: var(--hover); }
  .folder-row.on { background: var(--accent-soft); }
  .folder-row.broken .entry { color: var(--danger); }
  .folder-row .entry.inner { padding-left: 4px; border-radius: 0; background: transparent; }
  .folder-row .more { display: none; border: 0; background: transparent; color: var(--muted); cursor: pointer; padding: 4px; border-radius: var(--r-sm); margin-right: 4px; }
  .folder-row:hover .more, .folder-row.on .more { display: inline-flex; }
  .folder-row .more:hover { background: var(--hover-strong); color: var(--text); }
  .unrated { font-size: 10.5px; font-weight: 700; color: var(--warn); background: var(--warn-soft); padding: 0 6px; border-radius: 8px; line-height: 16px; }
  :global(.sidebar .pin) { color: var(--faint); }
  .swatch { width: 9px; height: 9px; border-radius: 50%; }
  .foot { margin-top: auto; padding: var(--sp3) var(--sp2) 0; display: flex; flex-direction: column; border-top: 1px solid var(--border); }
</style>
