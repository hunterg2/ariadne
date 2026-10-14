"""Paths, constants and default settings.

Everything that used to be a module-level global in app.py lives here. The
runtime paths are an object (``paths``) rather than loose names so that a
project switch can replace them in one place and every module that reads
``config.paths.db_file`` at call time sees the change.

Tests call ``set_app_dir()`` with a temporary directory before creating the
app, so nothing they do touches a real library.
"""

import os
from pathlib import Path

APP_NAME = "Ariadne"
DEFAULT_PORT = 5000
DEFAULT_HOST = "127.0.0.1"        # loopback unless --host is given; there is no login
# what the launcher actually bound, so the Settings screen can say so
BIND_HOST = DEFAULT_HOST
BIND_PORT = DEFAULT_PORT
PORT_ENV = "IMGORG_PORT"          # hands the chosen port to the reloader child
NO_BROWSER_ENV = "ORGANIZER_NO_BROWSER"
# Names a loopback request may be addressed to besides localhost and the
# loopback addresses (see services/auth.host_ok), comma separated: for a
# hosts-file alias of your own.
TRUSTED_HOSTS_ENV = "ARIADNE_TRUSTED_HOSTS"
# Where the update notice looks for the newest release. The public
# repository: releases are tagged in both at once, and a private one cannot
# be asked without a token.
UPDATE_REPO = "hunterg2/ariadne"

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent              # app.py, web/
WEB_DIST = ROOT_DIR / "web" / "dist"

THUMB_SIZE = 512
THUMB_VERSION = 2          # bump to invalidate every cached thumbnail
THUMB_QUALITY = 82         # WebP quality; settings.thumb_quality overrides it
BACKUPS_KEPT = 7           # database copies kept in backups/
# what the index takes, and the only types /image and /thumb serve: a
# library folder can hold an .html or .svg too, and served from this origin
# that would be a page with the app's rights
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
VALID_EXTS = set(IMAGE_TYPES)
REWRITABLE_FORMATS = ("png", "jpeg", "webp")   # formats metadata can be written into
SCHEMA_VERSION = 2         # the v1 -> v2 JSON migration marker (kv.schema_version)
META_CACHE_VERSION = 4     # 4: kind + camera columns (Stage 1)

DEFAULT_SETTINGS = {
    "hotkeys": {
        "liked": ["1", "", ""],
        "loved": ["2", "", ""],
        "prompt": ["Spacebar", "", ""],
        "trash": ["Backspace", "Delete", ""],
        "reveal": ["C", "", ""],
        "tag": ["T", "", ""],
        "prev": ["ArrowLeft", "A", ""],
        "next": ["ArrowRight", "D", ""],
        "cull": ["F", "", ""],
        "select": ["S", "", ""],
    },
    "comfy_path": "",          # kept only so old settings can be migrated
    "auto_import_comfy": False,
    # each entry: {id, path, name, include_root, enabled}
    "auto_folders": [],
    "saved_queries": [],
    "delete_mode": "soft",
    "theme": 0,
    # added in v2
    "confirm_unlike": False,
    "guess_prompt_line": True,
    "sidebar_sort": "manual",
    "sort_subfolders": False,
    "tag_edits": True,
    # backend: prompt | ollama | openai | anthropic
    "tagger": {"backend": "prompt", "model": "", "url": "", "api_key": "",
               "max_tags": 12, "include_model": False, "include_loras": False,
               "extra": "", "prefer_existing": True},
    "allow_drag_when_sorted": True,
    "folder_opened": {},
    "warn_quality": True,
    "edit_colors": [],
    "edit_defaults": {"format": "png", "quality": 92, "metadata": "generation",
                      "dest": "suffix", "background": "#000000"},
    "cull_auto_advance": True,
    "thumb_quality": THUMB_QUALITY,
    "last_folder": "",
    "extra_roots": [],
    "ui": {"grid_size": 250, "layout": "square", "sort": "date_desc"},
    # added in the revamp
    "warm_thumbs": True,                    # build thumbnails while indexing
    "check_updates": True,                  # ask GitHub for a newer release once a day
}


class Paths:
    """Every file the app writes for one library (project)."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.db_file = self.data_dir / "organizer.db"
        self.cache_dir = self.data_dir / "cache"
        self.thumb_dir = self.cache_dir / "thumbs"
        self.backup_dir = self.data_dir / "backups"
        self.history_file = self.data_dir / "history.json"
        self.settings_file = self.data_dir / "settings.json"
        self.key_file = self.data_dir / "ariadne.key"

    def ensure(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.thumb_dir.mkdir(parents=True, exist_ok=True)


# Where runtime data lives. The default library sits beside app.py, exactly
# where it always has; other projects live under projects/<id>/.
APP_DIR = ROOT_DIR
PROJECTS_FILE = APP_DIR / "projects.json"
PROJECTS_DIR = APP_DIR / "projects"
LEGACY_CATEGORIES_FILE = APP_DIR / "categories.json"
LEGACY_TAGS_FILE = APP_DIR / "tags.json"

paths = Paths(APP_DIR)


def set_app_dir(path):
    """Point the whole app at another data directory (tests, portable runs)."""
    global APP_DIR, PROJECTS_FILE, PROJECTS_DIR, LEGACY_CATEGORIES_FILE
    global LEGACY_TAGS_FILE, paths
    APP_DIR = Path(path).resolve()
    PROJECTS_FILE = APP_DIR / "projects.json"
    PROJECTS_DIR = APP_DIR / "projects"
    LEGACY_CATEGORIES_FILE = APP_DIR / "categories.json"
    LEGACY_TAGS_FILE = APP_DIR / "tags.json"
    paths = Paths(APP_DIR)
    bump_roots()


def project_dir(project_id):
    return APP_DIR if project_id == "default" else PROJECTS_DIR / project_id


def set_paths(new_paths):
    global paths
    paths = new_paths
    bump_roots()


# The allowed-roots cache (see safety.py) is keyed on this counter so that any
# change to settings, history or the active project invalidates it without
# the storage layer having to import the safety layer.
roots_generation = 0


def bump_roots():
    global roots_generation
    roots_generation += 1


def env_flag(name):
    return os.environ.get(name) == "1"
