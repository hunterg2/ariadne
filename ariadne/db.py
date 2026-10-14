"""SQLite access: one connection per thread, the baseline schema, the small
key/value table and backups.

Schema changes after the baseline go through ``ariadne/migrations`` (Stage 1).
"""

import sqlite3
import threading
import time

from ariadne import config
from ariadne.log import log

_local = threading.local()
_generation = 0

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
        prompt_lines INTEGER,
        kind         TEXT,
        camera_make  TEXT,
        camera_model TEXT,
        lens         TEXT,
        exposure     TEXT,
        f_number     TEXT,
        iso          TEXT,
        focal        TEXT,
        taken_at     TEXT,
        lat          REAL,
        lon          REAL,
        software     TEXT
    );
"""

BASE_SQL = META_SQL + """
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
        stars         INTEGER DEFAULT 0,
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


# Every handle in use, by the thread holding it. A handle is only ever
# closed by its own thread: closing one from another thread while that
# thread is inside a query crashes the process (an access violation in
# sqlite3, seen during a project switch under load). A request lets go of
# its handle when it ends (``release`` from the app's teardown) and the
# workers after each pass, so between requests nothing is open and a switch
# has nothing to wait for.
_open = {}                    # connection -> ident of the thread using it
_open_lock = threading.Lock()
_switch_lock = threading.RLock()      # held across a project switch


def db():
    conn = getattr(_local, "conn", None)
    # a project switch bumps the generation, which retires every open handle
    if conn is not None and getattr(_local, "gen", -1) != _generation:
        release()
        conn = None
    if conn is None:
        # a switch in progress finishes first, or this would open the new
        # file before its tables exist
        with _switch_lock:
            conn = sqlite3.connect(str(config.paths.db_file), check_same_thread=False,
                                   timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                # WAL is a property of the file: once any connection has set it,
                # a second one racing for the lock can simply carry on
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            conn.execute("PRAGMA synchronous=NORMAL")
            # INSERT OR REPLACE must fire delete triggers, or the search index
            # keeps entries for rows that are gone
            conn.execute("PRAGMA recursive_triggers=ON")
            with _open_lock:
                _open[conn] = threading.get_ident()
            _local.conn = conn
            _local.gen = _generation
    return conn


def release():
    """Close this thread's handle, if it has one. Called when a request ends
    and after each worker pass, so that no idle thread keeps the file open
    (Windows will not delete or replace an open file) and no handle is
    pinned by a thread that is gone."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        return
    _local.conn = None
    with _open_lock:
        _open.pop(conn, None)
    try:
        conn.close()
    except sqlite3.Error:
        pass


def switch_lock():
    """Held by ``store.use_project`` for the whole switch. ``db`` takes it to
    open a handle, so a request arriving mid-switch waits for the new
    library to be ready instead of finding it half built ("no such table")."""
    return _switch_lock


# Full-text search over prompts. An external-content FTS5 table indexed by
# trigrams, so the query language's "...contains..." matches stay exact while
# a 200k-image library answers in tens of milliseconds instead of seconds.
# Kept in step with ``meta`` by triggers; rebuilt whenever ``meta`` is.
FTS_SQL = """
    CREATE VIRTUAL TABLE IF NOT EXISTS meta_fts USING fts5(
        prompt, negative, content='meta', content_rowid='rowid',
        tokenize='trigram'
    );
    CREATE TRIGGER IF NOT EXISTS trg_meta_fts_ai AFTER INSERT ON meta BEGIN
        INSERT INTO meta_fts(rowid, prompt, negative)
        VALUES (new.rowid, new.prompt, new.negative);
    END;
    CREATE TRIGGER IF NOT EXISTS trg_meta_fts_ad AFTER DELETE ON meta BEGIN
        INSERT INTO meta_fts(meta_fts, rowid, prompt, negative)
        VALUES ('delete', old.rowid, old.prompt, old.negative);
    END;
    CREATE TRIGGER IF NOT EXISTS trg_meta_fts_au AFTER UPDATE ON meta BEGIN
        INSERT INTO meta_fts(meta_fts, rowid, prompt, negative)
        VALUES ('delete', old.rowid, old.prompt, old.negative);
        INSERT INTO meta_fts(rowid, prompt, negative)
        VALUES (new.rowid, new.prompt, new.negative);
    END;
"""
FTS_ENABLED = True


def ensure_fts(d, rebuild=False):
    """Create the prompt search index and its triggers if they are missing.
    Without FTS5 (a custom SQLite build) searches fall back to plain LIKE."""
    global FTS_ENABLED
    try:
        d.executescript(FTS_SQL)
        if rebuild:
            d.execute("INSERT INTO meta_fts(meta_fts) VALUES ('rebuild')")
        d.commit()
        FTS_ENABLED = True
    except sqlite3.OperationalError as exc:
        FTS_ENABLED = False
        log.warning(f"[db] prompt search index unavailable ({exc}); searches use LIKE")


def retire_connections(wait=3.0):
    """Called on a project switch: every thread reopens against the new
    file. This thread's handle is closed here. One another thread is using
    is interrupted (``sqlite3_interrupt`` is the one call that is safe from
    another thread: the query fails, the request or pass ends) and that
    thread closes it itself, which is waited for, up to ``wait`` seconds,
    so the old database is let go of before the caller replaces or deletes
    it. A handle whose thread is gone is closed here, nothing else can be
    using it. Returns whether every old handle was closed in time."""
    global _generation
    me = threading.get_ident()
    alive = {t.ident for t in threading.enumerate()}
    with _open_lock:
        _generation += 1
        busy, orphans = [], []
        for conn, ident in list(_open.items()):
            if ident == me:
                continue
            if ident in alive:
                busy.append(conn)
            else:
                orphans.append(conn)
                del _open[conn]
    release()
    for conn in orphans:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    for conn in busy:
        try:
            conn.interrupt()
        except sqlite3.Error:
            pass
    deadline = time.time() + wait
    while busy:
        with _open_lock:
            busy = [c for c in busy if c in _open]
        if not busy or time.time() >= deadline:
            break
        time.sleep(0.01)
    if busy:
        log.warning(f"[db] {len(busy)} handle(s) to the old library still open after the switch")
    return not busy


def init_db():
    d = db()
    d.executescript(BASE_SQL)
    d.commit()

    # The parser has changed, so cached rows are stale. Drop and rebuild them;
    # nothing is lost, the values are all derived from the files themselves.
    rebuilt = False
    if kv_get("meta_cache_version") != str(config.META_CACHE_VERSION):
        d.execute("DROP TABLE IF EXISTS meta")
        d.executescript(META_SQL)
        # every indexed image has to be read again for the new columns
        d.execute("UPDATE images SET indexed_at=NULL") if _has_table(d, "images") else None
        d.commit()
        kv_set("meta_cache_version", config.META_CACHE_VERSION)
        log.info("[cache] metadata cache rebuilt for the new extractor")
        rebuilt = True
    # dropping meta took its triggers with it; the index must start over too
    ensure_fts(d, rebuild=rebuilt)


def _has_table(d, name):
    return d.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                     (name,)).fetchone() is not None


def kv_get(key, default=None):
    row = db().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(key, value):
    d = db()
    d.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, str(value)))
    d.commit()


def backup_db(keep=config.BACKUPS_KEPT):
    """A consistent copy of the ratings and tags on every start. The library is
    the one thing here that cannot be regenerated from the files on disk."""
    db_file = config.paths.db_file
    backup_dir = config.paths.backup_dir
    if not db_file.exists():
        return None
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / f"organizer-{time.strftime('%Y%m%d-%H%M%S')}.db"
        src = sqlite3.connect(str(db_file))
        dst = sqlite3.connect(str(dest))
        with dst:
            src.backup(dst)          # safe even with WAL and open readers
        src.close()
        dst.close()
        old = sorted(backup_dir.glob("organizer-*.db"))
        for stale in old[:-keep]:
            try:
                stale.unlink()
            except OSError:
                pass
        return dest
    except (sqlite3.Error, OSError) as exc:
        log.warning(f"[backup] skipped: {exc}")
        return None
