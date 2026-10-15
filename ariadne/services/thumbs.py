"""WebP thumbnail cache. Names are content hashes of path + mtime + size, so a
changed file gets a new thumbnail and the old one is pruned later."""

import hashlib
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from ariadne import config, metadata
from ariadne.db import db
from ariadne.log import log

_pool = ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) // 2))


def thumb_path_for(path, st=None):
    st = st or os.stat(path)
    key = (f"{os.path.realpath(path)}|{st.st_mtime_ns}|{st.st_size}"
           f"|{config.THUMB_SIZE}|v{config.THUMB_VERSION}")
    digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()
    return config.paths.thumb_dir / digest[:2] / f"{digest}.webp"


_made = set()          # thumbnail folders known to exist: one mkdir each per run
# how hard the WebP encoder tries (0 to 6). At the same quality setting,
# 2 gives the same bytes as Pillow's default of 4 and encodes three times
# faster (13 ms against 37 for a busy 512px thumbnail); 3 and up cost
# the time and save nothing at this size.
WEBP_METHOD = 2


def _save(im, tmp, quality):
    """Write the WebP. A thumbnail folder cleared meanwhile (Settings,
    clear thumbnails) is made again rather than failing the file."""
    try:
        im.save(tmp, "WEBP", quality=quality, method=WEBP_METHOD)
    except FileNotFoundError:
        _made.discard(tmp.parent)
        tmp.parent.mkdir(parents=True, exist_ok=True)
        im.save(tmp, "WEBP", quality=quality, method=WEBP_METHOD)


def build_thumb(path, quality=config.THUMB_QUALITY, st=None, img=None, commit=True):
    """The thumbnail for ``path``, built if it is not there yet. The indexer
    passes ``st`` and ``img`` (the file it has open, decoded already) and
    ``commit=False``, its own commit covering the record."""
    try:
        st = st or os.stat(path)
        dest = thumb_path_for(path, st)
        if dest.exists():
            return dest
        if dest.parent not in _made:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _made.add(dest.parent)
        size = config.THUMB_SIZE
        with metadata.opened(path, img) as im:
            try:
                im.seek(0)  # first frame of animated gif/webp
            except (EOFError, AttributeError):
                pass
            if img is None:
                im.draft("RGB", (size, size))   # fast JPEG downscale path
            im = metadata.oriented(im)      # honour EXIF rotation
            im = im.convert("RGB")
            im.thumbnail((size, size), Image.LANCZOS)
            # the indexer warms thumbnails while /thumb may be building the
            # same one: separate scratch names, and the first replace wins
            tmp = dest.with_name(f"{dest.stem}.{threading.get_ident()}.tmp")
            _save(im, tmp, quality)
            try:
                os.replace(tmp, dest)
            except OSError:
                if not dest.exists():
                    raise
                os.remove(tmp)
        remember_thumb(dest, path, st, commit)
        return dest
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        log.warning(f"[thumb] {path}: {exc}")
        return None


def remember_thumb(dest, path, st, commit=True):
    """Thumbnail names are content hashes and cannot be reversed, so the link
    back to the source has to be stored if the cache is ever to be cleaned."""
    try:
        d = db()
        d.execute("INSERT OR REPLACE INTO thumbs VALUES (?,?,?,?)",
                  (str(dest), path, st.st_mtime_ns, st.st_size))
        if commit:
            d.commit()
    except sqlite3.Error:
        pass


def thumb_cache_stats():
    """How many thumbnails are on disk and their total size. ``scandir``
    hands over each entry's size with the listing on Windows, where a
    ``getsize`` per file was a system call each: half a second for twenty
    thousand thumbnails, paid by the Settings screen on every open."""
    files = 0
    total = 0
    stack = [str(config.paths.thumb_dir)]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                elif e.name.endswith(".webp"):
                    files += 1
                    total += e.stat(follow_symlinks=False).st_size
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

    for root, _, names in os.walk(config.paths.thumb_dir):
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


def warm_thumbs(paths, quality=config.THUMB_QUALITY):
    for p in paths:
        _pool.submit(build_thumb, p, quality)
