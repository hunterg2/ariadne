"""Running Ariadne as a background service: tray availability and the
start-at-logon shortcut (Windows; other platforms report not supported)."""

import os
import socket
import subprocess
import sys
from pathlib import Path

from ariadne import config, tray

SHORTCUT_NAME = "Ariadne.lnk"


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
    path = startup_path()
    return {
        "platform": sys.platform,
        "tray_available": tray.available(),
        "startup_supported": path is not None,
        "startup_enabled": bool(path and path.exists()),
        "startup_path": str(path) if path else "",
        "launcher": str(config.ROOT_DIR / "start.bat"),
        "host": config.BIND_HOST,
        "port": config.BIND_PORT,
        "urls": lan_urls(),
    }


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
