"""Library-level operations: the portable export, and the one-time migration
from the v1 JSON files."""

import os
import time

from ariadne import config, store
from ariadne.db import db, kv_get, kv_set
from ariadne.log import log


def library_payload():
    """The portable export: ratings and tags keyed by path. Images are never
    part of it; only the library rows that point at them."""
    d = db()
    ratings = {}
    for r in d.execute("SELECT path, stars, rejected, label FROM ratings "
                       "WHERE stars>0 OR rejected=1 OR label IS NOT NULL"):
        ratings[r["path"]] = {"stars": r["stars"] or 0, "rejected": int(bool(r["rejected"])),
                              "label": r["label"]}
    tags = {}
    for r in d.execute("SELECT path, tag FROM tags"):
        tags.setdefault(r["path"], []).append(r["tag"])
    return {
        "format": "ariadne-library",
        "version": 2,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "counts": {"ratings": len(ratings), "tagged": len(tags),
                   "tag_links": sum(len(v) for v in tags.values())},
        "ratings": ratings,
        "tags": tags,
    }


def migrate_from_v1():
    """Pull categories.json / tags.json into SQLite and top up settings.json.

    Runs once per library. Old files are renamed to *.v1.bak rather than
    deleted, so nothing is lost if something goes wrong.
    """
    if kv_get("schema_version") == str(config.SCHEMA_VERSION):
        return

    log.info("[migrate] upgrading data from v1 ...")
    d = db()
    moved = []

    # 1. categories.json -> star ratings (liked = 3, loved = 5)
    if config.LEGACY_CATEGORIES_FILE.exists():
        legacy = store.load_json_file(config.LEGACY_CATEGORIES_FILE, dict)
        stars = {"liked": 3, "loved": 5}
        rows = [(p, stars[c], time.time()) for p, c in legacy.items()
                if isinstance(p, str) and c in stars]
        if rows:
            d.executemany("INSERT OR IGNORE INTO ratings (path, stars, rejected, label, updated) "
                          "VALUES (?,?,0,NULL,?)", rows)
        log.info(f"[migrate]   ratings: {len(rows)}")
        moved.append(config.LEGACY_CATEGORIES_FILE)

    # 2. tags.json -> tags table
    if config.LEGACY_TAGS_FILE.exists():
        legacy = store.load_json_file(config.LEGACY_TAGS_FILE, dict)
        rows = []
        for p, tags in legacy.items():
            if not isinstance(p, str):
                continue
            if isinstance(tags, str):
                tags = [tags]
            for t in tags or []:
                t = str(t).strip().lstrip("#")
                if t:
                    rows.append((p, t))
        if rows:
            d.executemany("INSERT OR REPLACE INTO tags VALUES (?,?)", rows)
        log.info(f"[migrate]   tag links: {len(rows)}")
        moved.append(config.LEGACY_TAGS_FILE)

    d.commit()

    for f in moved:
        try:
            os.replace(f, f.with_suffix(f.suffix + ".v1.bak"))
        except OSError:
            pass

    # 3. settings.json - add any keys the new build expects
    settings = store.load_settings()
    hk = settings.setdefault("hotkeys", {})
    for action, keys in config.DEFAULT_SETTINGS["hotkeys"].items():
        if action not in hk:
            hk[action] = list(keys)
    store.save_settings(settings)

    # 4. history.json - normalise entries written by older builds
    history = store.load_history()

    def normalise(items):
        for it in items:
            it.setdefault("type", "folder")
            it.setdefault("status", "")
            if it["type"] == "folder":
                it.setdefault("alias", "")
            if it["type"] == "group":
                it.setdefault("isOpen", True)
                it.setdefault("items", [])
                normalise(it["items"])

    normalise(history)
    store.save_history(history)

    kv_set("schema_version", config.SCHEMA_VERSION)
    log.info("[migrate] done. old files kept as *.v1.bak")
