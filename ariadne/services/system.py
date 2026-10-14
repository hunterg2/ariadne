"""Running Ariadne as a background service: tray availability and the
start-at-logon shortcut (Windows; other platforms report not supported),
plus the diagnostics text Settings copies for a bug report."""

import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from ariadne import config, tray
from ariadne import log as log_svc

SHORTCUT_NAME = "Ariadne.lnk"
LOG_LINES = 150              # how much of the log the diagnostics carry
REPORT_FIELD = 4000          # characters kept of what the user typed in a bug report
REPORT_URL = 6500            # GitHub refuses a longer prefilled new-issue address (414)


def startup_dir():
    if os.name != "nt":
        return None
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_path():
    folder = startup_dir()
    return folder / SHORTCUT_NAME if folder else None


def lan_urls():
    """Where other devices can reach this server, if it was started with
    --host. Loopback means nowhere, which is the default."""
    host, port = config.BIND_HOST, config.BIND_PORT
    if host in ("127.0.0.1", "localhost", "::1"):
        return []
    if host not in ("0.0.0.0", "::", ""):
        return [f"http://{host}:{port}"]
    addresses = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    return [f"http://{ip}:{port}" for ip in addresses]


def status():
    from ariadne import __version__
    from ariadne.services import backup

    path = startup_path()
    return {
        "version": __version__,
        "platform": sys.platform,
        "tray_available": tray.available(),
        "startup_supported": path is not None,
        "startup_enabled": bool(path and path.exists()),
        "startup_path": str(path) if path else "",
        "launcher": str(config.ROOT_DIR / "start.bat"),
        "host": config.BIND_HOST,
        "port": config.BIND_PORT,
        "urls": lan_urls(),
        "log_path": str(log_svc.path() or ""),
        "backup": backup.status(),
    }


def _when(stamp):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp)) if stamp else "never"


def diagnostics():
    """A text block for a bug report: versions, where things are, the
    posting settings, the accounts (never their secrets), what the
    scheduler last did, and the end of the log."""
    from ariadne import __version__, db, store
    from ariadne.services import updates

    settings = store.load_settings()
    tagger = settings.get("tagger") or {}
    kept = {
        "posting": settings.get("posting"), "warm_thumbs": settings.get("warm_thumbs"),
        "check_updates": settings.get("check_updates"), "delete_mode": settings.get("delete_mode"),
        "thumb_quality": settings.get("thumb_quality"),
        "tagger": {"backend": tagger.get("backend"), "model": tagger.get("model")},
        "auto_folders": len(settings.get("auto_folders") or []),
        "extra_roots": len(settings.get("extra_roots") or []),
    }
    lines = [
        f"Ariadne {__version__}",
        f"Python {platform.python_version()} on {platform.platform()}",
        f"App dir: {config.APP_DIR}",
        f"Data dir: {config.paths.data_dir}",
        f"Log: {log_svc.path() or '(none)'}",
        f"Bound to {config.BIND_HOST}:{config.BIND_PORT}; "
        f"reachable at {', '.join(lan_urls()) or 'this computer only'}",
        f"Prompt search: {'FTS5' if db.FTS_ENABLED else 'LIKE fallback'}",
        f"Settings: {json.dumps(kept)}",
        "",
    ]
    d = db.db()
    images = d.execute("SELECT COUNT(*) c FROM images").fetchone()["c"] if db._has_table(d, "images") else 0
    lines.append(f"Images indexed: {images}")
    if db._has_table(d, "posts"):          # the public build has no posting side
        from ariadne.services import accounts as accounts_svc
        from ariadne.services import scheduler as scheduler_svc

        counts = {r["status"]: r["n"] for r in d.execute("SELECT status, COUNT(*) n FROM posts GROUP BY status")}
        lines.append(f"Posts: {json.dumps(counts) if counts else 'none'}")
        lines.append("Accounts:")
        for a in accounts_svc.list_accounts():
            check = ("ok" if a["last_check_ok"] else f"failed: {a['last_check_msg']}") \
                if a["last_check_at"] else "not checked"
            defaults = a.get("defaults") if isinstance(a.get("defaults"), dict) else {}
            cap = defaults.get("max_per_day") or 0
            lines.append(f"  {a['label']} ({a['platform']}): {'on' if a['enabled'] else 'off'}, "
                         f"check {check} at {_when(a['last_check_at'])}, last post {_when(a['last_post_at'])}"
                         f"{f', cap {cap}/day' if cap else ''}")
        if not accounts_svc.list_accounts():
            lines.append("  none")
        s = scheduler_svc.scheduler
        alive = bool(s._thread and s._thread.is_alive())
        lines.append(f"Scheduler: {'running' if alive else 'not running'}, last pass {_when(s.last_run)}, "
                     f"last worked on {s.last_worked or 'nothing'}")
    u = updates.state()
    problem = f", error: {u['error']}" if u["error"] else ""
    lines.append(f"Updates: latest {u['latest'] or 'unknown'}, checked {_when(u['checked_at'])}{problem}")
    lines += ["", f"--- last {LOG_LINES} log lines ---", log_svc.tail(LOG_LINES).rstrip()]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# bug reports
# --------------------------------------------------------------------------

def issue_url():
    """Where a bug report goes: a new issue in the public repository."""
    return f"https://github.com/{config.UPDATE_REPO}/issues/new"


def _typed(value, limit=REPORT_FIELD):
    value = (value or "").replace("\r\n", "\n").strip()
    return value[:limit].rstrip() + ("…" if len(value) > limit else "")


def report(summary, steps="", include_diagnostics=True):
    """A bug report from what the user typed. Returns ``title`` and
    ``body`` (the issue's markdown), ``url`` (the new-issue page with both
    filled in, which the user reads and submits there: nothing leaves this
    computer before that), ``text`` (the whole report as plain text, for
    the clipboard or a file) and ``cut`` (whether the prefilled body had
    to leave out older log lines to fit in an address; the text has them
    all). The diagnostics name folders and accounts, never a secret."""
    from ariadne import __version__

    summary, steps = _typed(summary), _typed(steps)
    title = (summary.splitlines() or [""])[0].strip()[:120] or "Bug report"
    diag = diagnostics() if include_diagnostics else ""
    marker = f"--- last {LOG_LINES} log lines ---\n"
    head, _, tail = diag.partition(marker)
    log_lines = tail.strip("\n").split("\n") if tail.strip("\n") else []

    def compose(kept):
        parts = [f"**What went wrong**\n{summary or '(not said)'}",
                 f"**What I did just before**\n{steps or '(not said)'}",
                 f"Ariadne {__version__}, Python {platform.python_version()} on {platform.platform()}"]
        if include_diagnostics:
            left_out = len(log_lines) - kept
            shown = "\n".join(log_lines[left_out:])
            note = (f"\n({left_out} older log lines left out here; the downloaded report has them.)"
                    if left_out else "")
            parts.append("<details><summary>Diagnostics</summary>\n\n```text\n"
                         + head.rstrip("\n") + "\n--- last log lines ---\n" + shown + note + "\n```\n</details>")
        return "\n\n".join(parts) + "\n"

    def address(body):
        return issue_url() + "?" + urlencode({"title": title, "body": body, "labels": "bug"})

    kept = len(log_lines)
    body = compose(kept)
    url = address(body)
    while len(url) > REPORT_URL and kept > 0:
        kept = max(0, kept - max(1, kept // 4))         # a quarter of the lines at a time
        body = compose(kept)
        url = address(body)
    text = (f"{title}\n\nWhat went wrong:\n{summary or '(not said)'}\n\n"
            f"What I did just before:\n{steps or '(not said)'}\n\n"
            + (diag or f"Ariadne {__version__}, Python {platform.python_version()} on {platform.platform()}\n"))
    return {"title": title, "body": body, "url": url, "text": text,
            "cut": kept < len(log_lines), "repo": config.UPDATE_REPO}


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def enable_startup():
    """A shortcut in the Startup folder that runs the launcher in tray mode
    without opening a browser tab."""
    path = startup_path()
    if path is None:
        return False, "Start at logon is only wired up on Windows so far."
    target = config.ROOT_DIR / "start.bat"
    icon = config.ROOT_DIR / "icon.ico"
    script = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(path)})
$s.TargetPath = {_ps_quote(target)}
$s.Arguments = '--tray --no-browser'
$s.WorkingDirectory = {_ps_quote(config.ROOT_DIR)}
$s.Description = 'Ariadne (background)'
$s.WindowStyle = 7
{f"$s.IconLocation = {_ps_quote(icon)}" if icon.exists() else ""}
$s.Save()
"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       check=True, capture_output=True, timeout=30)
    except FileNotFoundError:
        return False, "PowerShell was not found, so the shortcut could not be made."
    except subprocess.CalledProcessError as exc:
        return False, f"Windows refused to make the shortcut: {exc.stderr.decode()[:200]}"
    except subprocess.SubprocessError as exc:
        return False, str(exc)[:200]
    return True, f"Ariadne will start in the tray when you log in ({path})."


def disable_startup():
    path = startup_path()
    if path is None:
        return False, "Not supported on this platform."
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        return False, str(exc)[:200]
    return True, "Removed from startup."
