"""One log file for everything the app reports: ``ariadne.log`` in the app
directory, rotated at 1 MB with three older copies kept.

Every module logs through ``log`` here. The lines also go to the console
when there is one, but in tray mode or from the release launcher the file
is the only record of why a scheduled post failed at three in the morning.
Werkzeug's per-request lines stay on the console: a thumbnail-heavy
session would fill the file with nothing anyone needs.
"""

import logging
import logging.handlers
from collections import deque
from pathlib import Path

NAME = "ariadne.log"
MAX_BYTES = 1_000_000
KEEP = 3

log = logging.getLogger("ariadne")
_file = None
_console = None


def setup(app_dir, console=True):
    """Point the file handler at ``app_dir``. A second call (tests, a
    project switch to another app dir) moves the file. Returns its path."""
    global _file, _console
    log.setLevel(logging.INFO)
    log.propagate = False
    if _file is not None:
        log.removeHandler(_file)
        _file.close()
        _file = None
    target = Path(app_dir) / NAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=MAX_BYTES, backupCount=KEEP, encoding="utf-8")
    except OSError as exc:              # a read-only folder: the console still works
        handler = None
        log.warning(f"[log] could not open {target}: {exc}")
    if handler is not None:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname).1s %(message)s",
                                               "%Y-%m-%d %H:%M:%S"))
        log.addHandler(handler)
        _file = handler
    if console and _console is None:
        _console = logging.StreamHandler()
        _console.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(_console)
    return target


def path():
    """Where the log is being written, or None before ``setup``."""
    return Path(_file.baseFilename) if _file is not None else None


def tail(lines=200):
    """The last ``lines`` of the current file, for the diagnostics copy."""
    target = path()
    if target is None or not target.exists():
        return ""
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            return "".join(deque(f, maxlen=lines))
    except OSError:
        return ""
