"""The image index.

A folder is scanned in two passes so a big one shows up at once:

1. ``scan_folder`` lists the directory and upserts one row per file with
   only what ``stat`` gives (name, size, times). Rows whose file changed are
   marked for re-reading; rows whose file is gone are marked missing.
2. ``enrich`` works through rows with no ``indexed_at`` yet, reading the
   image for its size, generation metadata, camera EXIF and ``kind``.

``query_images`` serves pages from the index with filters and sorting done in
SQL, so the browser never receives more than one page.
"""

import json
import os
import threading
import time

from PIL import Image

from ariadne import config, metadata, safety, store, text
from ariadne import db as db_module
from ariadne.db import db
from ariadne.log import log
from ariadne.services import collections as collections_svc
from ariadne.services import tags as tags_svc
from ariadne.services import thumbs
from ariadne.services.meta_cache import get_metadata
from ariadne.services.search import prepare_query, to_sql

# folders a recursive scan never descends into
SKIPPED_DIRS = {"trash"}

KINDS = ("generated", "photo", "other")

SORTS = {
    "date_desc": "i.ctime DESC, i.name DESC",
    "date_asc": "i.ctime ASC, i.name ASC",
    "mtime_desc": "i.mtime DESC, i.name DESC",
    "name_asc": "lower(i.name) ASC",
    "name_desc": "lower(i.name) DESC",
    "size_desc": "i.size DESC",
    "size_asc": "i.size ASC",
    "stars_desc": "i.stars DESC, i.ctime DESC",
    "stars_asc": "i.stars ASC, i.ctime DESC",
    "random": "random()",
}

CAMERA_KEYS = {
    "camera_make": "make", "camera_model": "model", "lens": "lens",
    "exposure": "exposure", "f_number": "aperture", "iso": "iso",
    "focal": "focal", "taken_at": "date_taken", "software": "software",
}


def kind_of(meta, camera):
    """Where the image came from, decided once from the file itself."""
    if meta.get("prompt") or meta.get("model") or meta.get("steps"):
        return "generated"
    if camera.get("make") or camera.get("model") or camera.get("date_taken"):
        return "photo"
    return "other"


# --------------------------------------------------------------------------
# pass 1: the directory listing
# --------------------------------------------------------------------------

def scope_sql(folder, recursive=False, col="i.folder"):
    """The WHERE fragment for one folder, or for it and everything under it.
    The recursive form is a range on the folder column, which the index
    answers directly: every descendant sorts between ``root + sep`` and
    ``root + sep`` followed by the largest code point."""
    root = safety.as_listed(folder)      # spelled as the rows are
    if not recursive:
        return f"{col}=?", [root]
    low = root + os.sep
    return f"({col}=? OR ({col} > ? AND {col} < ?))", [root, low, low + "\U0010FFFF"]


def _walk(root, recursive):
    """Yield (parent, DirEntry) for every file under ``root``; with
    ``recursive`` it descends, skipping dot-folders and ``trash``. An
    unreadable root raises; an unreadable subfolder is skipped."""
    stack = [root]
    first = True
    while stack:
        parent = stack.pop()
        try:
            entries = list(os.scandir(parent))
        except OSError:
            if first:
                raise
            continue
        first = False
        subdirs = []
        unstorable = 0
        for e in entries:
            if not text.encodable(e.name):
                # half an emoji in the name (NTFS allows it): the path cannot
                # go into SQLite, and one such file used to fail the whole scan
                unstorable += 1
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if (recursive and not e.name.startswith(".")
                            and e.name.lower() not in SKIPPED_DIRS):
                        subdirs.append(os.path.join(parent, e.name))
                    continue
                if not e.is_file():
                    continue
            except OSError:
                continue
            yield parent, e
        if unstorable:
            log.warning(f"[index] {parent}: skipped {unstorable} name(s) with characters "
                        f"that cannot be stored (an unpaired surrogate)")
        stack.extend(sorted(subdirs, reverse=True))


def scan_folder(folder, recursive=False):
    """Upsert every image file in ``folder``; with ``recursive`` also those in
    its subfolders, each row keeping its real parent in ``folder``. Returns
    counts."""
    # rows are spelled like the folder list, whatever spelling the request
    # used, or the same file could be indexed under two
    folder = safety.as_listed(folder)
    d = db()
    now = time.time()
    where, args = scope_sql(folder, recursive, "folder")
    known = {r["path"]: r for r in d.execute(
        f"SELECT path, mtime, size, missing FROM images WHERE {where}", args)}
    seen = set()
    added = updated = 0
    rows = []
    try:
        for parent, e in _walk(folder, recursive):
            try:
                ext = os.path.splitext(e.name)[1].lower()
                if ext not in config.VALID_EXTS:
                    continue
                st = e.stat()
            except OSError:
                continue
            path = os.path.join(parent, e.name)
            seen.add(path)
            old = known.get(path)
            if old is None:
                added += 1
            elif old["mtime"] != st.st_mtime_ns or old["size"] != st.st_size or old["missing"]:
                updated += 1
            else:
                continue            # unchanged: marked seen below, all at once
            rows.append((path, parent, os.path.basename(parent), e.name, ext,
                         st.st_mtime_ns, st.st_size, st.st_ctime, now))
    except OSError as exc:
        return {"error": str(exc), "added": 0, "updated": 0, "missing": 0, "total": 0}

    d.executemany(
        "INSERT INTO images (path, folder, folder_name, name, ext, mtime, size, ctime, "
        "seen_at, missing, indexed_at) VALUES (?,?,?,?,?,?,?,?,?,0,NULL) "
        "ON CONFLICT(path) DO UPDATE SET folder=excluded.folder, "
        "folder_name=excluded.folder_name, name=excluded.name, ext=excluded.ext, "
        "mtime=excluded.mtime, size=excluded.size, ctime=excluded.ctime, "
        "seen_at=excluded.seen_at, missing=0, indexed_at=NULL", rows)

    gone = [p for p in known if p not in seen and not known[p]["missing"]]
    if gone:
        d.executemany("UPDATE images SET missing=1 WHERE path=?", [(p,) for p in gone])
    # seen_at puts the most recently scanned folder first in the queue of
    # files still to be read (enrich), so only rows still waiting need the
    # new stamp: one statement, touching nothing in a folder that is fully
    # read. It used to be an UPDATE per unchanged file, 25 us each, a
    # quarter second per ten thousand, on every folder open and every start.
    if len(seen) > len(rows):
        d.execute(f"UPDATE images SET seen_at=? WHERE {where} AND missing=0 "
                  "AND indexed_at IS NULL", [now, *args])
    d.commit()
    return {"added": added, "updated": updated, "missing": len(gone),
            "total": len(seen), "folder": folder, "recursive": bool(recursive)}


def forget_path(path):
    db().execute("DELETE FROM images WHERE path=?", (path,))


def move_path(old_path, new_path):
    d = db()
    new_folder = os.path.dirname(new_path)
    d.execute("UPDATE OR REPLACE images SET path=?, folder=?, folder_name=?, name=? WHERE path=?",
              (new_path, new_folder, os.path.basename(new_folder),
               os.path.basename(new_path), old_path))
    d.execute("UPDATE OR REPLACE meta SET path=? WHERE path=?", (new_path, old_path))


# --------------------------------------------------------------------------
# pass 2: reading the files
# --------------------------------------------------------------------------

def pending_count(folder=None, recursive=False):
    d = db()
    if folder:
        where, args = scope_sql(folder, recursive, "folder")
        return d.execute("SELECT COUNT(*) FROM images WHERE indexed_at IS NULL AND missing=0 "
                         f"AND {where}", args).fetchone()[0]
    return d.execute("SELECT COUNT(*) FROM images WHERE indexed_at IS NULL AND missing=0"
                     ).fetchone()[0]


def warm_settings():
    """Whether the indexer builds thumbnails as it goes, and at what quality.
    Read once per batch, not per file."""
    s = store.load_settings()
    return bool(s.get("warm_thumbs", True)), int(s.get("thumb_quality") or config.THUMB_QUALITY)


def enrich_one(path, warm=False, quality=config.THUMB_QUALITY):
    """Read one file: generation metadata, camera EXIF, kind. With ``warm``
    the thumbnail is built too, while the file is still in the disk cache, so
    the grid never has to wait for it. Returns the kind or None when the file
    could not be read.

    The file is opened once and handed to each reader. The generation data
    (which decodes the image for its hash), the camera tags and the
    thumbnail each opened it for themselves before: a PNG was decoded
    twice, the file opened four times, and the records went in with three
    commits rather than one. On a fresh library that was most of the
    indexer's time."""
    d = db()
    try:
        st = os.stat(path)
    except OSError:
        d.execute("UPDATE images SET missing=1 WHERE path=?", (path,))
        d.commit()
        return None
    try:
        img = Image.open(path)
    except (OSError, ValueError, Image.DecompressionBombError):
        img = None                  # each reader reports an unreadable file its own way
    try:
        meta = get_metadata(path, st, img=img, commit=False)
        camera = metadata.read_camera(path, img=img)
        kind = kind_of(meta, camera)
        lat = _float(camera.get("latitude"))
        lon = _float(camera.get("longitude"))
        d.execute(
            "UPDATE meta SET kind=?, camera_make=?, camera_model=?, lens=?, exposure=?, "
            "f_number=?, iso=?, focal=?, taken_at=?, lat=?, lon=?, software=? WHERE path=?",
            (kind, camera.get("make", ""), camera.get("model", ""), camera.get("lens", ""),
             camera.get("exposure", ""), camera.get("aperture", ""), camera.get("iso", ""),
             camera.get("focal", ""), camera.get("date_taken", ""), lat, lon,
             camera.get("software", ""), path))
        d.execute("UPDATE images SET width=?, height=?, kind=?, indexed_at=?, missing=0 WHERE path=?",
                  (meta["width"], meta["height"], kind, time.time(), path))
        if warm:
            thumbs.build_thumb(path, quality, st=st, img=img, commit=False)
        d.commit()
    finally:
        if img is not None:
            img.close()
    return kind


def enrich(limit=50, folder=None, recursive=False):
    """Process up to ``limit`` pending rows, the given folder first."""
    d = db()
    if folder:
        where, args = scope_sql(folder, recursive, "folder")
        rows = d.execute("SELECT path FROM images WHERE indexed_at IS NULL AND missing=0 "
                         f"AND {where} ORDER BY ctime DESC LIMIT ?", [*args, limit]).fetchall()
    else:
        rows = d.execute("SELECT path FROM images WHERE indexed_at IS NULL AND missing=0 "
                         "ORDER BY seen_at DESC, ctime DESC LIMIT ?", (limit,)).fetchall()
    warm, quality = warm_settings() if rows else (False, config.THUMB_QUALITY)
    for row in rows:
        enrich_one(row["path"], warm, quality)
    return len(rows)


def index_folder(folder, enrich_all=True, recursive=False):
    """Scan then enrich a folder in the calling thread (tests, small folders)."""
    result = scan_folder(folder, recursive)
    if enrich_all and "error" not in result:
        while enrich(200, folder, recursive):
            pass
    return result


def _float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# background indexer
# --------------------------------------------------------------------------

class Indexer:
    """One thread that scans requested folders and then enriches whatever is
    pending, most recently requested folder first."""

    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._queue = []
        self._thread = None
        self._stopping = False
        self.status = {"busy": False, "folder": "", "pending": 0, "last": None}

    def request(self, folder, recursive=False):
        folder = safety.as_listed(folder)
        with self._lock:
            self._queue = [q for q in self._queue if q[0] != folder]
            self._queue.insert(0, (folder, bool(recursive)))
        self.start()
        self._wake.set()

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stopping = False
            self._thread = threading.Thread(target=self._run, daemon=True, name="indexer")
            self._thread.start()

    def stop(self, timeout=10):
        """Finish the current file and exit the thread (tests, project switch)."""
        if self._thread is None or not self._thread.is_alive():
            return
        self._stopping = True
        with self._lock:
            self._queue.clear()
        self._wake.set()
        self._thread.join(timeout)
        self._thread = None

    def _next(self):
        with self._lock:
            return self._queue.pop(0) if self._queue else None

    def _run(self):
        folder, recursive = None, False
        while not self._stopping:
            item = self._next()
            if item is not None:
                folder, recursive = item
                self.status.update(busy=True, folder=folder)
                try:
                    self.status["last"] = scan_folder(folder, recursive)
                except Exception as exc:          # a bad folder must not kill the thread
                    log.warning(f"[index] {folder}: {exc}")
            try:
                did = 0 if self._stopping else enrich(25, folder, recursive)
                self.status["pending"] = pending_count()
                if did:
                    continue
            except Exception as exc:
                log.warning(f"[index] enrich: {exc}")
            self.status.update(busy=False, folder="")
            db_module.release()               # hold no handle while idle
            self._wake.wait(timeout=5)
            self._wake.clear()
        self.status.update(busy=False, folder="")
        db_module.release()


indexer = Indexer()


def request_all():
    """Queue every saved folder for a scan: the cheap listing pass runs first
    for each, then the files are read in the background. Called at start so
    the dashboard has counts to show."""
    folders = []

    def walk(items):
        for it in items:
            if it.get("type") == "folder" and it.get("path") and os.path.isdir(it["path"]):
                folders.append((it["path"], bool(it.get("recursive"))))
            elif it.get("type") == "group":
                walk(it.get("items", []))

    walk(store.load_history())
    for folder, recursive in reversed(folders):      # request() puts each at the front
        indexer.request(folder, recursive)
    return len(folders)


# --------------------------------------------------------------------------
# queries
# --------------------------------------------------------------------------

ROW_COLUMNS = """
    i.path, i.folder, i.name, i.ext, i.mtime, i.size, i.ctime, i.width, i.height,
    i.kind, i.indexed_at, i.stars, i.rejected,
    r.label,
    m.prompt, m.negative, m.steps, m.cfg, m.sampler, m.scheduler, m.seed, m.denoise,
    m.model, m.loras, m.phash, m.source, m.prompt_list, m.prompt_line, m.prompt_lines,
    m.camera_make, m.camera_model, m.lens, m.exposure, m.f_number, m.iso, m.focal,
    m.taken_at, m.lat, m.lon, m.software
"""

FROM_SQL = ("FROM images i LEFT JOIN ratings r ON r.path = i.path "
            "LEFT JOIN meta m ON m.path = i.path")


def _row_dict(r, tags, in_collections):
    stars = r["stars"] or 0
    return {
        "path": r["path"], "folder": r["folder"], "name": r["name"], "ext": r["ext"],
        "time": r["ctime"], "mtime": (r["mtime"] or 0) / 1e9, "bytes": r["size"],
        "width": r["width"] or 0, "height": r["height"] or 0,
        "kind": r["kind"] or "", "indexed": r["indexed_at"] is not None,
        "stars": stars, "rejected": r["rejected"] or 0, "label": r["label"],
        "prompt": r["prompt"] or "", "negative": r["negative"] or "",
        "steps": r["steps"] or "", "cfg": r["cfg"] or "", "sampler": r["sampler"] or "",
        "scheduler": r["scheduler"] or "", "seed": r["seed"] or "",
        "denoise": r["denoise"] or "", "model": r["model"] or "",
        "loras": json.loads(r["loras"] or "[]"), "phash": r["phash"] or "",
        "source": r["source"] or "", "prompt_list": r["prompt_list"] or "",
        "prompt_line": r["prompt_line"] or 0, "prompt_lines": r["prompt_lines"] or 0,
        "camera": {
            "make": r["camera_make"] or "", "model": r["camera_model"] or "",
            "lens": r["lens"] or "", "exposure": r["exposure"] or "",
            "aperture": r["f_number"] or "", "iso": r["iso"] or "", "focal": r["focal"] or "",
            "taken_at": r["taken_at"] or "", "lat": r["lat"], "lon": r["lon"],
            "software": r["software"] or "",
        },
        "user_tags": tags, "collections": in_collections,
    }


def query_images(folder=None, q="", sort="date_desc", offset=0, limit=200,
                 stars_min=None, stars_max=None, rejected=None, kind=None,
                 tag=None, collection=None, include_missing=False, recursive=False):
    """One page of the index. ``folder=None`` means the whole library;
    ``recursive`` widens a folder to everything under it.

    The count and the page are computed over ``images`` alone whenever the
    filters allow it: stars and the reject flag are mirrored into it, and
    everything else is expressed as an IN (...) over a small subquery, which
    SQLite materialises once. Only the query language still needs the meta
    and ratings joins, and only for the rows it looks at. The joins for the
    returned columns happen after LIMIT, on one page of rows."""
    where, args = [], []
    joins = ""
    if not include_missing:
        where.append("i.missing=0")
    if folder:
        sql, params = scope_sql(folder, recursive)
        where.append(sql)
        args.extend(params)
    if stars_min is not None and int(stars_min) > 0:
        where.append("i.stars >= ?")
        args.append(int(stars_min))
    if stars_max is not None:
        where.append("i.stars <= ?")
        args.append(int(stars_max))
    if rejected is not None:
        where.append("i.rejected = ?")
        args.append(1 if rejected else 0)
    if kind:
        where.append("i.kind=?")
        args.append(kind)
    if tag:
        where.append("i.path IN (SELECT path FROM tags WHERE tag=?)")
        args.append(tags_svc.clean(tag))
    if collection:
        where.append("i.path IN (SELECT path FROM collection_items WHERE collection_id=?)")
        args.append(collection)
    base = "images i"
    if q:
        sql, params, match = to_sql(prepare_query(q))
        if sql:
            where.append(sql)
            args.extend(params)
            if match:
                # drive the whole query from the trigram index: the planner
                # then only touches the candidates, however many there are
                base = "meta_fts f JOIN meta m ON m.rowid = f.rowid JOIN images i ON i.path = m.path"
                where.insert(0, "meta_fts MATCH ?")
                args.insert(0, match)
            elif "m." in sql:
                joins += " LEFT JOIN meta m ON m.path = i.path"
            if "r." in sql:
                joins += " LEFT JOIN ratings r ON r.path = i.path"

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order = SORTS.get(sort, SORTS["date_desc"])
    d = db()
    total = d.execute(f"SELECT COUNT(*) FROM {base}{joins} {where_sql}", args).fetchone()[0]
    page_sql = (f"SELECT i.path FROM {base}{joins} {where_sql} ORDER BY {order} "
                f"LIMIT ? OFFSET ?")
    rows = d.execute(
        f"SELECT {ROW_COLUMNS} FROM ({page_sql}) pg JOIN images i ON i.path = pg.path "
        f"LEFT JOIN ratings r ON r.path = i.path LEFT JOIN meta m ON m.path = i.path "
        f"ORDER BY {order}", [*args, int(limit), int(offset)]).fetchall()
    paths = [r["path"] for r in rows]
    tags = tags_svc.tags_of(paths)
    cols = collections_svc.collections_of(paths)
    return {
        "total": total, "offset": int(offset), "limit": int(limit),
        "rows": [_row_dict(r, tags[r["path"]], cols[r["path"]]) for r in rows],
        "pending": pending_count(folder, recursive) if folder else pending_count(),
    }


def known_paths(paths):
    """The subset of ``paths`` the index holds, in the order given, one
    query per 500. The index only ever takes files under the listed
    folders, so membership is as good as ``safety.is_path_allowed`` for a
    route that reads rows by path and touches no file: that guard
    realpaths each path, 17 ms for a page of 200, which the tile badges
    paid after every page the grid loaded."""
    wanted = [p for p in paths if isinstance(p, str)]
    if not wanted:
        return []
    d = db()
    known = set()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        marks = ",".join("?" * len(chunk))
        known.update(r["path"] for r in d.execute(
            f"SELECT path FROM images WHERE path IN ({marks})", chunk))
    return [p for p in wanted if p in known]


def get_image(path):
    d = db()
    r = d.execute(f"SELECT {ROW_COLUMNS} {FROM_SQL} WHERE i.path=?", (path,)).fetchone()
    if not r:
        return None
    return _row_dict(r, tags_svc.tags_of([path])[path],
                     collections_svc.collections_of([path])[path])


FACET_COLUMNS = {
    "model": "m.model", "sampler": "m.sampler", "scheduler": "m.scheduler",
    "camera": "m.camera_model", "lens": "m.lens", "software": "m.software",
}


def facets(field, q="", limit=20):
    """Distinct values of one metadata field with counts, most used first,
    narrowed by ``q`` (a substring). ``lora`` looks inside the JSON list and
    ``tag`` at the tags table."""
    d = db()
    like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if field == "lora":
        rows = d.execute(
            "SELECT je.value v, COUNT(*) n FROM meta m, json_each(COALESCE(m.loras,'[]')) je "
            "WHERE je.value <> '' AND lower(je.value) LIKE ? ESCAPE '\\' "
            "GROUP BY je.value ORDER BY n DESC, v LIMIT ?", (like, limit)).fetchall()
    elif field == "tag":
        rows = d.execute(
            "SELECT tag v, COUNT(*) n FROM tags WHERE lower(tag) LIKE ? ESCAPE '\\' "
            "GROUP BY tag ORDER BY n DESC, v LIMIT ?", (like, limit)).fetchall()
    else:
        col = FACET_COLUMNS.get(field)
        if not col:
            return []
        rows = d.execute(
            f"SELECT {col} v, COUNT(*) n FROM meta m WHERE {col} IS NOT NULL AND {col} <> '' "
            f"AND lower({col}) LIKE ? ESCAPE '\\' GROUP BY {col} ORDER BY n DESC, v LIMIT ?",
            (like, limit)).fetchall()
    return [{"value": r["v"], "count": r["n"]} for r in rows]


SUMMARY_COLUMNS = ("COUNT(*) total, "
                   "SUM(CASE WHEN i.stars=0 AND i.rejected=0 THEN 1 ELSE 0 END) unrated, "
                   "SUM(i.rejected) rejected, "
                   "SUM(CASE WHEN i.indexed_at IS NULL THEN 1 ELSE 0 END) pending")


def _summary(row):
    return {"total": (row and row["total"]) or 0, "unrated": (row and row["unrated"]) or 0,
            "rejected": (row and row["rejected"]) or 0, "pending": (row and row["pending"]) or 0}


def folder_summary(folder, recursive=False):
    """Counts the sidebar and dashboard want for one folder."""
    where, args = scope_sql(folder, recursive)
    row = db().execute(f"SELECT {SUMMARY_COLUMNS} FROM images i WHERE {where} AND i.missing=0",
                       args).fetchone()
    return _summary(row)


def _add(target, row):
    for key in ("total", "unrated", "rejected", "pending"):
        target[key] += row[key] or 0


def folder_summaries(folders, recursive=()):
    """The same for many folders in one pass over the index. Folders named in
    ``recursive`` have their subfolders' counts added in."""
    wanted = {os.path.normpath(f): f for f in folders}
    out = {f: _summary(None) for f in folders}
    if not wanted:
        return out
    rec = {f for f in recursive if f in out}
    prefixes = [(os.path.normpath(f) + os.sep, f) for f in rec]
    for row in db().execute(f"SELECT i.folder, {SUMMARY_COLUMNS} FROM images i "
                            f"WHERE i.missing=0 GROUP BY i.folder"):
        key = wanted.get(row["folder"])
        if key is not None:
            if key in rec:
                _add(out[key], row)
            else:
                out[key] = _summary(row)
        for prefix, f in prefixes:
            if row["folder"].startswith(prefix):
                _add(out[f], row)
    return out
