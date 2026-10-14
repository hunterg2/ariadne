"""Path safety. Every path the browser sends is checked here before the server
reads, writes or moves it. Stops ``/image?path=/etc/passwd``."""

import os
import threading
import time

from ariadne import config, db, store

_roots_cache = {"ts": 0.0, "gen": -1, "roots": [], "listed": []}
_real = {}                    # root as spelled in the list -> its realpath
_real_lock = threading.Lock()


def _resolve(path):
    """``os.path.realpath`` remembered per spelling, for the life of the
    process. Resolving a path on a network share that does not answer
    takes seconds (a name lookup per path component; a connection timeout
    per component for a host that is down), and this ran for every root on
    every refresh of the list, so one dead share in the sidebar stalled
    some request every 5 s. A root's resolution changes only if that folder
    is replaced by a link while Ariadne runs, which is not worth that."""
    hit = _real.get(path)
    if hit is not None:
        return hit
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError, TypeError):
        return None
    with _real_lock:
        _real[path] = real
    return real


def allowed_roots():
    now = time.time()
    fresh = (_roots_cache["roots"]
             and _roots_cache["gen"] == config.roots_generation
             and now - _roots_cache["ts"] < 5)
    if fresh:
        return _roots_cache["roots"]

    roots = set()
    listed = set()

    def add(path):
        # the stores already drop entries that are not text; this is the
        # last line, since a failure here would fail every request
        if isinstance(path, str) and path:
            listed.add(os.path.normpath(path))
            real = _resolve(path)
            if real:
                roots.add(real)

    def walk(items):
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("type") == "folder":
                add(it.get("path"))
            elif it.get("type") == "group":
                walk(it.get("items") or [])

    walk(store.load_history())
    settings = store.load_settings()
    for entry in settings.get("auto_folders") or []:
        if isinstance(entry, dict):
            add(entry.get("path"))
    for extra in settings.get("extra_roots") or []:
        add(extra)

    _roots_cache["roots"] = sorted(roots)
    # longest first, so a folder inside two listed roots takes the nearer
    _roots_cache["listed"] = sorted(listed, key=len, reverse=True)
    _roots_cache["ts"] = now
    _roots_cache["gen"] = config.roots_generation
    return _roots_cache["roots"]


def listed_roots():
    """The roots as the folder list spells them (``allowed_roots`` has
    their realpaths), longest first."""
    allowed_roots()                    # refreshes both lists
    return _roots_cache["listed"]


def as_listed(path):
    """``path`` normalised, with its root spelled as the folder list spells
    it. The index stores a file under the spelling the scan was given, so
    the same folder scanned as ``C:\\Pics`` and ``c:/pics/`` was indexed
    twice and a folder scope asked with the other spelling found nothing.
    Every scan and every folder scope goes through here first."""
    p = os.path.normpath(path)
    for root in listed_roots():
        n = len(root)
        if os.path.normcase(p[:n]) != os.path.normcase(root):
            continue
        if root.endswith(os.sep) or len(p) == n or p[n] == os.sep:
            return root + p[n:]
    return p


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
            # commonpath compares without case but answers in the spelling
            # of its first argument, so the equality must not mind case either
            if os.path.normcase(os.path.commonpath([real, root])) == os.path.normcase(root):
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
