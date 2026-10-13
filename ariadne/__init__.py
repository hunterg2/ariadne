"""Ariadne: a local photo manager.

``create_app()`` builds the Flask app. ``app.py`` at the repository root is
the launcher that picks a port, starts the background workers and opens a
browser; nothing in here does any of that, so tests can create as many apps
as they like.
"""

import sqlite3

from flask import Flask, jsonify
from PIL import Image

from ariadne import config

Image.MAX_IMAGE_PIXELS = None

__version__ = "0.2.0-dev"


def create_app(app_dir=None):
    """Build the Flask app and open the active project.

    ``app_dir`` points runtime data somewhere else (tests use a temp dir).
    """
    from ariadne import api, store
    from ariadne.services import auth
    from ariadne.services.library import migrate_from_v1

    if app_dir is not None:
        config.set_app_dir(app_dir)

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

    @app.errorhandler(sqlite3.Error)
    def database_error(exc):
        """The page expects JSON from every /api call, so a failing database
        answers with a message it can show rather than an HTML stack trace."""
        print(f"[db] {exc}")
        return jsonify({"success": False, "error": f"Database error: {exc}"}), 500

    @app.errorhandler(OSError)
    def file_error(exc):
        print(f"[io] {exc}")
        return jsonify({"success": False, "error": f"File error: {exc}"}), 500

    store.use_project(store.load_projects()["active"])
    migrate_from_v1()
    return app
