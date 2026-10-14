"""Folders, the sidebar, and the images in them."""

import os
import platform
import subprocess

from flask import Blueprint, jsonify, request, send_file
from PIL import Image

from ariadne import config, store
from ariadne.db import db
from ariadne.safety import guard, same_path, under
from ariadne.services import index, sidebar
from ariadne.services.thumbs import build_thumb

bp = Blueprint("library", __name__)


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def thumb_quality():
    """``settings.thumb_quality`` inside WebP's 1..100, the default for
    anything that is not a number."""
    try:
        return max(1, min(100, int(store.load_settings().get("thumb_quality", config.THUMB_QUALITY))))
    except (TypeError, ValueError):
        return config.THUMB_QUALITY


# --------------------------------------------------------------------------
# sidebar history
# --------------------------------------------------------------------------

@bp.route("/api/history", methods=["GET", "POST"])
def handle_history():
    history = store.load_history()
    settings = store.load_settings()
    dirty = False

    if request.method == "POST":
        data = request.json or {}
        folders = [f for f in (data.get("folders") if isinstance(data.get("folders"), list) else [])
                   if isinstance(f, str)]
        if isinstance(data.get("folder"), str) and data["folder"]:
            folders.append(data["folder"])
        for new_folder in folders:
            if not new_folder.strip():
                continue
            # "x\" and "x\." are x; the index spells its rows like the list
            new_folder = os.path.normpath(new_folder)
            if (os.path.isabs(new_folder) and os.path.isdir(new_folder)
                    and not sidebar.folder_exists(history, new_folder)):
                history.insert(0, {
                    "type": "folder", "path": new_folder, "alias": "", "status": "",
                })
                dirty = True
                index.indexer.request(new_folder)

    history, changed = sidebar.update_auto_groups(history, settings)
    if dirty or changed:
        store.save_history(history)
    return jsonify({"success": True, "history": history})


def _spelled_as_before(history, previous):
    """A folder already in the list keeps its spelling: the index spells its
    rows like the list, and a sync is not where a folder is renamed (the
    repath route is, and it respells the rows)."""
    known = {}

    def collect(items):
        for it in items:
            if it.get("type") == "folder":
                known[os.path.normcase(it["path"])] = it["path"]
            elif it.get("type") == "group":
                collect(it.get("items", []))

    def apply(items):
        for it in items:
            if it.get("type") == "folder":
                it["path"] = known.get(os.path.normcase(it["path"]), it["path"])
            elif it.get("type") == "group":
                apply(it.get("items", []))

    collect(previous)
    apply(history)
    return history


@bp.route("/api/history/sync", methods=["POST"])
def sync_history():
    history = (request.json or {}).get("history", [])
    if not isinstance(history, list):
        return jsonify({"success": False, "error": "The sidebar list must be a list."}), 400
    # entries that are not folders or groups are dropped, so is a second
    # spelling of a folder, and a folder already listed keeps its spelling
    history = _spelled_as_before(store.clean_history(history), store.load_history())
    store.save_history(history)
    return jsonify({"success": True, "history": history})


@bp.route("/api/history/update", methods=["POST"])
def update_history():
    data = request.json or {}
    history = store.load_history()
    found = sidebar.find_and_update(history, data.get("path"), data.get("action"), data.get("value"))
    history, _ = sidebar.update_auto_groups(history, store.load_settings())
    store.save_history(history)
    if found and data.get("action") == "recursive" and data.get("value"):
        # the subfolders have never been listed: do that in the background
        # now. Only for a folder in the list: an indexed file is a readable
        # file (safety.is_path_allowed trusts the index), so this must not
        # index whatever path it is handed.
        index.indexer.request(data["path"], recursive=True)
    return jsonify({"success": True, "history": history})


@bp.route("/api/history/check")
def check_history():
    """Which saved folders can still be opened, plus what the sidebar needs to
    sort by. Called after the sidebar has drawn, so a dead network path cannot
    stall the first paint. Counting files is opt-in because it means listing
    every folder, which is not free on a big library."""
    want_counts = request.args.get("counts") == "1"
    status = {}

    def walk(items):
        for it in items:
            if it.get("type") == "folder" and it.get("path"):
                path = it["path"]
                entry = {"ok": False, "mtime": 0, "count": None}
                try:
                    st = os.stat(path)
                    entry["ok"] = os.path.isdir(path)
                    entry["mtime"] = st.st_mtime
                except OSError:
                    pass
                if want_counts and entry["ok"]:
                    try:
                        entry["count"] = sum(
                            1 for e in os.scandir(path)
                            if e.is_file()
                            and os.path.splitext(e.name)[1].lower() in config.VALID_EXTS)
                    except OSError:
                        entry["count"] = None
                status[path] = entry
            elif it.get("type") == "group":
                walk(it.get("items", []))

    walk(store.load_history())
    return jsonify({"status": status})


@bp.route("/api/history/repath", methods=["POST"])
def repath_folder():
    """Point a saved folder at its new location and carry every rating, tag and
    trash record across with it."""
    data = request.json or {}
    old = _text(data.get("old"))
    new = _text(data.get("new"))

    if not old or not new:
        return jsonify({"success": False, "error": "Give both the old and the new path."}), 400
    new = os.path.normpath(new)      # typed by hand, "x\..\pics" would otherwise be stored as such
    if not os.path.isdir(new):
        return jsonify({"success": False,
                        "error": "That folder does not exist. Check the path and try again."}), 400

    history = store.load_history()
    hit = [False]

    def walk(items):
        for it in items:
            if it.get("type") == "folder" and it.get("path") and same_path(it["path"], old):
                it["path"] = new
                hit[0] = True
            elif it.get("type") == "group":
                walk(it.get("items", []))

    walk(history)
    if not hit[0]:
        return jsonify({"success": False, "error": "That folder is no longer in the list."}), 404
    store.save_history(history)

    d = db()
    moved = 0
    for table in ("tags", "meta", "ratings", "collection_items"):
        for row in d.execute(f"SELECT path FROM {table}").fetchall():
            p = row["path"]
            if not under(p, old):
                continue
            new_p = os.path.join(new, os.path.relpath(p, old)) if not same_path(p, old) else new
            d.execute(f"UPDATE OR REPLACE {table} SET path=? WHERE path=?", (new_p, p))
            moved += 1

    for row in d.execute("SELECT id, original_path, trash_path FROM trash").fetchall():
        orig, trash_p = row["original_path"], row["trash_path"]
        changes = {}
        if orig and under(orig, old):
            changes["original_path"] = os.path.join(new, os.path.relpath(orig, old))
        if trash_p and under(trash_p, old):
            changes["trash_path"] = os.path.join(new, os.path.relpath(trash_p, old))
        if changes:
            sets = ", ".join(f"{k}=?" for k in changes)
            d.execute(f"UPDATE trash SET {sets} WHERE id=?", (*changes.values(), row["id"]))
            moved += 1

    # the index is rebuilt from disk for the new location
    d.execute("DELETE FROM images WHERE folder=? OR folder LIKE ?",
              (os.path.normpath(old), os.path.normpath(old) + os.sep + "%"))
    d.commit()
    config.bump_roots()
    index.indexer.request(new)
    return jsonify({"success": True, "history": history, "moved": moved, "path": new})


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

@bp.route("/api/images/check")
def check_folder():
    folder = request.args.get("folder")
    if not folder or not os.path.isdir(folder):
        return jsonify({"success": False, "error": "Folder not found or cannot be opened."})
    return jsonify({"success": True})


def _image_type(path):
    """The type to serve a library file as, or None for anything that is
    not one of the image formats the index takes. A folder in the list can
    hold an .html or .svg as well, and served from this origin that would
    be a page with the app's rights, able to call every route."""
    return config.IMAGE_TYPES.get(os.path.splitext(path or "")[1].lower())


@bp.route("/thumb")
def serve_thumb():
    path = request.args.get("path")
    mimetype = _image_type(path)
    if not mimetype or not guard(path) or not os.path.isfile(path):
        return "Not found", 404
    dest = build_thumb(path, thumb_quality())
    if dest and dest.exists():
        return send_file(dest, mimetype="image/webp", max_age=31536000)
    return send_file(path, mimetype=mimetype, max_age=3600)  # fall back to the original


@bp.route("/image")
def serve_image():
    path = request.args.get("path")
    mimetype = _image_type(path)
    if not mimetype or not guard(path) or not os.path.isfile(path):
        return "Not found", 404
    return send_file(path, mimetype=mimetype, max_age=3600, conditional=True)


@bp.route("/api/prompt")
def get_prompt():
    path = request.args.get("path")
    if not guard(path):
        return jsonify({"raw_workflow": "{}"})
    try:
        with Image.open(path) as img:
            info = img.info or {}
            raw = info.get("workflow") or info.get("prompt") or info.get("parameters") or "{}"
            return jsonify({"raw_workflow": raw})
    except (OSError, ValueError, Image.DecompressionBombError):
        return jsonify({"raw_workflow": "{}"})


@bp.route("/api/reveal", methods=["POST"])
def reveal_file():
    path = (request.json or {}).get("path")
    if not guard(path):
        return jsonify({"success": False, "error": "File not found"})
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
        return jsonify({"success": True})
    except OSError as exc:
        return jsonify({"success": False, "error": str(exc)})
