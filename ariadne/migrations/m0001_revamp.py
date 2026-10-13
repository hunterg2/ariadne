"""Revamp tables: the image index, star ratings, tag definitions and
collections.

Nothing legacy is dropped here. ``categories`` stays until m0003 retires the
old page; the importer copies its rows across.
"""

SQL = """
CREATE TABLE IF NOT EXISTS images (
    path        TEXT PRIMARY KEY,
    folder      TEXT NOT NULL,
    folder_name TEXT,
    name        TEXT NOT NULL,
    ext         TEXT,
    mtime       INTEGER,
    size        INTEGER,
    ctime       REAL,
    width       INTEGER,
    height      INTEGER,
    kind        TEXT,
    missing     INTEGER DEFAULT 0,
    indexed_at  REAL,
    seen_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_images_folder ON images(folder);
CREATE INDEX IF NOT EXISTS idx_images_ctime ON images(ctime);
CREATE INDEX IF NOT EXISTS idx_images_kind ON images(kind);
CREATE INDEX IF NOT EXISTS idx_images_pending ON images(indexed_at) WHERE indexed_at IS NULL;

CREATE TABLE IF NOT EXISTS ratings (
    path     TEXT PRIMARY KEY,
    stars    INTEGER DEFAULT 0,
    rejected INTEGER DEFAULT 0,
    label    TEXT,
    updated  REAL
);
CREATE INDEX IF NOT EXISTS idx_ratings_stars ON ratings(stars);

CREATE TABLE IF NOT EXISTS tag_defs (
    tag     TEXT PRIMARY KEY,
    grp     TEXT,
    color   TEXT,
    created REAL
);

CREATE TABLE IF NOT EXISTS collections (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'manual',
    query      TEXT,
    icon       TEXT,
    color      TEXT,
    sort_order INTEGER DEFAULT 0,
    created    REAL,
    updated    REAL
);
CREATE TABLE IF NOT EXISTS collection_items (
    collection_id TEXT NOT NULL,
    path          TEXT NOT NULL,
    position      INTEGER DEFAULT 0,
    added         REAL,
    PRIMARY KEY (collection_id, path)
);
CREATE INDEX IF NOT EXISTS idx_collection_items_path ON collection_items(path);
"""

META_EXTRAS = [
    ("kind", "TEXT"), ("camera_make", "TEXT"), ("camera_model", "TEXT"),
    ("lens", "TEXT"), ("exposure", "TEXT"), ("f_number", "TEXT"), ("iso", "TEXT"),
    ("focal", "TEXT"), ("taken_at", "TEXT"), ("lat", "REAL"), ("lon", "REAL"),
    ("software", "TEXT"),
]


def up(d):
    d.executescript(SQL)
    # the baseline meta table gained these columns in the same release; an
    # older database that kept its cache still needs them added
    present = {row[1] for row in d.execute("PRAGMA table_info(meta)")}
    for column, typ in META_EXTRAS:
        if column not in present:
            d.execute(f"ALTER TABLE meta ADD COLUMN {column} {typ}")
