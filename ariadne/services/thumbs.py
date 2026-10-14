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


def build_thumb(path, quality=config.THUMB_QUALITY):
    try:
        st = os.stat(path)
        dest = thumb_path_for(path, st)
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = config.THUMB_SIZE
        with Image.open(path) as im:
            try:
                im.seek(0)  # first frame of animated gif/webp
            except (EOFError, AttributeError):
                pass
            im.draft("RGB", (size, size))   # fast JPEG downscale path
            im = metadata.oriented(im)      # honour EXIF rotation
            im = im.convert("RGB")
            im.thumbnail((size, size), Image.LANCZOS)
            # the indexer warms thumbnails while /thumb may be building the
            # same one: separate scratch names, and the first replace wins
            tmp = dest.with_name(f"{dest.stem}.{threading.get_ident()}.tmp")
            im.save(tmp, "WEBP", quality=quality, method=4)
            try:
                os.replace(tmp, dest)
            except OSError:
                if not dest.exists():
                    raise
                os.remove(tmp)
        remember_thumb(dest, path, st)
        return dest
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        log.warning(f"[thumb] {path}: {exc}")
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
    for root, _, names in os.walk(config.paths.thumb_dir):
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
