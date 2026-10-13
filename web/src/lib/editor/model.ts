/* The image editor's document: the picture with its rotation and flip baked
   into a source canvas, the annotations in image coordinates, and the crop.
   Nothing in here is reactive; the component bumps a counter and redraws.
   Everything is stored in image pixels, so zooming the view never changes
   what gets saved. */

export type Pt = [number, number];

export interface StrokeItem { type: "stroke" | "highlight"; color: string; size: number; points: Pt[] }
export interface ArrowItem { type: "arrow"; color: string; size: number; x1: number; y1: number; x2: number; y2: number }
export interface ShapeItem { type: "rect" | "ellipse"; color: string; size: number; x: number; y: number; w: number; h: number }
export interface TextItem { type: "text"; x: number; y: number; text: string; color: string; size: number; font: string; hidden?: boolean }
export interface BlurItem {
  type: "blur"; kind: string; amount: number;
  size?: number; points?: Pt[];                       // brush
  shape?: "rect" | "ellipse"; x?: number; y?: number; w?: number; h?: number;   // area
}
export interface StampItem { type: "stamp"; src: string; x: number; y: number; w: number; h: number; angle: number; opacity: number; flip: boolean; tile: boolean }
export type Item = StrokeItem | ArrowItem | ShapeItem | TextItem | BlurItem | StampItem;
export interface Crop { x: number; y: number; w: number; h: number }
export type Tool = "marker" | "highlight" | "arrow" | "rect" | "ellipse" | "text" | "blur" | "blurarea" | "stamp" | "crop";

export const COLORS = ["#ff3b30", "#ff9500", "#ffd60a", "#34c759", "#0a84ff", "#bf5af2", "#ffffff", "#000000"];

/* Only stacks that resolve to something on every platform, so what you see
   while typing is what the canvas draws. */
export const FONTS: [string, string, string][] = [
  ["sans", "Sans", '-apple-system, "Segoe UI", Roboto, sans-serif'],
  ["serif", "Serif", 'Georgia, "Times New Roman", serif'],
  ["mono", "Monospace", '"JetBrains Mono", Consolas, "Courier New", monospace'],
  ["heavy", "Heavy", 'Impact, "Arial Black", "Haettenschweiler", sans-serif'],
  ["round", "Rounded", '"Trebuchet MS", Verdana, sans-serif'],
  ["hand", "Handwritten", '"Comic Sans MS", "Segoe Print", cursive'],
];
const FONT_STACK = Object.fromEntries(FONTS.map((f) => [f[0], f[2]]));
export const fontStack = (key: string) => FONT_STACK[key] ?? FONT_STACK.sans;

export const BLUR_KINDS: [string, string, string][] = [
  ["gaussian", "Gaussian", "An even, soft blur. The usual choice for hiding a face or a name."],
  ["pixelate", "Pixelate", "Big flat squares. Unmistakably deliberate, which is sometimes what you want."],
  ["unfocus", "Unfocus", "Rounder and creamier, the way a lens throws a background out of focus."],
];

export const HINTS: Record<Tool, string> = {
  marker: "Drag to draw. Size and colour apply to the next stroke.",
  highlight: "Drag to highlight. Strokes are translucent and overlap softly.",
  arrow: "Drag from the tail to the head.",
  rect: "Drag out a rectangle.",
  ellipse: "Drag out an ellipse.",
  text: "Click the image and type where you want it. Click existing text to pick it up, double-click to retype.",
  crop: "Drag the box or its corners. Pick a ratio to lock the shape.",
  blur: "Paint over what you want hidden. Size sets the width of the brush.",
  blurarea: "Drag a box over what you want hidden.",
  stamp: "Drag it about, pull the corner to resize, use the handle above to turn it. Shift while turning snaps to 15 degrees.",
};
export const ZOOM_HINT = " Scroll to zoom, hold Space to pan, right-click an annotation to delete it.";

export const ASPECTS: { value: string; label: string; group?: string }[] = [
  { value: "free", label: "Free" }, { value: "orig", label: "Original" }, { value: "1", label: "Square 1:1" },
  { value: "1.25", label: "5:4", group: "Landscape" }, { value: "1.3333", label: "4:3", group: "Landscape" },
  { value: "1.4", label: "7:5", group: "Landscape" }, { value: "1.5", label: "3:2", group: "Landscape" },
  { value: "1.7778", label: "16:9", group: "Landscape" }, { value: "2", label: "2:1", group: "Landscape" },
  { value: "0.8", label: "4:5", group: "Portrait" }, { value: "0.75", label: "3:4", group: "Portrait" },
  { value: "0.7143", label: "5:7", group: "Portrait" }, { value: "0.6667", label: "2:3", group: "Portrait" },
  { value: "0.5625", label: "9:16", group: "Portrait" }, { value: "0.5", label: "1:2", group: "Portrait" },
];

const norm = (deg: number) => ((deg % 360) + 360) % 360;

function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number) {
  const dx = x2 - x1, dy = y2 - y1;
  const len = dx * dx + dy * dy;
  let t = len ? ((px - x1) * dx + (py - y1) * dy) / len : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

/* A stroke is a line and a clip needs an area, so the line becomes a run of
   overlapping discs joined by quads. Round ends come free. */
function strokeToRegion(pts: Pt[], size: number) {
  const path = new Path2D();
  const r = Math.max(1, size / 2);
  for (let i = 0; i < pts.length; i++) {
    path.moveTo(pts[i][0] + r, pts[i][1]);
    path.arc(pts[i][0], pts[i][1], r, 0, Math.PI * 2);
    if (i > 0) {
      const [x1, y1] = pts[i - 1], [x2, y2] = pts[i];
      const a = Math.atan2(y2 - y1, x2 - x1) + Math.PI / 2;
      const dx = Math.cos(a) * r, dy = Math.sin(a) * r;
      path.moveTo(x1 + dx, y1 + dy); path.lineTo(x2 + dx, y2 + dy);
      path.lineTo(x2 - dx, y2 - dy); path.lineTo(x1 - dx, y1 - dy);
      path.closePath();
    }
  }
  return path;
}

export class Scene {
  base: HTMLImageElement | null = null;
  baseW = 0; baseH = 0;
  rot = 0; flip = false;
  source: HTMLCanvasElement | null = null;
  w = 0; h = 0;
  items: Item[] = [];
  crop: Crop | null = null;
  onStampLoaded: (() => void) | null = null;

  private blurCache = new Map<string, HTMLCanvasElement>();
  private blurStamp = 0;
  private stampImages = new Map<string, HTMLImageElement>();

  load(img: HTMLImageElement) {
    this.base = img; this.baseW = img.naturalWidth; this.baseH = img.naturalHeight;
    this.rot = 0; this.flip = false; this.items = []; this.crop = null;
    this.rebuildSource();
  }

  /* ---- rotation and flip are state, not baked pixels ------------------ */
  rebuildSource() {
    this.blurCache = new Map(); this.blurStamp++;
    if (!this.base) return;
    const rot = norm(this.rot);
    const swap = rot === 90 || rot === 270;
    const w = swap ? this.baseH : this.baseW, h = swap ? this.baseW : this.baseH;
    const c = document.createElement("canvas");
    c.width = Math.max(1, w); c.height = Math.max(1, h);
    const ctx = c.getContext("2d")!;
    ctx.save();
    if (rot === 90) { ctx.translate(this.baseH, 0); ctx.rotate(Math.PI / 2); }
    else if (rot === 180) { ctx.translate(this.baseW, this.baseH); ctx.rotate(Math.PI); }
    else if (rot === 270) { ctx.translate(0, this.baseW); ctx.rotate(-Math.PI / 2); }
    if (this.flip) { ctx.translate(this.baseW, 0); ctx.scale(-1, 1); }
    ctx.drawImage(this.base, 0, 0, this.baseW, this.baseH);
    ctx.restore();
    this.source = c; this.w = w; this.h = h;
  }

  private fwd(state: { rot: number; flip: boolean }, x: number, y: number) {
    const rot = norm(state.rot);
    const bx = state.flip ? this.baseW - x : x, by = y;
    if (rot === 0) return { x: bx, y: by };
    if (rot === 90) return { x: this.baseH - by, y: bx };
    if (rot === 180) return { x: this.baseW - bx, y: this.baseH - by };
    return { x: by, y: this.baseW - bx };
  }
  private inv(state: { rot: number; flip: boolean }, x: number, y: number) {
    const rot = norm(state.rot);
    let bx: number, by: number;
    if (rot === 0) { bx = x; by = y; }
    else if (rot === 90) { bx = y; by = this.baseH - x; }
    else if (rot === 180) { bx = this.baseW - x; by = this.baseH - y; }
    else { bx = this.baseW - y; by = x; }
    return { x: state.flip ? this.baseW - bx : bx, y: by };
  }

  /* Change rotation or flip, carrying the annotations and crop along. */
  transform(rot: number, flip: boolean) {
    const before = { rot: this.rot, flip: this.flip };
    this.rot = norm(rot); this.flip = flip;
    const after = { rot: this.rot, flip: this.flip };
    const map = (x: number, y: number) => { const b = this.inv(before, x, y); return this.fwd(after, b.x, b.y); };
    for (const it of this.items) {
      if ("points" in it && it.points) it.points = it.points.map(([x, y]) => { const p = map(x, y); return [p.x, p.y] as Pt; });
      if (it.type === "arrow") {
        const a = map(it.x1, it.y1), b = map(it.x2, it.y2);
        it.x1 = a.x; it.y1 = a.y; it.x2 = b.x; it.y2 = b.y;
      }
      if (it.type === "rect" || it.type === "ellipse" || (it.type === "blur" && it.shape) || it.type === "stamp") {
        const box = it as { x: number; y: number; w: number; h: number };
        const a = map(box.x, box.y), b = map(box.x + box.w, box.y + box.h);
        box.x = Math.min(a.x, b.x); box.y = Math.min(a.y, b.y);
        box.w = Math.abs(b.x - a.x); box.h = Math.abs(b.y - a.y);
      }
      if (it.type === "text") { const a = map(it.x, it.y); it.x = a.x; it.y = a.y; }
    }
    if (this.crop) {
      const a = map(this.crop.x, this.crop.y), b = map(this.crop.x + this.crop.w, this.crop.y + this.crop.h);
      this.crop = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) };
    }
    this.rebuildSource();
  }

  /* ---- undo snapshots -------------------------------------------------- */
  snapshot() {
    return JSON.stringify({ items: this.items, crop: this.crop, rot: this.rot, flip: this.flip });
  }
  restore(json: string) {
    const st = JSON.parse(json);
    this.items = st.items ?? [];
    this.crop = st.crop ?? null;
    this.rot = st.rot ?? 0;
    this.flip = !!st.flip;
    this.rebuildSource();
  }

  /* ---- geometry -------------------------------------------------------- */
  area(): Crop { return this.crop ?? { x: 0, y: 0, w: this.w, h: this.h }; }
  cropIsFull() {
    const c = this.crop;
    return !c || (c.x <= 0.5 && c.y <= 0.5 && c.w >= this.w - 0.5 && c.h >= this.h - 0.5);
  }
  hasChanges() {
    return this.items.length > 0 || this.rot !== 0 || this.flip || !this.cropIsFull();
  }

  textBounds(ctx: CanvasRenderingContext2D, it: TextItem) {
    ctx.save();
    ctx.font = `600 ${it.size}px ${fontStack(it.font)}`;
    const w = ctx.measureText(it.text).width || it.text.length * it.size * 0.55;
    ctx.restore();
    return { x: it.x, y: it.y, w, h: it.size * 1.2 };
  }

  /* Which annotation is under the cursor, topmost first. */
  itemHit(ctx: CanvasRenderingContext2D, p: { x: number; y: number }) {
    for (let i = this.items.length - 1; i >= 0; i--) {
      const it = this.items[i];
      const grab = Math.max("size" in it && it.size ? it.size : 8, 10);
      if (it.type === "text") {
        const b = this.textBounds(ctx, it);
        if (p.x >= b.x - 6 && p.x <= b.x + b.w + 6 && p.y >= b.y - 6 && p.y <= b.y + b.h + 6) return i;
      } else if ("points" in it && it.points) {
        const pts = it.points;
        const reach = it.type === "highlight" ? grab * 1.6 : grab;
        for (let k = 1; k < pts.length; k++) {
          if (distToSegment(p.x, p.y, pts[k - 1][0], pts[k - 1][1], pts[k][0], pts[k][1]) <= reach) return i;
        }
        if (pts.length === 1 && Math.hypot(p.x - pts[0][0], p.y - pts[0][1]) <= reach) return i;
      } else if (it.type === "arrow") {
        if (distToSegment(p.x, p.y, it.x1, it.y1, it.x2, it.y2) <= grab) return i;
      } else if (it.type === "rect" || it.type === "ellipse" || (it.type === "blur" && it.shape)) {
        const box = it as { x: number; y: number; w: number; h: number };
        const inX = p.x >= box.x - grab && p.x <= box.x + box.w + grab;
        const inY = p.y >= box.y - grab && p.y <= box.y + box.h + grab;
        if (it.type === "blur") { if (inX && inY) return i; continue; }
        const onV = Math.abs(p.x - box.x) <= grab || Math.abs(p.x - (box.x + box.w)) <= grab;
        const onH = Math.abs(p.y - box.y) <= grab || Math.abs(p.y - (box.y + box.h)) <= grab;
        if (inX && inY && (onV || onH)) return i;
      } else if (it.type === "stamp" && !it.tile) {
        if (this.stampContains(it, p)) return i;
      }
    }
    return -1;
  }
  textHit(ctx: CanvasRenderingContext2D, p: { x: number; y: number }) {
    for (let i = this.items.length - 1; i >= 0; i--) {
      const it = this.items[i];
      if (it.type !== "text") continue;
      const b = this.textBounds(ctx, it);
      if (p.x >= b.x - 6 && p.x <= b.x + b.w + 6 && p.y >= b.y - 6 && p.y <= b.y + b.h + 6) return i;
    }
    return -1;
  }
  private stampContains(it: StampItem, p: { x: number; y: number }) {
    // undo the rotation, then it is a plain box test
    const cx = it.x + it.w / 2, cy = it.y + it.h / 2;
    const a = -(it.angle || 0);
    const dx = p.x - cx, dy = p.y - cy;
    const rx = dx * Math.cos(a) - dy * Math.sin(a);
    const ry = dx * Math.sin(a) + dy * Math.cos(a);
    return Math.abs(rx) <= it.w / 2 && Math.abs(ry) <= it.h / 2;
  }
  stampHit(p: { x: number; y: number }) {
    for (let i = this.items.length - 1; i >= 0; i--) {
      const it = this.items[i];
      if (it.type === "stamp" && !it.tile && this.stampContains(it, p)) return i;
    }
    return -1;
  }

  /* ---- painting -------------------------------------------------------- */
  draw(canvas: HTMLCanvasElement, scale: number, live: Item | null) {
    if (!this.source) return;
    const ctx = canvas.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);
    ctx.drawImage(this.source, 0, 0, this.w, this.h);
    for (const it of this.items) this.paintItem(ctx, it);
    if (live) this.paintItem(ctx, live);
  }

  /* The full-size result: the crop area with every annotation flattened in. */
  renderFull() {
    const a = this.area();
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(a.w)); c.height = Math.max(1, Math.round(a.h));
    const ctx = c.getContext("2d")!;
    ctx.translate(-a.x, -a.y);
    if (this.source) ctx.drawImage(this.source, 0, 0, this.w, this.h);
    for (const it of this.items) this.paintItem(ctx, it);
    return c;
  }

  paintItem(ctx: CanvasRenderingContext2D, it: Item) {
    if (it.type === "text" && it.hidden) return;
    if (it.type === "stamp") { this.paintStamp(ctx, it); return; }
    if (it.type === "blur") { this.paintBlur(ctx, it); return; }
    ctx.save();
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.strokeStyle = it.color; ctx.fillStyle = it.color; ctx.lineWidth = it.size;
    if (it.type === "highlight") { ctx.globalAlpha = 0.38; ctx.lineWidth = it.size * 2.5; }
    if (it.type === "stroke" || it.type === "highlight") {
      const pts = it.points;
      if (pts.length === 1) {
        ctx.beginPath(); ctx.arc(pts[0][0], pts[0][1], ctx.lineWidth / 2, 0, Math.PI * 2); ctx.fill();
      } else if (pts.length > 1) {
        ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        ctx.stroke();
      }
    } else if (it.type === "rect") {
      ctx.strokeRect(it.x, it.y, it.w, it.h);
    } else if (it.type === "ellipse") {
      ctx.beginPath();
      ctx.ellipse(it.x + it.w / 2, it.y + it.h / 2, Math.abs(it.w / 2), Math.abs(it.h / 2), 0, 0, Math.PI * 2);
      ctx.stroke();
    } else if (it.type === "arrow") {
      const head = Math.max(it.size * 3.2, 12);
      const ang = Math.atan2(it.y2 - it.y1, it.x2 - it.x1);
      const bx = it.x2 - Math.cos(ang) * head * 0.72, by = it.y2 - Math.sin(ang) * head * 0.72;
      ctx.beginPath(); ctx.moveTo(it.x1, it.y1); ctx.lineTo(bx, by); ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(it.x2, it.y2);
      ctx.lineTo(it.x2 - Math.cos(ang - 0.42) * head, it.y2 - Math.sin(ang - 0.42) * head);
      ctx.lineTo(it.x2 - Math.cos(ang + 0.42) * head, it.y2 - Math.sin(ang + 0.42) * head);
      ctx.closePath(); ctx.fill();
    } else if (it.type === "text") {
      ctx.font = `600 ${it.size}px ${fontStack(it.font)}`;
      ctx.textBaseline = "top";
      ctx.lineWidth = Math.max(2, it.size / 7);
      ctx.strokeStyle = "rgba(0,0,0,.65)";
      ctx.strokeText(it.text, it.x, it.y);
      ctx.fillStyle = it.color;
      ctx.fillText(it.text, it.x, it.y);
    }
    ctx.restore();
  }

  /* Every blur works the same way: one blurred copy of the whole picture,
     drawn through a clip. The copy is the expensive step, so it is cached by
     kind and strength until the picture underneath changes. */
  private blurredCopy(kind: string, amount: number) {
    const key = `${kind}:${amount}:${this.blurStamp}`;
    const hit = this.blurCache.get(key);
    if (hit) return hit;
    const out = document.createElement("canvas");
    out.width = this.w; out.height = this.h;
    const ctx = out.getContext("2d")!;
    const src = this.source!;
    if (kind === "pixelate") {
      const block = Math.max(2, Math.round(amount));
      const sw = Math.max(1, Math.round(this.w / block)), sh = Math.max(1, Math.round(this.h / block));
      const small = document.createElement("canvas");
      small.width = sw; small.height = sh;
      small.getContext("2d")!.drawImage(src, 0, 0, sw, sh);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(small, 0, 0, sw, sh, 0, 0, this.w, this.h);
    } else if (kind === "unfocus") {
      // a ring of offset copies approximates a disc, which is what a lens does
      const r = Math.max(1, amount / 2), steps = 12;
      ctx.filter = `blur(${(amount / 3).toFixed(2)}px)`;
      ctx.globalAlpha = 1 / steps;
      for (let i = 0; i < steps; i++) {
        const a = (i / steps) * Math.PI * 2;
        ctx.drawImage(src, Math.cos(a) * r, Math.sin(a) * r, this.w, this.h);
      }
      ctx.globalAlpha = 1; ctx.filter = "none";
    } else {
      ctx.filter = `blur(${Math.max(0.5, amount).toFixed(2)}px)`;
      ctx.drawImage(src, 0, 0, this.w, this.h);
      ctx.filter = "none";
    }
    if (this.blurCache.size > 6) this.blurCache.clear();
    this.blurCache.set(key, out);
    return out;
  }

  private paintBlur(ctx: CanvasRenderingContext2D, it: BlurItem) {
    if (!this.source) return;
    const copy = this.blurredCopy(it.kind || "gaussian", it.amount || 12);
    ctx.save();
    ctx.beginPath();
    if (it.points) {
      ctx.clip(strokeToRegion(it.points, it.size ?? 12));
    } else {
      const x = Math.min(it.x!, it.x! + it.w!), y = Math.min(it.y!, it.y! + it.h!);
      const w = Math.abs(it.w!), h = Math.abs(it.h!);
      if (it.shape === "ellipse") ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
      else ctx.rect(x, y, w, h);
      ctx.clip();
    }
    ctx.drawImage(copy, 0, 0, this.w, this.h);
    ctx.restore();
  }

  stampImage(src: string) {
    let img = this.stampImages.get(src);
    if (!img) {
      img = new Image();
      img.onload = () => this.onStampLoaded?.();
      img.src = src;
      this.stampImages.set(src, img);
    }
    return img;
  }

  private paintStamp(ctx: CanvasRenderingContext2D, it: StampItem) {
    const img = this.stampImage(it.src);
    if (!img.complete || !img.naturalWidth) return;
    ctx.save();
    ctx.globalAlpha = it.opacity ?? 1;
    const cx = it.x + it.w / 2, cy = it.y + it.h / 2;
    if (it.tile) {
      const stepX = it.w * 1.6, stepY = it.h * 1.9;
      for (let y = -this.h; y < this.h * 2; y += stepY) {
        for (let x = -this.w; x < this.w * 2; x += stepX) {
          ctx.save();
          ctx.translate(x + it.w / 2, y + it.h / 2);
          if (it.angle) ctx.rotate(it.angle);
          if (it.flip) ctx.scale(-1, 1);
          ctx.drawImage(img, -it.w / 2, -it.h / 2, it.w, it.h);
          ctx.restore();
        }
      }
    } else {
      ctx.translate(cx, cy);
      if (it.angle) ctx.rotate(it.angle);
      if (it.flip) ctx.scale(-1, 1);
      ctx.drawImage(img, -it.w / 2, -it.h / 2, it.w, it.h);
    }
    ctx.restore();
  }
}

/* What a save will cost, spelled out before the file is written. */
export function qualityWarnings(opts: { format: string; quality: number; metadata: string; sourceName: string; background: string; edited: boolean }) {
  const { format: fmt, quality: q, metadata: mode, background } = opts;
  const srcExt = opts.sourceName.split(".").pop()?.toLowerCase() ?? "";
  const out: [string, string][] = [];
  if (fmt === "jpeg") {
    out.push(["JPEG throws away detail to save space",
      `At quality ${q} the image is re-compressed. Fine texture, smooth gradients and hard edges soften slightly, and JPEG artefacts appear around high-contrast lines. This is baked into the new file and cannot be undone by re-saving.`]);
    if (srcExt === "png" || srcExt === "webp") {
      out.push(["You're moving off a lossless format",
        `The original .${srcExt} holds exact pixel values. The JPEG copy will not, so treat it as an export rather than a replacement.`]);
    }
    out.push(["No transparency", `JPEG cannot store an alpha channel. Anything transparent is filled with ${background}.`]);
  }
  if (fmt === "webp") {
    if (q < 100) out.push(["WebP is lossy below 100", `At quality ${q} some detail is discarded, though usually less than JPEG at the same number. Slide quality to 100 for a near-lossless file.`]);
    if (srcExt === "png") out.push(["Leaving PNG", "Even at quality 100 this WebP encoder is not bit-exact with the PNG original."]);
  }
  if (fmt !== "png" && mode !== "none") {
    out.push(["Prompt data may not fit",
      "Generation data lives in PNG text chunks and has to be rewritten into EXIF for this format. EXIF caps out at 64 KB, and a ComfyUI workflow often exceeds that, in which case it is dropped entirely. You'll be told if that happens."]);
  }
  if (mode === "none") {
    out.push(["Every trace of metadata is removed",
      "The copy will carry no prompt, model, seed or workflow. That's the point if you're sharing it publicly, but the copy can't be traced back to how it was made."]);
  }
  if (opts.edited) {
    out.push(["The edit is flattened",
      "Crop, strokes and text are rendered into the pixels. The copy is a picture, not a layered file, so they can't be moved or removed later. Your original is untouched."]);
  }
  return out;
}
