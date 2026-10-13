"""Retire the legacy page's table.

``categories`` (liked / loved) became star ratings in m0001; the importer
copied them across on every start. This migration runs it one last time, in
case a library jumps straight from the old build, then drops the table. The
trash remembers stars instead of a category from here on.
"""


def _has_table(d, name):
    return d.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                     (name,)).fetchone() is not None


def up(d):
    from ariadne.services import importers

    if _has_table(d, "categories"):
        importers.import_categories()
    d.execute("DROP TABLE IF EXISTS categories")

    present = {row[1] for row in d.execute("PRAGMA table_info(trash)")}
    if "stars" not in present:
        d.execute("ALTER TABLE trash ADD COLUMN stars INTEGER DEFAULT 0")
