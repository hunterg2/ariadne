"""Projects (separate libraries) and the portable library export/import."""

import hashlib
import io
import json
import os
import shutil
import time

from flask import Blueprint, jsonify, request, send_file

from ariadne import config, store
from ariadne.db import backup_db, db
from ariadne.services.library import library_payload

bp = Blueprint("projects", __name__)


def _text(value):
    return value.strip() if isinstance(value, str) else ""


@bp.route("/api/projects")
def list_projects():
    data = store.load_projects()
    out = []
    for p in data["projects"]:
        d = config.project_dir(p["id"])
        db_path = d / "organizer.db"
        out.append({**p, "active": p["id"] == data["active"],
                    "size": db_path.stat().st_size if db_path.exists() else 0,
                    "folder": str(d)})
    return jsonify({"active": data["active"], "projects": out})


@bp.route("/api/projects/create", methods=["POST"])
def create_project():
    name = _text((request.json or {}).get("name"))
    if not name:
        return jsonify({"success": False, "error": "Give the project a name."}), 400
    data = store.load_projects()
    pid = "p_" + hashlib.sha1(f"{name}{time.time()}".encode()).hexdigest()[:10]
    data["projects"].append({"id": pid, "name": name, "created": time.time()})
    if (request.json or {}).get("switch", True):
        data["active"] = pid
    store.save_projects(data)
    store.use_project(data["active"])
    return jsonify({"success": True, "id": pid, "active": data["active"]})


@bp.route("/api/projects/switch", methods=["POST"])
def switch_project():
    pid = (request.json or {}).get("id")
    data = store.load_projects()
    if not any(p["id"] == pid for p in data["projects"]):
        return jsonify({"success": False, "error": "No such project."}), 404
    data["active"] = pid
    store.save_projects(data)
    store.use_project(pid)
    return jsonify({"success": True, "active": pid})


@bp.route("/api/projects/rename", methods=["POST"])
def rename_project():
    body = request.json or {}
    name = _text(body.get("name"))
    if not name:
        return jsonify({"success": False, "error": "Give the project a name."}), 400
    data = store.load_projects()
    for p in data["projects"]:
        if p["id"] == body.get("id"):
            p["name"] = name
    store.save_projects(data)
    return jsonify({"success": True, "projects": data["projects"]})


@bp.route("/api/projects/delete", methods=["POST"])
def delete_project():
    pid = (request.json or {}).get("id")
    data = store.load_projects()
    if pid == "default":
        return jsonify({"success": False,
                        "error": "The main library cannot be deleted."}), 400
    if len(data["projects"]) < 2:
        return jsonify({"success": False, "error": "That is your only project."}), 400

    data["projects"] = [p for p in data["projects"] if p["id"] != pid]
    if data["active"] == pid:
        data["active"] = data["projects"][0]["id"]
    store.save_projects(data)
    # switch away first: use_project is what closes the database handles
    # and stops the indexer, and Windows will not delete an open file
    store.use_project(data["active"])
    # only the library is removed; the image folders it pointed at are untouched
    folder = config.project_dir(pid)
    for _attempt in range(5):
        try:
            shutil.rmtree(folder)
            break
        except FileNotFoundError:
            break
        except OSError:
            time.sleep(0.2)          # a request that still had the old file is finishing
    else:
        shutil.rmtree(folder, ignore_errors=True)
    return jsonify({"success": True, "active": data["active"]})


@bp.route("/api/library/export")
def export_library():
    payload = library_payload()
    buf = io.BytesIO(json.dumps(payload, indent=1).encode("utf-8"))
    return send_file(buf, mimetype="application/json", as_attachment=True,
                     download_name=f"organizer-library-{time.strftime('%Y%m%d')}.json")


@bp.route("/api/library/stats")
def library_stats():
    payload = library_payload()
    backup_dir = config.paths.backup_dir
    backups = sorted(backup_dir.glob("organizer-*.db")) if backup_dir.exists() else []
    return jsonify({"counts": payload["counts"],
                    "backups": len(backups),
                    "latest_backup": backups[-1].name if backups else ""})


@bp.route("/api/library/import", methods=["POST"])
def import_library():
    """Restore ratings and tags from an export. Files are never touched, only
    the library rows that point at them."""
    body = request.json or {}
    payload = body.get("data") if isinstance(body.get("data"), dict) else {}
    mode = body.get("mode", "merge")

    fmt = payload.get("format")
    if fmt not in ("ariadne-library", "image-organizer-library"):
        return jsonify({"success": False,
                        "error": "That does not look like a library export."}), 400

    tags = payload.get("tags") or {}
    ratings = payload.get("ratings") or {}
    if fmt == "image-organizer-library":
        # the previous build exported liked / loved categories
        categories = payload.get("categories") if isinstance(payload.get("categories"), dict) else {}
        ratings = {p: {"stars": {"liked": 3, "loved": 5}[c]}
                   for p, c in categories.items()
                   if isinstance(p, str) and c in ("liked", "loved")}
    if not isinstance(ratings, dict) or not isinstance(tags, dict):
        return jsonify({"success": False, "error": "The export is malformed."}), 400

    # Read the whole file first, skipping entries that make no sense, and
    # only then write, in one transaction. A bad entry half-way through used
    # to leave "replace" with its deletes done and its inserts not.
    rows, links = [], []
    now = time.time()
    for path, r in ratings.items():
        if not isinstance(path, str) or not isinstance(r, dict):
            continue
        try:
            stars = max(0, min(5, int(r.get("stars") or 0)))
        except (TypeError, ValueError, OverflowError):
            continue
        label = r.get("label") if isinstance(r.get("label"), str) and r.get("label") else None
        rows.append((path, stars, 1 if r.get("rejected") else 0, label, now))
    for path, names in tags.items():
        if not isinstance(path, str) or not isinstance(names, list):
            continue
        for tag in names:
            if isinstance(tag, (str, int, float)) and not isinstance(tag, bool):
                tag = str(tag).strip().lstrip("#")
                if tag:
                    links.append((path, tag))

    if mode == "replace" and not rows and not links:
        return jsonify({"success": False,
                        "error": "That export holds no ratings or tags; nothing was replaced."}), 400

    backup_db()          # before touching anything
    d = db()
    try:
        if mode == "replace":
            d.execute("DELETE FROM ratings")
            d.execute("DELETE FROM tags")
        d.executemany("INSERT OR REPLACE INTO ratings (path, stars, rejected, label, updated) "
                      "VALUES (?,?,?,?,?)", rows)
        d.executemany("INSERT OR REPLACE INTO tags VALUES (?,?)", links)
        d.commit()
    except Exception:
        d.rollback()
        raise

    missing = sum(1 for p in {r[0] for r in rows} | {t[0] for t in links} if not os.path.exists(p))
    return jsonify({"success": True, "ratings": len(rows), "tag_links": len(links),
                    "missing_files": missing})
