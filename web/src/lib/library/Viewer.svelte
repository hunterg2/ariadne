<script lang="ts">
  /* Full-screen viewer: fit or zoom, filmstrip, the inspector as the info
     panel, and cull mode (rate, auto-advance, progress HUD). */
  import { imageUrl } from "../api";
  import * as api from "../api";
  import Button from "../ui/Button.svelte";
  import Icon from "../ui/Icon.svelte";
  import Kbd from "../ui/Kbd.svelte";
  import StarRating from "../ui/StarRating.svelte";
  import Thumb from "../ui/Thumb.svelte";
  import Inspector from "./Inspector.svelte";
  import { library } from "../stores/library.svelte";
  import { settings, ui, patchUi } from "../stores/settings.svelte";
  import { keysFor, useHotkeys } from "../hotkeys";
  import { count } from "../format";

  interface Props {
    index: number;
    cull?: boolean;
    onclose: () => void;
    ontag: (paths: string[]) => void;
    oncollect: (paths: string[]) => void;
    onedit?: (path: string) => void;
  }
  let { index = $bindable(), cull = $bindable(false), onclose, ontag, oncollect, onedit }: Props = $props();

  const row = $derived(library.rows[index]);
  let info = $state(ui("inspector_open"));
  let zoom = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let dragging: { x: number; y: number; px: number; py: number } | null = null;
  let stage: HTMLDivElement | undefined = $state();
  let loadedPath = $state("");
  let culled = $state(0);

  $effect(() => {
    // keep neighbours loaded and preload their files
    library.ensureRange(Math.max(0, index - 6), Math.min(library.total, index + 7));
    for (const i of [index + 1, index - 1]) {
      const r = library.rows[i];
      if (r) { const im = new Image(); im.src = imageUrl(r.path); }
    }
    zoom = 1; panX = 0; panY = 0;
  });

  function step(delta: number) {
    const next = index + delta;
    if (next < 0 || next >= library.total) return false;
    index = next;
    library.setFocus(next);
    return true;
  }

  function advance() {
    if (cull && settings.data.cull_auto_advance !== false) {
      culled++;
      if (!step(1)) onclose();
    }
  }

  function rate(stars: number) {
    if (!row) return;
    library.rate([row.path], { stars }).then(advance);
  }
  function reject() {
    if (!row) return;
    library.rate([row.path], { rejected: !row.rejected }).then(advance);
  }
  async function trash() {
    if (!row) return;
    const at = index;
    await library.trash([row.path]);
    if (library.total === 0) onclose();
    else index = Math.min(at, library.total - 1);
  }

  function wheel(e: WheelEvent) {
    if (!stage) return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const next = Math.min(12, Math.max(1, zoom * factor));
    if (next === 1) { zoom = 1; panX = 0; panY = 0; return; }
    const rect = stage.getBoundingClientRect();
    const cx = e.clientX - rect.left - rect.width / 2;
    const cy = e.clientY - rect.top - rect.height / 2;
    panX = cx - (cx - panX) * (next / zoom);
    panY = cy - (cy - panY) * (next / zoom);
    zoom = next;
  }
  function down(e: MouseEvent) {
    if (zoom === 1 || e.button !== 0) return;
    dragging = { x: e.clientX, y: e.clientY, px: panX, py: panY };
  }
  function move(e: MouseEvent) {
    if (!dragging) return;
    panX = dragging.px + (e.clientX - dragging.x);
    panY = dragging.py + (e.clientY - dragging.y);
  }
  function up() { dragging = null; }

  /* a quick horizontal swipe (touch, pen or mouse) steps to the next or
     previous image when the picture is not zoomed; pointer events so a
     finger counts, with touch-action: none on the stage */
  let swipe: { x: number; y: number; t: number } | null = null;
  function swipeStart(e: PointerEvent) { swipe = { x: e.clientX, y: e.clientY, t: Date.now() }; }
  function swipeEnd(e: PointerEvent) {
    const s = swipe;
    swipe = null;
    if (!s || zoom !== 1) return;
    const dx = e.clientX - s.x, dy = e.clientY - s.y;
    if (Date.now() - s.t < 800 && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
  }
  function toggleZoom() {
    if (zoom === 1) zoom = 2; else { zoom = 1; panX = 0; panY = 0; }
  }

  $effect(() => useHotkeys("viewer", {
    star1: () => rate(1), star2: () => rate(2), star3: () => rate(3), star4: () => rate(4), star5: () => rate(5),
    star0: () => rate(0), reject,
    prev: () => step(-1), next: () => step(1),
    up: () => step(-1), down: () => step(1),
    escape: () => onclose(),
    info: () => { info = !info; patchUi({ inspector_open: info }); },
    tag: () => { if (row) ontag([row.path]); },
    trash, reveal: () => { if (row) api.reveal(row.path); },
    cull: () => { cull = !cull; culled = 0; },
    select: () => { if (row) library.toggleSelect(row.path); },
    open: () => toggleZoom(),
    selectAll: () => false,
  }));

  const stripRange = $derived(Array.from({ length: 11 }, (_, k) => index - 5 + k).filter((i) => i >= 0 && i < library.total));
</script>

<div class="viewer" class:cull role="dialog" aria-modal="true" aria-label="Image viewer">
  <header class="top">
    <span class="name" title={row?.path}>{row?.name ?? ""}</span>
    <span class="pos">{count(index + 1)} / {count(library.total)}</span>
    {#if row}<span class="dims">{row.width}×{row.height}</span>{/if}
    <button class="zoom" type="button" onclick={toggleZoom} title="Zoom (Enter)">{Math.round(zoom * 100)}%</button>
    <span class="spacer"></span>
    {#if row}
      <StarRating value={row.stars} rejected={!!row.rejected} size={18} onchange={rate} onreject={reject} />
      <span class="sep"></span>
    {/if}
    <Button size="sm" variant={cull ? "primary" : "ghost"} icon="bolt" onclick={() => { cull = !cull; culled = 0; }} title="Cull mode (F)">Cull</Button>
    <Button size="sm" variant="ghost" icon="tag" onclick={() => row && ontag([row.path])} title="Tag (T)">Tag</Button>
    <Button size="sm" variant={info ? "default" : "ghost"} icon="info" onclick={() => { info = !info; patchUi({ inspector_open: info }); }} title="Info (Space)">Info</Button>
    <Button size="sm" variant="ghost" square icon="x" onclick={onclose} title="Close (Esc)" />
  </header>

  <div class="body">
    <div class="stage-col">
      <div
        class="stage"
        bind:this={stage}
        class:grab={zoom > 1}
        onwheel={wheel}
        onmousedown={down}
        onmousemove={move}
        onmouseup={up}
        onmouseleave={up}
        onpointerdown={swipeStart}
        onpointerup={swipeEnd}
        ondblclick={toggleZoom}
        role="img"
        aria-label={row?.name}
      >
        {#if row}
          <img
            src={imageUrl(row.path)}
            alt={row.name}
            draggable="false"
            class:ready={loadedPath === row.path}
            style={`transform: translate(${panX}px, ${panY}px) scale(${zoom})`}
            onload={() => (loadedPath = row.path)}
          />
          {#if row.rejected}<div class="rejected-badge"><Icon name="x" size={14} stroke={3} /> Rejected</div>{/if}
        {/if}
        <button class="nav prev" type="button" onclick={() => step(-1)} disabled={index <= 0} aria-label="Previous"><Icon name="chevronLeft" size={28} /></button>
        <button class="nav next" type="button" onclick={() => step(1)} disabled={index >= library.total - 1} aria-label="Next"><Icon name="chevronRight" size={28} /></button>
      </div>
      <div class="strip">
        {#each stripRange as i (i)}
          {@const r = library.rows[i]}
          <button class="strip-item" class:current={i === index} type="button" onclick={() => { index = i; library.setFocus(i); }} aria-label={r?.name}>
            {#if r}<Thumb path={r.path} />{#if r.stars}<span class="s">{r.stars}</span>{/if}{/if}
          </button>
        {/each}
      </div>
      {#if cull}
        <div class="hud">
          <span class="progress">Culled {count(culled)} · {count(index + 1)} of {count(library.total)}</span>
          <span><Kbd combo={keysFor("star1")[0] ?? "1"} />…<Kbd combo={keysFor("star5")[0] ?? "5"} /> rate</span>
          <span><Kbd combo={keysFor("reject")[0] ?? "x"} /> reject</span>
          <span><Kbd combo={keysFor("trash")[0] ?? "delete"} /> trash</span>
          <span><Kbd combo={keysFor("next")[0] ?? "arrowright"} /> skip</span>
          <span><Kbd combo="escape" /> exit</span>
        </div>
      {/if}
    </div>
    {#if info}
      <Inspector {row} {ontag} {oncollect} {onedit} compact />
    {/if}
  </div>
</div>

<style>
  .viewer { position: fixed; inset: 0; z-index: 180; background: var(--bg); display: flex; flex-direction: column; animation: fade .15s var(--ease); }
  .top { display: flex; align-items: center; gap: var(--sp2); padding: var(--sp2) var(--sp3); border-bottom: 1px solid var(--border); background: var(--surface); }
  .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 40vw; }
  .pos, .dims { color: var(--muted); font-size: 12.5px; font-variant-numeric: tabular-nums; }
  .zoom { border: 1px solid var(--border); background: var(--surface-2); color: var(--muted); font: inherit; font-size: 12px; padding: 2px 8px; border-radius: var(--r-pill); cursor: pointer; }
  .sep { width: 1px; height: 18px; background: var(--border-strong); }
  .body { flex: 1; min-height: 0; display: flex; }
  .stage-col { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; }
  .stage { flex: 1; min-height: 0; position: relative; overflow: hidden; display: grid; place-items: center; background: #0b0b12; touch-action: none; }
  .stage.grab { cursor: grab; }
  .stage img { max-width: 100%; max-height: 100%; object-fit: contain; opacity: 0; transition: opacity .15s var(--ease); transform-origin: center; user-select: none; }
  .stage img.ready { opacity: 1; }
  .nav { position: absolute; top: 50%; transform: translateY(-50%); width: 44px; height: 72px; border: 0; border-radius: var(--r); background: rgba(0, 0, 0, .35); color: #fff; cursor: pointer; opacity: 0; transition: opacity var(--dur) var(--ease); display: grid; place-items: center; }
  .nav.prev { left: var(--sp3); }
  .nav.next { right: var(--sp3); }
  .stage:hover .nav:not(:disabled) { opacity: .8; }
  .nav:disabled { display: none; }
  .rejected-badge { position: absolute; top: var(--sp3); left: var(--sp3); display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: var(--r-pill); background: var(--danger); color: #11111b; font-weight: 700; font-size: 12px; }
  .strip { display: flex; gap: 4px; justify-content: center; padding: 6px; background: var(--surface); border-top: 1px solid var(--border); overflow: hidden; }
  .strip-item { position: relative; width: 56px; height: 56px; flex: none; border: 2px solid transparent; border-radius: 4px; overflow: hidden; padding: 0; background: var(--surface-2); cursor: pointer; opacity: .6; }
  .strip-item.current { border-color: var(--accent); opacity: 1; }
  .strip-item:hover { opacity: 1; }
  .strip-item .s { position: absolute; right: 2px; bottom: 2px; font-size: 10px; font-weight: 700; color: var(--star); text-shadow: 0 1px 2px #000; }
  .hud { position: absolute; left: 50%; bottom: 76px; transform: translateX(-50%); display: flex; gap: var(--sp4); align-items: center; padding: 6px 14px; border-radius: var(--r-pill); background: var(--scrim); backdrop-filter: blur(8px); font-size: 12px; color: var(--text); white-space: nowrap; }
  .hud .progress { font-weight: 600; color: var(--accent); }
  .hud span { display: inline-flex; align-items: center; gap: 5px; }
  .viewer.cull .top { border-bottom-color: var(--accent); }
  /* phones: no filmstrip, arrows always showing, the info panel below */
  @media (max-width: 760px) {
    .top { flex-wrap: wrap; gap: 4px; padding: 6px var(--sp2); }
    .name { max-width: 42vw; }
    .strip { display: none; }
    .nav { opacity: .7; width: 38px; height: 60px; }
    .hud { bottom: 14px; gap: var(--sp2); padding: 4px 10px; font-size: 11px; }
    .hud span:nth-child(n+4) { display: none; }
    .body { flex-direction: column; }
    .body :global(.inspector.compact) { width: 100%; height: 45%; flex: none; border-top: 1px solid var(--border); }
  }
  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
</style>
