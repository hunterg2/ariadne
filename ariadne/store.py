"""The small JSON files beside the database: settings, the sidebar history
and the project list. Also the project switch, since it is what decides
which set of files is live.
"""

import hashlib
import json
import math
import os
import time
from pathlib import Path

from ariadne import config, db
from ariadne.log import log

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
            log.warning(f"[json] {p.name} is not valid JSON and was ignored: {exc}")
        except OSError as exc:
            log.warning(f"[json] {p.name} could not be read: {exc}")
    return default_type()


def save_json_file(filepath, data):
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    replace_file(tmp, p)


def replace_file(tmp, dest, tries=20, pause=0.05):
    """``os.replace`` with patience. On Windows a file another thread has
    open for reading at that instant (the indexer loading settings) cannot
    be replaced: the rename fails with "access is denied" rather than
    waiting, which CI saw as a failed settings save. A read takes a
    millisecond, so a few short retries cover it."""
    for attempt in range(tries):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(pause)


def _merge_defaults(data, defaults):
    """``data`` with every default key present and in the default's shape.
    Keys the defaults do not know pass through untouched."""
    for k, v in defaults.items():
        if k not in data:
            data[k] = json.loads(json.dumps(v))
        else:
            data[k] = _coerce(data[k], v)
    return data


def _coerce(value, default):
    """``value`` in the type of ``default``. A hand-edited settings.json or
    an odd client used to be able to put a string where a list belongs, and
    every later request then failed on it; a wrong type now becomes the
    default, and a number written as text becomes the number."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        return bool(value) if isinstance(value, (int, float)) else default
    if isinstance(default, int):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if math.isfinite(value) else default
        if isinstance(value, str):
            try:
                return int(float(value))
            except (ValueError, OverflowError):
                return default
        return default
    if isinstance(default, str):
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return default
    if isinstance(default, list):
        return value if isinstance(value, list) else json.loads(json.dumps(default))
    if isinstance(default, dict):
        if isinstance(value, dict):
            return _merge_defaults(value, default)
        return json.loads(json.dumps(default))
    return value


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

def normalise_settings(settings):
    """The ComfyUI output folder used to be a single special case. It is now
    just the first entry in a list of auto-updating folders."""
    changed = False
    autos = settings.setdefault("auto_folders", [])
    if not isinstance(autos, list):
        autos = settings["auto_folders"] = []
        changed = True
    # an entry that is not {path: ...} cannot be watched or be a root
    kept = [a for a in autos if isinstance(a, dict) and isinstance(a.get("path"), (str, type(None)))]
    if len(kept) != len(autos):
        autos[:] = kept
        changed = True
    roots = settings.get("extra_roots")
    clean_roots = [r for r in (roots if isinstance(roots, list) else []) if isinstance(r, str) and r.strip()]
    if clean_roots != roots:
        settings["extra_roots"] = clean_roots
        changed = True
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
    return clean_history(load_json_file(config.paths.history_file, list))


def clean_history(data, seen=None):
    """The sidebar list with anything that cannot be a sidebar entry
    dropped: a folder needs a path that is text, a group a list of items.
    The list is what decides which folders may be read (safety.py), so a
    bad sync or a hand edit must not be able to break every request. A
    folder's path is normalised and a second spelling of a folder already
    in the list is dropped: the index spells its rows like the list does,
    so ``C:\\Pics`` and ``c:/pics/`` both listed meant every file twice."""
    history = []
    seen = set() if seen is None else seen
    for item in (data if isinstance(data, list) else []):
        if isinstance(item, str):
            item = {"type": "folder", "path": item, "alias": "", "status": ""}
        if not isinstance(item, dict):
            continue
        item.setdefault("type", "folder")
        if item["type"] == "folder":
            if not isinstance(item.get("path"), str) or not item["path"].strip():
                continue
            item["path"] = os.path.normpath(item["path"])
            key = os.path.normcase(item["path"])
            if key in seen:
                continue
            seen.add(key)
        elif item["type"] == "group":
            item["items"] = clean_history(item.get("items"), seen)
        history.append(item)
    return history


def save_history(history):
    save_json_file(config.paths.history_file, clean_history(history))
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
    """Point every path at this project and retire the old database handles.

    The indexer thread is stopped first: it reads ``config.paths`` on every
    database call, so a scan still running across the switch would write
    the old library's files into the new library's database, and hold that
    file locked while the migrations try to create it (seen in CI as
    "database is locked"). The next scan request starts it again."""
    from ariadne import migrations
    from ariadne.services.index import indexer

    indexer.stop()
    # a request that arrives meanwhile opens its handle once this is done
    with db.switch_lock():
        new_paths = config.Paths(config.project_dir(project_id))
        new_paths.ensure()
        config.set_paths(new_paths)
        db.retire_connections()
        db.init_db()
        migrations.apply()
