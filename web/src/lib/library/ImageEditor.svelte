<script lang="ts">
  /* The image editor: annotate, blur, stamp, crop, rotate and flip, then
     save a copy with exactly the metadata you asked for. The document lives
     in a non-reactive Scene (see lib/editor/model.ts) drawn straight onto a
     canvas; the chrome around it is reactive and refreshes on `version`. */
  import { untrack } from "svelte";
  import * as api from "../api";
  import type { MetaLevel } from "../api";
  import Button from "../ui/Button.svelte";
  import Icon from "../ui/Icon.svelte";
  import Modal from "../ui/Modal.svelte";
  import BrowseDialog from "./BrowseDialog.svelte";
  import { Scene, COLORS, FONTS, fontStack, BLUR_KINDS, HINTS, ZOOM_HINT, ASPECTS, qualityWarnings } from "../editor/model";
  import type { Item, TextItem, StampItem, Tool, Crop } from "../editor/model";
  import { library } from "../stores/library.svelte";
  import { settings, patchSettings } from "../stores/settings.svelte";
  import { toast, reportError } from "../stores/toasts.svelte";
  import { useModalHotkeys } from "../hotkeys";
  import { basename } from "../format";

  interface Props { open: boolean; path: string; onclose: () => void; onsaved?: (path: string) => void }
  let { open, path, onclose, onsaved }: Props = $props();

  const name = $derived(basename(path));
  const scene = new Scene();
  let version = $state(0);
  let ready = $state(false);
  let tool = $state<Tool>("marker");
  let color = $state(COLORS[0]);
  let size = $state(8);
  let font = $state("sans");
  let aspect = $state("free");
  let zoom = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let fit = $state({ scale: 1, fitScale: 1, left: 0, top: 0 });
  let stageEl: HTMLDivElement | undefined = $state();
  let canvasEl: HTMLCanvasElement | undefined = $state();
  let liveBox: HTMLDivElement | undefined = $state();
  let stampInput: HTMLInputElement | undefined = $state();
  let spaceDown = $state(false);
  let textSel = $state(-1);
  let stampSel = $state(-1);
  let textEditor: { x: number; y: number; index: number; size: number; color: string; font: string; initial: string } | null = $state(null);
  let undoN = $state(0);
  let redoN = $state(0);
  let blurKind = $state("gaussian");
  let blurAmount = $state(14);
  let format = $state<"png" | "jpeg" | "webp">("png");
  let quality = $state(92);
  let metaLevel = $state<MetaLevel>("generation");
  let bg = $state("#000000");
  let dest = $state<"suffix" | "folder">("suffix");
  let warn: { list: [string, string][]; dest: string | null } | null = $state(null);
  let warnAgain = $state(false);
  let discardOpen = $state(false);
  let browseOpen = $state(false);
  let saving = $state(false);

  // not reactive: pointer bookkeeping and the undo stacks
  let live: Item | null = null;
  let pointer = $state<string | null>(null);
  let start: any = null;
  let textDrag: { mode: "move" | "size"; mouse: { x: number; y: number }; from: { x: number; y: number; size: number }; width: number } | null = null;
  let stampDrag: { mode: "move" | "scale" | "rotate"; mouse: { x: number; y: number }; from: { x: number; y: number; w: number; h: number; angle: number } } | null = null;
  let past: string[] = [];
  let future: string[] = [];
  let nudgeOpen = false;
  let nudgeTimer: ReturnType<typeof setTimeout> | null = null;

  const savedColors = $derived<string[]>((settings.data.edit_colors as string[] | undefined) ?? []);
  const ctx2d = () => canvasEl?.getContext("2d") ?? document.createElement("canvas").getContext("2d")!;

  /* ---- opening --------------------------------------------------------- */
  function load() {
    ready = false;
    const el = new Image();
    el.onload = () => {
      scene.load(el);
      scene.onStampLoaded = () => draw();
      past = []; future = []; undoN = 0; redoN = 0;
      textSel = -1; stampSel = -1; textEditor = null; live = null; pointer = null;
      zoom = 1; panX = 0; panY = 0; aspect = "free";
      loadDefaults();
      ready = true;
      setTool("marker");
      // the stage is already in the DOM; lay out now and once more after the
      // next frame (fonts and scrollbars can still move it)
      layout();
      requestAnimationFrame(layout);
    };
    el.onerror = () => { toast("Could not open that image for editing.", { error: true }); onclose(); };
    el.src = api.imageUrl(path);
  }
  $effect(() => { if (open && path) untrack(load); });

  function loadDefaults() {
    const d = (settings.data.edit_defaults as Record<string, any> | undefined) ?? {};
    format = d.format ?? "png";
    quality = d.quality ?? 92;
    metaLevel = d.metadata ?? "generation";
    font = d.font ?? "sans";
    blurKind = d.blur_kind ?? "gaussian";
    blurAmount = d.blur_amount ?? 14;
    bg = d.background ?? "#000000";
    dest = d.dest ?? "suffix";
  }
  function saveDefault(patch: Record<string, unknown>) {
    patchSettings({ edit_defaults: { ...((settings.data.edit_defaults as Record<string, unknown>) ?? {}), ...patch } });
  }

  /* ---- layout and drawing --------------------------------------------- */
  function layout() {
    if (!stageEl || !canvasEl || !scene.source) return;
    const aw = Math.max(50, stageEl.clientWidth - 48), ah = Math.max(50, stageEl.clientHeight - 48);
    const fitScale = Math.min(aw / scene.w, ah / scene.h, 1);
    const scale = fitScale * zoom;
    const w = Math.round(scene.w * scale), h = Math.round(scene.h * scale);
    fit = { scale, fitScale, left: Math.round((stageEl.clientWidth - w) / 2) + panX, top: Math.round((stageEl.clientHeight - h) / 2) + panY };
    const dpr = window.devicePixelRatio || 1;
    canvasEl.width = Math.max(1, Math.round(w * dpr));
    canvasEl.height = Math.max(1, Math.round(h * dpr));
    canvasEl.style.width = w + "px";
    canvasEl.style.height = h + "px";
    canvasEl.style.left = fit.left + "px";
    canvasEl.style.top = fit.top + "px";
    draw();
  }
  function draw() {
    if (canvasEl) scene.draw(canvasEl, fit.scale, live);
    version++;
  }
  const toImage = (clientX: number, clientY: number) => {
    const r = canvasEl!.getBoundingClientRect();
    return { x: (clientX - r.left) / fit.scale, y: (clientY - r.top) / fit.scale };
  };
  const zoomLabel = $derived(Math.abs(zoom - 1) < 0.005 ? "Fit" : Math.round(fit.scale * 100) + "%");
  const dims = $derived.by(() => {
    version;
    if (!ready) return "";
    const a = scene.area();
    return scene.cropIsFull() ? `${scene.w} × ${scene.h}` : `Crop ${Math.round(a.w)} × ${Math.round(a.h)} of ${scene.w} × ${scene.h}`;
  });

  function zoomBy(factor: number, cx?: number, cy?: number) {
    if (!ready || !stageEl) return;
    const prev = zoom;
    zoom = Math.max(0.1, Math.min(16, zoom * factor));
    if (zoom === prev) return;
    if (zoom <= 1) { panX = 0; panY = 0; }
    else if (cx !== undefined && cy !== undefined) {
      const r = stageEl.getBoundingClientRect();
      const ox = cx - (r.left + r.width / 2), oy = cy - (r.top + r.height / 2);
      panX -= ox * (zoom / prev - 1);
      panY -= oy * (zoom / prev - 1);
    }
    layout();
  }
  function zoomFit() { zoom = 1; panX = 0; panY = 0; layout(); }
  function zoomActual() { if (!fit.fitScale) return; zoom = 1 / fit.fitScale; panX = 0; panY = 0; layout(); }

  /* ---- undo ------------------------------------------------------------ */
  function mark() {
    past.push(scene.snapshot());
    if (past.length > 80) past.shift();
    future = [];
    undoN = past.length; redoN = 0;
  }
  function push(item: Item) { mark(); scene.items.push(item); draw(); }
  function restore(json: string) {
    removeTextEditor(true);
    scene.restore(json);
    textSel = -1; stampSel = -1;
    layout();
  }
  function undo() {
    if (!past.length) { toast("Nothing to undo."); return; }
    future.push(scene.snapshot());
    restore(past.pop()!);
    undoN = past.length; redoN = future.length;
  }
  function redo() {
    if (!future.length) return;
    past.push(scene.snapshot());
    restore(future.pop()!);
    undoN = past.length; redoN = future.length;
  }

  /* ---- tools ----------------------------------------------------------- */
  function setTool(t: Tool) {
    if (textEditor) commitTextEditor();
    tool = t;
    if (t !== "text") textSel = -1;
    if (t !== "stamp") stampSel = -1;
    if (t === "crop" && !scene.crop) scene.crop = { x: scene.w * 0.1, y: scene.h * 0.1, w: scene.w * 0.8, h: scene.h * 0.8 };
    version++;
  }
  const hint = $derived((HINTS[tool] ?? "") + ZOOM_HINT);

  function rotate(deg: number) {
    if (!ready) return;
    if (textEditor) commitTextEditor();
    mark();
    scene.transform(scene.rot + deg, scene.flip);
    layout();
  }
  function flip() {
    if (!ready) return;
    if (textEditor) commitTextEditor();
    mark();
    scene.transform(scene.rot, !scene.flip);
    layout();
  }

  /* ---- colours --------------------------------------------------------- */
  function saveColor(c: string) {
    c = c.toLowerCase();
    color = c;
    const known = COLORS.map((x) => x.toLowerCase());
    if (!known.includes(c) && !savedColors.includes(c)) {
      const next = [...savedColors, c];
      if (next.length > 12) next.shift();
      patchSettings({ edit_colors: next });
      toast(`Kept ${c}. Right-click a saved colour to forget it.`);
    }
  }
  function forgetColor(c: string) {
    patchSettings({ edit_colors: savedColors.filter((x) => x !== c) });
    toast("Colour forgotten.");
  }

  /* ---- crop ------------------------------------------------------------ */
  const ratioOf = () => aspect === "free" ? null : aspect === "orig" ? scene.w / scene.h : Number(aspect);
  function setAspect() {
    const c = scene.crop;
    const r = ratioOf();
    if (c && r) {
      c.h = c.w / r;
      if (c.y + c.h > scene.h) { c.h = scene.h - c.y; c.w = c.h * r; }
    }
    layout();
  }
  function resetCrop() {
    scene.crop = tool === "crop" ? { x: 0, y: 0, w: scene.w, h: scene.h } : null;
    aspect = "free";
    layout();
  }
  const cropBox = $derived.by(() => {
    version;
    const c = scene.crop;
    if (!c || tool !== "crop" || !ready) return null;
    return { left: fit.left + c.x * fit.scale, top: fit.top + c.y * fit.scale, w: c.w * fit.scale, h: c.h * fit.scale };
  });

  /* ---- text ------------------------------------------------------------ */
  const selectedText = $derived.by((): TextItem | null => {
    version;
    const it = textSel >= 0 ? scene.items[textSel] : null;
    return it && it.type === "text" ? it : null;
  });
  const textBox = $derived.by(() => {
    version;
    const it = selectedText;
    if (!it || textEditor || !ready) return null;
    const b = scene.textBounds(ctx2d(), it);
    const pad = 4;
    const left = fit.left + (b.x - pad) * fit.scale, top = fit.top + (b.y - pad) * fit.scale;
    const w = Math.max(8, (b.w + pad * 2) * fit.scale), h = Math.max(8, (b.h + pad * 2) * fit.scale);
    return { left, top, w, h, barTop: top - 36 > 0 ? top - 36 : top + h + 6, barLeft: Math.max(4, left) };
  });
  function textResize(direction: number) {
    const it = selectedText; if (!it) return;
    mark();
    it.size = Math.max(6, Math.min(600, Math.round(it.size * (direction > 0 ? 1.15 : 1 / 1.15) * 10) / 10));
    draw();
  }
  function textEdit() {
    const it = selectedText; if (!it) return;
    const index = textSel;
    textSel = -1;
    startTextEditor({ x: it.x, y: it.y }, index);
  }
  function textDuplicate() {
    const it = selectedText; if (!it) return;
    push({ ...it, x: it.x + 12, y: it.y + 12 });
    textSel = scene.items.length - 1;
    toast("Copied. It sits just below the original.");
  }
  function textDelete() {
    if (textSel < 0) return;
    mark();
    scene.items.splice(textSel, 1);
    textSel = -1;
    draw();
    toast("Text deleted.", { action: { label: "Undo", run: undo } });
  }
  function textSetFont(key: string) {
    const it = selectedText; if (!it) return;
    mark(); it.font = key; draw();
  }
  function nudge(dx: number, dy: number) {
    const it = selectedText; if (!it) return;
    // one undo step for a run of taps, not one per tap
    if (!nudgeOpen) { mark(); nudgeOpen = true; }
    if (nudgeTimer) clearTimeout(nudgeTimer);
    nudgeTimer = setTimeout(() => { nudgeOpen = false; }, 700);
    it.x += dx; it.y += dy;
    draw();
  }
  function startTextEditor(p: { x: number; y: number }, index: number) {
    removeTextEditor();
    const existing = index >= 0 ? (scene.items[index] as TextItem) : null;
    textEditor = {
      x: p.x, y: p.y, index,
      size: existing ? existing.size : Math.max(12, size * 3),
      color: existing ? existing.color : color,
      font: existing ? existing.font || "sans" : font,
      initial: existing ? existing.text : "",
    };
    if (existing) { existing.hidden = true; draw(); }
  }
  $effect(() => {
    const box = liveBox, ed = textEditor;
    if (!box || !ed) return;
    box.textContent = ed.initial;
    setTimeout(() => {
      box.focus();
      const r = document.createRange();
      r.selectNodeContents(box); r.collapse(false);
      const sel = window.getSelection();
      sel?.removeAllRanges(); sel?.addRange(r);
    }, 0);
  });
  function commitTextEditor() {
    const ed = textEditor, box = liveBox;
    if (!ed) return;
    const text = (box?.textContent ?? "").replace(/\s+$/, "").trim();
    textEditor = null;
    if (ed.index >= 0) {
      const before = scene.snapshot();
      const existing = scene.items[ed.index] as TextItem | undefined;
      if (!text) scene.items.splice(ed.index, 1);
      else if (existing) { existing.text = text; delete existing.hidden; }
      if (scene.snapshot() !== before) { past.push(before); if (past.length > 80) past.shift(); future = []; undoN = past.length; redoN = 0; }
    } else if (text) {
      push({ type: "text", x: ed.x, y: ed.y, text, color: ed.color, size: ed.size, font: ed.font });
    }
    draw();
  }
  function removeTextEditor(restoreHidden = false) {
    const ed = textEditor;
    if (!ed) return;
    textEditor = null;
    const existing = ed.index >= 0 ? (scene.items[ed.index] as TextItem | undefined) : undefined;
    if (restoreHidden && existing) delete existing.hidden;
    draw();
  }

  /* ---- stamps ---------------------------------------------------------- */
  const selectedStamp = $derived.by((): StampItem | null => {
    version;
    const it = stampSel >= 0 ? scene.items[stampSel] : null;
    return it && it.type === "stamp" ? it : null;
  });
  const stampBox = $derived.by(() => {
    version;
    const it = selectedStamp;
    if (!it || !ready || !stageEl) return null;
    const left = fit.left + it.x * fit.scale, top = fit.top + it.y * fit.scale;
    const w = it.w * fit.scale, h = it.h * fit.scale;
    return { left, top, w, h, angle: it.angle, opacity: Math.round((it.opacity ?? 1) * 100), barLeft: Math.max(4, left), barTop: top + h + 34 < stageEl.clientHeight ? top + h + 8 : Math.max(4, top - 36) };
  });
  function stampChosen(input: HTMLInputElement) {
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const src = String(reader.result);
      const img = new Image();
      img.onload = () => {
        const w = Math.max(24, scene.w * 0.25);
        const h = w * (img.naturalHeight / Math.max(1, img.naturalWidth));
        push({ type: "stamp", src, x: (scene.w - w) / 2, y: (scene.h - h) / 2, w, h, angle: 0, opacity: 1, flip: false, tile: false });
        setTool("stamp");
        stampSel = scene.items.length - 1;
        toast("Drag it about, pull the corner to resize, use the handle to turn it.");
      };
      img.src = src;
    };
    reader.readAsDataURL(file);
  }
  function stampOpacity(v: number) { const it = selectedStamp; if (!it) return; it.opacity = v / 100; draw(); }
  function stampFlip() { const it = selectedStamp; if (!it) return; mark(); it.flip = !it.flip; draw(); }
  function stampTile() {
    const it = selectedStamp; if (!it) return;
    mark(); it.tile = !it.tile; draw();
    toast(it.tile ? "Repeated across the whole picture." : "Back to a single mark.");
  }
  function stampDelete() {
    if (stampSel < 0) return;
    mark(); scene.items.splice(stampSel, 1); stampSel = -1; draw();
    toast("Watermark removed.", { action: { label: "Undo", run: undo } });
  }

  /* ---- pointer --------------------------------------------------------- */
  function onCanvasDown(e: MouseEvent) {
    if (!ready || tool === "crop" || spaceDown || e.button === 1 || e.button === 2) return;
    e.preventDefault();
    const p = toImage(e.clientX, e.clientY);
    if (tool === "stamp") { stampSel = scene.stampHit(p); return; }
    if (tool === "blur") {
      pointer = "draw"; start = p;
      live = { type: "blur", kind: blurKind, amount: blurAmount, size: Math.max(6, size * 2.5), points: [[p.x, p.y]] };
      draw(); return;
    }
    if (tool === "blurarea") {
      pointer = "draw"; start = p;
      live = { type: "blur", kind: blurKind, amount: blurAmount, shape: "rect", x: p.x, y: p.y, w: 0, h: 0 };
      draw(); return;
    }
    if (tool === "text") {
      if (textEditor) { commitTextEditor(); return; }
      const hit = scene.textHit(ctx2d(), p);
      if (hit >= 0) textSel = hit;            // pick it up; the box handles moving
      else if (textSel >= 0) textSel = -1;    // first click puts down what you held
      else startTextEditor(p, -1);
      return;
    }
    pointer = "draw"; start = p;
    if (tool === "marker") live = { type: "stroke", color, size, points: [[p.x, p.y]] };
    else if (tool === "highlight") live = { type: "highlight", color, size, points: [[p.x, p.y]] };
    else if (tool === "arrow") live = { type: "arrow", color, size, x1: p.x, y1: p.y, x2: p.x, y2: p.y };
    else live = { type: tool, color, size, x: p.x, y: p.y, w: 0, h: 0 } as Item;
    draw();
  }
  function onStageDown(e: MouseEvent) {
    if (!ready) return;
    if (!spaceDown && e.button !== 1) return;
    e.preventDefault();
    pointer = "view-pan";
    start = { mouse: { x: e.clientX, y: e.clientY }, pan: { x: panX, y: panY } };
  }
  function onCropDown(e: MouseEvent, handle?: string) {
    e.preventDefault(); e.stopPropagation();
    pointer = handle ? "crop-" + handle : "crop-move";
    start = { mouse: toImage(e.clientX, e.clientY), crop: { ...scene.crop! } };
  }
  function onContext(e: MouseEvent) {
    if (!ready) return;
    e.preventDefault();
    const hit = scene.itemHit(ctx2d(), toImage(e.clientX, e.clientY));
    if (hit === -1) { toast("Right-click directly on a mark to delete it."); return; }
    const label = scene.items[hit].type === "stroke" ? "stroke" : scene.items[hit].type;
    mark();
    scene.items.splice(hit, 1);
    if (textEditor?.index === hit) removeTextEditor();
    if (textSel === hit) textSel = -1;
    if (stampSel === hit) stampSel = -1;
    draw();
    toast(`Deleted that ${label}.`, { action: { label: "Undo", run: undo } });
  }
  function beginTextDrag(e: MouseEvent, mode: "move" | "size") {
    const it = selectedText; if (!it) return;
    e.preventDefault(); e.stopPropagation();
    mark();
    textDrag = { mode, mouse: { x: e.clientX, y: e.clientY }, from: { x: it.x, y: it.y, size: it.size }, width: Math.max(1, scene.textBounds(ctx2d(), it).w) };
  }
  function beginStampDrag(e: MouseEvent, mode: "move" | "scale" | "rotate") {
    const it = selectedStamp; if (!it) return;
    e.preventDefault(); e.stopPropagation();
    mark();
    stampDrag = { mode, mouse: { x: e.clientX, y: e.clientY }, from: { x: it.x, y: it.y, w: it.w, h: it.h, angle: it.angle || 0 } };
  }

  function onMove(e: MouseEvent) {
    if (!ready) return;
    if (textDrag) {
      const it = selectedText; if (!it) return;
      const dx = (e.clientX - textDrag.mouse.x) / fit.scale, dy = (e.clientY - textDrag.mouse.y) / fit.scale;
      if (textDrag.mode === "move") { it.x = textDrag.from.x + dx; it.y = textDrag.from.y + dy; }
      else it.size = Math.max(6, Math.min(600, Math.round(textDrag.from.size * ((textDrag.width + dx) / textDrag.width) * 10) / 10));
      draw(); return;
    }
    if (stampDrag) {
      const it = selectedStamp; if (!it || !stageEl) return;
      const dx = (e.clientX - stampDrag.mouse.x) / fit.scale, dy = (e.clientY - stampDrag.mouse.y) / fit.scale;
      const from = stampDrag.from;
      if (stampDrag.mode === "move") { it.x = from.x + dx; it.y = from.y + dy; }
      else if (stampDrag.mode === "scale") {
        const ratio = Math.max(0.05, (from.w + dx) / from.w);     // proportions kept
        it.w = Math.max(12, from.w * ratio); it.h = Math.max(12, from.h * ratio);
      } else {
        const cx = fit.left + (it.x + it.w / 2) * fit.scale, cy = fit.top + (it.y + it.h / 2) * fit.scale;
        const r = stageEl.getBoundingClientRect();
        let a = Math.atan2(e.clientY - r.top - cy, e.clientX - r.left - cx) + Math.PI / 2;
        if (e.shiftKey) a = Math.round(a / (Math.PI / 12)) * (Math.PI / 12);
        it.angle = a;
      }
      draw(); return;
    }
    if (!pointer) return;
    if (pointer === "view-pan") {
      panX = start.pan.x + (e.clientX - start.mouse.x);
      panY = start.pan.y + (e.clientY - start.mouse.y);
      layout(); return;
    }
    const p = toImage(e.clientX, e.clientY);
    if (pointer === "draw" && live) {
      if ("points" in live && live.points) live.points.push([p.x, p.y]);
      else if (live.type === "arrow") { live.x2 = p.x; live.y2 = p.y; }
      else {
        const box = live as { x: number; y: number; w: number; h: number };
        box.x = Math.min(start.x, p.x); box.y = Math.min(start.y, p.y);
        box.w = Math.abs(p.x - start.x); box.h = Math.abs(p.y - start.y);
      }
      draw(); return;
    }
    // crop handles
    const dx = p.x - start.mouse.x, dy = p.y - start.mouse.y;
    const c: Crop = start.crop, ratio = ratioOf();
    const n = { ...c };
    if (pointer === "crop-move") { n.x = c.x + dx; n.y = c.y + dy; }
    else {
      if (pointer.includes("w")) { n.x = c.x + dx; n.w = c.w - dx; }
      if (pointer.includes("e")) n.w = c.w + dx;
      if (pointer.includes("n")) { n.y = c.y + dy; n.h = c.h - dy; }
      if (pointer.includes("s")) n.h = c.h + dy;
      if (ratio) { n.h = n.w / ratio; if (pointer.includes("n")) n.y = c.y + c.h - n.h; }
    }
    n.w = Math.max(16, n.w); n.h = Math.max(16, n.h);
    n.x = Math.max(0, Math.min(n.x, scene.w - n.w)); n.y = Math.max(0, Math.min(n.y, scene.h - n.h));
    n.w = Math.min(n.w, scene.w - n.x); n.h = Math.min(n.h, scene.h - n.y);
    scene.crop = n;
    version++;
  }
  function onUp() {
    if (textDrag) { textDrag = null; version++; return; }
    if (stampDrag) { stampDrag = null; version++; return; }
    if (pointer === "draw" && live) {
      const drawn = live; live = null;
      const tiny = (drawn.type === "rect" || drawn.type === "ellipse") && drawn.w < 3 && drawn.h < 3;
      if (!tiny) push(drawn); else draw();
    }
    pointer = null; start = null;
  }
  function isTyping(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
  }
  function onKeyDown(e: KeyboardEvent) {
    if (!ready || isTyping(e)) return;
    if (e.code === "Space") { spaceDown = true; e.preventDefault(); return; }
    if (selectedText) {
      if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); textDelete(); }
      else if (e.key === "[") { e.preventDefault(); textResize(-1); }
      else if (e.key === "]") { e.preventDefault(); textResize(1); }
      else if (e.key === "Enter") { e.preventDefault(); textEdit(); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d") { e.preventDefault(); textDuplicate(); }
      else if (e.key.startsWith("Arrow")) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        nudge(e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0, e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0);
      }
    } else if (selectedStamp && (e.key === "Backspace" || e.key === "Delete")) { e.preventDefault(); stampDelete(); }
  }
  function onKeyUp(e: KeyboardEvent) { if (e.code === "Space") spaceDown = false; }

  $effect(() => {
    if (!open) return;
    const stage = stageEl;
    const wheel = (e: WheelEvent) => { if (!ready) return; e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY); };
    const resize = () => layout();
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("resize", resize);
    stage?.addEventListener("wheel", wheel, { passive: false });
    const off = useModalHotkeys({
      escape: () => { if (textEditor) return false; if (browseOpen || warn || discardOpen) return false; requestClose(); },
      write: () => save(), undo, redo,
      zoomIn: () => zoomBy(1.25), zoomOut: () => zoomBy(1 / 1.25), zoomFit, zoomActual,
    });
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("resize", resize);
      stage?.removeEventListener("wheel", wheel);
      off();
    };
  });

  /* ---- closing --------------------------------------------------------- */
  function hasChanges() {
    if (textEditor && (liveBox?.textContent ?? "").trim()) return true;
    return scene.hasChanges();
  }
  function requestClose() {
    if (!hasChanges()) { onclose(); return; }
    discardOpen = true;
  }
  const discardText = $derived.by(() => {
    version;
    const bits: string[] = [];
    if (scene.items.length) bits.push(`${scene.items.length} annotation${scene.items.length === 1 ? "" : "s"}`);
    if (!scene.cropIsFull()) bits.push("a crop");
    if (scene.rot !== 0 || scene.flip) bits.push("a rotation or flip");
    return `You have ${bits.join(", ") || "changes"} on ${name} that have not been saved. Closing now throws them away. The original file is untouched either way.`;
  });

  /* ---- saving ---------------------------------------------------------- */
  const formatNote = $derived(format !== "png" && metaLevel !== "none" ? "Prompt data has to move into EXIF for this format, and is dropped if it goes over 64 KB. PNG keeps it intact." : "");
  const destNote = $derived(dest === "folder" ? "You'll pick the folder when you save." : `Saves alongside the original as ${name.replace(/\.[^.]+$/, "")}_edit`);

  function save() {
    if (!ready || saving) return;
    if (textEditor) commitTextEditor();
    if (dest === "folder") { browseOpen = true; return; }
    confirmThenSave(null);
  }
  function confirmThenSave(dir: string | null) {
    const list = qualityWarnings({ format, quality, metadata: metaLevel, sourceName: name, background: bg, edited: scene.hasChanges() });
    if (!list.length || settings.data.warn_quality === false) { run(dir); return; }
    warnAgain = false;
    warn = { list, dest: dir };
  }
  function proceed() {
    const w = warn; warn = null;
    if (!w) return;
    if (warnAgain) { patchSettings({ warn_quality: false }); toast("Export warnings turned off. You can switch them back on in Settings."); }
    run(w.dest);
  }
  async function run(dir: string | null) {
    saving = true;
    try {
      const canvas = scene.renderFull();
      const mime = format === "png" ? "image/png" : format === "jpeg" ? "image/jpeg" : "image/webp";
      const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, mime, format === "png" ? undefined : quality / 100));
      if (!blob) throw new Error("the browser could not render the image");
      const payload: api.EditPayload = {
        source_path: path, format, quality, metadata: metaLevel,
        dest: dir ? "folder" : "suffix", dest_dir: dir ?? "", background: bg,
      };
      const res = await api.saveEdit(blob, payload);
      patchSettings({ edit_defaults: { ...((settings.data.edit_defaults as Record<string, unknown>) ?? {}), font, format, quality, metadata: metaLevel, dest, background: bg, blur_kind: blurKind, blur_amount: blurAmount } });
      for (const n of res.notes ?? []) toast(n, { duration: 8000 });
      toast(`Saved ${res.name}.` + (res.tagged ? " Tagged #edited." : ""));
      onsaved?.(res.path);
      onclose();
    } catch (e) { reportError(e, "Could not save."); }
    finally { saving = false; }
  }
</script>

{#if open}
  <div class="ed" role="dialog" aria-modal="true" aria-label="Image editor">
    <header class="top">
      <span class="title" title={path}>{name}</span>
      <div class="tools" role="toolbar" aria-label="Tools">
        {#each [["marker", "Marker", "✎"], ["highlight", "Highlighter", "▬"], ["arrow", "Arrow", "↗"], ["rect", "Rectangle", "▭"], ["ellipse", "Ellipse", "◯"], ["text", "Text", "T"], ["blur", "Blur brush", "◍"], ["blurarea", "Blur an area", "▨"]] as [t, label, glyph] (t)}
          <button type="button" class:on={tool === t} title={label} onclick={() => setTool(t as Tool)}>{glyph}</button>
        {/each}
        <button type="button" class:on={tool === "stamp"} title="Watermark or logo" onclick={() => stampInput?.click()}>⬚</button>
        <button type="button" class:on={tool === "crop"} title="Crop" onclick={() => setTool("crop")}>⌗</button>
      </div>
      <input bind:this={stampInput} type="file" accept="image/*" class="hidden" onchange={(e) => stampChosen(e.currentTarget)} />
      <div class="swatches">
        {#each COLORS as c (c)}
          <button type="button" class="sw" class:on={c.toLowerCase() === color.toLowerCase()} style={`background:${c}`} title={c} onclick={() => (color = c)} aria-label={c}></button>
        {/each}
        {#each savedColors as c (c)}
          <button type="button" class="sw saved" class:on={c === color.toLowerCase()} style={`background:${c}`} title={`${c}: right-click to forget`} onclick={() => (color = c)} oncontextmenu={(e) => { e.preventDefault(); forgetColor(c); }} aria-label={c}></button>
        {/each}
        <label class="sw add" title="Pick any colour and keep it">+<input type="color" value={color} oninput={(e) => (color = e.currentTarget.value)} onchange={(e) => saveColor(e.currentTarget.value)} /></label>
      </div>
      {#if tool === "blur" || tool === "blurarea"}
        <select bind:value={blurKind} onchange={() => { const k = BLUR_KINDS.find((b) => b[0] === blurKind); if (k) toast(k[2], { duration: 5000 }); saveDefault({ blur_kind: blurKind }); }} title="Kind of blur">
          {#each BLUR_KINDS as [key, label] (key)}<option value={key}>{label}</option>{/each}
        </select>
        <label class="slider"><span>Strength</span><input type="range" min="2" max="80" bind:value={blurAmount} onchange={() => saveDefault({ blur_amount: blurAmount })} /><span class="val">{blurAmount}</span></label>
      {/if}
      <label class="slider"><span>Size</span><input type="range" min="1" max="220" bind:value={size} /><span class="val">{size}</span></label>
      {#if tool === "text"}
        <select bind:value={font} onchange={() => saveDefault({ font })} title="Font used for new text">
          {#each FONTS as [key, label, stack] (key)}<option value={key} style={`font-family:${stack}`}>{label}</option>{/each}
        </select>
      {/if}
      <span class="sep"></span>
      <Button size="sm" variant="ghost" disabled={!undoN} title="Undo (Ctrl+Z)" onclick={undo}>Undo</Button>
      <Button size="sm" variant="ghost" disabled={!redoN} title="Redo (Ctrl+Shift+Z)" onclick={redo}>Redo</Button>
      <Button size="sm" variant="ghost" title="Rotate left" onclick={() => rotate(-90)}>⟲</Button>
      <Button size="sm" variant="ghost" title="Rotate right" onclick={() => rotate(90)}>⟳</Button>
      <Button size="sm" variant="ghost" title="Flip horizontally" onclick={flip}>⇋</Button>
      <span class="sep"></span>
      <span class="zoom">{zoomLabel}</span>
      <Button size="sm" variant="ghost" square icon="minus" title="Zoom out (-)" onclick={() => zoomBy(1 / 1.25)} />
      <Button size="sm" variant="ghost" square icon="plus" title="Zoom in (+)" onclick={() => zoomBy(1.25)} />
      <Button size="sm" variant="ghost" title="Fit (0)" onclick={zoomFit}>Fit</Button>
      <Button size="sm" variant="ghost" title="Actual size (1)" onclick={zoomActual}>1:1</Button>
      <span class="spacer"></span>
      <Button size="sm" variant="ghost" square icon="x" title="Close (Esc)" onclick={requestClose} />
    </header>

    <div class="body">
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="stage" bind:this={stageEl} class:grab={spaceDown} class:grabbing={pointer === "view-pan"} onmousedown={onStageDown}>
        <canvas bind:this={canvasEl} class:text-tool={tool === "text"} class:stamp-tool={tool === "stamp"} onmousedown={onCanvasDown} oncontextmenu={onContext}></canvas>
        {#if !ready}<p class="loading hint">Opening…</p>{/if}

        {#if textEditor}
          <div bind:this={liveBox} class="text-live" contenteditable="true" spellcheck="false" role="textbox" tabindex="0"
            style={`left:${fit.left + textEditor.x * fit.scale}px; top:${fit.top + textEditor.y * fit.scale}px; font-size:${textEditor.size * fit.scale}px; color:${textEditor.color}; font-family:${fontStack(textEditor.font)}`}
            onkeydown={(e) => { e.stopPropagation(); if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commitTextEditor(); } if (e.key === "Escape") { e.preventDefault(); removeTextEditor(true); } }}
            onblur={() => { if (textEditor) commitTextEditor(); }}></div>
        {/if}

        {#if textBox && selectedText}
          <div class="text-sel" style={`left:${textBox.left}px; top:${textBox.top}px; width:${textBox.w}px; height:${textBox.h}px`} onmousedown={(e) => beginTextDrag(e, "move")} ondblclick={(e) => { e.preventDefault(); textEdit(); }} role="presentation">
            <div class="grip" onmousedown={(e) => beginTextDrag(e, "size")} role="presentation"></div>
          </div>
          <div class="bar" style={`left:${textBox.barLeft}px; top:${textBox.barTop}px`}>
            <button type="button" title="Smaller ([)" onclick={() => textResize(-1)}>A−</button>
            <span class="sz">{Math.round(selectedText.size)}px</span>
            <button type="button" title="Bigger (])" onclick={() => textResize(1)}>A+</button>
            <span class="bsep"></span>
            <select value={selectedText.font || "sans"} onchange={(e) => textSetFont(e.currentTarget.value)} title="Font">
              {#each FONTS as [key, label] (key)}<option value={key}>{label}</option>{/each}
            </select>
            <button type="button" title="Edit the words (Enter)" onclick={textEdit}>✎</button>
            <button type="button" title="Duplicate (Ctrl+D)" onclick={textDuplicate}>⧉</button>
            <button type="button" title="Delete (Backspace)" onclick={textDelete}>✕</button>
          </div>
        {/if}

        {#if stampBox && selectedStamp}
          <div class="stamp-sel" style={`left:${stampBox.left}px; top:${stampBox.top}px; width:${stampBox.w}px; height:${stampBox.h}px; transform:${stampBox.angle ? `rotate(${stampBox.angle}rad)` : "none"}`} onmousedown={(e) => beginStampDrag(e, "move")} role="presentation">
            <div class="stem"></div>
            <div class="grip rot" onmousedown={(e) => beginStampDrag(e, "rotate")} role="presentation"></div>
            <div class="grip br" onmousedown={(e) => beginStampDrag(e, "scale")} role="presentation"></div>
          </div>
          <div class="bar" style={`left:${stampBox.barLeft}px; top:${stampBox.barTop}px`}>
            <span class="lbl">Opacity</span>
            <input type="range" min="5" max="100" value={stampBox.opacity} oninput={(e) => stampOpacity(+e.currentTarget.value)} />
            <span class="lbl">{stampBox.opacity}%</span>
            <button type="button" title="Flip" onclick={stampFlip}>⇋</button>
            <button type="button" title="Tile it across the whole picture" class:on={selectedStamp.tile} onclick={stampTile}>▦</button>
            <button type="button" title="Remove (Backspace)" onclick={stampDelete}>✕</button>
          </div>
        {/if}

        {#if cropBox}
          <div class="crop" style={`left:${cropBox.left}px; top:${cropBox.top}px; width:${cropBox.w}px; height:${cropBox.h}px`} onmousedown={(e) => onCropDown(e)} role="presentation">
            <div class="thirds"></div>
            {#each ["nw", "ne", "sw", "se"] as h (h)}
              <div class={`handle ${h}`} onmousedown={(e) => onCropDown(e, h)} role="presentation"></div>
            {/each}
          </div>
        {/if}
      </div>

      <aside class="side">
        <p class="hint">{hint}</p>
        <h5>Crop</h5>
        <div class="row">
          <select bind:value={aspect} onchange={setAspect} style="flex:1">
            {#each ASPECTS.filter((a) => !a.group) as a (a.value)}<option value={a.value}>{a.label}</option>{/each}
            <optgroup label="Landscape">{#each ASPECTS.filter((a) => a.group === "Landscape") as a (a.value)}<option value={a.value}>{a.label}</option>{/each}</optgroup>
            <optgroup label="Portrait">{#each ASPECTS.filter((a) => a.group === "Portrait") as a (a.value)}<option value={a.value}>{a.label}</option>{/each}</optgroup>
          </select>
          <Button size="sm" onclick={resetCrop}>Reset</Button>
        </div>
        <p class="hint">{dims}</p>

        <h5>Export</h5>
        <select bind:value={format}>
          <option value="png">PNG: lossless, keeps prompt data</option>
          <option value="jpeg">JPEG: smaller, no transparency</option>
          <option value="webp">WebP: smaller, lossless-ish</option>
        </select>
        {#if format !== "png"}
          <label class="slider wide"><span>Quality</span><input type="range" min="50" max="100" bind:value={quality} /><span class="val">{quality}</span></label>
        {/if}
        {#if format === "jpeg"}
          <div class="row"><span class="hint lbl">Backing</span><input type="color" bind:value={bg} class="color" /><span class="hint">used where the image is transparent</span></div>
        {/if}

        <h5>Metadata</h5>
        <select bind:value={metaLevel}>
          <option value="generation">Keep generation data only</option>
          <option value="all">Keep everything</option>
          <option value="none">Strip everything</option>
        </select>
        {#if formatNote}<p class="warn">{formatNote}</p>{/if}

        <h5>Save to</h5>
        <select bind:value={dest}>
          <option value="suffix">Same folder, _edit suffix</option>
          <option value="folder">Choose a folder…</option>
        </select>
        <p class="hint">{destNote}</p>

        <span class="spacer"></span>
        <Button variant="primary" disabled={!ready || saving} onclick={save} title="Ctrl+Enter">{saving ? "Saving…" : "Save a copy"}</Button>
        <p class="hint">The original is never modified.</p>
      </aside>
    </div>
  </div>

  <Modal open={!!warn} title="Before this is saved" width={560} onclose={() => (warn = null)}>
    {#if warn}
      <p class="hint">Saving {name} as {format.toUpperCase()}. Here's what that costs.</p>
      <div class="stack" style="margin-top:var(--sp3)">
        {#each warn.list as [title, body] (title)}<div><strong>{title}</strong><p class="hint">{body}</p></div>{/each}
      </div>
      <label class="check" style="margin-top:var(--sp4)"><input type="checkbox" bind:checked={warnAgain} /> Don't show these warnings again</label>
    {/if}
    {#snippet actions()}
      <Button onclick={() => (warn = null)}>Go back</Button>
      <Button variant="primary" onclick={proceed}>Save anyway</Button>
    {/snippet}
  </Modal>

  <Modal open={discardOpen} title="Throw away this edit?" width={480} onclose={() => (discardOpen = false)}>
    <p class="hint">{discardText}</p>
    {#snippet actions()}
      <Button onclick={() => (discardOpen = false)}>Keep editing</Button>
      <Button variant="danger" onclick={() => { discardOpen = false; onclose(); }}>Discard</Button>
      <Button variant="primary" onclick={() => { discardOpen = false; save(); }}>Save a copy</Button>
    {/snippet}
  </Modal>

  <BrowseDialog open={browseOpen} title="Save the copy to…" confirmLabel="Save here" start={library.folder ?? ""} onpick={(dir) => { browseOpen = false; confirmThenSave(dir); }} onclose={() => (browseOpen = false)} />
{/if}

<style>
  .ed { position: fixed; inset: 0; z-index: 180; background: var(--bg); display: flex; flex-direction: column; }
  .top { display: flex; align-items: center; gap: var(--sp2); flex-wrap: wrap; padding: var(--sp2) var(--sp3); border-bottom: 1px solid var(--border); background: var(--surface); }
  .title { font-weight: 600; max-width: 22vw; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-right: var(--sp2); }
  .tools { display: flex; border: 1px solid var(--border); border-radius: var(--r-sm); overflow: hidden; }
  .tools button { min-height: 30px; min-width: 34px; padding: 0 var(--sp2); border: 0; background: transparent; color: var(--muted); font: inherit; font-size: 15px; cursor: pointer; }
  .tools button:hover { background: var(--hover); color: var(--text); }
  .tools button.on { background: var(--accent); color: var(--on-accent); }
  .hidden { display: none; }
  .swatches { display: flex; gap: 4px; align-items: center; }
  .sw { width: 20px; height: 20px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; padding: 0; box-shadow: 0 0 0 1px var(--border); }
  .sw:hover { transform: scale(1.12); }
  .sw.on { border-color: var(--text); box-shadow: 0 0 0 2px var(--bg) inset; }
  .sw.add { display: grid; place-items: center; background: var(--surface-2); color: var(--muted); font-size: 14px; position: relative; overflow: hidden; }
  .sw.add input { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%; }
  .top select { width: auto; max-width: 160px; height: 28px; font-size: 12.5px; }
  .slider { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
  .slider input[type=range] { width: 90px; }
  .slider.wide input[type=range] { flex: 1; width: auto; }
  .slider .val { min-width: 24px; font-variant-numeric: tabular-nums; color: var(--text); }
  .sep { width: 1px; height: 20px; background: var(--border-strong); }
  .zoom { font-size: 12px; color: var(--muted); min-width: 36px; text-align: right; font-variant-numeric: tabular-nums; }
  .body { flex: 1; display: flex; min-height: 0; }
  .stage { flex: 1; min-width: 0; position: relative; overflow: hidden; background: var(--rail); }
  .stage.grab { cursor: grab; }
  .stage.grabbing { cursor: grabbing; }
  canvas { position: absolute; cursor: crosshair; touch-action: none; }
  canvas.text-tool { cursor: text; }
  canvas.stamp-tool { cursor: default; }
  .loading { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); }
  .text-live { position: absolute; z-index: 8; min-width: 14px; font-weight: 600; line-height: 1; padding: 0; outline: 1px dashed var(--accent); background: rgba(0, 0, 0, .28); white-space: pre; caret-color: var(--accent); text-shadow: 0 1px 2px rgba(0, 0, 0, .85); }
  .text-sel { position: absolute; z-index: 7; border: 1px dashed var(--accent); cursor: move; }
  .text-sel .grip { position: absolute; right: -6px; bottom: -6px; width: 12px; height: 12px; background: var(--accent); border-radius: 2px; cursor: nwse-resize; }
  .stamp-sel { position: absolute; z-index: 7; border: 1px dashed var(--accent); cursor: move; transform-origin: center center; }
  .stamp-sel .stem { position: absolute; left: 50%; top: -26px; width: 1px; height: 26px; background: var(--accent); }
  .stamp-sel .grip { position: absolute; width: 12px; height: 12px; background: var(--accent); border-radius: 50%; }
  .stamp-sel .grip.rot { left: calc(50% - 6px); top: -34px; cursor: grab; }
  .stamp-sel .grip.br { right: -6px; bottom: -6px; border-radius: 2px; cursor: nwse-resize; }
  .bar { position: absolute; z-index: 9; display: flex; align-items: center; gap: 4px; padding: 3px 6px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-sm); box-shadow: var(--shadow-1); font-size: 12px; }
  .bar button { border: 0; background: transparent; color: var(--text); font: inherit; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
  .bar button:hover, .bar button.on { background: var(--hover-strong); }
  .bar .sz, .bar .lbl { color: var(--muted); font-variant-numeric: tabular-nums; }
  .bar .bsep { width: 1px; height: 16px; background: var(--border); }
  .bar select { height: 24px; width: auto; font-size: 12px; }
  .bar input[type=range] { width: 80px; }
  .crop { position: absolute; z-index: 6; border: 1px solid var(--accent); box-shadow: 0 0 0 9999px rgba(0, 0, 0, .55); cursor: move; }
  .crop .thirds { position: absolute; inset: 0; pointer-events: none; background: linear-gradient(to right, transparent calc(33.33% - .5px), rgba(255,255,255,.35) calc(33.33% - .5px), rgba(255,255,255,.35) calc(33.33% + .5px), transparent calc(33.33% + .5px), transparent calc(66.66% - .5px), rgba(255,255,255,.35) calc(66.66% - .5px), rgba(255,255,255,.35) calc(66.66% + .5px), transparent calc(66.66% + .5px)), linear-gradient(to bottom, transparent calc(33.33% - .5px), rgba(255,255,255,.35) calc(33.33% - .5px), rgba(255,255,255,.35) calc(33.33% + .5px), transparent calc(33.33% + .5px), transparent calc(66.66% - .5px), rgba(255,255,255,.35) calc(66.66% - .5px), rgba(255,255,255,.35) calc(66.66% + .5px), transparent calc(66.66% + .5px)); }
  .crop .handle { position: absolute; width: 12px; height: 12px; background: var(--accent); border-radius: 2px; }
  .crop .handle.nw { left: -6px; top: -6px; cursor: nwse-resize; }
  .crop .handle.ne { right: -6px; top: -6px; cursor: nesw-resize; }
  .crop .handle.sw { left: -6px; bottom: -6px; cursor: nesw-resize; }
  .crop .handle.se { right: -6px; bottom: -6px; cursor: nwse-resize; }
  .side { width: 300px; flex: none; overflow-y: auto; padding: var(--sp4); background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; gap: var(--sp2); }
  .side h5 { margin: var(--sp3) 0 0; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); font-weight: 600; }
  .side .lbl { min-width: 52px; }
  .side .color { width: 44px; padding: 2px; height: 28px; }
  .side .warn { color: var(--warn); font-size: 12px; }
  .wrap { flex-wrap: wrap; }
  .check { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; }
  .check input { width: auto; }
</style>
