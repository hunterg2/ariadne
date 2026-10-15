"""Ariadne: a local photo manager.

``create_app()`` builds the Flask app. ``app.py`` at the repository root is
the launcher that picks a port, starts the background workers and opens a
browser; nothing in here does any of that, so tests can create as many apps
as they like.
"""

import gzip
import mimetypes
import platform
import sqlite3
import sys

from flask import Flask, jsonify, request
from PIL import Image
from werkzeug.exceptions import HTTPException, InternalServerError

from ariadne import config, db, text
from ariadne import log as applog  # the module; "log" itself is its logger

# Pillow's default ceiling (89 MP) is below a big upscale, so it was off
# entirely. Off, a 50 KB PNG claiming 100,000 x 100,000 pixels makes the
# indexer and every /thumb request try to allocate 30 GB. Pillow warns past
# this figure and refuses past twice it (2 GP, a 45,000-pixel square);
# nothing a camera or a model makes comes near, and the thumbnailer and the
# extractor treat the refusal as a file they cannot read.
Image.MAX_IMAGE_PIXELS = 1_000_000_000
# the home-screen manifest in web/public; Windows does not know the suffix
mimetypes.add_type("application/manifest+json", ".webmanifest")

__version__ = "2.1.0"

# JSON answers to other devices are gzipped past this size, at this level
# (4: a 360 KB page of the grid becomes 48 KB in under 2 ms)
GZIP_FROM = 2048
GZIP_LEVEL = 4


def os_name():
    """The operating system for the log, as ``platform.platform()`` gives
    it, except on Windows, where that call asks WMI for the version and
    took 60 ms of every start for one log line."""
    if sys.platform == "win32":
        v = sys.getwindowsversion()
        return f"Windows-{v.major}.{v.minor}.{v.build}"
    return platform.platform()


def create_app(app_dir=None):
    """Build the Flask app and open the active project.

    ``app_dir`` points runtime data somewhere else (tests use a temp dir).
    """
    from ariadne import api, store
    from ariadne.services import auth
    from ariadne.services.library import migrate_from_v1

    if app_dir is not None:
        config.set_app_dir(app_dir)
    # every report from here on lands in ariadne.log beside the data
    applog.setup(config.APP_DIR)
    applog.log.info(f"[start] Ariadne {__version__} on Python {platform.python_version()} "
                    f"({os_name()}), data in {config.APP_DIR}")

    static_folder = str(config.WEB_DIST) if config.WEB_DIST.exists() else None
    app = Flask(
        "ariadne",
        static_folder=static_folder,
        static_url_path="" if static_folder else None,
    )
    app.config["JSON_SORT_KEYS"] = False

    for bp in api.ALL:
        app.register_blueprint(bp)

    # other devices need the PIN; the computer itself never does
    app.before_request(auth.gate)

    @app.before_request
    def json_bodies_are_objects():
        """Every /api body is a JSON object. A list or a bare value is a
        client bug; it is told so here instead of failing somewhere inside
        (a bare ``[]`` used to reset the settings to their defaults). The
        strings in it are made storable (``text.scrub``): a lone surrogate
        would otherwise fail in whichever table it reached."""
        if (request.path.startswith("/api/") and request.method in ("POST", "PATCH", "PUT")
                and request.is_json):
            try:
                body = request.get_json(silent=True)
                if body is not None and not isinstance(body, dict):
                    return jsonify({"success": False,
                                    "error": "The request body must be a JSON object."}), 400
                if body is not None:
                    text.scrub(body)
            except (RecursionError, text.TooDeep):
                # fifty thousand nested brackets: the parser gives up, or
                # takes it and whatever walks the body gives up later
                return jsonify({"success": False,
                                "error": "The request body is nested too deeply."}), 400
        return None

    @app.after_request
    def headers(response):
        # a browser must take the type a route says: /image serves raster
        # images only, and a file served as one must not be read as a page
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # the bundle files carry a content hash in their names, so a copy
        # the browser holds is good until the page names another file;
        # Flask's default had it ask again for the half megabyte each open
        if request.path.startswith("/assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        # JSON for another device goes gzipped: a page of the grid is a few
        # hundred KB that packs to a tenth, which a phone on wifi feels. On
        # this computer the packing costs more than the bytes, so loopback
        # answers go as they are. Files (send_file) pass through untouched.
        if (response.mimetype == "application/json" and response.status_code == 200
                and not response.direct_passthrough
                and "gzip" in request.headers.get("Accept-Encoding", "")
                and not auth.is_loopback(request.remote_addr)):
            data = response.get_data()
            if len(data) > GZIP_FROM:
                response.set_data(gzip.compress(data, GZIP_LEVEL))
                response.headers["Content-Encoding"] = "gzip"
                response.vary.add("Accept-Encoding")
        return response

    # a request lets go of its database handle when it ends, so an idle
    # thread never keeps a library file open across a project switch
    app.teardown_request(lambda exc: db.release())

    @app.errorhandler(HTTPException)
    def http_error(exc):
        """/api answers JSON for 400, 404, 405 and 415 too; the page shell
        and the image routes keep Werkzeug's own pages."""
        if not request.path.startswith("/api/"):
            return exc
        message = exc.description
        if exc.code == 400 and request.is_json:
            try:
                if request.get_json(silent=True) is None:
                    message = "The request body is not valid JSON."
            except RecursionError:
                message = "The request body is nested too deeply."
        return jsonify({"success": False, "error": message, "code": exc.code}), exc.code

    @app.errorhandler(InternalServerError)
    def internal_error(exc):
        """An exception nothing caught, on /api: Flask has already logged
        the traceback through the app logger (ours), so the page gets JSON
        it can show instead of an HTML error page. Tests never see this:
        pytest runs with exceptions propagated."""
        if not request.path.startswith("/api/"):
            return exc
        original = exc.original_exception or exc
        return jsonify({"success": False,
                        "error": f"{type(original).__name__}: {original}"}), 500

    @app.errorhandler(sqlite3.Error)
    def database_error(exc):
        """The page expects JSON from every /api call, so a failing database
        answers with a message it can show rather than an HTML stack trace."""
        if isinstance(exc, sqlite3.OperationalError) and "interrupted" in str(exc):
            # a project switch stopped this request's query on the old library
            return jsonify({"success": False, "error": "The library was switched while "
                            "this request ran. Try again."}), 409
        applog.log.exception(f"[db] {exc}")
        return jsonify({"success": False, "error": f"Database error: {exc}"}), 500

    @app.errorhandler(OSError)
    def file_error(exc):
        applog.log.exception(f"[io] {exc}")
        return jsonify({"success": False, "error": f"File error: {exc}"}), 500

    store.use_project(store.load_projects()["active"])
    migrate_from_v1()
    # the thread that built the app (the launcher's main thread) keeps no
    # handle: it never asks again, and an open one would hold the first
    # library's file for the life of the process
    db.release()
    return app
