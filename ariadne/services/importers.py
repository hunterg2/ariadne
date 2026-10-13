"""Copy legacy data into the revamp tables.

The old build kept liked / loved in a ``categories`` table. Migration m0003
runs ``import_categories`` once before dropping that table, so a library that
jumps straight from the old build keeps its ratings. Idempotent: only paths
with no rating yet are touched.
"""

import time

from ariadne.db import db


def import_categories():
    """liked -> 3 stars, loved -> 5 stars, for paths without a rating yet."""
    d = db()
    cur = d.execute(
        "INSERT INTO ratings (path, stars, rejected, label, updated) "
        "SELECT c.path, CASE c.category WHEN 'loved' THEN 5 WHEN 'liked' THEN 3 ELSE 0 END, "
        "0, NULL, ? FROM categories c WHERE c.path NOT IN (SELECT path FROM ratings)",
        (time.time(),))
    d.commit()
    return cur.rowcount
