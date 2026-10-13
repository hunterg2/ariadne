"""Copy, move, zip and the editor's save."""

import io
import json
import os
import shutil
import time
import zipfile

from flask import Blueprint, jsonify, request, send_file
from PIL import Image

from ariadne import metadata, store
from ariadne.db import db
from ariadne.safety import guard
from ariadne.services import collections as collections_svc
from ariadne.services import files, index
from ariadne.services import ratings as ratings_svc

bp = Blueprint("export", __name__)


@bp.route("/api/export", methods=["POST"])
def export_files():
    """mode = copy | move"""
    data = request.json or {}
    paths = [p for p in data.get("paths", []) if guard(p)]
    dest_dir = data.get("dest")
    mode = data.get("mode", "copy")

    if not dest_dir or not os.path.isdir(dest_dir):
        return jsonify({"success": False, "error": "Pick a destination folder that exists."}), 400

    d = db()
    moved = []
    for src in paths:
        dest = files.unique_dest(dest_dir, os.path.basename(src))
        try:
            if mode == "move":
                shutil.move(src, dest)
                d.execute("UPDATE OR REPLACE tags SET path=? WHERE path=?", (dest, src))
                d.execute("DELETE FROM meta WHERE path=?", (src,))
                ratings_svc.move(src, dest)
                collections_svc.move(src, dest)
                index.forget_path(src)
                moved.append({"from": src, "to": dest})
            else:
                shutil.copy2(src, dest)
        except OSError as exc:
            print(f"[export] {src}: {exc}")
    d.commit()
    return jsonify({"success": True, "count": len(paths), "moved": moved})


@bp.route("/api/export/zip", methods=["POST"])
def export_zip():
    paths = [p for p in (request.json or {}).get("paths", []) if guard(p)]
    if not paths:
        return jsonify({"success": False, "error": "Nothing selected."}), 400

    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for p in paths:
            name = os.path.basename(p)
            stem, ext = os.path.splitext(name)
            i = 1
            while name in used:
                name = f"{stem} ({i}){ext}"
                i += 1
            used.add(name)
            try:
                zf.write(p, name)
            except OSError as exc:
                print(f"[zip] {p}: {exc}")
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"export-{int(time.time())}.zip")


@bp.route("/api/edit/save", methods=["POST"])
def save_edit():
    """Take the canvas the browser rendered and write it out with exactly the
    metadata the user asked for."""
    try:
        payload = json.loads(request.form.get("payload") or "{}")
    except ValueError:
        return jsonify({"success": False, "error": "Bad request."}), 400

    source = payload.get("source_path") or ""
    if not guard(source):
        return jsonify({"success": False, "error": "Original file not found."}), 404

    blob = request.files.get("image")
    if blob is None:
        return jsonify({"success": False, "error": "No image data arrived."}), 400

    fmt = (payload.get("format") or "png").lower()
    if fmt not in ("png", "jpeg", "jpg", "webp"):
        return jsonify({"success": False, "error": "Unsupported format."}), 400

    mode = payload.get("metadata") or "generation"
    settings = store.load_settings()

    try:
        chunks = metadata.collect_chunks(source, mode)
        # "keep everything" starts from the file's own EXIF; location data
        # still stays behind
        base_exif = files.source_exif(source) if mode == "all" else None
        dest = files.edit_dest(source, fmt, payload.get("dest") or "suffix",
                               payload.get("dest_dir"))
        with Image.open(blob.stream) as im:
            im.load()
            notes = metadata.write_image(
                im, dest, fmt, quality=int(payload.get("quality", 92)),
                chunks=chunks, background=payload.get("background") or "#000000",
                base_exif=base_exif, strip_gps=True)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"success": False, "error": f"Could not write the file: {exc}"}), 500

    d = db()
    d.execute("DELETE FROM meta WHERE path=?", (dest,))
    tagged = False
    if settings.get("tag_edits", True):
        # so an edited copy is findable later, and tellable from the original
        d.execute("INSERT OR REPLACE INTO tags VALUES (?,?)", (dest, "edited"))
        tagged = True
    d.commit()
    return jsonify({"success": True, "path": dest, "tagged": tagged,
                    "name": os.path.basename(dest), "notes": notes})
