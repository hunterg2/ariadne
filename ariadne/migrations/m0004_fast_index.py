"""The 200k-image pass.

Every LEFT JOIN costs about five microseconds a row, so anything that walked
the whole index through ``ratings`` took a second. Stars and the reject flag
are now mirrored into ``images`` by triggers, which makes the common filters
and sorts index-only; the sort columns get indexes; and prompts get a
trigram FTS5 index so "contains" searches stop scanning every prompt.
"""

from ariadne.db import ensure_fts

SQL = """
CREATE INDEX IF NOT EXISTS idx_images_stars ON images(stars DESC, ctime DESC);
CREATE INDEX IF NOT EXISTS idx_images_name ON images(lower(name));
CREATE INDEX IF NOT EXISTS idx_images_size ON images(size);
CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime);

CREATE TRIGGER IF NOT EXISTS trg_ratings_ai AFTER INSERT ON ratings BEGIN
    UPDATE images SET stars=COALESCE(new.stars,0), rejected=COALESCE(new.rejected,0)
    WHERE path=new.path;
END;
CREATE TRIGGER IF NOT EXISTS trg_ratings_au AFTER UPDATE ON ratings BEGIN
    UPDATE images SET stars=COALESCE(new.stars,0), rejected=COALESCE(new.rejected,0)
    WHERE path=new.path;
END;
CREATE TRIGGER IF NOT EXISTS trg_ratings_ad AFTER DELETE ON ratings BEGIN
    UPDATE images SET stars=0, rejected=0 WHERE path=old.path;
END;
CREATE TRIGGER IF NOT EXISTS trg_images_ai AFTER INSERT ON images
WHEN EXISTS (SELECT 1 FROM ratings WHERE path=new.path) BEGIN
    UPDATE images SET
        stars=(SELECT COALESCE(stars,0) FROM ratings WHERE path=new.path),
        rejected=(SELECT COALESCE(rejected,0) FROM ratings WHERE path=new.path)
    WHERE path=new.path;
END;
"""


def up(d):
    present = {row[1] for row in d.execute("PRAGMA table_info(images)")}
    if "stars" not in present:
        d.execute("ALTER TABLE images ADD COLUMN stars INTEGER DEFAULT 0")
    if "rejected" not in present:
        d.execute("ALTER TABLE images ADD COLUMN rejected INTEGER DEFAULT 0")
    d.execute("UPDATE images SET stars=COALESCE((SELECT stars FROM ratings r WHERE r.path=images.path),0), "
              "rejected=COALESCE((SELECT rejected FROM ratings r WHERE r.path=images.path),0)")
    d.executescript(SQL)
    ensure_fts(d, rebuild=True)
