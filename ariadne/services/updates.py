"""Is there a newer release? Asks GitHub for the latest release of the
public repository at most once a day, remembers the answer in ``kv`` and
shows it on the Settings screen. Nothing is downloaded or installed: the
notice carries a link and the person decides.

The check runs shortly after start (``check_soon``) and, in the full build,
from the scheduler loop while the app stays up in the tray. ``settings
.check_updates`` turns it off; "Check now" in Settings forces one.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request

from ariadne import config, db, store

API = "https://api.github.com/repos/{repo}/releases/latest"
KV_KEY = "update_check"
EVERY = 86400               # seconds between checks
DELAY = 20                  # seconds after start before the first look
TIMEOUT = 8

VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$")


def current():
    from ariadne import __version__
    return __version__


def parse_version(text):
    """"v2.1.0" -> (2, 1, 0, 1); a pre-release suffix sorts below the plain
    number: "2.1.0-beta" -> (2, 1, 0, 0, "beta"). None when it is not a
    version at all."""
    m = VERSION_RE.match((text or "").strip())
    if not m:
        return None
    major, minor, patch, suffix = m.groups()
    out = (int(major), int(minor), int(patch), 0 if suffix else 1)
    return out + ((suffix,) if suffix else ())


def is_newer(candidate, than):
    a, b = parse_version(candidate), parse_version(than)
    return bool(a and b and a > b)


def enabled():
    return bool(store.load_settings().get("check_updates", True))


def _fetch(repo):
    """The latest release as {version, url, published}. Raises on any
    network or format problem; the caller stores the message."""
    req = urllib.request.Request(API.format(repo=repo), headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Ariadne/{current()}",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        data = json.loads(res.read().decode("utf-8"))
    tag = data.get("tag_name") or ""
    if not parse_version(tag):
        raise ValueError(f"the newest release is tagged {tag!r}, not a version number")
    return {"version": tag.lstrip("v"), "url": data.get("html_url") or "",
            "published": data.get("published_at") or ""}


def _stored():
    try:
        return json.loads(db.kv_get(KV_KEY) or "{}")
    except (TypeError, ValueError):
        return {}


def state():
    """What Settings shows: the running version, the last answer, and
    whether that answer is newer."""
    saved = _stored()
    latest = saved.get("version") or ""
    return {
        "current": current(),
        "repo": config.UPDATE_REPO,
        "enabled": enabled(),
        "checked_at": saved.get("at") or None,
        "latest": latest,
        "url": saved.get("url") or "",
        "error": saved.get("error") or "",
        "newer": is_newer(latest, current()) if latest else False,
    }


def check(now=None, force=False):
    """Ask GitHub if the last look is older than a day (or ``force``), and
    remember the answer. A failed look is remembered too, so a dead network
    is asked once a day and not every pass. Returns ``state()``."""
    now = now or time.time()
    if not force and not enabled():
        return state()
    saved = _stored()
    if not force and (saved.get("at") or 0) > now - EVERY:
        return state()
    entry = {"at": now, "version": saved.get("version") or "", "url": saved.get("url") or ""}
    try:
        entry.update(_fetch(config.UPDATE_REPO))
        entry["error"] = ""
    except urllib.error.HTTPError as exc:
        entry["error"] = f"GitHub answered {exc.code}."
    except (urllib.error.URLError, OSError, ValueError) as exc:
        entry["error"] = f"Could not reach GitHub: {getattr(exc, 'reason', None) or exc}"
    db.kv_set(KV_KEY, json.dumps(entry))
    return state()


def check_soon(delay=DELAY):
    """Run one check on a background thread a little after start, so the
    launcher is not held up by a slow network. Does nothing when the
    setting is off or the last look is recent."""
    def run():
        time.sleep(delay)
        try:
            check()
        except Exception as exc:          # a background look must never surface
            from ariadne.log import log
            log.warning(f"[updates] {exc}")

    thread = threading.Thread(target=run, daemon=True, name="updates")
    thread.start()
    return thread
