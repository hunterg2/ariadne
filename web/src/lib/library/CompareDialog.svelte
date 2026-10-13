<script lang="ts">
  /* Two to six images side by side, as a wipe between two, or as a
     difference blend; with a table of which generation settings differ. */
  import type { ImageRow } from "../api";
  import { imageUrl } from "../api";
  import Button from "../ui/Button.svelte";
  import Chip from "../ui/Chip.svelte";
  import { bytes } from "../format";

  interface Props { open: boolean; rows: ImageRow[]; onclose: () => void }
  let { open, rows, onclose }: Props = $props();

  const MAX = 6;
  const images = $derived(rows.slice(0, MAX));
  let mode = $state<"side" | "wipe" | "diff">("side");
  let orient = $state<"v" | "h">("v");
  let a = $state(0);
  let b = $state(1);
  let split = $state(50);
  let zoom = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let drag: "split" | "pan" | null = null;
  let dragFrom = { x: 0, y: 0 };
  let stage: HTMLDivElement | undefined = $state();
  let showDiff = $state(true);

  $effect(() => {
    if (open) { mode = images.length === 2 ? "wipe" : "side"; a = 0; b = 1; split = 50; zoom = 1; panX = 0; panY = 0; }
  });

  const FIELDS: [string, (i: ImageRow) => string][] = [
    ["Prompt", (i) => i.prompt], ["Negative", (i) => i.negative], ["Model", (i) => i.model],
    ["LoRAs", (i) => i.loras.join(", ")], ["Steps", (i) => i.steps], ["CFG", (i) => i.cfg],
    ["Sampler", (i) => i.sampler], ["Scheduler", (i) => i.scheduler], ["Seed", (i) => i.seed],
    ["Size", (i) => (i.width ? `${i.width}x${i.height}` : "")], ["File", (i) => bytes(i.bytes)],
    ["Camera", (i) => [i.camera.make, i.camera.model].filter(Boolean).join(" ")],
    ["Exposure", (i) => [i.camera.exposure, i.camera.aperture && "f/" + i.camera.aperture, i.camera.iso && "ISO " + i.camera.iso].filter(Boolean).join(" ")],
  ];
  const shown = $derived(mode === "side" ? images : [images[a], images[b]].filter(Boolean));
  const letters = $derived(mode === "side" ? images.map((_, i) => String.fromCharCode(65 + i)) : ["A", "B"]);
  const differing = $derived(FIELDS.filter(([, get]) => new Set(shown.map(get)).size > 1));
  const transform = $derived(`translate(${panX}px, ${panY}px) scale(${zoom})`);
  const cols = $derived(images.length <= 3 ? images.length : Math.ceil(images.length / 2));

  function wheel(e: WheelEvent) {
    if (!stage) return;
    e.preventDefault();
    const prev = zoom;
    zoom = Math.max(0.1, Math.min(20, zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    const r = stage.getBoundingClientRect();
    const ox = e.clientX - (r.left + r.width / 2), oy = e.clientY - (r.top + r.height / 2);
    panX -= ox * (zoom / prev - 1); panY -= oy * (zoom / prev - 1);
  }
  function down(e: MouseEvent) {
    if (drag === "split") return;
    drag = "pan"; dragFrom = { x: e.clientX - panX, y: e.clientY - panY }; e.preventDefault();
  }
  function move(e: MouseEvent) {
    if (!drag || !stage) return;
    if (drag === "split") {
      const r = stage.getBoundingClientRect();
      split = Math.max(0, Math.min(100, orient === "v" ? ((e.clientX - r.left) / r.width) * 100 : ((e.clientY - r.top) / r.height) * 100));
    } else { panX = e.clientX - dragFrom.x; panY = e.clientY - dragFrom.y; }
  }
  function up() { drag = null; }
  function fit() { zoom = 1; panX = 0; panY = 0; }
  function pixel() {
    const img = stage?.querySelector("img") as HTMLImageElement | null;
    if (img && img.naturalWidth && img.clientWidth) {
      const shownW = Math.min(img.clientWidth, img.clientHeight * (img.naturalWidth / Math.max(1, img.naturalHeight)));
      zoom = Math.max(0.05, Math.min(20, img.naturalWidth / Math.max(1, shownW))); panX = 0; panY = 0;
    }
  }
  function onkey(e: KeyboardEvent) {
    if (e.key === "Escape") { e.stopPropagation(); onclose(); }
  }
</script>

<svelte:window onmousemove={move} onmouseup={up} />

{#if open && images.length >= 2}
  <div class="cmp" role="dialog" aria-modal="true" aria-label="Compare" tabindex="-1" onkeydown={onkey}>
    <header class="top">
      <h2>Comparing {images.length} images</h2>
      <Chip active={mode === "side"} onclick={() => (mode = "side")}>Side by side</Chip>
      <Chip active={mode === "wipe"} onclick={() => (mode = "wipe")}>Wipe</Chip>
      <Chip active={mode === "diff"} onclick={() => (mode = "diff")}>Difference</Chip>
      {#if mode === "wipe"}<Button size="sm" variant="ghost" onclick={() => (orient = orient === "v" ? "h" : "v")}>{orient === "v" ? "Left / right" : "Top / bottom"}</Button>{/if}
      {#if mode !== "side" && images.length > 2}
        <select bind:value={a}>{#each images as img, i}<option value={i}>A: {img.name}</option>{/each}</select>
        <select bind:value={b}>{#each images as img, i}<option value={i}>B: {img.name}</option>{/each}</select>
        <Button size="sm" variant="ghost" onclick={() => { const t = a; a = b; b = t; }}>Swap</Button>
      {/if}
      <span class="spacer"></span>
      <button class="zoom" onclick={fit} title="Fit">{Math.round(zoom * 100)}%</button>
      <Button size="sm" variant="ghost" onclick={pixel}>1:1</Button>
      <Button size="sm" variant={showDiff ? "default" : "ghost"} onclick={() => (showDiff = !showDiff)}>What differs</Button>
      <Button size="sm" variant="ghost" square icon="x" onclick={onclose} title="Close (Esc)" />
    </header>
    <div class="body">
      <div class="stage" bind:this={stage} class:panning={!!drag} onwheel={wheel} onmousedown={down} ondblclick={fit} role="img" aria-label="Comparison">
        {#if mode === "side"}
          <div class="grid" style={`grid-template-columns: repeat(${cols}, 1fr)`}>
            {#each images as img, i (img.path)}
              <div class="pane">
                <div class="zoomer" style={`transform:${transform}`}><img src={imageUrl(img.path)} alt={img.name} draggable="false" /></div>
                <div class="label left"><span class="badge accent">{String.fromCharCode(65 + i)}</span>{img.name}</div>
              </div>
            {/each}
          </div>
        {:else if mode === "diff"}
          <div class="zoomer" style={`transform:${transform}`}><img src={imageUrl(images[b].path)} alt={images[b].name} draggable="false" /></div>
          <div class="zoomer" style={`transform:${transform}`}><img class="diff" src={imageUrl(images[a].path)} alt={images[a].name} draggable="false" /></div>
          <div class="label left">{images[a].name} vs {images[b].name} — black means identical</div>
        {:else}
          <div class="zoomer" style={`transform:${transform}`}><img src={imageUrl(images[b].path)} alt={images[b].name} draggable="false" /></div>
          <div class="clip" style={orient === "v" ? `clip-path: inset(0 ${100 - split}% 0 0)` : `clip-path: inset(0 0 ${100 - split}% 0)`}>
            <div class="zoomer" style={`transform:${transform}`}><img src={imageUrl(images[a].path)} alt={images[a].name} draggable="false" /></div>
          </div>
          <div class={`handle ${orient}`} style={orient === "v" ? `left:${split}%` : `top:${split}%`} role="separator" aria-orientation={orient === "v" ? "vertical" : "horizontal"} tabindex="-1"
            onmousedown={(e) => { e.preventDefault(); e.stopPropagation(); drag = "split"; }}>
            <span class="grip">{orient === "v" ? "‹ ›" : "⌃⌄"}</span>
          </div>
          <div class="label left"><span class="badge accent">A</span>{images[a].name}</div>
          <div class={`label ${orient === "v" ? "right" : "bottom"}`}><span class="badge accent">B</span>{images[b].name}</div>
        {/if}
      </div>
      {#if showDiff}
        <aside class="diffpanel">
          <h4>What differs</h4>
          <table>
            {#each shown as img, i (img.path)}<tr><td class="f"><span class="badge accent">{letters[i]}</span></td><td>{img.name}</td></tr>{/each}
          </table>
          {#if differing.length}
            <table class="vals">
              {#each differing as [label, get] (label)}
                <tr><td class="group" colspan="2">{label}</td></tr>
                {#each shown as img, i (img.path + label)}
                  <tr><td class="f"><span class="badge accent">{letters[i]}</span></td><td class="v">{get(img) || "—"}</td></tr>
                {/each}
              {/each}
            </table>
          {:else}
            <p class="hint">Every recorded setting matches. Any visual difference comes from something the files did not record.</p>
          {/if}
        </aside>
      {/if}
    </div>
  </div>
{/if}

<style>
  .cmp { position: fixed; inset: 0; z-index: 185; background: var(--bg); display: flex; flex-direction: column; outline: none; }
  .top { display: flex; align-items: center; gap: var(--sp2); padding: var(--sp2) var(--sp3); border-bottom: 1px solid var(--border); background: var(--surface); flex-wrap: wrap; }
  .top h2 { font-size: 15px; margin-right: var(--sp2); }
  .zoom { border: 1px solid var(--border); background: var(--surface-2); color: var(--muted); font: inherit; font-size: 12px; padding: 2px 8px; border-radius: var(--r-pill); cursor: pointer; }
  .body { flex: 1; min-height: 0; display: flex; }
  .stage { flex: 1; position: relative; overflow: hidden; background: #0b0b12; cursor: grab; }
  .stage.panning { cursor: grabbing; }
  .grid { position: absolute; inset: 0; display: grid; gap: 4px; padding: 4px; }
  .pane { position: relative; overflow: hidden; background: #0b0b12; border: 1px solid var(--border); }
  .zoomer { position: absolute; inset: 0; display: grid; place-items: center; transform-origin: center; }
  .zoomer img { max-width: 100%; max-height: 100%; object-fit: contain; user-select: none; }
  img.diff { mix-blend-mode: difference; }
  .clip { position: absolute; inset: 0; }
  .handle { position: absolute; z-index: 2; background: var(--accent); }
  .handle.v { top: 0; bottom: 0; width: 2px; cursor: ew-resize; transform: translateX(-1px); }
  .handle.h { left: 0; right: 0; height: 2px; cursor: ns-resize; transform: translateY(-1px); }
  .grip { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); background: var(--accent); color: var(--on-accent); font-size: 12px; padding: 2px 6px; border-radius: var(--r-pill); white-space: nowrap; }
  .label { position: absolute; display: inline-flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: var(--r-sm); background: rgba(0, 0, 0, .6); color: #fff; font-size: 12px; pointer-events: none; max-width: 45%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .label.left { left: 8px; top: 8px; }
  .label.right { right: 8px; top: 8px; }
  .label.bottom { left: 8px; bottom: 8px; }
  .diffpanel { width: 300px; flex: none; overflow-y: auto; padding: var(--sp3) var(--sp4); border-left: 1px solid var(--border); background: var(--surface); font-size: 12.5px; }
  table { width: 100%; border-collapse: collapse; margin-top: var(--sp2); }
  td { padding: 3px 4px; vertical-align: top; }
  td.f { width: 32px; }
  td.group { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; padding-top: var(--sp2); }
  td.v { white-space: pre-wrap; word-break: break-word; }
</style>
