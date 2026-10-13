<script lang="ts">
  import Button from "../ui/Button.svelte";
  import Chip from "../ui/Chip.svelte";
  import Icon from "../ui/Icon.svelte";
  import Menu from "../ui/Menu.svelte";
  import SearchHelp from "./SearchHelp.svelte";
  import { library } from "../stores/library.svelte";
  import { patchUi, ui, rememberSearch } from "../stores/settings.svelte";
  import { viewport } from "../stores/viewport.svelte";
  import { count } from "../format";

  interface Props { searchInput?: HTMLInputElement; ondupes: () => void; onprompts: () => void; onfolders?: () => void }
  let { searchInput = $bindable(), ondupes, onprompts, onfolders }: Props = $props();

  let q = $state(library.filters.q);
  $effect(() => { q = library.filters.q; });
  let help: SearchHelp | undefined = $state();

  function onSearchKey(e: KeyboardEvent) {
    if (help?.handleKey(e)) { e.preventDefault(); return; }
    if (e.key === "Escape") { q = ""; library.setFilters({ q: "" }); (e.target as HTMLInputElement).blur(); }
  }

  const SORTS: [string, string][] = [
    ["date_desc", "Newest first"], ["date_asc", "Oldest first"], ["mtime_desc", "Recently modified"],
    ["name_asc", "Name A to Z"], ["name_desc", "Name Z to A"],
    ["stars_desc", "Best rated"], ["stars_asc", "Lowest rated"],
    ["size_desc", "Largest file"], ["size_asc", "Smallest file"], ["random", "Random"],
  ];
  const KINDS: [string, string, string][] = [
    ["generated", "Generated", "sparkles"], ["photo", "Photos", "camera"], ["other", "Other", "image"],
  ];

  const summary = $derived(library.folder ? library.summaries[library.folder] : null);
  const topTags = $derived(library.tags.slice(0, 40));
  let tagSearch = $state("");
  const tagChoices = $derived(
    tagSearch ? library.tags.filter((t) => t.tag.toLowerCase().includes(tagSearch.toLowerCase())).slice(0, 40) : topTags);

  const activeCount = $derived(
    (library.filters.stars_min ? 1 : 0) + (library.filters.kind ? 1 : 0) + (library.filters.tag ? 1 : 0)
    + (library.filters.rejected !== false ? 1 : 0));

  function submit(e: Event) {
    e.preventDefault();
    help?.close();
    rememberSearch(q);
    library.setFilters({ q: q.trim() });
  }
  function clearAll() {
    q = "";
    library.setFilters({ q: "", stars_min: null, kind: null, tag: null, rejected: false });
  }
</script>

<div class="bar">
  <div class="title">
    {#if viewport.phone}<Button size="sm" variant="subtle" square icon="sidebar" title="Folders" onclick={() => onfolders?.()} />{/if}
    <h2>{library.title}</h2>
    <span class="meta">
      {count(library.total)} image{library.total === 1 ? "" : "s"}
      {#if library.recursive}<span class="dot"></span><span title="This folder includes its subfolders">with subfolders</span>{/if}
      {#if summary && summary.unrated}<span class="dot"></span>{count(summary.unrated)} unrated{/if}
      {#if library.pending}<span class="dot"></span><Icon name="loader" size={12} class="spin" /> reading {count(library.pending)}{/if}
    </span>
  </div>

  <form class="search" onsubmit={submit}>
    <Icon name="search" size={15} />
    <input
      bind:this={searchInput}
      bind:value={q}
      placeholder={'Search… e.g. prompt: "red dress" & night; tag: portrait; steps: 20...30'}
      spellcheck="false"
      autocomplete="off"
      onkeydown={onSearchKey}
    />
    {#if q}<button class="clear" type="button" onclick={() => { q = ""; library.setFilters({ q: "" }); }} aria-label="Clear search"><Icon name="x" size={13} /></button>{/if}
    <button class="clear" type="button" onmousedown={(e) => e.preventDefault()} onclick={() => help?.toggleReference()} title="Search syntax" aria-label="Search syntax"><Icon name="info" size={14} /></button>
    <SearchHelp bind:this={help} input={searchInput} />
  </form>

  <div class="filters">
    <Menu>
      {#snippet trigger({ toggle })}
        <Chip icon="star" active={library.filters.stars_min != null} onclick={toggle}>
          {library.filters.stars_min ? `${library.filters.stars_min}+ stars` : "Rating"}<Icon name="chevronDown" size={12} />
        </Chip>
      {/snippet}
      {#snippet children({ close })}
        <button class="menu-item" class:active={library.filters.stars_min == null} onclick={() => { library.setFilters({ stars_min: null }); close(); }}>Any rating</button>
        {#each [5, 4, 3, 2, 1] as n}
          <button class="menu-item" class:active={library.filters.stars_min === n} onclick={() => { library.setFilters({ stars_min: n }); close(); }}>
            {"★".repeat(n)} <span class="hint">{n}+ stars</span>
          </button>
        {/each}
        <div class="menu-sep"></div>
        <button class="menu-item" onclick={() => { q = "stars: 0"; library.setFilters({ q: "stars: 0", stars_min: null }); close(); }}>Unrated only</button>
      {/snippet}
    </Menu>

    <Menu>
      {#snippet trigger({ toggle })}
        <Chip icon={KINDS.find((k) => k[0] === library.filters.kind)?.[2] ?? "layers"} active={!!library.filters.kind} onclick={toggle}>
          {KINDS.find((k) => k[0] === library.filters.kind)?.[1] ?? "Any kind"}<Icon name="chevronDown" size={12} />
        </Chip>
      {/snippet}
      {#snippet children({ close })}
        <button class="menu-item" class:active={!library.filters.kind} onclick={() => { library.setFilters({ kind: null }); close(); }}>Any kind</button>
        {#each KINDS as [key, label, icon]}
          <button class="menu-item" class:active={library.filters.kind === key} onclick={() => { library.setFilters({ kind: key }); close(); }}><Icon name={icon} size={14} />{label}</button>
        {/each}
      {/snippet}
    </Menu>

    <Menu width={240}>
      {#snippet trigger({ toggle })}
        <Chip icon="tag" active={!!library.filters.tag} onclick={toggle}>
          {library.filters.tag ?? "Tag"}<Icon name="chevronDown" size={12} />
        </Chip>
      {/snippet}
      {#snippet children({ close })}
        <div class="tag-search"><input bind:value={tagSearch} placeholder="Find a tag" /></div>
        <button class="menu-item" class:active={!library.filters.tag} onclick={() => { library.setFilters({ tag: null }); close(); }}>Any tag</button>
        <div class="tag-list">
          {#each tagChoices as t (t.tag)}
            <button class="menu-item" class:active={library.filters.tag === t.tag} onclick={() => { library.setFilters({ tag: t.tag }); close(); }}>
              {#if t.color}<i class="swatch" style={`background:${t.color}`}></i>{/if}{t.tag}<span class="hint">{t.count}</span>
            </button>
          {:else}
            <div class="menu-title">No tags yet</div>
          {/each}
        </div>
      {/snippet}
    </Menu>

    <Menu>
      {#snippet trigger({ toggle })}
        <Chip icon="ban" active={library.filters.rejected !== false} onclick={toggle}>
          {library.filters.rejected === null ? "With rejected" : library.filters.rejected ? "Rejected only" : "Hide rejected"}<Icon name="chevronDown" size={12} />
        </Chip>
      {/snippet}
      {#snippet children({ close })}
        <button class="menu-item" class:active={library.filters.rejected === false} onclick={() => { library.setFilters({ rejected: false }); close(); }}>Hide rejected</button>
        <button class="menu-item" class:active={library.filters.rejected === null} onclick={() => { library.setFilters({ rejected: null }); close(); }}>Show everything</button>
        <button class="menu-item" class:active={library.filters.rejected === true} onclick={() => { library.setFilters({ rejected: true }); close(); }}>Rejected only</button>
      {/snippet}
    </Menu>

    {#if activeCount || library.filters.q}
      <Button variant="subtle" size="sm" icon="x" onclick={clearAll}>Clear</Button>
    {/if}

    <span class="spacer"></span>

    <Button variant="ghost" size="sm" icon="dupes" title="Find duplicates" onclick={ondupes}>Duplicates</Button>
    {#if library.folder}<Button variant="ghost" size="sm" icon="hash" title="Unique prompts in this folder" onclick={onprompts}>Prompts</Button>{/if}

    <Menu align="right">
      {#snippet trigger({ toggle })}
        <Button variant="ghost" size="sm" icon="sort" iconRight="chevronDown" onclick={toggle}>
          {SORTS.find((s) => s[0] === library.sort)?.[1] ?? "Sort"}
        </Button>
      {/snippet}
      {#snippet children({ close })}
        {#each SORTS as [key, label]}
          <button class="menu-item" class:active={library.sort === key} onclick={() => { library.setSort(key); patchUi({ sort: key }); close(); }}>{label}</button>
        {/each}
      {/snippet}
    </Menu>

    <div class="size" title="Tile size">
      <Icon name="gridSmall" size={14} />
      <input type="range" min="110" max="420" step="10" value={ui("grid_size")} oninput={(e) => patchUi({ grid_size: +(e.target as HTMLInputElement).value })} />
    </div>
    <Button variant="ghost" size="sm" square icon={ui("layout") === "natural" ? "image" : "grid"}
      title={ui("layout") === "natural" ? "Showing whole images. Click for square tiles." : "Square tiles. Click to show whole images."}
      onclick={() => patchUi({ layout: ui("layout") === "natural" ? "square" : "natural" })} />
    <Button variant="ghost" size="sm" square icon="panelRight" active={ui("inspector_open")} title="Inspector (Space)"
      onclick={() => patchUi({ inspector_open: !ui("inspector_open") })} />
  </div>
</div>

<style>
  .bar { display: flex; flex-direction: column; gap: var(--sp2); padding: var(--sp3) var(--sp4) var(--sp2); border-bottom: 1px solid var(--border); background: var(--surface); }
  .title { display: flex; align-items: baseline; gap: var(--sp3); min-height: 24px; }
  .title h2 { font-size: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meta { color: var(--muted); font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
  .dot { width: 3px; height: 3px; border-radius: 50%; background: var(--faint); }
  .search { position: relative; display: flex; align-items: center; gap: var(--sp2); background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-sm); padding: 0 var(--sp2); height: 32px; color: var(--muted); }
  .search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .search input { flex: 1; border: 0; background: transparent; padding: 0; box-shadow: none; font-family: var(--mono); font-size: 12.5px; }
  .search input:focus { box-shadow: none; }
  .clear { border: 0; background: transparent; color: var(--muted); cursor: pointer; display: flex; padding: 2px; }
  .filters { display: flex; align-items: center; gap: var(--sp2); flex-wrap: wrap; }
  .size { display: flex; align-items: center; gap: 6px; color: var(--muted); }
  .size input { width: 90px; }
  .tag-search { padding: 4px; }
  .tag-search input { width: 100%; }
  .tag-list { max-height: 280px; overflow: auto; }
  .swatch { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }

  @media (max-width: 760px) {
    .bar { padding: var(--sp2) var(--sp3); }
    .title { align-items: center; }
    .title h2 { font-size: 15px; }
    .filters { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
    .filters > :global(*) { flex: none; }
    .size { display: none; }
  }
</style>
