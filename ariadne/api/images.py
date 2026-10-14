"""The image index API used by the new frontend: paged listing, scanning,
ratings, collections and tag definitions."""

import json
import os
import time

from flask import Blueprint, Response, jsonify, request

from ariadne.safety import guard, is_path_allowed
from ariadne.services import collections as collections_svc
from ariadne.services import index
from ariadne.services import ratings as ratings_svc
from ariadne.services import tags as tags_svc

bp = Blueprint("images", __name__)


BIG = 2 ** 62        # SQLite integers end at 2**63; anything near it is a typo


def _int(value, default=None):
    try:
        out = int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default
    return max(-BIG, min(BIG, out)) if isinstance(out, int) else out


def _text(value):
    return value if isinstance(value, str) else ""


def _strings(value):
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def _bool(value):
    if value in (None, ""):
        return None
    return str(value).lower() in ("1", "true", "yes", "on")


def _allowed_paths(paths):
    return [p for p in _strings(paths) if is_path_allowed(p)]


# --------------------------------------------------------------------------
# listing and scanning
# --------------------------------------------------------------------------

@bp.route("/api/images")
def list_images():
    folder = request.args.get("folder") or None
    if folder and not os.path.isdir(folder):
        return jsonify({"success": False, "error": "Folder not found."}), 404
    if folder and not is_path_allowed(folder):
        return jsonify({"success": False, "error": "That folder has not been added."}), 403
    page = index.query_images(
        folder=folder,
        q=request.args.get("q", ""),
        sort=request.args.get("sort", "date_desc"),
        offset=_int(request.args.get("offset"), 0),
        limit=max(1, min(1000, _int(request.args.get("limit"), 200))),
        stars_min=_int(request.args.get("stars_min")),
        stars_max=_int(request.args.get("stars_max")),
        rejected=_bool(request.args.get("rejected")),
        kind=request.args.get("kind") or None,
        tag=request.args.get("tag") or None,
        collection=request.args.get("collection") or None,
        recursive=bool(_bool(request.args.get("recursive"))),
    )
    page["success"] = True
    return jsonify(page)


@bp.route("/api/images/one")
def one_image():
    path = request.args.get("path")
    if not guard(path):
        return jsonify({"success": False, "error": "File not found."}), 404
    row = index.get_image(path)
    if row is None:
        index.scan_folder(os.path.dirname(path))
        index.enrich_one(path)
        row = index.get_image(path)
    elif not row["indexed"]:
        index.enrich_one(path)
        row = index.get_image(path)
    return jsonify({"success": True, "image": row})


@bp.route("/api/images/scan", methods=["POST"])
def scan():
    """Scan a folder now (pass 1) and hand the file reads to the background
    indexer. ``wait=1`` enriches everything before answering (small folders,
    tests)."""
    body = request.json or {}
    folder = _text(body.get("folder"))
    if not folder or not os.path.isdir(folder):
        return jsonify({"success": False, "error": "Folder not found."}), 404
    if not is_path_allowed(folder):
        return jsonify({"success": False, "error": "That folder has not been added."}), 403
    recursive = bool(body.get("recursive"))
    if body.get("wait"):
        result = index.index_folder(folder, recursive=recursive)
    else:
        result = index.scan_folder(folder, recursive)
        index.indexer.request(folder, recursive)
    result["success"] = "error" not in result
    result["summary"] = index.folder_summary(folder, recursive)
    return jsonify(result)


@bp.route("/api/images/scan/progress")
def scan_progress():
    """Server-sent events while the indexer works, one per second, ending when
    nothing is pending any more."""
    folder = request.args.get("folder") or None

    def generate():
        quiet = 0
        while True:
            status = dict(index.indexer.status)
            status["pending"] = index.pending_count(folder) if folder else index.pending_count()
            status["type"] = "progress"
            yield f"data: {json.dumps(status)}\n\n"
            if not status["busy"] and status["pending"] == 0:
                quiet += 1
                if quiet >= 2:
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return
            else:
                quiet = 0
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/api/images/summary")
def summary():
    folder = request.args.get("folder") or ""
    if not folder or not is_path_allowed(folder):
        return jsonify({"success": False, "error": "That folder has not been added."}), 403
    return jsonify({"success": True,
                    **index.folder_summary(folder, bool(_bool(request.args.get("recursive"))))})


@bp.route("/api/duplicates")
def duplicates():
    from ariadne.services import duplicates as dupes
    folder = request.args.get("folder") or None
    if folder and not is_path_allowed(folder):
        return jsonify({"success": False, "error": "That folder has not been added."}), 403
    level = request.args.get("level") or "similar"
    try:
        out = dupes.find_groups(folder, level, bool(_bool(request.args.get("recursive"))))
    except dupes.TooMany as exc:
        # still a usable answer: the screen keeps its level picker and says why
        out = {"level": dupes.level(level), "groups": [], "total": 0, "error": str(exc)}
    out["success"] = True
    out["levels"] = dupes.LEVELS
    return jsonify(out)


@bp.route("/api/prompts")
def prompts():
    from ariadne.services import duplicates as dupes
    folder = request.args.get("folder") or ""
    if not folder or not is_path_allowed(folder):
        return jsonify({"success": False, "error": "That folder has not been added."}), 403
    return jsonify({"success": True, "prompts": dupes.unique_prompts(
        folder, bool(_bool(request.args.get("recursive"))))})


@bp.route("/api/images/facets")
def facets():
    """Distinct values of one metadata field, for the search helper."""
    field = request.args.get("field") or "model"
    q = (request.args.get("q") or "").strip()[:200]      # a LIKE pattern has a size limit
    limit = max(1, min(50, _int(request.args.get("limit"), 20)))
    return jsonify({"success": True, "field": field, "values": index.facets(field, q, limit)})


@bp.route("/api/images/summaries", methods=["POST"])
def summaries():
    """Counts for many folders in one call, for the sidebar. ``recursive``
    names the folders whose subfolders count too."""
    body = request.json or {}
    folders = [f for f in _strings(body.get("folders")) if is_path_allowed(f)]
    recursive = _strings(body.get("recursive"))
    return jsonify({"success": True, "summaries": index.folder_summaries(folders, recursive)})


# --------------------------------------------------------------------------
# ratings
# --------------------------------------------------------------------------

@bp.route("/api/ratings", methods=["POST"])
def set_ratings():
    body = request.json or {}
    paths = _allowed_paths(body.get("paths"))
    if not paths:
        return jsonify({"success": False, "error": "No images."}), 400
    try:
        if "stars" in body:
            ratings_svc.set_stars(paths, body["stars"])
        if "rejected" in body:
            ratings_svc.set_rejected(paths, body["rejected"])
        if "label" in body:
            ratings_svc.set_label(paths, _text(body["label"]))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Stars must be a number from 0 to 5."}), 400
    return jsonify({"success": True, "ratings": ratings_svc.get_many(paths)})


# --------------------------------------------------------------------------
# tags: definitions, rename, merge
# --------------------------------------------------------------------------

@bp.route("/api/tags/list")
def list_tags():
    return jsonify({"success": True, "tags": tags_svc.list_tags()})


@bp.route("/api/tags/define", methods=["POST"])
def define_tag():
    body = request.json or {}
    tags_svc.define(body.get("tag"), body.get("group"), body.get("color"))
    return jsonify({"success": True})


@bp.route("/api/tags/rename", methods=["POST"])
def rename_tag():
    body = request.json or {}
    moved = tags_svc.rename(body.get("old"), body.get("new"))
    return jsonify({"success": True, "moved": moved})


@bp.route("/api/tags/merge", methods=["POST"])
def merge_tags():
    body = request.json or {}
    moved = tags_svc.merge(body.get("sources") or [], body.get("target"))
    return jsonify({"success": True, "moved": moved})


@bp.route("/api/tags/delete", methods=["POST"])
def delete_tag():
    removed = tags_svc.delete((request.json or {}).get("tag"))
    return jsonify({"success": True, "removed": removed})


# --------------------------------------------------------------------------
# collections
# --------------------------------------------------------------------------

@bp.route("/api/collections")
def list_collections():
    return jsonify({"success": True, "collections": collections_svc.list_collections()})


@bp.route("/api/collections", methods=["POST"])
def create_collection():
    body = request.json or {}
    try:
        cid = collections_svc.create_collection(
            _text(body.get("name")), body.get("kind", "manual"), _text(body.get("query")),
            _text(body.get("icon")), _text(body.get("color")))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if body.get("paths"):
        collections_svc.add_items(cid, _allowed_paths(body["paths"]))
    return jsonify({"success": True, "id": cid,
                    "collection": collections_svc.get_collection(cid)})


@bp.route("/api/collections/<cid>", methods=["PATCH"])
def update_collection(cid):
    body = request.json or {}
    given = {k: body.get(k) for k in ("name", "query", "icon", "color")}
    order = body.get("sort_order")
    ok = collections_svc.update_collection(
        cid, **{k: (v if isinstance(v, str) else None) for k, v in given.items()},
        sort_order=order if isinstance(order, int) and not isinstance(order, bool) else None)
    return jsonify({"success": ok, "collection": collections_svc.get_collection(cid)})


@bp.route("/api/collections/<cid>", methods=["DELETE"])
def delete_collection(cid):
    collections_svc.delete_collection(cid)
    return jsonify({"success": True})


@bp.route("/api/collections/<cid>/items", methods=["POST"])
def add_to_collection(cid):
    body = request.json or {}
    if not collections_svc.get_collection(cid):
        return jsonify({"success": False, "error": "No such collection."}), 404
    paths = _allowed_paths(body.get("paths"))
    if body.get("remove"):
        collections_svc.remove_items(cid, paths)
        return jsonify({"success": True, "removed": len(paths)})
    if body.get("order"):
        collections_svc.reorder(cid, paths)
        return jsonify({"success": True})
    added = collections_svc.add_items(cid, paths)
    return jsonify({"success": True, "added": added})
