<script lang="ts">
  /* Groups of look-alike images with a suggested keeper in each. Marked
     copies go to the trash in one go. */
  import * as api from "../api";
  import type { DupeGroup, DupeLevel } from "../api";
  import Button from "../ui/Button.svelte";
  import Icon from "../ui/Icon.svelte";
  import Thumb from "../ui/Thumb.svelte";
  import { library } from "../stores/library.svelte";
  import { settings, patchUi } from "../stores/settings.svelte";
  import { toast, reportError } from "../stores/toasts.svelte";
  import { bytes, count, basename } from "../format";

  interface Props { open: boolean; folder: string | null; onclose: () => void }
  let { open, folder, onclose }: Props = $props();

  let level = $state((settings.data.ui?.dupe_level as string) || "similar");
  let levels: DupeLevel[] = $state([]);
  let groups: DupeGroup[] = $state([]);
  let stats: { groups: number; images: number; redundant: number; bytes: number; pct: number } | null = $state(null);
  let index = $state(0);
  let marked = $state(new Set<string>());
  let loading = $state(false);
  let total = $state(0);
  let problem = $state("");

  async function load() {
    loading = true;
    try {
      const res = await api.findDuplicates(folder, level, library.isRecursive(folder));
      levels = res.levels; groups = res.groups; stats = res.stats ?? null; total = res.total;
      problem = res.error ?? "";
      index = 0;
      suggestAll(true);
    } catch (e) { reportError(e); }
    finally { loading = false; }
  }
  $effect(() => { if (open) load(); });

  const current = $derived(groups[index]);
  const levelInfo = $derived(levels.find((l) => l.key === level));

  function toggle(path: string) {
    const next = new Set(marked);
    if (next.has(path)) next.delete(path); else next.add(path);
    marked = next;
  }
  function suggestAll(quiet = false) {
    const next = new Set<string>();
    for (const g of groups) for (const i of g.items) if (i.path !== g.keep) next.add(i.path);
    marked = next;
    if (!quiet) toast("Best copy kept in every group.");
  }
  function suggestGroup() {
    if (!current) return;
    const next = new Set(marked);
    for (const i of current.items) { if (i.path === current.keep) next.delete(i.path); else next.add(i.path); }
    marked = next;
  }
  function keepAll() {
    if (!current) return;
    const next = new Set(marked);
    for (const i of current.items) next.delete(i.path);
    marked = next;
  }
  function changeLevel(key: string) {
    level = key;
    patchUi({ dupe_level: key } as any);
    const info = levels.find((l) => l.key === key);
    if (info) toast(info.note, { duration: 6000 });
    load();
  }
  async function trashMarked() {
    const paths = Array.from(marked);
    if (!paths.length) return;
    if (!confirm(`Move ${count(paths.length)} image${paths.length === 1 ? "" : "s"} to the trash?`)) return;
    await library.trash(paths);
    await load();
  }
  function markedIn(g: DupeGroup) { return g.items.filter((i) => marked.has(i.path)).length; }
  function statLine() {
    if (problem) return problem;
    if (!stats || !stats.groups) return "No duplicates found.";
    return `${count(stats.groups)} group${stats.groups === 1 ? "" : "s"} · ${count(stats.images)} images involved · ${count(stats.redundant)} could be removed, freeing ${bytes(stats.bytes)} (${stats.pct}% of ${folder ? "this folder" : "the library"})`;
  }
</script>

{#if open}
  <div class="dr" role="dialog" aria-modal="true" aria-label="Duplicates">
    <header class="top">
      <h2>Duplicates in {folder ? basename(folder) : "the whole library"}</h2>
      <select value={level} onchange={(e) => changeLevel(e.currentTarget.value)}>
        {#each levels as l (l.key)}<option value={l.key}>{l.label}</option>{/each}
      </select>
      <span class="hint">{loading ? "Comparing…" : statLine()}</span>
      <span class="spacer"></span>
      <Button size="sm" variant="ghost" onclick={() => suggestAll()}>Keep best in all</Button>
      <Button size="sm" variant="ghost" onclick={() => (marked = new Set())}>Clear marks</Button>
      <Button size="sm" variant="danger" icon="trash" disabled={!marked.size} onclick={trashMarked}>Trash {count(marked.size)} marked</Button>
      <Button size="sm" variant="ghost" square icon="x" onclick={onclose} title="Close (Esc)" />
    </header>
    {#if levelInfo}<p class="note">{levelInfo.note}</p>{/if}
    <div class="body">
      <aside class="list">
        {#each groups as g, i (g.keep + i)}
          <button class="item" class:on={i === index} class:done={markedIn(g) > 0} onclick={() => (index = i)}>
            <span class="t"><Thumb path={g.items[0].path} /></span>
            <span class="n">Group {i + 1} · {g.items.length}</span>
            {#if markedIn(g)}<span class="m">−{markedIn(g)}</span>{/if}
          </button>
        {:else}
          {#if !loading}<p class="hint pad">Nothing to review at this level.</p>{/if}
        {/each}
      </aside>
      <section class="main">
        {#if current}
          <p class="hint">{current.distance === 0 ? "These are pixel-for-pixel identical." : `These differ by ${current.distance} bits out of 64, so they are near matches rather than exact.`} Click a card to keep or remove it.</p>
          <div class="row tools">
            <Button size="sm" onclick={suggestGroup}>Suggest for this group</Button>
            <Button size="sm" variant="ghost" onclick={keepAll}>Keep all of these</Button>
            <span class="spacer"></span>
            <Button size="sm" variant="ghost" icon="chevronLeft" disabled={index === 0} onclick={() => index--}>Previous</Button>
            <Button size="sm" variant="ghost" iconRight="chevronRight" disabled={index >= groups.length - 1} onclick={() => index++}>Next</Button>
          </div>
          <div class="cards">
            {#each current.items as img (img.path)}
              {@const remove = marked.has(img.path)}
              <button class="card" class:remove onclick={() => toggle(img.path)}>
                <span class="pic"><Thumb path={img.path} fit="contain" /></span>
                <span class="state" class:bad={remove}>{remove ? "REMOVE" : "KEEP"}</span>
                <span class="meta">
                  <b>{img.name}</b>
                  <span class="dim">{img.width}×{img.height} · {bytes(img.bytes)}</span>
                  <span class="badges">
                    {#if img.stars}<span class="badge accent">{"★".repeat(img.stars)}</span>{/if}
                    {#if img.rejected}<span class="badge danger">rejected</span>{/if}
                    {#each img.user_tags.slice(0, 3) as t}<span class="badge">#{t}</span>{/each}
                    {#if img.path === current.keep}<span class="badge ok">best copy</span>{/if}
                  </span>
                  <span class="dim path">{img.folder}</span>
                </span>
              </button>
            {/each}
          </div>
        {:else if !loading}
          <p class="hint pad">Nothing left to review.</p>
        {/if}
      </section>
    </div>
  </div>
{/if}

<style>
  .dr { position: fixed; inset: 0; z-index: 185; background: var(--bg); display: flex; flex-direction: column; }
  .top { display: flex; align-items: center; gap: var(--sp2); padding: var(--sp2) var(--sp4); border-bottom: 1px solid var(--border); background: var(--surface); flex-wrap: wrap; }
  .top h2 { font-size: 15px; }
  .note { padding: 6px var(--sp4); font-size: 12px; color: var(--muted); background: var(--surface); border-bottom: 1px solid var(--border); }
  .body { flex: 1; min-height: 0; display: flex; }
  .list { width: 220px; flex: none; overflow-y: auto; border-right: 1px solid var(--border); background: var(--surface); padding: var(--sp2); display: flex; flex-direction: column; gap: 4px; }
  .item { display: flex; align-items: center; gap: 8px; border: 1px solid transparent; background: transparent; color: var(--text); font: inherit; text-align: left; padding: 4px; border-radius: var(--r-sm); cursor: pointer; }
  .item:hover { background: var(--hover); }
  .item.on { border-color: var(--accent); background: var(--accent-soft); }
  .item .t { width: 40px; height: 40px; flex: none; border-radius: 4px; overflow: hidden; }
  .item .n { flex: 1; font-size: 12.5px; }
  .item .m { color: var(--danger); font-weight: 700; font-size: 12px; }
  .main { flex: 1; overflow-y: auto; padding: var(--sp4); display: flex; flex-direction: column; gap: var(--sp3); }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--sp3); }
  .card { position: relative; display: flex; flex-direction: column; border: 2px solid var(--select); border-radius: var(--r); background: var(--surface); padding: 0; overflow: hidden; cursor: pointer; text-align: left; color: var(--text); font: inherit; }
  .card.remove { border-color: var(--danger); opacity: .75; }
  .card .pic { aspect-ratio: 1; background: var(--bg); display: block; }
  .state { position: absolute; top: 8px; left: 8px; padding: 2px 8px; border-radius: var(--r-pill); font-size: 11px; font-weight: 800; background: var(--select); color: #11111b; }
  .state.bad { background: var(--danger); }
  .meta { display: flex; flex-direction: column; gap: 3px; padding: 8px 10px; font-size: 12.5px; }
  .dim { color: var(--muted); font-size: 11.5px; }
  .path { word-break: break-all; }
  .badges { display: flex; flex-wrap: wrap; gap: 3px; }
  .pad { padding: var(--sp3); }
</style>
