/* Library state: the sidebar tree, the current view and its page cache, and
   the selection. The grid never holds more than the pages it has asked for. */

import { SvelteSet } from "svelte/reactivity";
import * as api from "../api";
import type { Collection, FolderStatus, FolderSummary, HistoryItem, ImageRow, TagInfo } from "../api";
import { reportError, toast } from "./toasts.svelte";
import { settings, ui } from "./settings.svelte";

export const PAGE = 200;
/* how long the visible range has to hold still, while it keeps changing,
   before its pages are fetched (ms) */
const RANGE_SETTLE = 24;

export interface Filters {
  q: string;
  stars_min: number | null;
  rejected: boolean | null;   // null = both, false = hide rejected, true = only rejected
  kind: string | null;
  tag: string | null;
}

export const EMPTY_FILTERS: Filters = { q: "", stars_min: null, rejected: false, kind: null, tag: null };

export type Scope =
  | { type: "folder"; path: string }
  | { type: "collection"; id: string }
  | { type: "all" };

class Library {
  history: HistoryItem[] = $state([]);
  status: Record<string, FolderStatus> = $state({});
  summaries: Record<string, FolderSummary> = $state({});
  collections: Collection[] = $state([]);
  tags: TagInfo[] = $state([]);

  scope: Scope = $state({ type: "all" });
  filters: Filters = $state({ ...EMPTY_FILTERS });
  sort = $state("date_desc");

  total = $state(0);
  pending = $state(0);
  rows: (ImageRow | undefined)[] = $state([]);
  loading = $state(false);
  loadedPages = new Set<number>();
  inflight = new Map<number, Promise<void>>();
  generation = 0;
  /* the pages the grid shows right now; a fetch for any other page is
     dropped, so a drag through the scrollbar asks for its destination only */
  private wanted = new Set<number>();
  private aborts = new Map<number, AbortController>();
  private rangeTimer: ReturnType<typeof setTimeout> | null = null;
  private rangeChangedAt = 0;

  selected = new SvelteSet<string>();
  focus = $state(-1);
  anchor = -1;

  /* ---- sidebar data ---- */

  async loadSidebar() {
    try {
      const [{ history }, { collections }, { tags }] = await Promise.all([
        api.getHistory(), api.listCollections(), api.listTags(),
      ]);
      this.history = history;
      this.collections = collections;
      this.tags = tags;
      this.refreshFolderStatus();
    } catch (e) {
      reportError(e, "Could not load the sidebar.");
    }
  }

  folderPaths(items: HistoryItem[] = this.history): string[] {
    const out: string[] = [];
    for (const it of items) {
      if (it.type === "folder" && it.path) out.push(it.path);
      else if (it.type === "group" && it.items) out.push(...this.folderPaths(it.items));
    }
    return out;
  }

  /* the sidebar folders whose counts and views include their subfolders */
  recursiveFolders(): string[] {
    return this.folderPaths().filter((p) => this.findFolder(p)?.recursive);
  }

  isRecursive(path: string | null | undefined): boolean {
    return !!path && !!this.findFolder(path)?.recursive;
  }

  /* Turn "include subfolders" on or off for a sidebar folder. The server
     remembers it and lists the subfolders in the background. */
  async setRecursive(path: string, on: boolean) {
    try {
      const res = await api.updateHistory(path, "recursive", on);
      this.history = res.history;
      if (this.scope.type === "folder" && this.scope.path === path) {
        if (on) await api.scanFolder(path, false, true).catch(() => {});
        this.reload();
        this.refreshPending();
      }
      this.refreshFolderStatus();
    } catch (e) { reportError(e); }
  }

  async refreshFolderStatus() {
    try {
      const [{ status }, { summaries }] = await Promise.all([
        api.checkHistory(true), api.folderSummaries(this.folderPaths(), this.recursiveFolders()),
      ]);
      this.status = status;
      this.summaries = summaries;
    } catch {
      /* a dead network path must not break the sidebar */
    }
  }

  async refreshTags() {
    try {
      this.tags = (await api.listTags()).tags;
    } catch { /* ignore */ }
  }

  async refreshCollections() {
    try {
      this.collections = (await api.listCollections()).collections;
    } catch { /* ignore */ }
  }

  /* ---- the current view ---- */

  get folder(): string | null {
    return this.scope.type === "folder" ? this.scope.path : null;
  }

  /* does the open folder include its subfolders? */
  get recursive(): boolean {
    return this.scope.type === "folder" && this.isRecursive(this.scope.path);
  }

  get title(): string {
    const s = this.scope;
    if (s.type === "folder") {
      const item = this.findFolder(s.path);
      return item?.alias || s.path.split(/[\\/]/).filter(Boolean).pop() || s.path;
    }
    if (s.type === "collection") {
      const id = s.id;
      return this.collections.find((c) => c.id === id)?.name ?? "Collection";
    }
    return "Whole library";
  }

  findFolder(path: string, items: HistoryItem[] = this.history): HistoryItem | null {
    for (const it of items) {
      if (it.type === "folder" && it.path === path) return it;
      if (it.type === "group" && it.items) {
        const hit = this.findFolder(path, it.items);
        if (hit) return hit;
      }
    }
    return null;
  }

  open(scope: Scope) {
    this.scope = scope;
    this.clearSelection();
    this.focus = -1;
    if (scope.type === "folder") {
      settings.data.last_folder = scope.path;
      api.scanFolder(scope.path, false, this.isRecursive(scope.path)).then(() => this.refreshPending()).catch(() => {});
    }
    this.reload();
  }

  setFilters(patch: Partial<Filters>) {
    this.filters = { ...this.filters, ...patch };
    this.reload();
  }

  setSort(sort: string) {
    this.sort = sort;
    this.reload();
  }

  private params(offset: number): api.ListParams {
    const s = this.scope;
    const collectionId = s.type === "collection" ? s.id : null;
    const collection = collectionId ? this.collections.find((c) => c.id === collectionId) : null;
    let q = this.filters.q;
    if (collection?.kind === "smart" && collection.query) q = q ? `${collection.query}; ${q}` : collection.query;
    return {
      folder: this.folder, recursive: this.recursive,
      collection: collection && collection.kind === "manual" ? collection.id : null,
      q, sort: this.sort, offset, limit: PAGE,
      stars_min: this.filters.stars_min, rejected: this.filters.rejected,
      kind: this.filters.kind, tag: this.filters.tag,
    };
  }

  reload() {
    this.generation++;
    this.loadedPages.clear();
    this.inflight.clear();
    this.rows = [];
    this.total = 0;
    this.loading = true;
    return this.ensurePage(0);
  }

  /* The grid's visible rows changed. Pages it no longer shows stop
     loading; the ones it shows load now, or, while the range is still
     moving (a scrollbar drag changes it every frame), once it has held
     still for a moment. Before this every page a drag passed was fetched
     and parsed, two hundred rows each, and the destination waited behind
     them all. */
  ensureRange(start: number, end: number): Promise<void> {
    const first = Math.max(0, Math.floor(start / PAGE));
    const last = Math.max(0, Math.floor(Math.max(end - 1, 0) / PAGE));
    this.wanted = new Set<number>();
    for (let p = first; p <= last; p++) this.wanted.add(p);
    for (const [p, ctl] of this.aborts) {
      if (!this.wanted.has(p)) { ctl.abort(); this.aborts.delete(p); this.inflight.delete(p); }
    }
    const now = performance.now();
    const moving = now - this.rangeChangedAt < RANGE_SETTLE;
    this.rangeChangedAt = now;
    if (this.rangeTimer) { clearTimeout(this.rangeTimer); this.rangeTimer = null; }
    const fetchWanted = () => Promise.all(Array.from(this.wanted, (p) => this.ensurePage(p, true))).then(() => undefined);
    if (!moving) return fetchWanted();
    return new Promise((resolve) => {
      this.rangeTimer = setTimeout(() => { this.rangeTimer = null; fetchWanted().then(resolve); }, RANGE_SETTLE);
    });
  }

  /* ``windowed``: the grid asked, so a later ensureRange may drop it */
  ensurePage(page: number, windowed = false): Promise<void> {
    if (this.loadedPages.has(page)) return Promise.resolve();
    const existing = this.inflight.get(page);
    if (existing) return existing;
    const gen = this.generation;
    const ctl = windowed ? new AbortController() : null;
    if (ctl) this.aborts.set(page, ctl);
    const promise = api.listImages(this.params(page * PAGE), ctl?.signal)
      .then((res) => {
        if (gen !== this.generation) return;
        this.total = res.total;
        this.pending = res.pending;
        if (this.rows.length !== res.total) this.rows.length = res.total;
        res.rows.forEach((row, i) => { this.rows[page * PAGE + i] = row; });
        this.loadedPages.add(page);
        this.loading = false;
      })
      .catch((e) => {
        if (ctl?.signal.aborted) return;                 // the grid moved on
        if (gen === this.generation) { this.loading = false; reportError(e, "Could not list images."); }
      })
      .finally(() => {
        if (this.inflight.get(page) === promise) this.inflight.delete(page);
        if (ctl && this.aborts.get(page) === ctl) this.aborts.delete(page);
      });
    this.inflight.set(page, promise);
    return promise;
  }

  async refreshPending() {
    if (this.pending > 0) {
      // the indexer is still reading files: fetch the first page again later
      setTimeout(() => this.refreshRows(0, Math.min(this.rows.length, PAGE)), 1500);
    }
  }

  /* Re-fetch a range in place (after the indexer filled in metadata). */
  async refreshRows(start: number, end: number) {
    const gen = this.generation;
    const first = Math.floor(start / PAGE);
    const last = Math.floor(Math.max(end - 1, 0) / PAGE);
    for (let p = first; p <= last; p++) {
      try {
        const res = await api.listImages(this.params(p * PAGE));
        if (gen !== this.generation) return;
        this.pending = res.pending;
        res.rows.forEach((row, i) => { this.rows[p * PAGE + i] = row; });
      } catch { /* ignore */ }
    }
    if (this.pending > 0) setTimeout(() => this.refreshRows(start, end), 2000);
  }

  rowAt(i: number): ImageRow | undefined {
    return this.rows[i];
  }

  indexOf(path: string): number {
    return this.rows.findIndex((r) => r?.path === path);
  }

  /* ---- selection ---- */

  get focused(): ImageRow | undefined {
    return this.focus >= 0 ? this.rows[this.focus] : undefined;
  }

  /* Moving focus with the keyboard or in the viewer carries a single
     selection along, so the inspector and every action agree on the target.
     A multi-selection is left alone (it is a batch). Click handlers pass
     sync=false because they manage the selection themselves. */
  setFocus(i: number, sync = true) {
    if (i < 0 || i >= this.total) return;
    this.focus = i;
    if (sync && this.selected.size <= 1) {
      const row = this.rows[i];
      if (row) { this.selected.clear(); this.selected.add(row.path); this.anchor = i; }
    }
  }

  toggleSelect(path: string) {
    if (this.selected.has(path)) this.selected.delete(path);
    else this.selected.add(path);
  }

  selectOnly(path: string) {
    this.selected.clear();
    this.selected.add(path);
  }

  selectRange(from: number, to: number) {
    const [a, b] = from < to ? [from, to] : [to, from];
    for (let i = a; i <= b; i++) {
      const row = this.rows[i];
      if (row) this.selected.add(row.path);
    }
  }

  clearSelection() {
    this.selected.clear();
    this.anchor = -1;
  }

  async selectAllLoaded() {
    await this.ensureRange(0, Math.min(this.total, 5000));
    for (const row of this.rows) if (row) this.selected.add(row.path);
  }

  /* The paths an action applies to: the selection, else the focused image. */
  targets(): string[] {
    if (this.selected.size) return Array.from(this.selected);
    const f = this.focused;
    return f ? [f.path] : [];
  }

  /* ---- mutations ---- */

  patchRows(paths: string[], patch: Partial<ImageRow>) {
    const set = new Set(paths);
    for (let i = 0; i < this.rows.length; i++) {
      const row = this.rows[i];
      if (row && set.has(row.path)) this.rows[i] = { ...row, ...patch };
    }
  }

  async rate(paths: string[], patch: { stars?: number; rejected?: boolean; label?: string | null }) {
    if (!paths.length) return;
    try {
      const res = await api.setRatings(paths, patch);
      for (const p of paths) {
        const r = res.ratings[p];
        if (r) this.patchRows([p], { stars: r.stars, rejected: r.rejected, label: r.label });
      }
      for (const p of new Set(paths.map((p) => this.rows.find((r) => r?.path === p)?.folder).filter(Boolean) as string[])) {
        this.updateSummary(p);
      }
    } catch (e) {
      reportError(e);
    }
  }

  /* Refresh the sidebar counts that cover ``folder``: the entry itself and
     any recursive entry it sits under. */
  async updateSummary(folder: string) {
    const sep = folder.includes("\\") ? "\\" : "/";
    const targets = this.folderPaths().filter((f) => f === folder || (this.isRecursive(f) && folder.startsWith(f + sep)));
    if (!targets.length) targets.push(folder);
    try {
      const { summaries } = await api.folderSummaries(targets, targets.filter((f) => this.isRecursive(f)));
      Object.assign(this.summaries, summaries);
    } catch { /* ignore */ }
  }

  async addTags(paths: string[], tags: string[]) {
    if (!paths.length || !tags.length) return;
    try {
      await api.setTags(paths, { add_tags: tags });
      for (const p of paths) {
        const row = this.rows.find((r) => r?.path === p);
        if (row) this.patchRows([p], { user_tags: Array.from(new Set([...row.user_tags, ...tags])).sort() });
      }
      this.refreshTags();
    } catch (e) {
      reportError(e);
    }
  }

  async removeTags(paths: string[], tags: string[]) {
    if (!paths.length || !tags.length) return;
    try {
      await api.setTags(paths, { remove_tags: tags });
      for (const p of paths) {
        const row = this.rows.find((r) => r?.path === p);
        if (row) this.patchRows([p], { user_tags: row.user_tags.filter((t) => !tags.includes(t)) });
      }
      this.refreshTags();
    } catch (e) {
      reportError(e);
    }
  }

  async trash(paths: string[]) {
    if (!paths.length) return;
    try {
      const res = await api.action(paths, "trash");
      this.removeRows(paths);
      const n = res.trashed.length || paths.length;
      toast(`${n} image${n === 1 ? "" : "s"} moved to trash.`);
      for (const p of paths) this.selected.delete(p);
    } catch (e) {
      reportError(e);
    }
  }

  /* An editor wrote a new file: index its folder, then show it if that folder
     (or everything) is open. */
  async afterWrite(path: string) {
    const folder = path.replace(/[\\/][^\\/]*$/, "");
    try { await api.scanFolder(folder, true); } catch { /* the indexer picks it up later */ }
    const sep = folder.includes("\\") ? "\\" : "/";
    const shown = this.scope.type === "all"
      || (this.scope.type === "folder" && (this.scope.path === folder || (this.recursive && folder.startsWith(this.scope.path + sep))));
    if (shown) {
      const focused = this.focused?.path;
      await this.reload();
      if (focused) { const i = this.indexOf(focused); if (i >= 0) this.setFocus(i, false); }
    }
    this.updateSummary(folder);
    this.refreshTags();
  }

  removeRows(paths: string[]) {
    const set = new Set(paths);
    const kept = this.rows.filter((r) => !r || !set.has(r.path));
    const removed = this.rows.length - kept.length;
    this.rows = kept;
    this.total = Math.max(0, this.total - removed);
    if (this.focus >= this.rows.length) this.focus = this.rows.length - 1;
    // the pages after the hole are now shifted: forget them so they reload
    this.loadedPages.clear();
    this.loadedPages.add(0);
    const folders = new Set(paths.map((p) => p.replace(/[\\/][^\\/]*$/, "")));
    for (const f of folders) this.updateSummary(f);
  }
}

export const library = new Library();

export function gridSize() {
  return ui("grid_size");
}
