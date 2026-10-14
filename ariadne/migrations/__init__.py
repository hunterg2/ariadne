"""Versioned schema migrations.

Each module in this package is named ``mNNNN_<what>.py`` and defines
``up(d)``, which receives the open connection. ``apply()`` runs every module
whose number is above ``kv.db_version``, in order, after taking a backup.
Never edit a migration that has shipped; add a new one.
"""

import importlib
import pkgutil

from ariadne.db import backup_db, db, kv_get, kv_set
from ariadne.log import log


def available():
    names = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("m") and info.name[1:5].isdigit():
            names.append(info.name)
    return sorted(names)


def version_of(name):
    return int(name[1:5])


def current():
    try:
        return int(kv_get("db_version", "0") or 0)
    except ValueError:
        return 0


def apply():
    """Apply pending migrations. Returns the names that ran."""
    cur = current()
    pending = [n for n in available() if version_of(n) > cur]
    if not pending:
        return []
    if cur > 0:
        backup_db()          # an existing library gets a copy first
    d = db()
    for name in pending:
        module = importlib.import_module(f"ariadne.migrations.{name}")
        module.up(d)
        d.commit()
        kv_set("db_version", version_of(name))
        log.info(f"[migrate] applied {name}")
    return pending
