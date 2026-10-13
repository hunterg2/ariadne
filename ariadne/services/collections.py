"""Collections: manual ones hold an ordered list of paths, smart ones hold a
query and are evaluated by the image index when opened."""

import time
import uuid

from ariadne.db import db


def _row(r, count=None):
    out = {"id": r["id"], "name": r["name"], "kind": r["kind"], "query": r["query"] or "",
           "icon": r["icon"] or "", "color": r["color"] or "",
           "sort_order": r["sort_order"] or 0, "created": r["created"], "updated": r["updated"]}
    if count is not None:
        out["count"] = count
    return out


def list_collections():
    d = db()
    counts = {r["collection_id"]: r["n"] for r in d.execute(
        "SELECT collection_id, COUNT(*) n FROM collection_items GROUP BY collection_id")}
    return [_row(r, counts.get(r["id"], 0) if r["kind"] == "manual" else None)
            for r in d.execute("SELECT * FROM collections ORDER BY sort_order, name")]


def get_collection(cid):
    r = db().execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
    return _row(r) if r else None


def create_collection(name, kind="manual", query="", icon="", color=""):
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the collection a name.")
    if kind not in ("manual", "smart"):
        raise ValueError("kind must be manual or smart.")
    d = db()
    cid = "c_" + uuid.uuid4().hex[:10]
    order = d.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM collections").fetchone()[0]
    now = time.time()
    d.execute("INSERT INTO collections (id, name, kind, query, icon, color, sort_order, "
              "created, updated) VALUES (?,?,?,?,?,?,?,?,?)",
              (cid, name, kind, query or "", icon or "", color or "", order, now, now))
    d.commit()
    return cid


def update_collection(cid, **fields):
    allowed = {"name", "query", "icon", "color", "sort_order"}
    sets, args = [], []
    for key, value in fields.items():
        if key in allowed and value is not None:
            sets.append(f"{key}=?")
            args.append(value)
    if not sets:
        return False
    sets.append("updated=?")
    args.append(time.time())
    args.append(cid)
    d = db()
    cur = d.execute(f"UPDATE collections SET {', '.join(sets)} WHERE id=?", args)
    d.commit()
    return cur.rowcount > 0


def delete_collection(cid):
    d = db()
    d.execute("DELETE FROM collection_items WHERE collection_id=?", (cid,))
    d.execute("DELETE FROM collections WHERE id=?", (cid,))
    d.commit()


def add_items(cid, paths):
    d = db()
    start = d.execute("SELECT COALESCE(MAX(position), 0) FROM collection_items "
                      "WHERE collection_id=?", (cid,)).fetchone()[0]
    now = time.time()
    added = 0
    for i, path in enumerate(paths, 1):
        cur = d.execute("INSERT OR IGNORE INTO collection_items VALUES (?,?,?,?)",
                        (cid, path, start + i, now))
        added += cur.rowcount
    d.execute("UPDATE collections SET updated=? WHERE id=?", (now, cid))
    d.commit()
    return added


def remove_items(cid, paths):
    d = db()
    d.executemany("DELETE FROM collection_items WHERE collection_id=? AND path=?",
                  [(cid, p) for p in paths])
    d.commit()


def reorder(cid, paths):
    d = db()
    for i, path in enumerate(paths):
        d.execute("UPDATE collection_items SET position=? WHERE collection_id=? AND path=?",
                  (i, cid, path))
    d.commit()


def collections_of(paths):
    """{path: [collection ids]} for a page of images."""
    out = {p: [] for p in paths}
    if not paths:
        return out
    d = db()
    for start in range(0, len(paths), 500):
        chunk = paths[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for r in d.execute(f"SELECT collection_id, path FROM collection_items "
                           f"WHERE path IN ({marks})", chunk):
            out[r["path"]].append(r["collection_id"])
    return out


def move(old_path, new_path):
    db().execute("UPDATE OR REPLACE collection_items SET path=? WHERE path=?",
                 (new_path, old_path))
