"""The sidebar tree: saved folders, groups, and the auto-updating groups that
mirror a watched folder's subfolders."""

import os
import platform
import string

AUTO_GROUP_STATUS = "\U0001F916"
LOOSE_ALIAS = "Not in a subfolder"


def is_auto_group(item):
    gid = str(item.get("id") or "")
    return item.get("type") == "group" and (gid == "comfy_auto_group"
                                            or gid.startswith("auto_"))


def build_auto_groups(settings):
    """What the sidebar should contain for each watched folder right now."""
    wanted = {}
    for entry in settings.get("auto_folders", []) or []:
        path = (entry.get("path") or "").strip()
        if not entry.get("enabled", True) or not path:
            continue
        items = []
        # Images sitting directly in the watched folder have nowhere to appear
        # otherwise, since only subfolders become entries. This gives them one.
        if entry.get("include_root"):
            items.append({"type": "folder", "path": path,
                          "alias": entry.get("root_name") or LOOSE_ALIAS,
                          "status": "◇"})
        excluded = {os.path.normpath(x) for x in (entry.get("excluded") or [])}
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if os.path.isdir(full) and os.path.normpath(full) not in excluded:
                    items.append({"type": "folder", "path": full, "alias": "", "status": ""})
        wanted[entry["id"]] = {
            "type": "group", "id": entry["id"],
            "name": entry.get("name") or os.path.basename(path.rstrip("/\\")) or path,
            "isOpen": True, "status": AUTO_GROUP_STATUS, "items": items,
        }
    return wanted


def update_auto_groups(history, settings):
    """Returns (history, changed). Auto groups are rebuilt from disk; a group
    whose folder was removed from the settings disappears with it."""
    wanted = build_auto_groups(settings)
    changed = False
    seen = set()

    def walk(items):
        nonlocal changed
        for i in range(len(items) - 1, -1, -1):
            item = items[i]
            if item.get("type") != "group":
                continue
            if is_auto_group(item):
                gid = item.get("id")
                if gid in wanted:
                    seen.add(gid)
                    target = wanted[gid]
                    # carry across anything the user set on these entries, or a
                    # sync would quietly undo their renames and pins
                    keep = {c.get("path"): c for c in item.get("items", [])}
                    merged = []
                    for child in target["items"]:
                        old = keep.get(child.get("path"))
                        if old:
                            for field in ("alias", "status", "pinned", "sort"):
                                if old.get(field):
                                    child[field] = old[field]
                        merged.append(child)
                    if (item.get("items") != merged or item.get("name") != target["name"]):
                        item["items"] = merged
                        item["name"] = target["name"]
                        changed = True
                else:
                    items.pop(i)
                    changed = True
            else:
                walk(item.get("items", []))

    walk(history)

    for gid, group in wanted.items():
        if gid not in seen and group["items"]:
            history.insert(0, group)
            changed = True
    return history, changed


def folder_exists(history, path):
    for item in history:
        if item.get("type") == "folder" and item.get("path") == path:
            return True
        if item.get("type") == "group" and folder_exists(item.get("items", []), path):
            return True
    return False


def find_and_update(history, identifier, action, value):
    for i, item in enumerate(history):
        item_id = item.get("path") if item.get("type") == "folder" else item.get("id")
        if item_id == identifier:
            if action == "pin":
                # "top", "bottom", or nothing. An older saved True means top.
                if value in ("top", "bottom"):
                    item["pinned"] = value
                elif value is True:
                    item["pinned"] = "top"
                else:
                    item.pop("pinned", None)
            elif action == "rename":
                if item.get("type") in ("group", "smart_folder"):
                    item["name"] = value
                else:
                    item["alias"] = value
            elif action == "status":
                item["status"] = value
            elif action == "recursive":
                # the folder shows its subfolders' images too
                if value:
                    item["recursive"] = True
                else:
                    item.pop("recursive", None)
            elif action == "delete":
                history.pop(i)
            return True
        if item.get("type") == "group" and find_and_update(
            item.get("items", []), identifier, action, value
        ):
            return True
    return False


def get_drives():
    if platform.system() == "Windows":
        return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
    return ["/"]
