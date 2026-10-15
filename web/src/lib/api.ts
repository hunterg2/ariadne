/* The only place that calls fetch. Types mirror the JSON the backend sends. */

export interface Camera {
  make: string; model: string; lens: string; exposure: string; aperture: string;
  iso: string; focal: string; taken_at: string; lat: number | null; lon: number | null;
  software: string;
}

export type Kind = "generated" | "photo" | "other" | "";

export interface ImageRow {
  path: string; folder: string; name: string; ext: string;
  time: number; mtime: number; bytes: number; width: number; height: number;
  kind: Kind; indexed: boolean;
  stars: number; rejected: number; label: string | null; category: string;
  prompt: string; negative: string; steps: string; cfg: string; sampler: string;
  scheduler: string; seed: string; denoise: string; model: string; loras: string[];
  phash: string; source: string; prompt_list: string; prompt_line: number; prompt_lines: number;
  camera: Camera; user_tags: string[]; collections: string[];
}

export interface Page {
  total: number; offset: number; limit: number; rows: ImageRow[]; pending: number;
}

export interface FolderSummary { total: number; unrated: number; rejected: number; pending: number }

export interface HistoryItem {
  type: "folder" | "group" | string;
  path?: string; alias?: string; status?: string;
  id?: string; name?: string; isOpen?: boolean; items?: HistoryItem[];
  pinned?: "top" | "bottom" | boolean;
  recursive?: boolean;        // the folder shows its subfolders' images too
}

export interface FolderStatus { ok: boolean; mtime: number; count: number | null }

export interface TagInfo { tag: string; count: number; group: string; color: string }

export interface Collection {
  id: string; name: string; kind: "manual" | "smart"; query: string; icon: string;
  color: string; sort_order: number; created: number; updated: number; count?: number;
}

export interface TrashItem {
  id: number; name: string; original_path: string; trash_path: string;
  deleted_at: number; category: string; tags: string[];
}

export interface Project { id: string; name: string; created: number; active: boolean; size: number; folder: string }

export interface ScanResult {
  success: boolean; added: number; updated: number; missing: number; total: number;
  folder: string; recursive: boolean; summary: FolderSummary; error?: string;
}

export type Settings = Record<string, any> & {
  hotkeys: Record<string, string[]>;
  ui: Record<string, any>;
  delete_mode: string;
  thumb_quality: number;
  last_folder: string;
};

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/* Another device has to enter the PIN first. The app registers a handler
   that shows the gate; "unset" means the server is exposed with no PIN yet. */
export type PinNeed = "pin" | "unset";
let pinHandler: ((need: PinNeed, message: string) => void) | null = null;
export function onPinNeeded(handler: (need: PinNeed, message: string) => void) {
  pinHandler = handler;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    if (body && body.pin && (res.status === 401 || res.status === 403) && pinHandler) {
      pinHandler(body.pin === "unset" ? "unset" : "pin", body.error || "");
    }
    throw new ApiError((body && body.error) || `${res.status} ${res.statusText}`, res.status);
  }
  if (body && body.success === false) {
    throw new ApiError(body.error || "That did not work.", res.status);
  }
  return body as T;
}

const get = <T,>(url: string, signal?: AbortSignal) => request<T>(url, signal ? { signal } : undefined);
const post = <T,>(url: string, body?: unknown, method = "POST") =>
  request<T>(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

export const enc = encodeURIComponent;

export const thumbUrl = (path: string) => "/thumb?path=" + enc(path);
export const imageUrl = (path: string) => "/image?path=" + enc(path);

/* settings and history */
export const getSettings = () => get<Settings>("/api/settings");
export const saveSettings = (settings: Settings) => post<{ success: boolean }>("/api/settings", settings);
export const getHistory = () => get<{ history: HistoryItem[] }>("/api/history");
export const addFolder = (folder: string) => post<{ history: HistoryItem[] }>("/api/history", { folder });
export const syncHistory = (history: HistoryItem[]) => post("/api/history/sync", { history });
export const updateHistory = (path: string, action: string, value?: unknown) =>
  post<{ history: HistoryItem[] }>("/api/history/update", { path, action, value });
export const checkHistory = (counts = false) =>
  get<{ status: Record<string, FolderStatus> }>("/api/history/check" + (counts ? "?counts=1" : ""));
export const repathFolder = (oldPath: string, newPath: string) =>
  post<{ history: HistoryItem[]; moved: number; path: string }>("/api/history/repath", { old: oldPath, new: newPath });
export const browse = (path: string) =>
  get<{ directories: { name: string; path: string }[]; current_path: string; parent_path: string }>(
    "/api/browse?path=" + enc(path));

/* images */
export interface ListParams {
  folder?: string | null; recursive?: boolean; q?: string; sort?: string; offset?: number; limit?: number;
  stars_min?: number | null; stars_max?: number | null; rejected?: boolean | null;
  kind?: string | null; tag?: string | null; collection?: string | null;
}

export function listImages(p: ListParams, signal?: AbortSignal) {
  const qs = new URLSearchParams();
  if (p.folder) qs.set("folder", p.folder);
  if (p.folder && p.recursive) qs.set("recursive", "1");
  if (p.q) qs.set("q", p.q);
  if (p.sort) qs.set("sort", p.sort);
  qs.set("offset", String(p.offset ?? 0));
  qs.set("limit", String(p.limit ?? 200));
  if (p.stars_min != null) qs.set("stars_min", String(p.stars_min));
  if (p.stars_max != null) qs.set("stars_max", String(p.stars_max));
  if (p.rejected != null) qs.set("rejected", p.rejected ? "1" : "0");
  if (p.kind) qs.set("kind", p.kind);
  if (p.tag) qs.set("tag", p.tag);
  if (p.collection) qs.set("collection", p.collection);
  return get<Page>("/api/images?" + qs.toString(), signal);
}
export const getImage = (path: string) => get<{ image: ImageRow }>("/api/images/one?path=" + enc(path));
export const scanFolder = (folder: string, wait = false, recursive = false) =>
  post<ScanResult>("/api/images/scan", { folder, wait, recursive });
export const folderSummaries = (folders: string[], recursive: string[] = []) =>
  post<{ summaries: Record<string, FolderSummary> }>("/api/images/summaries", { folders, recursive });
export const setRatings = (paths: string[], patch: { stars?: number; rejected?: boolean; label?: string | null }) =>
  post<{ ratings: Record<string, { stars: number; rejected: number; label: string | null }> }>(
    "/api/ratings", { paths, ...patch });
export const getPrompt = (path: string) => get<{ raw_workflow: string }>("/api/prompt?path=" + enc(path));
/* distinct values of a metadata field, for the search helper */
export interface Facet { value: string; count: number }
export const facets = (field: string, q = "", limit = 20) =>
  get<{ field: string; values: Facet[] }>(`/api/images/facets?field=${enc(field)}&q=${enc(q)}&limit=${limit}`);

/* duplicates, prompts, AI tag suggestions */
export interface DupeItem { path: string; name: string; folder: string; width: number; height: number; bytes: number; time: number; phash: string; stars: number; rejected: number; user_tags: string[] }
export interface DupeGroup { distance: number; items: DupeItem[]; keep: string }
export interface DupeLevel { key: string; d: number; label: string; note: string }
export const findDuplicates = (folder: string | null, level: string, recursive = false): Promise<{ level: DupeLevel; groups: DupeGroup[]; total: number; levels: DupeLevel[]; stats?: { groups: number; images: number; redundant: number; bytes: number; pct: number }; error?: string }> =>
  get<{ level: DupeLevel; levels: DupeLevel[]; groups: DupeGroup[]; total: number; stats?: { groups: number; images: number; redundant: number; bytes: number; pct: number } }>(
    "/api/duplicates?level=" + enc(level) + (folder ? "&folder=" + enc(folder) + (recursive ? "&recursive=1" : "") : ""));
export const uniquePrompts = (folder: string, recursive = false) =>
  get<{ prompts: { text: string; count: number; newest: number }[] }>("/api/prompts?folder=" + enc(folder) + (recursive ? "&recursive=1" : ""));
export const tagCheck = (tagger?: Record<string, unknown>) => post<{ ok: boolean; message: string }>("/api/tag/check", tagger ? { tagger } : {});
/* server-sent events: one message per image */
export function tagAutoStream(paths: string[]): EventSource {
  return new EventSource("/api/tag/auto?" + paths.map((p) => "path=" + enc(p)).join("&"));
}

/* tags */
export const setTags = (paths: string[], patch: { tags?: string[]; add_tags?: string[]; remove_tags?: string[] }) =>
  post("/api/tags", { paths, ...patch });
export const listTags = () => get<{ tags: TagInfo[] }>("/api/tags/list");
export const defineTag = (tag: string, group?: string, color?: string) => post("/api/tags/define", { tag, group, color });
export const renameTag = (oldName: string, newName: string) => post<{ moved: number }>("/api/tags/rename", { old: oldName, new: newName });
export const mergeTags = (sources: string[], target: string) => post<{ moved: number }>("/api/tags/merge", { sources, target });
export const deleteTag = (tag: string) => post<{ removed: number }>("/api/tags/delete", { tag });

/* collections */
export const listCollections = () => get<{ collections: Collection[] }>("/api/collections");
export const createCollection = (body: { name: string; kind?: string; query?: string; paths?: string[]; icon?: string; color?: string }) =>
  post<{ id: string; collection: Collection }>("/api/collections", body);
export const updateCollection = (id: string, body: Partial<Collection>) =>
  post<{ collection: Collection }>("/api/collections/" + enc(id), body, "PATCH");
export const deleteCollection = (id: string) => post("/api/collections/" + enc(id), {}, "DELETE");
export const collectionItems = (id: string, paths: string[], opts: { remove?: boolean; order?: boolean } = {}) =>
  post<{ added?: number; removed?: number }>("/api/collections/" + enc(id) + "/items", { paths, ...opts });

/* actions, trash, export */
export const action = (paths: string[], what: "trash" | "liked" | "loved" | "rest") =>
  post<{ trashed: { id: number; path: string }[] }>("/api/action", { paths, action: what });
export const listTrash = () => get<{ items: TrashItem[] }>("/api/trash");
export const restoreTrash = (ids: number[]) => post<{ restored: { id: number; path: string }[] }>("/api/trash/restore", { ids });
export const purgeTrash = (ids: number[] | "all") =>
  post<{ purged: number }>("/api/trash/purge", ids === "all" ? { all: true } : { ids });
export const exportFiles = (paths: string[], dest: string, mode: "copy" | "move") =>
  post<{ count: number; moved: { from: string; to: string }[] }>("/api/export", { paths, dest, mode });
export async function downloadZip(paths: string[]) {
  const res = await fetch("/api/export/zip", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paths }),
  });
  if (!res.ok) throw new ApiError("Could not build the zip.", res.status);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `export-${Date.now()}.zip`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}
export const reveal = (path: string) => post("/api/reveal", { path });

/* system */
export const stats = () => get<{ images_indexed: number; categorised: number; tag_links: number; in_trash: number }>("/api/stats");
export const projects = () => get<{ active: string; projects: Project[] }>("/api/projects");
export const switchProject = (id: string) => post("/api/projects/switch", { id });
export const createProject = (name: string) => post<{ id: string }>("/api/projects/create", { name });
export const renameProject = (id: string, name: string) => post("/api/projects/rename", { id, name });
export const deleteProject = (id: string) => post("/api/projects/delete", { id });
export const cacheStats = () => get<{ files: number; bytes: number; db_bytes: number }>("/api/cache/stats");
export const clearCache = (what: "thumbs" | "meta" | "all") => post("/api/cache/clear", { what });
export const pruneCache = () => post<{ removed: number }>("/api/cache/prune");
export const libraryStats = () => get<{ counts: Record<string, number>; backups: number; latest_backup: string }>("/api/library/stats");
export const importLibrary = (data: unknown, mode: "merge" | "replace") =>
  post<{ ratings: number; tag_links: number; missing_files: number }>("/api/library/import", { data, mode });
export interface SystemInfo {
  version: string; platform: string; tray_available: boolean; startup_supported: boolean; startup_enabled: boolean;
  startup_path: string; launcher: string; host: string; port: number; urls: string[];
  log_path: string;
  /* what the backup zip would hold (services/backup) */
  backup: { key_exists: boolean; key_path: string; data_dir: string; files: string[]; bytes: number };
}
export const systemInfo = () => get<SystemInfo>("/api/system");
export const setStartup = (on: boolean) => post<SystemInfo & { success: boolean; message: string }>("/api/system/startup", {}, on ? "POST" : "DELETE");
/* the text Settings copies for a bug report; the log itself is at /api/system/log */
export const diagnostics = () => get<{ text: string; log_path: string }>("/api/system/diagnostics");
/* a bug report drafted from what the user typed: the prefilled GitHub issue
   (title, body, url) and the whole report as text; ?download=1 is the file */
export interface BugReport { title: string; body: string; url: string; text: string; cut: boolean; repo: string }
const reportQuery = (summary: string, steps: string, diagnostics: boolean) =>
  `summary=${enc(summary)}&steps=${enc(steps)}&diagnostics=${diagnostics ? 1 : 0}`;
export const bugReport = (summary: string, steps: string, diagnostics: boolean) =>
  get<BugReport>("/api/system/report?" + reportQuery(summary, steps, diagnostics));
export const bugReportDownloadUrl = (summary: string, steps: string, diagnostics: boolean) =>
  "/api/system/report?download=1&" + reportQuery(summary, steps, diagnostics);
/* the update notice: the last look at GitHub's newest release */
export interface UpdateState { current: string; repo: string; enabled: boolean; checked_at: number | null; latest: string; url: string; error: string; newer: boolean }
export const updateState = () => get<UpdateState>("/api/updates");
export const checkUpdates = () => post<UpdateState>("/api/updates/check");
/* the PIN other devices enter; the computer itself never needs it */
export interface AuthStatus { exposed: boolean; required: boolean; has_pin: boolean; authenticated: boolean; locked: boolean }
export const authStatus = () => get<AuthStatus>("/api/auth/status");
export const enterPin = (pin: string) => post<AuthStatus>("/api/auth/pin", { pin });
export const setPin = (pin: string) => post<AuthStatus>("/api/settings/pin", { pin });
export const clearPin = () => post<AuthStatus>("/api/settings/pin", {}, "DELETE");
export const draftCaption = (paths: string[], kind: "caption" | "alt", limit?: number) => post<{ success: boolean; text: string; error?: string; backend: string }>("/api/captions/draft", { paths, kind, limit });
export const socialInspect = (paths: string[]) => get<{ prompt: number; model: number; camera: number; gps: number; edited: number; meta_edited: number; total: number }>("/api/social/inspect?paths=" + enc(JSON.stringify(paths)));

/* image editor: what the saved copy carries */
export type MetaLevel = "generation" | "all" | "none";
export interface WriteResult { success: boolean; path: string; name: string; tagged: boolean; notes: string[] }
export interface EditPayload {
  source_path: string; format: "png" | "jpeg" | "webp"; quality: number; metadata: MetaLevel;
  dest: "suffix" | "folder"; dest_dir: string; background: string;
}
export async function saveEdit(blob: Blob, payload: EditPayload) {
  const form = new FormData();
  form.append("image", blob, "edit." + (payload.format === "jpeg" ? "jpg" : payload.format));
  form.append("payload", JSON.stringify(payload));
  return request<WriteResult>("/api/edit/save", { method: "POST", body: form });
}
