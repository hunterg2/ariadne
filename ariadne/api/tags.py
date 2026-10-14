"""Tags, ratings (as "actions"), AI tag suggestions and the trash."""

import json
import os
import shutil
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

from ariadne import store, tagger
from ariadne.db import db
from ariadne.log import log
from ariadne.safety import guard, is_path_allowed
from ariadne.services import files, index
from ariadne.services import ratings as ratings_svc
from ariadne.services.meta_cache import get_metadata

try:
    import send2trash  # optional: real recycle bin for hard deletes
except ImportError:
    send2trash = None

bp = Blueprint("tags", __name__)


def _names(value):
    """Tag names from the request: text (or a number), trimmed, no '#'."""
    if not isinstance(value, list):
        return []
    out = []
    for t in value:
        if isinstance(t, (str, int, float)) and not isinstance(t, bool) and str(t).strip():
            out.append(str(t).strip().lstrip("#"))
    return out


def _ids(value):
    """Trash row ids from the request: whole numbers only."""
    out = []
    for v in (value if isinstance(value, list) else []):
        if isinstance(v, bool):
            continue
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


@bp.route("/api/tags", methods=["POST"])
def update_tags():
    data = request.json or {}
    # library files only: a tag row makes its path readable
    # (safety.is_path_allowed), so an outside path must not get one here
    given = data.get("paths") if isinstance(data.get("paths"), list) else []
    paths = [p for p in given if isinstance(p, str) and is_path_allowed(p)]
    tags = _names(data.get("tags"))
    add_tags = _names(data.get("add_tags"))
    remove_tags = _names(data.get("remove_tags"))

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


@bp.route("/api/tag/check", methods=["POST"])
def check_tagger():
    given = (request.json or {}).get("tagger")
    ok, message = tagger.check(given if isinstance(given, dict) and given
                               else store.load_settings().get("tagger") or {})
    return jsonify({"ok": ok, "message": message})


@bp.route("/api/tag/auto")
def auto_tag():
    """Propose tags for a set of images, one event per image so the screen can
    fill in as it goes. Nothing is written here; the review decides."""
    paths = [p for p in request.args.getlist("path") if guard(p)]
    settings = store.load_settings()
    # the backend, its URL and its key come from the settings alone: a GET
    # that could name the URL would send the stored key wherever it said
    cfg = dict(settings.get("tagger") or {})
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


@bp.route("/api/tags/all")
def all_tags():
    rows = db().execute(
        "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY n DESC, tag ASC"
    ).fetchall()
    return jsonify({"tags": [{"tag": r["tag"], "count": r["n"]} for r in rows]})


# --------------------------------------------------------------------------
# ratings and trash
# --------------------------------------------------------------------------

@bp.route("/api/action", methods=["POST"])
def handle_action():
    data = request.json or {}
    given = data.get("paths") if isinstance(data.get("paths"), list) else []
    # files only: a folder handed in here would be moved whole into trash/
    paths = [p for p in given if isinstance(p, str) and os.path.isfile(p) and is_path_allowed(p)]
    action = data.get("action")

    d = db()
    settings = store.load_settings()
    delete_mode = settings.get("delete_mode", "soft")
    trashed = []

    if action != "trash":
        return jsonify({"success": False, "error": "Ratings go through /api/ratings."}), 400

    for img_path in paths:
            if not os.path.exists(img_path):
                continue
            stars = ratings_svc.get_one(img_path)["stars"]
            tags = [r["tag"] for r in d.execute("SELECT tag FROM tags WHERE path=?", (img_path,))]

            if delete_mode == "soft":
                trash_dir = os.path.join(os.path.dirname(img_path), "trash")
                os.makedirs(trash_dir, exist_ok=True)
                dest = files.unique_dest(trash_dir, os.path.basename(img_path))
                try:
                    shutil.move(img_path, dest)
                except OSError as exc:
                    log.warning(f"[trash] {img_path}: {exc}")
                    continue
                cur = d.execute(
                    "INSERT INTO trash (original_path, trash_path, deleted_at, stars, tags, restorable) "
                    "VALUES (?,?,?,?,?,1)",
                    (img_path, dest, time.time(), stars, json.dumps(tags)),
                )
                trashed.append({"id": cur.lastrowid, "path": img_path})
            else:
                try:
                    if send2trash is not None:
                        send2trash.send2trash(os.path.normpath(img_path))
                    else:
                        os.remove(img_path)
                except OSError as exc:
                    log.warning(f"[trash] {img_path}: {exc}")
                    continue
                d.execute(
                    "INSERT INTO trash (original_path, trash_path, deleted_at, stars, tags, restorable) "
                    "VALUES (?,?,?,?,?,0)",
                    (img_path, "", time.time(), stars, json.dumps(tags)),
                )
            files.forget(d, img_path)
            ratings_svc.forget(img_path)
            index.forget_path(img_path)

    d.commit()
    return jsonify({"success": True, "trashed": trashed})


@bp.route("/api/trash")
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
            "stars": _trash_stars(r),
            "tags": json.loads(r["tags"] or "[]"),
        })
    return jsonify({"items": items})


@bp.route("/api/trash/restore", methods=["POST"])
def restore_trash():
    ids = _ids((request.json or {}).get("ids"))
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
        dest = original if not os.path.exists(original) else files.unique_dest(
            os.path.dirname(original), os.path.basename(original)
        )
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
        except OSError as exc:
            log.warning(f"[restore] {src}: {exc}")
            continue

        for t in json.loads(r["tags"] or "[]"):
            d.execute("INSERT OR REPLACE INTO tags VALUES (?,?)", (dest, t))
        d.execute("DELETE FROM trash WHERE id=?", (r["id"],))
        restored.append({"id": r["id"], "path": dest, "stars": _trash_stars(r)})

    d.commit()
    for item in restored:
        if item["stars"]:
            ratings_svc.set_stars([item["path"]], item["stars"])
        index.scan_folder(os.path.dirname(item["path"]))
    return jsonify({"success": True, "restored": restored})


def _trash_stars(row):
    """Rows trashed by the old build carry a category instead of stars."""
    keys = row.keys()
    if "stars" in keys and row["stars"]:
        return row["stars"]
    if "category" in keys:
        return {"liked": 3, "loved": 5}.get(row["category"] or "", 0)
    return 0


@bp.route("/api/trash/purge", methods=["POST"])
def purge_trash():
    data = request.json or {}
    d = db()
    if data.get("all"):
        rows = d.execute("SELECT * FROM trash WHERE restorable=1").fetchall()
    else:
        ids = _ids(data.get("ids"))
        if not ids:
            return jsonify({"success": True})
        placeholders = ",".join("?" * len(ids))
        rows = d.execute(f"SELECT * FROM trash WHERE id IN ({placeholders})", ids).fetchall()

    for r in rows:
        try:
            if r["trash_path"] and os.path.exists(r["trash_path"]):
                os.remove(r["trash_path"])
        except OSError as exc:
            log.warning(f"[purge] {r['trash_path']}: {exc}")
        d.execute("DELETE FROM trash WHERE id=?", (r["id"],))
    d.commit()
    return jsonify({"success": True, "purged": len(rows)})
