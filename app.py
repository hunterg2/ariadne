#!/usr/bin/env python3
"""Ariadne: a local web app for browsing, rating, tagging and tidying large
folders of images, built for the output of image generators such as ComfyUI.

This file is the Flask server. It serves the single-page UI in
templates/index.html, keeps the library (ratings, tags, trash records, cached
metadata and thumbnail bookkeeping) in a SQLite database next to this file,
and exposes the JSON API the page calls. The other modules are:

    metadata.py   reads generation metadata out of image files, and carries
                  it (or strips it) when the editor saves a copy
    tagger.py     proposes tags, from the prompt or from a vision model

Run it with ``python app.py`` (or start.bat on Windows). It listens on
http://127.0.0.1:5000 by default and opens a browser tab once the server is
up. Options:

    --port N        listen on another port (--port=N also works)
    --no-browser    do not open a browser tab (same as ORGANIZER_NO_BROWSER=1)
    --reload        restart whenever a source file changes (development)

Everything the app writes lives beside this file: organizer.db, cache/,
backups/, settings.json, history.json and projects.json.
Image folders are only ever changed by explicit actions taken in the UI
(trash, move, export, edit).
"""

import hashlib
import io
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import string
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import (Flask, Response, jsonify, render_template, request,
                   send_file, stream_with_context)
from PIL import Image

try:
    import metadata
    import tagger
except ImportError as _missing:
    raise SystemExit(
        f"{_missing.name}.py is missing. Put it in the same folder as app.py."
    )

try:
    import send2trash          # optional: real recycle bin for hard deletes
except ImportError:
    send2trash = None

Image.MAX_IMAGE_PIXELS = None

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

APP_NAME = "Image Organizer"      # what the page and the console call it
DEFAULT_PORT = 5000
PORT_ENV = "IMGORG_PORT"          # hands the chosen port to the reloader child
NO_BROWSER_ENV = "ORGANIZER_NO_BROWSER"

APP_DIR = Path(__file__).resolve().parent
PROJECTS_FILE = APP_DIR / "projects.json"
PROJECTS_DIR = APP_DIR / "projects"

# Everything below is rebound by use_project(). The default project keeps its
# data next to this file; every other project lives under projects/<id>/.
DATA_DIR = APP_DIR
DB_FILE = APP_DIR / "organizer.db"
CACHE_DIR = APP_DIR / "cache"
THUMB_DIR = CACHE_DIR / "thumbs"
BACKUP_DIR = APP_DIR / "backups"
HISTORY_FILE = APP_DIR / "history.json"
SETTINGS_FILE = APP_DIR / "settings.json"

# v1 kept categories and tags as JSON. migrate_from_v1() reads them once and
# renames them to *.v1.bak.
LEGACY_CATEGORIES_FILE = APP_DIR / "categories.json"
LEGACY_TAGS_FILE = APP_DIR / "tags.json"

THUMB_SIZE = 512
THUMB_VERSION = 2          # bump to invalidate every cached thumbnail
THUMB_QUALITY = 82         # WebP quality; settings.thumb_quality overrides it
STREAM_BATCH = 40          # images per server-sent event
STREAM_LIMIT = 4000        # default cap on a library-wide search
BACKUPS_KEPT = 7           # database copies kept in backups/
VALID_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
SCHEMA_VERSION = 2
META_CACHE_VERSION = 3

# virtual folders the page can ask for instead of a real path
GLOBAL_TAGS_FOLDER = "__global_tags__"
SEARCH_FOLDER = "__search__"

app = Flask(__name__)

DEFAULT_SETTINGS = {
    "hotkeys": {
        "liked": ["1", "", ""],
        "loved": ["2", "", ""],
        "prompt": ["Spacebar", "", ""],
        "trash": ["Backspace", "Delete", ""],
        "reveal": ["C", "", ""],
        "tag": ["T", "", ""],
        "prev": ["ArrowLeft", "A", ""],
        "next": ["ArrowRight", "D", ""],
        "cull": ["F", "", ""],
        "select": ["S", "", ""],
    },
    "comfy_path": "",          # kept only so old settings can be migrated
    "auto_import_comfy": False,
    # each entry: {id, path, name, include_root, enabled}
    "auto_folders": [],
    "saved_queries": [],
    "delete_mode": "soft",
    "theme": 0,
    # added in v2
    "confirm_unlike": False,
    "guess_prompt_line": True,
    "sidebar_sort": "manual",
    "sort_subfolders": False,
    "tag_edits": True,
    # backend: prompt | ollama | openai | anthropic
    "tagger": {"backend": "prompt", "model": "", "url": "", "api_key": "",
               "max_tags": 12, "include_model": False, "include_loras": False,
               "extra": "", "prefer_existing": True},
    "allow_drag_when_sorted": True,
    "folder_opened": {},
    "warn_quality": True,
    "edit_colors": [],
    "edit_defaults": {"format": "png", "quality": 92, "metadata": "generation",
                      "dest": "suffix", "background": "#000000"},
    "cull_auto_advance": True,
    "thumb_quality": THUMB_QUALITY,
    "last_folder": "",
    "extra_roots": [],
    "ui": {"grid_size": 250, "layout": "square", "sort": "date_desc"},
}


# --------------------------------------------------------------------------
# database
# --------------------------------------------------------------------------

META_SQL = """
    CREATE TABLE IF NOT EXISTS meta (
        path      TEXT PRIMARY KEY,
        mtime     INTEGER,
        size      INTEGER,
        ctime     REAL,
        width     INTEGER,
        height    INTEGER,
        prompt    TEXT,
        negative  TEXT,
        steps     TEXT,
        cfg       TEXT,
        sampler   TEXT,
        scheduler TEXT,
        seed      TEXT,
        denoise   TEXT,
        model     TEXT,
        loras     TEXT,
        phash     TEXT,
        source    TEXT,
        prompt_list  TEXT,
        prompt_line  INTEGER,
        prompt_lines INTEGER
    );
"""

_local = threading.local()
_db_generation = 0


def db():
    conn = getattr(_local, "conn", None)
    # a project switch bumps the generation, which retires every open handle
    if conn is not None and getattr(_local, "gen", -1) != _db_generation:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        conn = None
        _local.conn = None
    if conn is None:
        conn = sqlite3.connect(str(DB_FILE), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
        _local.gen = _db_generation
    return conn


def init_db():
    d = db()
    d.executescript(
        META_SQL + """
        CREATE TABLE IF NOT EXISTS categories (
            path     TEXT PRIMARY KEY,
            category TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tags (
            path TEXT NOT NULL,
            tag  TEXT NOT NULL,
            PRIMARY KEY (path, tag)
        );
        CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
        CREATE TABLE IF NOT EXISTS trash (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            original_path TEXT NOT NULL,
            trash_path    TEXT NOT NULL,
            deleted_at    REAL NOT NULL,
            category      TEXT,
            tags          TEXT,
            restorable    INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS thumbs (
            key   TEXT PRIMARY KEY,
            path  TEXT NOT NULL,
            mtime INTEGER,
            size  INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_thumbs_path ON thumbs(path);
        CREATE TABLE IF NOT EXISTS kv (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    d.commit()

    # The parser has changed, so cached rows are stale. Drop and rebuild them;
    # nothing is lost, the values are all derived from the files themselves.
    if kv_get("meta_cache_version") != str(META_CACHE_VERSION):
        d.execute("DROP TABLE IF EXISTS meta")
        d.executescript(META_SQL)
        d.commit()
        kv_set("meta_cache_version", META_CACHE_VERSION)
        print("[cache] metadata cache rebuilt for the new extractor")


def kv_get(key, default=None):
    row = db().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(key, value):
    d = db()
    d.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, str(value)))
    d.commit()


# --------------------------------------------------------------------------
# json files (history + settings stay as plain files; they are small and
# hand-editable, and the sidebar tree is easier to reason about as JSON)
# --------------------------------------------------------------------------


def load_json_file(filepath, default_type=dict):
    """A JSON file, or an empty default when it is missing or unreadable. A
    corrupt file is reported rather than raised, since every caller can carry
    on with defaults."""
    p = Path(filepath)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except ValueError as exc:
            print(f"[json] {p.name} is not valid JSON and was ignored: {exc}")
        except OSError as exc:
            print(f"[json] {p.name} could not be read: {exc}")
    return default_type()


def save_json_file(filepath, data):
    p = Path(filepath)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


def _merge_defaults(data, defaults):
    for k, v in defaults.items():
        if k not in data:
            data[k] = json.loads(json.dumps(v))
        elif isinstance(v, dict) and isinstance(data[k], dict):
            _merge_defaults(data[k], v)
    return data


def normalise_settings(settings):
    """The ComfyUI output folder used to be a single special case. It is now
    just the first entry in a list of auto-updating folders."""
    changed = False
    autos = settings.setdefault("auto_folders", [])
    legacy = (settings.get("comfy_path") or "").strip()
    if legacy:
        if not any((a.get("path") or "") == legacy for a in autos):
            autos.insert(0, {
                "id": "comfy_auto_group",
                "path": legacy,
                "name": "ComfyUI Outputs",
                "include_root": False,
                "enabled": bool(settings.get("auto_import_comfy")),
            })
        settings["comfy_path"] = ""
        settings["auto_import_comfy"] = False
        changed = True

    for entry in autos:
        if not entry.get("id"):
            entry["id"] = "auto_" + hashlib.sha1(
                (entry.get("path") or "").encode("utf-8", "replace")).hexdigest()[:10]
            changed = True
        entry.setdefault("name", os.path.basename(
            (entry.get("path") or "").rstrip("/\\")) or "Auto folder")
        entry.setdefault("include_root", False)
        entry.setdefault("enabled", True)
        # subfolders you have deliberately dragged out of the group. Without
        # this the rebuild would put them straight back, since they are still
        # sitting on disk inside the watched folder.
        if not isinstance(entry.get("excluded"), list):
            entry["excluded"] = []
    return settings, changed


def load_settings():
    settings = _merge_defaults(load_json_file(SETTINGS_FILE, dict), DEFAULT_SETTINGS)
    settings, changed = normalise_settings(settings)
    if changed:
        save_json_file(SETTINGS_FILE, settings)
        _roots_cache["ts"] = 0
    return settings


def save_settings(settings):
    save_json_file(SETTINGS_FILE, settings)
    _roots_cache["ts"] = 0


def load_history():
    data = load_json_file(HISTORY_FILE, list)
    history = []
    for item in data:
        if isinstance(item, str):
            history.append({"type": "folder", "path": item, "alias": "", "status": ""})
        elif isinstance(item, dict):
            item.setdefault("type", "folder")
            history.append(item)
    return history


def save_history(history):
    save_json_file(HISTORY_FILE, history)
    _roots_cache["ts"] = 0


# --------------------------------------------------------------------------
# one-time migration from the v1 layout
# --------------------------------------------------------------------------


def migrate_from_v1():
    """Pull categories.json / tags.json into SQLite and top up settings.json.

    Runs once per library. Old files are renamed to *.v1.bak rather than
    deleted, so nothing is lost if something goes wrong.
    """
    if kv_get("schema_version") == str(SCHEMA_VERSION):
        return

    print("[migrate] upgrading data from v1 ...")
    d = db()
    moved = []

    # 1. categories.json -> categories table
    if LEGACY_CATEGORIES_FILE.exists():
        legacy = load_json_file(LEGACY_CATEGORIES_FILE, dict)
        rows = [(p, c) for p, c in legacy.items() if isinstance(p, str) and isinstance(c, str)]
        if rows:
            d.executemany("INSERT OR REPLACE INTO categories VALUES (?,?)", rows)
        print(f"[migrate]   categories: {len(rows)}")
        moved.append(LEGACY_CATEGORIES_FILE)

    # 2. tags.json -> tags table
    if LEGACY_TAGS_FILE.exists():
        legacy = load_json_file(LEGACY_TAGS_FILE, dict)
        rows = []
        for p, tags in legacy.items():
            if not isinstance(p, str):
                continue
            if isinstance(tags, str):
                tags = [tags]
            for t in tags or []:
                t = str(t).strip().lstrip("#")
                if t:
                    rows.append((p, t))
        if rows:
            d.executemany("INSERT OR REPLACE INTO tags VALUES (?,?)", rows)
        print(f"[migrate]   tag links: {len(rows)}")
        moved.append(LEGACY_TAGS_FILE)

    d.commit()

    for f in moved:
        try:
            os.replace(f, f.with_suffix(f.suffix + ".v1.bak"))
        except OSError:
            pass

    # 3. settings.json - add any keys the new build expects
    settings = load_settings()
    hk = settings.setdefault("hotkeys", {})
    for action, keys in DEFAULT_SETTINGS["hotkeys"].items():
        if action not in hk:
            hk[action] = list(keys)
    save_settings(settings)

    # 4. history.json - normalise entries written by older builds
    history = load_history()

    def normalise(items):
        for it in items:
            it.setdefault("type", "folder")
            it.setdefault("status", "")
            if it["type"] == "folder":
                it.setdefault("alias", "")
            if it["type"] == "group":
                it.setdefault("isOpen", True)
                it.setdefault("items", [])
                normalise(it["items"])

    normalise(history)
    save_history(history)

    kv_set("schema_version", SCHEMA_VERSION)
    print("[migrate] done. old files kept as *.v1.bak")


def migrate_folder_layout(base_folder):
    """v0 layout: images filed into liked/ and loved/ subfolders plus
    per-folder .comfy_tags.json / .user_tags.json. Flatten into the DB."""
    d = db()
    changed = False

    for category in ("liked", "loved"):
        cat_dir = os.path.join(base_folder, category)
        if not os.path.isdir(cat_dir):
            continue
        for filename in os.listdir(cat_dir):
            if os.path.splitext(filename)[1].lower() not in VALID_EXTS:
                continue
            old_path = os.path.join(cat_dir, filename)
            new_path = os.path.join(base_folder, filename)
            if not os.path.isfile(old_path) or os.path.exists(new_path):
                continue
            try:
                shutil.move(old_path, new_path)
                d.execute("INSERT OR REPLACE INTO categories VALUES (?,?)", (new_path, category))
                changed = True
            except OSError:
                pass
        try:
            if not os.listdir(cat_dir):
                os.rmdir(cat_dir)
        except OSError:
            pass

    local_cats = os.path.join(base_folder, ".comfy_tags.json")
    if os.path.exists(local_cats):
        try:
            for fn, cat in load_json_file(local_cats, dict).items():
                d.execute(
                    "INSERT OR REPLACE INTO categories VALUES (?,?)",
                    (os.path.join(base_folder, fn), cat),
                )
            os.remove(local_cats)
            changed = True
        except OSError:
            pass

    local_tags = os.path.join(base_folder, ".user_tags.json")
    if os.path.exists(local_tags):
        try:
            for fn, tags in load_json_file(local_tags, dict).items():
                full = os.path.join(base_folder, fn)
                for t in tags or []:
                    t = str(t).strip().lstrip("#")
                    if t:
                        d.execute("INSERT OR REPLACE INTO tags VALUES (?,?)", (full, t))
            os.remove(local_tags)
            changed = True
        except OSError:
            pass

    if changed:
        d.commit()


# --------------------------------------------------------------------------
# projects
#
# A project is a separate library: its own folder list, ratings, tags, thumbs
# and settings. The default one stays exactly where it has always been, so an
# existing install needs nothing moved; the rest live under projects/<id>/.
# --------------------------------------------------------------------------


def load_projects():
    data = load_json_file(PROJECTS_FILE, dict)
    projects = data.get("projects")
    if not isinstance(projects, list) or not projects:
        projects = [{"id": "default", "name": "Main library", "created": time.time()}]
    active = data.get("active")
    if not any(p.get("id") == active for p in projects):
        active = projects[0]["id"]
    return {"active": active, "projects": projects}


def save_projects(data):
    save_json_file(PROJECTS_FILE, data)


def project_dir(project_id):
    return APP_DIR if project_id == "default" else PROJECTS_DIR / project_id


def use_project(project_id):
    """Point every path at this project and retire the old database handles."""
    global DATA_DIR, DB_FILE, CACHE_DIR, THUMB_DIR, BACKUP_DIR
    global HISTORY_FILE, SETTINGS_FILE, _db_generation

    DATA_DIR = project_dir(project_id)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_FILE = DATA_DIR / "organizer.db"
    CACHE_DIR = DATA_DIR / "cache"
    THUMB_DIR = CACHE_DIR / "thumbs"
    BACKUP_DIR = DATA_DIR / "backups"
    HISTORY_FILE = DATA_DIR / "history.json"
    SETTINGS_FILE = DATA_DIR / "settings.json"
    THUMB_DIR.mkdir(parents=True, exist_ok=True)

    _db_generation += 1
    _roots_cache["ts"] = 0
    init_db()


# --------------------------------------------------------------------------
# path safety
# --------------------------------------------------------------------------

_roots_cache = {"ts": 0.0, "roots": []}


def allowed_roots():
    now = time.time()
    if _roots_cache["roots"] and now - _roots_cache["ts"] < 5:
        return _roots_cache["roots"]

    roots = set()

    def walk(items):
        for it in items:
            if it.get("type") == "folder" and it.get("path"):
                roots.add(os.path.realpath(it["path"]))
            elif it.get("type") == "group":
                walk(it.get("items", []))

    walk(load_history())
    settings = load_settings()
    for entry in settings.get("auto_folders", []) or []:
        if entry.get("path"):
            roots.add(os.path.realpath(entry["path"]))
    for extra in settings.get("extra_roots", []) or []:
        if extra:
            roots.add(os.path.realpath(extra))

    _roots_cache["roots"] = sorted(roots)
    _roots_cache["ts"] = now
    return _roots_cache["roots"]


def is_path_allowed(p):
    """A path is readable if it sits under a folder the user has added, or if
    it is a file we already track. Stops /image?path=/etc/passwd."""
    if not p:
        return False
    try:
        real = os.path.realpath(p)
    except (OSError, ValueError):
        return False

    for root in allowed_roots():
        try:
            if os.path.commonpath([real, root]) == root:
                return True
        except ValueError:
            continue

    row = db().execute(
        "SELECT 1 FROM categories WHERE path=? "
        "UNION ALL SELECT 1 FROM tags WHERE path=? "
        "UNION ALL SELECT 1 FROM meta WHERE path=? "
        "UNION ALL SELECT 1 FROM trash WHERE trash_path=? OR original_path=? LIMIT 1",
        (p, p, p, p, p),
    ).fetchone()
    return row is not None


def guard(p):
    return bool(p) and os.path.exists(p) and is_path_allowed(p)


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _under(path, root):
    """Is `path` inside `root`? Tolerates mixed separators and Windows case."""
    p = os.path.normcase(os.path.normpath(path))
    r = os.path.normcase(os.path.normpath(root))
    return p == r or p.startswith(r + os.sep)


# --------------------------------------------------------------------------
# metadata  (the extraction itself lives in metadata.py)
# --------------------------------------------------------------------------

def _meta_from_row(row):
    """A cached meta row in the shape metadata.extract() returns."""
    return {
        "width": row["width"] or 0, "height": row["height"] or 0,
        "prompt": row["prompt"] or "", "negative": row["negative"] or "",
        "steps": row["steps"] or "", "cfg": row["cfg"] or "",
        "sampler": row["sampler"] or "", "scheduler": row["scheduler"] or "",
        "seed": row["seed"] or "", "denoise": row["denoise"] or "",
        "model": row["model"] or "", "loras": json.loads(row["loras"] or "[]"),
        "phash": row["phash"] or "", "source": row["source"] or "",
        "prompt_list": row["prompt_list"] or "",
        "prompt_line": row["prompt_line"] or 0,
        "prompt_lines": row["prompt_lines"] or 0,
    }


def get_metadata(full_path, st=None):
    """Cached wrapper. Re-reads the file only when mtime or size changed."""
    try:
        st = st or os.stat(full_path)
    except OSError:
        return metadata.blank()

    d = db()
    row = d.execute("SELECT * FROM meta WHERE path=?", (full_path,)).fetchone()
    if row and row["mtime"] == st.st_mtime_ns and row["size"] == st.st_size:
        return _meta_from_row(row)

    meta = metadata.extract(full_path)
    d.execute(
        "INSERT OR REPLACE INTO meta (path, mtime, size, ctime, width, height, "
        "prompt, negative, steps, cfg, sampler, scheduler, seed, denoise, model, "
        "loras, phash, source, prompt_list, prompt_line, prompt_lines) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (full_path, st.st_mtime_ns, st.st_size, st.st_ctime,
         meta["width"], meta["height"], meta["prompt"], meta["negative"],
         meta["steps"], meta["cfg"], meta["sampler"], meta["scheduler"],
         meta["seed"], meta["denoise"], meta["model"],
         json.dumps(meta["loras"]), meta["phash"], meta["source"],
         meta["prompt_list"], meta["prompt_line"], meta["prompt_lines"]),
    )
    d.commit()
    return meta


# --------------------------------------------------------------------------
# thumbnails
# --------------------------------------------------------------------------

_thumb_pool = ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) // 2))


def thumb_path_for(path, st=None):
    st = st or os.stat(path)
    key = (f"{os.path.realpath(path)}|{st.st_mtime_ns}|{st.st_size}"
           f"|{THUMB_SIZE}|v{THUMB_VERSION}")
    digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()
    return THUMB_DIR / digest[:2] / f"{digest}.webp"


def build_thumb(path, quality=THUMB_QUALITY):
    try:
        st = os.stat(path)
        dest = thumb_path_for(path, st)
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as im:
            try:
                im.seek(0)  # first frame of animated gif/webp
            except (EOFError, AttributeError):
                pass
            im.draft("RGB", (THUMB_SIZE, THUMB_SIZE))  # fast JPEG downscale path
            im = metadata.oriented(im)                 # honour EXIF rotation
            im = im.convert("RGB")
            im.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            tmp = dest.with_suffix(".tmp.webp")
            im.save(tmp, "WEBP", quality=quality, method=4)
            os.replace(tmp, dest)
        remember_thumb(dest, path, st)
        return dest
    except (OSError, ValueError) as exc:
        print(f"[thumb] {path}: {exc}")
        return None


def remember_thumb(dest, path, st):
    """Thumbnail names are content hashes and cannot be reversed, so the link
    back to the source has to be stored if the cache is ever to be cleaned."""
    try:
        d = db()
        d.execute("INSERT OR REPLACE INTO thumbs VALUES (?,?,?,?)",
                  (str(dest), path, st.st_mtime_ns, st.st_size))
        d.commit()
    except sqlite3.Error:
        pass


def thumb_cache_stats():
    files = 0
    total = 0
    for root, _, names in os.walk(THUMB_DIR):
        for name in names:
            if name.endswith(".webp"):
                files += 1
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    return files, total


def prune_thumbs():
    """Drop thumbnails whose source is gone or has changed, plus any file on
    disk we have no record of at all."""
    d = db()
    known = set()
    removed = 0

    for row in d.execute("SELECT key, path, mtime, size FROM thumbs").fetchall():
        key = row["key"]
        keep = False
        try:
            st = os.stat(row["path"])
            keep = st.st_mtime_ns == row["mtime"] and st.st_size == row["size"]
        except OSError:
            keep = False
        if keep and os.path.exists(key):
            known.add(os.path.realpath(key))
        else:
            try:
                if os.path.exists(key):
                    os.remove(key)
                    removed += 1
            except OSError:
                pass
            d.execute("DELETE FROM thumbs WHERE key=?", (key,))
    d.commit()

    for root, _, names in os.walk(THUMB_DIR):
        for name in names:
            if not name.endswith(".webp"):
                continue
            full = os.path.realpath(os.path.join(root, name))
            if full not in known:
                try:
                    os.remove(full)
                    removed += 1
                except OSError:
                    pass
    return removed


def warm_thumbs(paths, quality=THUMB_QUALITY):
    for p in paths:
        _thumb_pool.submit(build_thumb, p, quality)


# --------------------------------------------------------------------------
# search
#
# A deliberate mirror of the filter in index.html, so a query behaves the same
# whether it runs over one folder in the browser or over every indexed image
# here. Change one and change the other.
# --------------------------------------------------------------------------

_QUOTED = re.compile(r'"([^"]+)"')
_TAG_SHORTHAND = re.compile(r"#([\w-]+)")
_STASH = re.compile(r"\$S(\d+)\$")


def parse_search(query):
    rules = {}
    for part in (query or "").split(";"):
        if ":" not in part:
            continue
        key, _, raw = part.partition(":")
        key = key.strip().lower()
        strings = []

        def stash(match):
            strings.append(match.group(1))
            return f"$S{len(strings) - 1}$"

        clean = _QUOTED.sub(stash, raw.strip())
        groups = []
        for or_part in clean.split("||"):
            ands = []
            for and_part in or_part.split("&"):
                hit = _STASH.search(and_part)
                if hit:
                    ands.append(strings[int(hit.group(1))])
                else:
                    bare = and_part.strip()
                    if bare:
                        ands.append(bare)
            if ands:
                groups.append(ands)
        if groups:
            rules[key] = groups
    return rules


def match_text(text, needle):
    if not text:
        return False
    text = str(text).lower()
    needle = str(needle).lower()
    if needle.startswith("...") and needle.endswith("...") and len(needle) > 6:
        return needle[3:-3] in text
    if needle.startswith("..."):
        return text.endswith(needle[3:])
    if needle.endswith("..."):
        return text.startswith(needle[:-3])
    return text == needle


def text_rule(text, groups):
    return any(all(match_text(text, m) for m in group) for group in groups)


def match_number(value, needle):
    if "..." in needle:
        low, _, high = needle.partition("...")
        try:
            lo = float(low) if low.strip() else float("-inf")
            hi = float(high) if high.strip() else float("inf")
        except ValueError:
            return False
        return lo <= value <= hi
    try:
        return value == float(needle)
    except ValueError:
        return False


def number_rule(raw, groups):
    if raw in ("", "-", None):
        return False
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return False
    return any(all(match_number(value, m) for m in group) for group in groups)


def prepare_query(query):
    return parse_search(_TAG_SHORTHAND.sub(r'tag: "\1"', query or ""))


def row_matches(row, rules, category, tags):
    for key, rule in rules.items():
        if key == "prompt":
            if not text_rule(row["prompt"], rule):
                return False
        elif key == "negative":
            if not text_rule(row["negative"], rule):
                return False
        elif key == "title":
            if not text_rule(os.path.basename(row["path"]), rule):
                return False
        elif key == "model":
            if not text_rule(row["model"], rule):
                return False
        elif key == "folder":
            if not text_rule(os.path.basename(os.path.dirname(row["path"])), rule):
                return False
        elif key in ("sampler", "scheduler"):
            if not text_rule(row[key], rule):
                return False
        elif key == "lora":
            try:
                loras = json.loads(row["loras"] or "[]")
            except ValueError:
                loras = []
            if not any(text_rule(l, rule) for l in loras):
                return False
        elif key == "tag":
            names = list(tags or [])
            if category in ("liked", "loved"):
                names.append(category)
            if not any(text_rule(t, rule) for t in names):
                return False
        elif key in ("steps", "cfg", "width", "height", "seed"):
            if not number_rule(row[key], rule):
                return False
    return True


# --------------------------------------------------------------------------
# library backup and portability
# --------------------------------------------------------------------------

def backup_db(keep=BACKUPS_KEPT):
    """A consistent copy of the ratings and tags on every start. The library is
    the one thing here that cannot be regenerated from the files on disk."""
    if not DB_FILE.exists():
        return None
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dest = BACKUP_DIR / f"organizer-{time.strftime('%Y%m%d-%H%M%S')}.db"
        src = sqlite3.connect(str(DB_FILE))
        dst = sqlite3.connect(str(dest))
        with dst:
            src.backup(dst)          # safe even with WAL and open readers
        src.close()
        dst.close()
        old = sorted(BACKUP_DIR.glob("organizer-*.db"))
        for stale in old[:-keep]:
            try:
                stale.unlink()
            except OSError:
                pass
        return dest
    except (sqlite3.Error, OSError) as exc:
        print(f"[backup] skipped: {exc}")
        return None


def library_payload():
    d = db()
    categories = {r["path"]: r["category"]
                  for r in d.execute("SELECT path, category FROM categories")}
    tags = {}
    for r in d.execute("SELECT path, tag FROM tags"):
        tags.setdefault(r["path"], []).append(r["tag"])
    return {
        "format": "image-organizer-library",
        "version": 1,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "counts": {"categories": len(categories),
                   "tagged": len(tags),
                   "tag_links": sum(len(v) for v in tags.values())},
        "categories": categories,
        "tags": tags,
    }


# --------------------------------------------------------------------------
# sidebar history helpers
# --------------------------------------------------------------------------


AUTO_GROUP_STATUS = "\U0001F916"
LOOSE_ALIAS = "Not in a subfolder"


def is_auto_group(item):
    gid = str(item.get("id") or "")
    return item.get("type") == "group" and (gid == "comfy_auto_group"
                                            or gid.startswith("auto_"))


def build_auto_groups(settings):
    """What the sidebar should contain for each watched folder right now."""
    wanted = {}
    for entry in settings.get("auto_folders", []) or []:
        path = (entry.get("path") or "").strip()
        if not entry.get("enabled", True) or not path:
            continue
        items = []
        # Images sitting directly in the watched folder have nowhere to appear
        # otherwise, since only subfolders become entries. This gives them one.
        if entry.get("include_root"):
            items.append({"type": "folder", "path": path,
                          "alias": entry.get("root_name") or LOOSE_ALIAS,
                          "status": "\u25c7"})
        excluded = {os.path.normpath(x) for x in (entry.get("excluded") or [])}
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if os.path.isdir(full) and os.path.normpath(full) not in excluded:
                    items.append({"type": "folder", "path": full, "alias": "", "status": ""})
        wanted[entry["id"]] = {
            "type": "group", "id": entry["id"],
            "name": entry.get("name") or os.path.basename(path.rstrip("/\\")) or path,
            "isOpen": True, "status": AUTO_GROUP_STATUS, "items": items,
        }
    return wanted


def update_auto_groups(history, settings):
    """Returns (history, changed). Auto groups are rebuilt from disk; a group
    whose folder was removed from the settings disappears with it."""
    wanted = build_auto_groups(settings)
    changed = False
    seen = set()

    def walk(items):
        nonlocal changed
        for i in range(len(items) - 1, -1, -1):
            item = items[i]
            if item.get("type") != "group":
                continue
            if is_auto_group(item):
                gid = item.get("id")
                if gid in wanted:
                    seen.add(gid)
                    target = wanted[gid]
                    # carry across anything the user set on these entries, or a
                    # sync would quietly undo their renames and pins
                    keep = {c.get("path"): c for c in item.get("items", [])}
                    merged = []
                    for child in target["items"]:
                        old = keep.get(child.get("path"))
                        if old:
                            for field in ("alias", "status", "pinned", "sort"):
                                if old.get(field):
                                    child[field] = old[field]
                        merged.append(child)
                    if (item.get("items") != merged or item.get("name") != target["name"]):
                        item["items"] = merged
                        item["name"] = target["name"]
                        changed = True
                else:
                    items.pop(i)
                    changed = True
            else:
                walk(item.get("items", []))

    walk(history)

    for gid, group in wanted.items():
        if gid not in seen and group["items"]:
            history.insert(0, group)
            changed = True
    return history, changed


def folder_exists(history, path):
    for item in history:
        if item.get("type") == "folder" and item.get("path") == path:
            return True
        if item.get("type") == "group" and folder_exists(item.get("items", []), path):
            return True
    return False


def find_and_update(history, identifier, action, value):
    for i, item in enumerate(history):
        item_id = item.get("path") if item.get("type") == "folder" else item.get("id")
        if item_id == identifier:
            if action == "pin":
                # "top", "bottom", or nothing. An older saved True means top.
                if value in ("top", "bottom"):
                    item["pinned"] = value
                elif value is True:
                    item["pinned"] = "top"
                else:
                    item.pop("pinned", None)
            elif action == "rename":
                if item.get("type") in ("group", "smart_folder"):
                    item["name"] = value
                else:
                    item["alias"] = value
            elif action == "status":
                item["status"] = value
            elif action == "delete":
                history.pop(i)
            return True
        if item.get("type") == "group" and find_and_update(
            item.get("items", []), identifier, action, value
        ):
            return True
    return False


def get_drives():
    if platform.system() == "Windows":
        return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
    return ["/"]


# --------------------------------------------------------------------------
# routes: shell
# --------------------------------------------------------------------------


@app.errorhandler(sqlite3.Error)
def database_error(exc):
    """The page expects JSON from every /api call, so a failing database
    answers with a message it can show rather than an HTML stack trace."""
    print(f"[db] {exc}")
    return jsonify({"success": False, "error": f"Database error: {exc}"}), 500


@app.errorhandler(OSError)
def file_error(exc):
    print(f"[io] {exc}")
    return jsonify({"success": False, "error": f"File error: {exc}"}), 500


@app.route("/")
def index():
    if (APP_DIR / "templates" / "index.html").exists():
        return render_template("index.html")
    local = APP_DIR / "index.html"
    if local.exists():
        return send_file(local)
    return "index.html not found. Put it in ./templates/ or next to app.py.", 500


@app.route("/api/settings", methods=["GET", "POST"])
def handle_settings():
    if request.method == "POST":
        incoming = request.json or {}
        merged = _merge_defaults(incoming, DEFAULT_SETTINGS)
        save_settings(merged)
        return jsonify({"success": True})
    return jsonify(load_settings())


@app.route("/api/browse")
def browse():
    path = request.args.get("path", "")
    if not path or path == "root":
        return jsonify({
            "directories": [{"name": d, "path": d} for d in get_drives()],
            "current_path": "root", "parent_path": "",
        })
    try:
        dirs = []
        for f in os.listdir(path):
            full = os.path.join(path, f)
            if os.path.isdir(full):
                dirs.append({"name": f, "path": full})
        dirs.sort(key=lambda x: x["name"].lower())
        parent = os.path.dirname(path)
        if parent == path or (
            platform.system() == "Windows" and len(path) == 3 and path.endswith(":\\")
        ):
            parent = "root"
        return jsonify({"directories": dirs, "current_path": path, "parent_path": parent})
    except OSError as exc:
        return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
# routes: history
# --------------------------------------------------------------------------


@app.route("/api/history", methods=["GET", "POST"])
def handle_history():
    history = load_history()
    settings = load_settings()
    dirty = False

    if request.method == "POST":
        data = request.json or {}
        folders = list(data.get("folders", []))
        if data.get("folder"):
            folders.append(data["folder"])
        for new_folder in folders:
            if new_folder and os.path.isdir(new_folder) and not folder_exists(history, new_folder):
                history.insert(0, {
                    "type": "folder", "path": new_folder, "alias": "", "status": "",
                })
                dirty = True

    history, changed = update_auto_groups(history, settings)
    if dirty or changed:
        save_history(history)
    return jsonify({"success": True, "history": history})


@app.route("/api/history/sync", methods=["POST"])
def sync_history():
    save_history((request.json or {}).get("history", []))
    return jsonify({"success": True})


@app.route("/api/history/update", methods=["POST"])
def update_history():
    data = request.json or {}
    history = load_history()
    find_and_update(history, data.get("path"), data.get("action"), data.get("value"))
    history, _ = update_auto_groups(history, load_settings())
    save_history(history)
    return jsonify({"success": True, "history": history})


@app.route("/api/history/check")
def check_history():
    """Which saved folders can still be opened, plus what the sidebar needs to
    sort by. Called after the sidebar has drawn, so a dead network path cannot
    stall the first paint. Counting files is opt-in because it means listing
    every folder, which is not free on a big library."""
    want_counts = request.args.get("counts") == "1"
    status = {}

    def walk(items):
        for it in items:
            if it.get("type") == "folder" and it.get("path"):
                path = it["path"]
                entry = {"ok": False, "mtime": 0, "count": None}
                try:
                    st = os.stat(path)
                    entry["ok"] = os.path.isdir(path)
                    entry["mtime"] = st.st_mtime
                except OSError:
                    pass
                if want_counts and entry["ok"]:
                    try:
                        entry["count"] = sum(
                            1 for e in os.scandir(path)
                            if e.is_file()
                            and os.path.splitext(e.name)[1].lower() in VALID_EXTS)
                    except OSError:
                        entry["count"] = None
                status[path] = entry
            elif it.get("type") == "group":
                walk(it.get("items", []))

    walk(load_history())
    return jsonify({"status": status})


@app.route("/api/history/repath", methods=["POST"])
def repath_folder():
    """Point a saved folder at its new location and carry every rating, tag and
    trash record across with it."""
    data = request.json or {}
    old = (data.get("old") or "").strip()
    new = (data.get("new") or "").strip().rstrip("/\\")

    if not old or not new:
        return jsonify({"success": False, "error": "Give both the old and the new path."}), 400
    if not os.path.isdir(new):
        return jsonify({"success": False,
                        "error": "That folder does not exist. Check the path and try again."}), 400

    history = load_history()
    hit = [False]

    def walk(items):
        for it in items:
            if it.get("type") == "folder" and it.get("path") and _same_path(it["path"], old):
                it["path"] = new
                hit[0] = True
            elif it.get("type") == "group":
                walk(it.get("items", []))

    walk(history)
    if not hit[0]:
        return jsonify({"success": False, "error": "That folder is no longer in the list."}), 404
    save_history(history)

    d = db()
    moved = 0
    for table in ("categories", "tags", "meta"):
        for row in d.execute(f"SELECT path FROM {table}").fetchall():
            p = row["path"]
            if not _under(p, old):
                continue
            new_p = os.path.join(new, os.path.relpath(p, old)) if not _same_path(p, old) else new
            d.execute(f"UPDATE OR REPLACE {table} SET path=? WHERE path=?", (new_p, p))
            moved += 1

    for row in d.execute("SELECT id, original_path, trash_path FROM trash").fetchall():
        orig, trash_p = row["original_path"], row["trash_path"]
        changes = {}
        if orig and _under(orig, old):
            changes["original_path"] = os.path.join(new, os.path.relpath(orig, old))
        if trash_p and _under(trash_p, old):
            changes["trash_path"] = os.path.join(new, os.path.relpath(trash_p, old))
        if changes:
            sets = ", ".join(f"{k}=?" for k in changes)
            d.execute(f"UPDATE trash SET {sets} WHERE id=?", (*changes.values(), row["id"]))
            moved += 1

    d.commit()
    _roots_cache["ts"] = 0
    return jsonify({"success": True, "history": history, "moved": moved, "path": new})


# --------------------------------------------------------------------------
# routes: images
# --------------------------------------------------------------------------


@app.route("/api/images/check")
def check_folder():
    folder = request.args.get("folder")
    if folder in (GLOBAL_TAGS_FOLDER, SEARCH_FOLDER):
        return jsonify({"success": True})
    if not folder or not os.path.isdir(folder):
        return jsonify({"success": False, "error": "Folder not found or cannot be opened."})
    return jsonify({"success": True})


def _row_for(full_path, name, category, tags):
    st = os.stat(full_path)
    meta = get_metadata(full_path, st)
    return {
        "name": name,
        "path": full_path,
        "category": category,
        "time": st.st_ctime,
        "mtime": st.st_mtime,
        "bytes": st.st_size,
        "width": meta["width"],
        "height": meta["height"],
        "prompt": meta["prompt"],
        "negative": meta["negative"],
        "steps": meta["steps"],
        "seed": meta["seed"],
        "source": meta["source"],
        "prompt_list": meta["prompt_list"],
        "prompt_line": meta["prompt_line"],
        "prompt_lines": meta["prompt_lines"],
        "cfg": meta["cfg"],
        "sampler": meta["sampler"],
        "scheduler": meta["scheduler"],
        "model": meta["model"],
        "loras": meta["loras"],
        "phash": meta["phash"],
        "user_tags": tags,
    }


@app.route("/api/images/stream")
def stream_images():
    base_folder = request.args.get("folder")
    is_global = base_folder == GLOBAL_TAGS_FOLDER
    is_search = base_folder == SEARCH_FOLDER
    query = request.args.get("q", "")
    limit = int(request.args.get("limit", STREAM_LIMIT))

    if not is_global and not is_search and (not base_folder or not os.path.isdir(base_folder)):
        return jsonify({"error": "Invalid directory"}), 400
    if not is_global and not is_search:
        migrate_folder_layout(base_folder)

    settings = load_settings()
    quality = int(settings.get("thumb_quality", THUMB_QUALITY))

    d = db()
    cat_map = {r["path"]: r["category"] for r in d.execute("SELECT path, category FROM categories")}
    tag_map = {}
    for r in d.execute("SELECT path, tag FROM tags"):
        tag_map.setdefault(r["path"], []).append(r["tag"])

    trashed = {r["trash_path"] for r in d.execute("SELECT trash_path FROM trash")}

    def generate():
        # everything ever indexed, filtered here rather than shipped to the
        # browser: the meta table already holds prompt, model and settings
        if is_search:
            rules = prepare_query(query)
            rows = list(d.execute("SELECT * FROM meta ORDER BY ctime DESC"))
            yield f"data: {json.dumps({'type': 'start', 'total': len(rows)})}\n\n"
            batch, done, sent = [], 0, 0
            for row in rows:
                done += 1
                path = row["path"]
                if path in trashed or not os.path.isfile(path):
                    continue
                cat = cat_map.get(path, "rest")
                tg = tag_map.get(path, [])
                if rules and not row_matches(row, rules, cat, tg):
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                batch.append({
                    "name": os.path.basename(path), "path": path, "category": cat,
                    "time": st.st_ctime, "mtime": st.st_mtime, "bytes": st.st_size,
                    **_meta_from_row(row),
                    "user_tags": tg, "folder": os.path.dirname(path),
                })
                sent += 1
                if len(batch) >= STREAM_BATCH:
                    warm_thumbs([b["path"] for b in batch], quality)
                    yield f"data: {json.dumps({'type': 'batch', 'current': done, 'total': len(rows), 'images': batch})}\n\n"
                    batch = []
                if sent >= limit:
                    break
            if batch:
                warm_thumbs([b["path"] for b in batch], quality)
                yield f"data: {json.dumps({'type': 'batch', 'current': done, 'total': len(rows), 'images': batch})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'matched': sent, 'scanned': len(rows), 'capped': sent >= limit})}\n\n"
            return

        targets = []
        if is_global:
            for p in sorted(set(cat_map) | set(tag_map)):
                if os.path.isfile(p) and p not in trashed:
                    targets.append((p, os.path.basename(p)))
        else:
            try:
                entries = list(os.scandir(base_folder))
            except OSError as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                return
            rows = []
            for e in entries:
                if not e.is_file():
                    continue
                if os.path.splitext(e.name)[1].lower() not in VALID_EXTS:
                    continue
                try:
                    rows.append((e.path, e.name, e.stat().st_ctime))
                except OSError:
                    continue
            # newest first so arrival order matches the default sort
            rows.sort(key=lambda r: r[2], reverse=True)
            targets = [(p, n) for p, n, _ in rows]

        total = len(targets)
        yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"

        batch = []
        done = 0
        for full_path, name in targets:
            try:
                batch.append(_row_for(full_path, name, cat_map.get(full_path, "rest"),
                                      tag_map.get(full_path, [])))
            except OSError:
                pass
            done += 1
            if len(batch) >= STREAM_BATCH:
                warm_thumbs([b["path"] for b in batch], quality)
                yield f"data: {json.dumps({'type': 'batch', 'current': done, 'total': total, 'images': batch})}\n\n"
                batch = []

        if batch:
            warm_thumbs([b["path"] for b in batch], quality)
            yield f"data: {json.dumps({'type': 'batch', 'current': done, 'total': total, 'images': batch})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/thumb")
def serve_thumb():
    path = request.args.get("path")
    if not guard(path):
        return "Not found", 404
    quality = int(load_settings().get("thumb_quality", THUMB_QUALITY))
    dest = build_thumb(path, quality)
    if dest and dest.exists():
        return send_file(dest, mimetype="image/webp", max_age=31536000)
    return send_file(path, max_age=3600)  # fall back to the original


@app.route("/image")
def serve_image():
    path = request.args.get("path")
    if not guard(path):
        return "Not found", 404
    return send_file(path, max_age=3600, conditional=True)


@app.route("/api/prompt")
def get_prompt():
    path = request.args.get("path")
    if not guard(path):
        return jsonify({"raw_workflow": "{}"})
    try:
        with Image.open(path) as img:
            info = img.info or {}
            raw = info.get("workflow") or info.get("prompt") or info.get("parameters") or "{}"
            return jsonify({"raw_workflow": raw})
    except (OSError, ValueError):
        return jsonify({"raw_workflow": "{}"})


@app.route("/api/reveal", methods=["POST"])
def reveal_file():
    path = (request.json or {}).get("path")
    if not guard(path):
        return jsonify({"success": False, "error": "File not found"})
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
        return jsonify({"success": True})
    except OSError as exc:
        return jsonify({"success": False, "error": str(exc)})


# --------------------------------------------------------------------------
# routes: tags
# --------------------------------------------------------------------------


@app.route("/api/tags", methods=["POST"])
def update_tags():
    data = request.json or {}
    paths = data.get("paths", [])
    tags = [str(t).strip().lstrip("#") for t in data.get("tags", []) if str(t).strip()]
    add_tags = [str(t).strip().lstrip("#") for t in data.get("add_tags", []) if str(t).strip()]
    remove_tags = [str(t).strip().lstrip("#") for t in data.get("remove_tags", []) if str(t).strip()]

    d = db()
    for path in paths:
        if remove_tags:
            d.executemany("DELETE FROM tags WHERE path=? AND tag=?",
                          [(path, t) for t in remove_tags])
        elif add_tags:
            d.executemany("INSERT OR REPLACE INTO tags VALUES (?,?)",
                          [(path, t) for t in add_tags])
        else:
            d.execute("DELETE FROM tags WHERE path=?", (path,))
            if tags:
                d.executemany("INSERT OR REPLACE INTO tags VALUES (?,?)",
                              [(path, t) for t in tags])
    d.commit()
    return jsonify({"success": True})


# --------------------------------------------------------------------------
# routes: tag suggestions
# --------------------------------------------------------------------------


@app.route("/api/tag/check", methods=["POST"])
def check_tagger():
    ok, message = tagger.check((request.json or {}).get("tagger")
                               or load_settings().get("tagger") or {})
    return jsonify({"ok": ok, "message": message})


@app.route("/api/tag/auto")
def auto_tag():
    """Propose tags for a set of images, one event per image so the screen can
    fill in as it goes. Nothing is written here; the review decides."""
    paths = [p for p in request.args.getlist("path") if guard(p)]
    settings = load_settings()
    cfg = dict(settings.get("tagger") or {})
    for key in ("backend", "model", "url", "api_key", "extra"):
        if request.args.get(key) is not None:
            cfg[key] = request.args.get(key)
    if request.args.get("max_tags"):
        try:
            cfg["max_tags"] = max(1, min(40, int(request.args["max_tags"])))
        except ValueError:
            pass

    vocabulary = []
    if cfg.get("prefer_existing", True):
        vocabulary = [r["tag"] for r in db().execute(
            "SELECT tag, COUNT(*) c FROM tags GROUP BY tag ORDER BY c DESC LIMIT 80")]

    d = db()
    existing = {}
    for row in d.execute("SELECT path, tag FROM tags"):
        existing.setdefault(row["path"], []).append(row["tag"])

    def generate():
        yield f"data: {json.dumps({'type': 'start', 'total': len(paths)})}\n\n"
        for i, path in enumerate(paths):
            meta = get_metadata(path) or {}
            tags, problem = tagger.suggest(path, meta, cfg, vocabulary)
            already = set(existing.get(path, []))
            payload = {
                "type": "image", "current": i + 1, "total": len(paths),
                "path": path, "name": os.path.basename(path),
                "tags": [t for t in tags if t not in already],
                "existing": sorted(already),
                "error": problem,
            }
            yield f"data: {json.dumps(payload)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/tags/all")
def all_tags():
    rows = db().execute(
        "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY n DESC, tag ASC"
    ).fetchall()
    return jsonify({"tags": [{"tag": r["tag"], "count": r["n"]} for r in rows]})


# --------------------------------------------------------------------------
# routes: actions, trash, export
# --------------------------------------------------------------------------


def _unique_dest(directory, filename):
    dest = os.path.join(directory, filename)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(filename)
    i = 1
    while True:
        candidate = os.path.join(directory, f"{stem} ({i}){ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def _forget(d, path):
    d.execute("DELETE FROM categories WHERE path=?", (path,))
    d.execute("DELETE FROM tags WHERE path=?", (path,))


@app.route("/api/action", methods=["POST"])
def handle_action():
    data = request.json or {}
    paths = [p for p in data.get("paths", []) if is_path_allowed(p)]
    action = data.get("action")

    d = db()
    settings = load_settings()
    delete_mode = settings.get("delete_mode", "soft")
    trashed = []

    if action == "trash":
        for img_path in paths:
            if not os.path.exists(img_path):
                continue
            cat_row = d.execute("SELECT category FROM categories WHERE path=?",
                                (img_path,)).fetchone()
            category = cat_row["category"] if cat_row else ""
            tags = [r["tag"] for r in d.execute("SELECT tag FROM tags WHERE path=?", (img_path,))]

            if delete_mode == "soft":
                trash_dir = os.path.join(os.path.dirname(img_path), "trash")
                os.makedirs(trash_dir, exist_ok=True)
                dest = _unique_dest(trash_dir, os.path.basename(img_path))
                try:
                    shutil.move(img_path, dest)
                except OSError as exc:
                    print(f"[trash] {img_path}: {exc}")
                    continue
                cur = d.execute(
                    "INSERT INTO trash (original_path, trash_path, deleted_at, category, tags, restorable) "
                    "VALUES (?,?,?,?,?,1)",
                    (img_path, dest, time.time(), category, json.dumps(tags)),
                )
                trashed.append({"id": cur.lastrowid, "path": img_path})
            else:
                try:
                    if send2trash is not None:
                        send2trash.send2trash(os.path.normpath(img_path))
                    else:
                        os.remove(img_path)
                except OSError as exc:
                    print(f"[trash] {img_path}: {exc}")
                    continue
                d.execute(
                    "INSERT INTO trash (original_path, trash_path, deleted_at, category, tags, restorable) "
                    "VALUES (?,?,?,?,?,0)",
                    (img_path, "", time.time(), category, json.dumps(tags)),
                )
            _forget(d, img_path)
    elif action == "rest":
        d.executemany("DELETE FROM categories WHERE path=?", [(p,) for p in paths])
    else:
        d.executemany("INSERT OR REPLACE INTO categories VALUES (?,?)",
                      [(p, action) for p in paths])

    d.commit()
    return jsonify({"success": True, "trashed": trashed})


@app.route("/api/trash")
def list_trash():
    rows = db().execute(
        "SELECT * FROM trash WHERE restorable=1 ORDER BY deleted_at DESC LIMIT 500"
    ).fetchall()
    items = []
    for r in rows:
        if not os.path.exists(r["trash_path"]):
            continue
        items.append({
            "id": r["id"],
            "name": os.path.basename(r["original_path"]),
            "original_path": r["original_path"],
            "trash_path": r["trash_path"],
            "deleted_at": r["deleted_at"],
            "category": r["category"] or "",
            "tags": json.loads(r["tags"] or "[]"),
        })
    return jsonify({"items": items})


@app.route("/api/trash/restore", methods=["POST"])
def restore_trash():
    ids = (request.json or {}).get("ids", [])
    if not ids:
        return jsonify({"success": True, "restored": []})

    d = db()
    placeholders = ",".join("?" * len(ids))
    rows = d.execute(f"SELECT * FROM trash WHERE id IN ({placeholders})", ids).fetchall()

    restored = []
    for r in rows:
        src, original = r["trash_path"], r["original_path"]
        if not src or not os.path.exists(src):
            continue
        dest = original if not os.path.exists(original) else _unique_dest(
            os.path.dirname(original), os.path.basename(original)
        )
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
        except OSError as exc:
            print(f"[restore] {src}: {exc}")
            continue

        if r["category"]:
            d.execute("INSERT OR REPLACE INTO categories VALUES (?,?)", (dest, r["category"]))
        for t in json.loads(r["tags"] or "[]"):
            d.execute("INSERT OR REPLACE INTO tags VALUES (?,?)", (dest, t))
        d.execute("DELETE FROM trash WHERE id=?", (r["id"],))
        restored.append({"id": r["id"], "path": dest})

    d.commit()
    return jsonify({"success": True, "restored": restored})


@app.route("/api/trash/purge", methods=["POST"])
def purge_trash():
    data = request.json or {}
    d = db()
    if data.get("all"):
        rows = d.execute("SELECT * FROM trash WHERE restorable=1").fetchall()
    else:
        ids = data.get("ids", [])
        if not ids:
            return jsonify({"success": True})
        placeholders = ",".join("?" * len(ids))
        rows = d.execute(f"SELECT * FROM trash WHERE id IN ({placeholders})", ids).fetchall()

    for r in rows:
        try:
            if r["trash_path"] and os.path.exists(r["trash_path"]):
                os.remove(r["trash_path"])
        except OSError as exc:
            print(f"[purge] {r['trash_path']}: {exc}")
        d.execute("DELETE FROM trash WHERE id=?", (r["id"],))
    d.commit()
    return jsonify({"success": True, "purged": len(rows)})


@app.route("/api/export", methods=["POST"])
def export_files():
    """mode = copy | move"""
    data = request.json or {}
    paths = [p for p in data.get("paths", []) if guard(p)]
    dest_dir = data.get("dest")
    mode = data.get("mode", "copy")

    if not dest_dir or not os.path.isdir(dest_dir):
        return jsonify({"success": False, "error": "Pick a destination folder that exists."}), 400

    d = db()
    moved = []
    for src in paths:
        dest = _unique_dest(dest_dir, os.path.basename(src))
        try:
            if mode == "move":
                shutil.move(src, dest)
                d.execute("UPDATE OR REPLACE categories SET path=? WHERE path=?", (dest, src))
                d.execute("UPDATE OR REPLACE tags SET path=? WHERE path=?", (dest, src))
                d.execute("DELETE FROM meta WHERE path=?", (src,))
                moved.append({"from": src, "to": dest})
            else:
                shutil.copy2(src, dest)
        except OSError as exc:
            print(f"[export] {src}: {exc}")
    d.commit()
    return jsonify({"success": True, "count": len(paths), "moved": moved})


@app.route("/api/export/zip", methods=["POST"])
def export_zip():
    paths = [p for p in (request.json or {}).get("paths", []) if guard(p)]
    if not paths:
        return jsonify({"success": False, "error": "Nothing selected."}), 400

    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for p in paths:
            name = os.path.basename(p)
            stem, ext = os.path.splitext(name)
            i = 1
            while name in used:
                name = f"{stem} ({i}){ext}"
                i += 1
            used.add(name)
            try:
                zf.write(p, name)
            except OSError as exc:
                print(f"[zip] {p}: {exc}")
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"export-{int(time.time())}.zip")


def _ext_for(fmt):
    return ".jpg" if fmt in ("jpg", "jpeg") else "." + fmt


def _source_exif(path):
    """The file's own EXIF block, or None if it cannot be read. "Keep all
    metadata" starts from this so untouched camera tags survive a rewrite."""
    try:
        with Image.open(path) as probe:
            return probe.getexif()
    except (OSError, ValueError):
        return None


def _edit_dest(source_path, fmt, dest_mode, dest_dir):
    """Where an edited copy goes. Originals are never the default target."""
    ext = _ext_for(fmt)
    stem = os.path.splitext(os.path.basename(source_path))[0]
    if dest_mode == "folder":
        if not dest_dir or not os.path.isdir(dest_dir):
            raise ValueError("Pick a destination folder that exists.")
        return _unique_dest(dest_dir, stem + ext)
    if dest_mode == "overwrite":
        return os.path.join(os.path.dirname(source_path), stem + ext)
    return _unique_dest(os.path.dirname(source_path), stem + "_edit" + ext)


@app.route("/api/edit/save", methods=["POST"])
def save_edit():
    """Take the canvas the browser rendered and write it out as a copy, carrying
    across as much of the original's metadata as the user asked for."""
    try:
        payload = json.loads(request.form.get("payload") or "{}")
    except ValueError:
        return jsonify({"success": False, "error": "Bad request."}), 400

    source = payload.get("source_path") or ""
    if not guard(source):
        return jsonify({"success": False, "error": "Original file not found."}), 404

    blob = request.files.get("image")
    if blob is None:
        return jsonify({"success": False, "error": "No image data arrived."}), 400

    fmt = (payload.get("format") or "png").lower()
    if fmt not in ("png", "jpeg", "jpg", "webp"):
        return jsonify({"success": False, "error": "Unsupported format."}), 400

    mode = payload.get("metadata") or "generation"
    settings = load_settings()

    try:
        chunks = metadata.collect_chunks(source, mode)
        base_exif = _source_exif(source) if mode == "all" else None
        dest = _edit_dest(source, fmt, payload.get("dest") or "suffix",
                          payload.get("dest_dir"))
        with Image.open(blob.stream) as im:
            im.load()
            notes = metadata.write_image(
                im, dest, fmt, quality=int(payload.get("quality", 92)),
                chunks=chunks, background=payload.get("background") or "#000000",
                base_exif=base_exif, strip_gps=payload.get("strip_gps", True))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"success": False, "error": f"Could not write the file: {exc}"}), 500

    d = db()
    d.execute("DELETE FROM meta WHERE path=?", (dest,))
    tagged = False
    if settings.get("tag_edits", True):
        # so an edited copy is findable later, and tellable from the original
        d.execute("INSERT OR REPLACE INTO tags VALUES (?,?)", (dest, "edited"))
        tagged = True
    d.commit()
    return jsonify({"success": True, "path": dest, "tagged": tagged,
                    "name": os.path.basename(dest), "notes": notes})


# --------------------------------------------------------------------------
# routes: projects, library, cache
# --------------------------------------------------------------------------


@app.route("/api/projects")
def list_projects():
    data = load_projects()
    out = []
    for p in data["projects"]:
        d = project_dir(p["id"])
        db_path = d / "organizer.db"
        out.append({**p, "active": p["id"] == data["active"],
                    "size": db_path.stat().st_size if db_path.exists() else 0,
                    "folder": str(d)})
    return jsonify({"active": data["active"], "projects": out})


@app.route("/api/projects/create", methods=["POST"])
def create_project():
    name = ((request.json or {}).get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Give the project a name."}), 400
    data = load_projects()
    pid = "p_" + hashlib.sha1(f"{name}{time.time()}".encode()).hexdigest()[:10]
    data["projects"].append({"id": pid, "name": name, "created": time.time()})
    if (request.json or {}).get("switch", True):
        data["active"] = pid
    save_projects(data)
    use_project(data["active"])
    return jsonify({"success": True, "id": pid, "active": data["active"]})


@app.route("/api/projects/switch", methods=["POST"])
def switch_project():
    pid = (request.json or {}).get("id")
    data = load_projects()
    if not any(p["id"] == pid for p in data["projects"]):
        return jsonify({"success": False, "error": "No such project."}), 404
    data["active"] = pid
    save_projects(data)
    use_project(pid)
    return jsonify({"success": True, "active": pid})


@app.route("/api/projects/rename", methods=["POST"])
def rename_project():
    body = request.json or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Give the project a name."}), 400
    data = load_projects()
    for p in data["projects"]:
        if p["id"] == body.get("id"):
            p["name"] = name
    save_projects(data)
    return jsonify({"success": True, "projects": data["projects"]})


@app.route("/api/projects/delete", methods=["POST"])
def delete_project():
    pid = (request.json or {}).get("id")
    data = load_projects()
    if pid == "default":
        return jsonify({"success": False,
                        "error": "The main library cannot be deleted."}), 400
    if len(data["projects"]) < 2:
        return jsonify({"success": False, "error": "That is your only project."}), 400

    data["projects"] = [p for p in data["projects"] if p["id"] != pid]
    if data["active"] == pid:
        data["active"] = data["projects"][0]["id"]
    save_projects(data)
    # only the library is removed; the image folders it pointed at are untouched
    shutil.rmtree(project_dir(pid), ignore_errors=True)
    use_project(data["active"])
    return jsonify({"success": True, "active": data["active"]})


@app.route("/api/library/export")
def export_library():
    payload = library_payload()
    buf = io.BytesIO(json.dumps(payload, indent=1).encode("utf-8"))
    return send_file(buf, mimetype="application/json", as_attachment=True,
                     download_name=f"organizer-library-{time.strftime('%Y%m%d')}.json")


@app.route("/api/library/stats")
def library_stats():
    payload = library_payload()
    backups = sorted(BACKUP_DIR.glob("organizer-*.db")) if BACKUP_DIR.exists() else []
    return jsonify({"counts": payload["counts"],
                    "backups": len(backups),
                    "latest_backup": backups[-1].name if backups else ""})


@app.route("/api/library/import", methods=["POST"])
def import_library():
    """Restore ratings and tags from an export. Files are never touched, only
    the library rows that point at them."""
    body = request.json or {}
    payload = body.get("data") or {}
    mode = body.get("mode", "merge")

    if payload.get("format") != "image-organizer-library":
        return jsonify({"success": False,
                        "error": "That does not look like a library export."}), 400

    categories = payload.get("categories") or {}
    tags = payload.get("tags") or {}
    if not isinstance(categories, dict) or not isinstance(tags, dict):
        return jsonify({"success": False, "error": "The export is malformed."}), 400

    backup_db()          # before touching anything
    d = db()
    if mode == "replace":
        d.execute("DELETE FROM categories")
        d.execute("DELETE FROM tags")

    cats = 0
    for path, cat in categories.items():
        if isinstance(path, str) and cat in ("liked", "loved"):
            d.execute("INSERT OR REPLACE INTO categories VALUES (?,?)", (path, cat))
            cats += 1
    links = 0
    for path, names in tags.items():
        if not isinstance(path, str) or not isinstance(names, list):
            continue
        for tag in names:
            tag = str(tag).strip().lstrip("#")
            if tag:
                d.execute("INSERT OR REPLACE INTO tags VALUES (?,?)", (path, tag))
                links += 1
    d.commit()

    missing = sum(1 for p in set(categories) | set(tags) if not os.path.exists(p))
    return jsonify({"success": True, "categories": cats, "tag_links": links,
                    "missing_files": missing})


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    what = (request.json or {}).get("what", "thumbs")
    if what in ("thumbs", "all"):
        shutil.rmtree(THUMB_DIR, ignore_errors=True)
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        d = db()
        d.execute("DELETE FROM thumbs")
        d.commit()
    if what in ("meta", "all"):
        d = db()
        d.execute("DELETE FROM meta")
        d.commit()
    return jsonify({"success": True})


@app.route("/api/cache/stats")
def cache_stats():
    files, total = thumb_cache_stats()
    return jsonify({"files": files, "bytes": total,
                    "db_bytes": os.path.getsize(DB_FILE) if DB_FILE.exists() else 0})


@app.route("/api/cache/prune", methods=["POST"])
def prune_cache():
    removed = prune_thumbs()
    files, total = thumb_cache_stats()
    return jsonify({"success": True, "removed": removed,
                    "files": files, "bytes": total})


@app.route("/api/stats")
def stats():
    d = db()
    return jsonify({
        "images_indexed": d.execute("SELECT COUNT(*) c FROM meta").fetchone()["c"],
        "categorised": d.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"],
        "tag_links": d.execute("SELECT COUNT(*) c FROM tags").fetchone()["c"],
        "in_trash": d.execute("SELECT COUNT(*) c FROM trash WHERE restorable=1").fetchone()["c"],
    })


# --------------------------------------------------------------------------
# startup
# --------------------------------------------------------------------------


def port_is_open(port, host="127.0.0.1", timeout=0.4):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def is_our_app(port):
    """Distinguish our own already-running copy from some unrelated service."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/stats", timeout=1.5) as res:
            return "images_indexed" in json.loads(res.read())
    except (OSError, ValueError):
        return False


def find_free_port(start, tries=20):
    for port in range(start, start + tries):
        if not port_is_open(port):
            return port
    return None


def open_browser_when_ready(url, port, timeout=15):
    """Wait until the server is actually listening, then open the browser.
    Polling beats a fixed sleep: no blank tab if startup is slow."""
    def wait():
        deadline = time.time() + timeout
        while time.time() < deadline:
            if port_is_open(port):
                break
            time.sleep(0.15)
        try:
            webbrowser.open(url)
        except (webbrowser.Error, OSError):
            pass   # headless or no browser configured; the URL is printed anyway

    threading.Thread(target=wait, daemon=True).start()


def parse_args(argv):
    port, launch, reload_on = DEFAULT_PORT, True, False
    for i, arg in enumerate(argv):
        if arg in ("--no-browser", "-n"):
            launch = False
        elif arg in ("--reload", "--dev", "-r"):
            reload_on = True
        elif arg == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                pass
        elif arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                pass
    if os.environ.get(NO_BROWSER_ENV) == "1":
        launch = False
    return port, launch, reload_on


def main(argv=None):
    port, launch, reload_on = parse_args(sys.argv[1:] if argv is None else argv)

    # With --reload the watcher runs the module twice: once to watch, once to
    # serve. Only the first pass should greet you, open a browser or take a
    # backup, or you get two of each every time you save a file.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        port = int(os.environ.get(PORT_ENV, port))
        use_project(load_projects()["active"])
        app.run(debug=False, threaded=True, port=port, use_reloader=True)
        return

    # Running it twice should just bring up the window, not fail with a stack
    # trace about the port being taken.
    if port_is_open(port):
        if is_our_app(port):
            print(f"{APP_NAME} is already running on http://127.0.0.1:{port}")
            if launch:
                webbrowser.open(f"http://127.0.0.1:{port}")
            return
        free = find_free_port(port + 1)
        if free is None:
            sys.exit(f"Port {port} is busy and nothing nearby is free. "
                     f"Try: python app.py --port 8080")
        print(f"Port {port} is in use by something else, switching to {free}.")
        port = free

    use_project(load_projects()["active"])
    migrate_from_v1()
    saved = backup_db()
    if saved:
        print(f"[backup] library copied to {saved.name} (last {BACKUPS_KEPT} kept)")

    url = f"http://127.0.0.1:{port}"
    print(f"{APP_NAME} running on {url}")
    if reload_on:
        print("Watching for changes: edit a file and it restarts by itself.")
    if launch:
        print("Opening your browser... (use --no-browser to stop this)")
        open_browser_when_ready(url, port)

    os.environ[PORT_ENV] = str(port)
    app.run(debug=False, threaded=True, port=port, use_reloader=reload_on)


if __name__ == "__main__":
    main()
