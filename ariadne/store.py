"""The small JSON files beside the database: settings, the sidebar history
and the project list. Also the project switch, since it is what decides
which set of files is live.
"""

import hashlib
import json
import os
import time
from pathlib import Path

from ariadne import config, db


# --------------------------------------------------------------------------
# json files
# --------------------------------------------------------------------------

def load_json_file(filepath, default_type=dict):
    """A JSON file, or an empty default when it is missing or unreadable. A
    corrupt file is reported rather than raised, since every caller can carry
    on with defaults."""
    p = Path(filepath)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except ValueError as exc:
            print(f"[json] {p.name} is not valid JSON and was ignored: {exc}")
        except OSError as exc:
            print(f"[json] {p.name} could not be read: {exc}")
    return default_type()


def save_json_file(filepath, data):
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


def _merge_defaults(data, defaults):
    for k, v in defaults.items():
        if k not in data:
            data[k] = json.loads(json.dumps(v))
        elif isinstance(v, dict) and isinstance(data[k], dict):
            _merge_defaults(data[k], v)
    return data


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

def normalise_settings(settings):
    """The ComfyUI output folder used to be a single special case. It is now
    just the first entry in a list of auto-updating folders."""
    changed = False
    autos = settings.setdefault("auto_folders", [])
    legacy = (settings.get("comfy_path") or "").strip()
    if legacy:
        if not any((a.get("path") or "") == legacy for a in autos):
            autos.insert(0, {
                "id": "comfy_auto_group",
                "path": legacy,
                "name": "ComfyUI Outputs",
                "include_root": False,
                "enabled": bool(settings.get("auto_import_comfy")),
            })
        settings["comfy_path"] = ""
        settings["auto_import_comfy"] = False
        changed = True

    for entry in autos:
        if not entry.get("id"):
            entry["id"] = "auto_" + hashlib.sha1(
                (entry.get("path") or "").encode("utf-8", "replace")).hexdigest()[:10]
            changed = True
        entry.setdefault("name", os.path.basename(
            (entry.get("path") or "").rstrip("/\\")) or "Auto folder")
        entry.setdefault("include_root", False)
        entry.setdefault("enabled", True)
        # subfolders you have deliberately dragged out of the group. Without
        # this the rebuild would put them straight back, since they are still
        # sitting on disk inside the watched folder.
        if not isinstance(entry.get("excluded"), list):
            entry["excluded"] = []
    return settings, changed


def load_settings():
    settings = _merge_defaults(load_json_file(config.paths.settings_file, dict),
                               config.DEFAULT_SETTINGS)
    settings, changed = normalise_settings(settings)
    if changed:
        save_json_file(config.paths.settings_file, settings)
        config.bump_roots()
    return settings


def save_settings(settings):
    save_json_file(config.paths.settings_file, settings)
    config.bump_roots()


# --------------------------------------------------------------------------
# sidebar history
# --------------------------------------------------------------------------

def load_history():
    data = load_json_file(config.paths.history_file, list)
    history = []
    for item in data:
        if isinstance(item, str):
            history.append({"type": "folder", "path": item, "alias": "", "status": ""})
        elif isinstance(item, dict):
            item.setdefault("type", "folder")
            history.append(item)
    return history


def save_history(history):
    save_json_file(config.paths.history_file, history)
    config.bump_roots()


# --------------------------------------------------------------------------
# projects
#
# A project is a separate library: its own folder list, ratings, tags, thumbs
# and settings. The default one stays exactly where it has always been, so an
# existing install needs nothing moved; the rest live under projects/<id>/.
# --------------------------------------------------------------------------

def load_projects():
    data = load_json_file(config.PROJECTS_FILE, dict)
    projects = data.get("projects")
    if not isinstance(projects, list) or not projects:
        projects = [{"id": "default", "name": "Main library", "created": time.time()}]
    active = data.get("active")
    if not any(p.get("id") == active for p in projects):
        active = projects[0]["id"]
    return {"active": active, "projects": projects}


def save_projects(data):
    save_json_file(config.PROJECTS_FILE, data)


def use_project(project_id):
    """Point every path at this project and retire the old database handles."""
    from ariadne import migrations

    new_paths = config.Paths(config.project_dir(project_id))
    new_paths.ensure()
    config.set_paths(new_paths)
    db.retire_connections()
    db.init_db()
    migrations.apply()
