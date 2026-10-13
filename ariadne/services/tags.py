"""Tag definitions (group and colour) and the rename and merge tools. The
``tags`` link table itself is unchanged from the original app."""

import time

from ariadne.db import db


def clean(tag):
    return str(tag or "").strip().lstrip("#")


def list_tags():
    """Every tag in use or defined, with its count, group and colour."""
    d = db()
    counts = {r["tag"]: r["n"] for r in d.execute(
        "SELECT tag, COUNT(*) n FROM tags GROUP BY tag")}
    defs = {r["tag"]: r for r in d.execute("SELECT * FROM tag_defs")}
    names = set(counts) | set(defs)
    out = []
    for name in sorted(names, key=lambda n: (-counts.get(n, 0), n)):
        definition = defs.get(name)
        out.append({"tag": name, "count": counts.get(name, 0),
                    "group": definition["grp"] if definition else "",
                    "color": definition["color"] if definition else ""})
    return out


def define(tag, group=None, color=None):
    tag = clean(tag)
    if not tag:
        return
    d = db()
    row = d.execute("SELECT * FROM tag_defs WHERE tag=?", (tag,)).fetchone()
    if row:
        d.execute("UPDATE tag_defs SET grp=COALESCE(?, grp), color=COALESCE(?, color) WHERE tag=?",
                  (group, color, tag))
    else:
        d.execute("INSERT INTO tag_defs VALUES (?,?,?,?)",
                  (tag, group or "", color or "", time.time()))
    d.commit()


def rename(old, new):
    old, new = clean(old), clean(new)
    if not old or not new or old == new:
        return 0
    d = db()
    moved = d.execute("SELECT COUNT(*) FROM tags WHERE tag=?", (old,)).fetchone()[0]
    # a path that already carries the new name keeps one row, not two
    d.execute("UPDATE OR IGNORE tags SET tag=? WHERE tag=?", (new, old))
    d.execute("DELETE FROM tags WHERE tag=?", (old,))
    definition = d.execute("SELECT * FROM tag_defs WHERE tag=?", (old,)).fetchone()
    if definition and not d.execute("SELECT 1 FROM tag_defs WHERE tag=?", (new,)).fetchone():
        d.execute("UPDATE tag_defs SET tag=? WHERE tag=?", (new, old))
    else:
        d.execute("DELETE FROM tag_defs WHERE tag=?", (old,))
    d.commit()
    return moved


def merge(sources, target):
    total = 0
    for source in sources:
        total += rename(source, target)
    return total


def delete(tag):
    tag = clean(tag)
    d = db()
    removed = d.execute("DELETE FROM tags WHERE tag=?", (tag,)).rowcount
    d.execute("DELETE FROM tag_defs WHERE tag=?", (tag,))
    d.commit()
    return removed


def tags_of(paths):
    out = {p: [] for p in paths}
    if not paths:
        return out
    d = db()
    for start in range(0, len(paths), 500):
        chunk = paths[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for r in d.execute(f"SELECT path, tag FROM tags WHERE path IN ({marks}) "
                           f"ORDER BY tag", chunk):
            out[r["path"]].append(r["tag"])
    return out
