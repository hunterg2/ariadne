"""A backup of the open library as one zip, for Settings to hand the browser
as a download: everything that cannot be rebuilt from the image folders.

- ``organizer.db``: a consistent copy through SQLite's backup API, so a
  write in flight does not tear it.
- ``ariadne.key``: without it the account credentials in the database are
  unreadable and every account has to be added again.
- ``settings.json``, ``history.json``: preferences and the sidebar.
- ``watermarks/``: the per-account logos.

The database copies in ``backups/`` are not included: they are older
versions of the same file. Thumbnails are not included: they are rebuilt.
"""

import io
import os
import sqlite3
import tempfile
import time
import zipfile

from ariadne import config

README = """Ariadne backup, made {when}.

To restore: stop Ariadne, copy these files into its data folder (beside
app.py, or the data folder of the zip install; another library lives under
projects/<id>/), replacing what is there, then start it again.

ariadne.key is the key that encrypts the account credentials inside
organizer.db. Keep the two together: the database is unreadable for
accounts without the key, and the key is useless without the database.
"""


def filename(when=None):
    return f"Ariadne-backup-{time.strftime('%Y%m%d-%H%M', time.localtime(when))}.zip"


def contents():
    """What the zip will hold, as (name in zip, path), for the Settings
    screen to say and for the build itself. The database is listed only
    when it exists; the rest only when present."""
    paths = config.paths
    out = []
    if paths.db_file.exists():
        out.append(("organizer.db", paths.db_file))
    for p in (paths.key_file, paths.settings_file, paths.history_file):
        if p.exists():
            out.append((p.name, p))
    marks = getattr(paths, "watermark_dir", None)       # the public build has no watermarks
    if marks is not None and marks.is_dir():
        for p in sorted(marks.iterdir()):
            if p.is_file():
                out.append((f"watermarks/{p.name}", p))
    return out


def _copy_db(src_path):
    """A clean copy of the database in a temp file; the caller deletes it."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(tmp)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    return tmp


def build(when=None):
    """The zip as bytes."""
    when = when or time.time()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(when=time.strftime("%Y-%m-%d %H:%M", time.localtime(when))))
        for name, path in contents():
            if name == "organizer.db":
                tmp = _copy_db(path)
                try:
                    z.write(tmp, name)
                finally:
                    os.unlink(tmp)
            else:
                z.write(path, name)
    return buf.getvalue()


def status():
    """For the Settings screen: is the key there, and how big is the lot."""
    paths = config.paths
    items = contents()
    return {
        "key_exists": paths.key_file.exists(),
        "key_path": str(paths.key_file),
        "data_dir": str(paths.data_dir),
        "files": [name for name, _ in items],
        "bytes": sum(p.stat().st_size for _, p in items if p.exists()),
    }
