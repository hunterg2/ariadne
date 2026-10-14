"""The page itself, settings, the folder picker, and maintenance."""

import io
import os
import platform
import shutil

from flask import Blueprint, jsonify, request, send_file

from ariadne import config, store, text
from ariadne import log as log_svc
from ariadne.db import db
from ariadne.services import thumbs
from ariadne.services.sidebar import get_drives

bp = Blueprint("shell", __name__)


@bp.route("/")
def index():
    page = config.WEB_DIST / "index.html"
    if page.exists():
        # the bundle files carry content hashes; the page that names them
        # must always be checked for a newer build
        resp = send_file(page, max_age=0)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp
    return ("The frontend has not been built. Run `npm install` and "
            "`npm run build` in web/, then reload."), 503


@bp.route("/api/settings", methods=["GET", "POST"])
def handle_settings():
    if request.method == "POST":
        incoming = request.json or {}
        merged = store._merge_defaults(incoming, config.DEFAULT_SETTINGS)
        store.save_settings(merged)
        return jsonify({"success": True})
    return jsonify(store.load_settings())


@bp.route("/api/browse")
def browse():
    path = request.args.get("path", "")
    if not path or path == "root":
        return jsonify({
            "directories": [{"name": d, "path": d} for d in get_drives()],
            "current_path": "root", "parent_path": "",
        })
    try:
        dirs = []
        for f in os.listdir(path):
            full = os.path.join(path, f)
            if os.path.isdir(full):
                dirs.append({"name": f, "path": full})
        dirs.sort(key=lambda x: x["name"].lower())
        parent = os.path.dirname(path)
        if parent == path or (
            platform.system() == "Windows" and len(path) == 3 and path.endswith(":\\")
        ):
            parent = "root"
        return jsonify({"directories": dirs, "current_path": path, "parent_path": parent})
    except (OSError, ValueError) as exc:         # ValueError: a NUL byte in the path
        return jsonify({"error": str(exc)}), 400


@bp.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    what = (request.json or {}).get("what", "thumbs")
    if what in ("thumbs", "all"):
        shutil.rmtree(config.paths.thumb_dir, ignore_errors=True)
        config.paths.thumb_dir.mkdir(parents=True, exist_ok=True)
        d = db()
        d.execute("DELETE FROM thumbs")
        d.commit()
    if what in ("meta", "all"):
        d = db()
        d.execute("DELETE FROM meta")
        d.commit()
    return jsonify({"success": True})


@bp.route("/api/cache/stats")
def cache_stats():
    files, total = thumbs.thumb_cache_stats()
    db_file = config.paths.db_file
    return jsonify({"files": files, "bytes": total,
                    "db_bytes": os.path.getsize(db_file) if db_file.exists() else 0})


@bp.route("/api/cache/prune", methods=["POST"])
def prune_cache():
    removed = thumbs.prune_thumbs()
    files, total = thumbs.thumb_cache_stats()
    return jsonify({"success": True, "removed": removed,
                    "files": files, "bytes": total})


@bp.route("/api/system")
def system_info():
    from ariadne.services import system
    return jsonify({"success": True, **system.status()})


@bp.route("/api/system/startup", methods=["POST", "DELETE"])
def system_startup():
    from ariadne.services import system
    ok, message = system.enable_startup() if request.method == "POST" else system.disable_startup()
    return jsonify({"success": ok, "message": message, **system.status()})


@bp.route("/api/system/diagnostics")
def system_diagnostics():
    """What Settings copies to the clipboard for a bug report; ``?download=1``
    hands it over as a text file when the browser refuses the clipboard."""
    from ariadne.services import system
    text = system.diagnostics()
    if request.args.get("download"):
        return send_file(io.BytesIO(text.encode("utf-8")), mimetype="text/plain", as_attachment=True,
                         download_name="ariadne-diagnostics.txt", max_age=0)
    return jsonify({"success": True, "text": text, "log_path": str(log_svc.path() or "")})


@bp.route("/api/system/report")
def system_report():
    """A bug report from what the user typed in Settings: the prefilled
    GitHub issue as JSON, or with ``?download=1`` the whole report as a
    text file to attach or paste."""
    from ariadne.services import system
    args = request.args
    out = system.report(text.clean_text(args.get("summary", "")), text.clean_text(args.get("steps", "")),
                        args.get("diagnostics", "1") != "0")
    if args.get("download"):
        return send_file(io.BytesIO(out["text"].encode("utf-8")), mimetype="text/plain",
                         as_attachment=True, download_name="ariadne-report.txt", max_age=0)
    return jsonify({"success": True, **out})


@bp.route("/api/system/log")
def system_log():
    path = log_svc.path()
    if path is None or not path.exists():
        return jsonify({"success": False, "error": "There is no log file yet."}), 404
    return send_file(path, mimetype="text/plain", as_attachment=True,
                     download_name=log_svc.NAME, max_age=0)


@bp.route("/api/backup")
def download_backup():
    """The open library's irreplaceable files as one zip (services/backup)."""
    from ariadne.services import backup
    return send_file(io.BytesIO(backup.build()), mimetype="application/zip",
                     as_attachment=True, download_name=backup.filename(), max_age=0)


@bp.route("/api/updates")
def updates_state():
    from ariadne.services import updates
    return jsonify({"success": True, **updates.state()})


@bp.route("/api/updates/check", methods=["POST"])
def updates_check():
    """"Check now" in Settings: asks GitHub whatever the last look said."""
    from ariadne.services import updates
    return jsonify({"success": True, **updates.check(force=True)})


@bp.route("/api/stats")
def stats():
    d = db()
    return jsonify({
        "images_indexed": d.execute("SELECT COUNT(*) c FROM meta").fetchone()["c"],
        "rated": d.execute("SELECT COUNT(*) c FROM ratings WHERE stars>0").fetchone()["c"],
        "tag_links": d.execute("SELECT COUNT(*) c FROM tags").fetchone()["c"],
        "in_trash": d.execute("SELECT COUNT(*) c FROM trash WHERE restorable=1").fetchone()["c"],
    })
