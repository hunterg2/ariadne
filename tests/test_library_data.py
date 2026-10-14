"""Ratings, collections, tag definitions, migrations and the legacy importer."""

from ariadne import migrations
from ariadne.db import db
from tests.conftest import register_folder


def test_migration_applied_once(app):
    # the numbering has gaps on purpose: m0002 and m0006 are not part of this build
    assert len(migrations.available()) == 4 and migrations.current() == 5
    assert migrations.apply() == []
    tables = {r["name"] for r in db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for name in ("images", "ratings", "tag_defs", "collections", "collection_items",
                 "meta", "tags", "trash", "thumbs", "kv"):
        assert name in tables
    assert not any(t in tables for t in ("accounts", "posts", "post_targets", "queue"))


def test_ratings_api_roundtrip(client, library):
    register_folder(client, library["folder"])
    a, b = library["paths"][:2]
    res = client.post("/api/ratings", json={"paths": [a], "stars": 5}).json
    assert res["ratings"][a]["stars"] == 5
    client.post("/api/ratings", json={"paths": [a], "stars": 2})
    assert db().execute("SELECT stars FROM ratings WHERE path=?", (a,)).fetchone()[0] == 2
    client.post("/api/ratings", json={"paths": [b], "rejected": True, "label": "red"})
    row = db().execute("SELECT rejected, label FROM ratings WHERE path=?", (b,)).fetchone()
    assert row["rejected"] == 1 and row["label"] == "red"
    # the legacy table is gone for good
    tables = {r["name"] for r in db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "categories" not in tables


def test_collections_crud_and_filter(client, library):
    register_folder(client, library["folder"])
    client.post("/api/images/scan", json={"folder": library["folder"], "wait": True})
    paths = library["paths"]
    res = client.post("/api/collections", json={"name": "Picks", "paths": paths[:3]}).json
    cid = res["id"]
    listing = client.get("/api/collections").json["collections"]
    assert listing[0]["name"] == "Picks" and listing[0]["count"] == 3

    page = client.get("/api/images?collection=" + cid).json
    assert page["total"] == 3
    assert all(cid in r["collections"] for r in page["rows"])

    client.post(f"/api/collections/{cid}/items", json={"paths": paths[:1], "remove": True})
    assert client.get("/api/images?collection=" + cid).json["total"] == 2
    client.post(f"/api/collections/{cid}/items", json={"paths": [paths[5]]})
    assert client.get("/api/collections").json["collections"][0]["count"] == 3

    res = client.patch(f"/api/collections/{cid}", json={"name": "Best"}).json
    assert res["collection"]["name"] == "Best"
    assert client.get("/api/images?q=collection: best").json["total"] == 3

    smart = client.post("/api/collections", json={"name": "Threes", "kind": "smart",
                                                  "query": "prompt: subject 3..."}).json
    assert smart["collection"]["kind"] == "smart"
    client.delete(f"/api/collections/{cid}")
    assert [c["name"] for c in client.get("/api/collections").json["collections"]] == ["Threes"]


def test_tag_definitions_rename_and_merge(client, library):
    register_folder(client, library["folder"])
    a, b, c = library["paths"][:3]
    client.post("/api/tags", json={"paths": [a, b], "add_tags": ["cat"]})
    client.post("/api/tags", json={"paths": [b, c], "add_tags": ["kitty"]})
    client.post("/api/tags/define", json={"tag": "cat", "group": "Subject", "color": "#f00"})

    tags = {t["tag"]: t for t in client.get("/api/tags/list").json["tags"]}
    assert tags["cat"]["group"] == "Subject" and tags["cat"]["count"] == 2

    res = client.post("/api/tags/merge", json={"sources": ["kitty"], "target": "cat"}).json
    assert res["moved"] == 2
    tags = {t["tag"]: t for t in client.get("/api/tags/list").json["tags"]}
    assert "kitty" not in tags and tags["cat"]["count"] == 3

    client.post("/api/tags/rename", json={"old": "cat", "new": "feline"})
    tags = {t["tag"]: t for t in client.get("/api/tags/list").json["tags"]}
    assert tags["feline"]["count"] == 3 and tags["feline"]["group"] == "Subject"

    client.post("/api/tags/delete", json={"tag": "feline"})
    assert client.get("/api/tags/list").json["tags"] == []


def test_importer_copies_legacy_categories_once(tmp_path, library):
    """A library from the old build: liked / loved rows become 3 and 5 stars
    when migration m0003 runs, and the table is dropped afterwards."""
    import sqlite3

    from ariadne import create_app
    data_dir = tmp_path / "legacy"
    data_dir.mkdir()
    conn = sqlite3.connect(str(data_dir / "organizer.db"))
    conn.executescript("""
        CREATE TABLE categories (path TEXT PRIMARY KEY, category TEXT NOT NULL);
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);
    """)
    a, b = library["paths"][:2]
    conn.execute("INSERT INTO categories VALUES (?,?)", (a, "loved"))
    conn.execute("INSERT INTO categories VALUES (?,?)", (b, "liked"))
    conn.commit()
    conn.close()

    app = create_app(app_dir=data_dir)
    with app.app_context():
        stars = {r["path"]: r["stars"] for r in db().execute("SELECT path, stars FROM ratings")}
        assert stars == {a: 5, b: 3}
        tables = {r["name"] for r in db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "categories" not in tables
        assert "stars" in {r[1] for r in db().execute("PRAGMA table_info(trash)")}
