"""Path safety. Every path the browser sends is checked here before the server
reads, writes or moves it. Stops ``/image?path=/etc/passwd``."""

import os
import time

from ariadne import config, db, store

_roots_cache = {"ts": 0.0, "gen": -1, "roots": []}


def allowed_roots():
    now = time.time()
    fresh = (_roots_cache["roots"]
             and _roots_cache["gen"] == config.roots_generation
             and now - _roots_cache["ts"] < 5)
    if fresh:
        return _roots_cache["roots"]

    roots = set()

    def walk(items):
        for it in items:
            if it.get("type") == "folder" and it.get("path"):
                roots.add(os.path.realpath(it["path"]))
            elif it.get("type") == "group":
                walk(it.get("items", []))

    walk(store.load_history())
    settings = store.load_settings()
    for entry in settings.get("auto_folders", []) or []:
        if entry.get("path"):
            roots.add(os.path.realpath(entry["path"]))
    for extra in settings.get("extra_roots", []) or []:
        if extra:
            roots.add(os.path.realpath(extra))

    _roots_cache["roots"] = sorted(roots)
    _roots_cache["ts"] = now
    _roots_cache["gen"] = config.roots_generation
    return _roots_cache["roots"]


def is_path_allowed(p):
    """A path is readable if it sits under a folder the user has added, or if
    it is a file we already track."""
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

    row = db.db().execute(
        "SELECT 1 FROM ratings WHERE path=? "
        "UNION ALL SELECT 1 FROM tags WHERE path=? "
        "UNION ALL SELECT 1 FROM meta WHERE path=? "
        "UNION ALL SELECT 1 FROM trash WHERE trash_path=? OR original_path=? LIMIT 1",
        (p, p, p, p, p),
    ).fetchone()
    return row is not None


def guard(p):
    return bool(p) and os.path.exists(p) and is_path_allowed(p)


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def under(path, root):
    """Is `path` inside `root`? Tolerates mixed separators and Windows case."""
    p = os.path.normcase(os.path.normpath(path))
    r = os.path.normcase(os.path.normpath(root))
    return p == r or p.startswith(r + os.sep)
