"""Star ratings, the reject flag and colour labels."""

import time

from ariadne.db import db


def _ensure(d, path, now):
    d.execute("INSERT OR IGNORE INTO ratings (path, stars, rejected, label, updated) "
              "VALUES (?,0,0,NULL,?)", (path, now))


def set_stars(paths, stars):
    stars = max(0, min(5, int(stars)))
    d = db()
    now = time.time()
    for path in paths:
        _ensure(d, path, now)
        d.execute("UPDATE ratings SET stars=?, updated=? WHERE path=?", (stars, now, path))
    d.commit()
    return stars


def set_rejected(paths, rejected):
    d = db()
    now = time.time()
    for path in paths:
        _ensure(d, path, now)
        d.execute("UPDATE ratings SET rejected=?, updated=? WHERE path=?",
                  (1 if rejected else 0, now, path))
    d.commit()


def set_label(paths, label):
    label = (label or "").strip() or None
    d = db()
    now = time.time()
    for path in paths:
        _ensure(d, path, now)
        d.execute("UPDATE ratings SET label=?, updated=? WHERE path=?", (label, now, path))
    d.commit()


def get_many(paths):
    out = {p: {"stars": 0, "rejected": 0, "label": None} for p in paths}
    if not paths:
        return out
    d = db()
    for chunk_start in range(0, len(paths), 500):
        chunk = paths[chunk_start:chunk_start + 500]
        marks = ",".join("?" * len(chunk))
        for row in d.execute(f"SELECT path, stars, rejected, label FROM ratings "
                             f"WHERE path IN ({marks})", chunk):
            out[row["path"]] = {"stars": row["stars"] or 0,
                                "rejected": row["rejected"] or 0,
                                "label": row["label"]}
    return out


def get_one(path):
    return get_many([path])[path]


def move(old_path, new_path):
    db().execute("UPDATE OR REPLACE ratings SET path=? WHERE path=?", (new_path, old_path))


def forget(path):
    db().execute("DELETE FROM ratings WHERE path=?", (path,))
