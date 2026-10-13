"""End-to-end checks through the Flask test client: the page, settings, the
path guard, ratings and tags over the index, the trash, projects."""

import os

from ariadne.services import ratings as ratings_svc
from tests.conftest import register_folder, scan_rows


def test_stats_and_pages(client):
    stats = client.get("/api/stats").json
    assert stats["images_indexed"] == 0 and stats["rated"] == 0
    assert client.get("/").status_code in (200, 503)   # 503 only without a built bundle
    assert client.get("/legacy").status_code == 404


def test_settings_roundtrip(client):
    settings = client.get("/api/settings").json
    assert "hotkeys" in settings
    settings["theme"] = 2
    assert client.post("/api/settings", json=settings).json["success"]
    assert client.get("/api/settings").json["theme"] == 2


def test_folder_index_reads_metadata(client, library):
    register_folder(client, library["folder"])
    rows = scan_rows(client, library["folder"])
    assert len(rows) == 7
    by_name = {r["name"]: r for r in rows}
    assert by_name["gen_00.png"]["prompt"].startswith("subject 0")
    assert by_name["gen_00.png"]["model"] == "testmodel_v1"
    assert by_name["gen_00.png"]["seed"] == "1000"
    assert by_name["plain.png"]["prompt"] == ""
    assert client.get("/api/stats").json["images_indexed"] == 7


def test_guard_blocks_unregistered_paths(client, library):
    # nothing registered yet: the file exists but is outside every root
    res = client.get("/image?path=" + library["paths"][0])
    assert res.status_code == 404
    register_folder(client, library["folder"])
    res = client.get("/image?path=" + library["paths"][0])
    assert res.status_code == 200
    thumb = client.get("/thumb?path=" + library["paths"][0])
    assert thumb.status_code == 200
    assert thumb.mimetype == "image/webp"


def test_rate_tag_and_search(client, library):
    register_folder(client, library["folder"])
    first, second = library["paths"][:2]
    assert client.post("/api/ratings", json={"paths": [first], "stars": 5}).json["success"]
    assert client.post("/api/tags", json={"paths": [first, second],
                                          "add_tags": ["portrait"]}).json["success"]
    tags = client.get("/api/tags/all").json["tags"]
    assert tags == [{"tag": "portrait", "count": 2}]

    rows = scan_rows(client, library["folder"])
    by_path = {r["path"]: r for r in rows}
    assert by_path[first]["stars"] == 5
    assert by_path[second]["stars"] == 0
    assert by_path[first]["user_tags"] == ["portrait"]

    # library-wide search over the index
    hits = client.get("/api/images?q=tag: portrait").json["rows"]
    assert {h["path"] for h in hits} == {first, second}
    hits = client.get('/api/images?q=prompt: "subject 3..."').json["rows"]
    assert [os.path.basename(h["path"]) for h in hits] == ["gen_03.png"]

    # the old like / love actions are gone; only trash remains on /api/action
    assert client.post("/api/action", json={"paths": [first], "action": "loved"}).status_code == 400


def test_soft_trash_and_restore(client, library):
    register_folder(client, library["folder"])
    victim = library["paths"][0]
    client.post("/api/tags", json={"paths": [victim], "tags": ["keep-me"]})
    client.post("/api/ratings", json={"paths": [victim], "stars": 4})
    res = client.post("/api/action", json={"paths": [victim], "action": "trash"}).json
    assert res["success"] and len(res["trashed"]) == 1
    assert not os.path.exists(victim)
    assert ratings_svc.get_one(victim)["stars"] == 0
    listing = client.get("/api/trash").json["items"]
    assert listing[0]["original_path"] == victim
    assert listing[0]["tags"] == ["keep-me"]
    assert listing[0]["stars"] == 4

    res = client.post("/api/trash/restore", json={"ids": [listing[0]["id"]]}).json
    assert res["restored"][0]["path"] == victim
    assert os.path.exists(victim)
    row = client.get("/api/images/one?path=" + victim).json["image"]
    assert row["user_tags"] == ["keep-me"] and row["stars"] == 4


def test_projects_switch_isolates_libraries(client, library):
    register_folder(client, library["folder"])
    client.post("/api/tags", json={"paths": [library["paths"][0]], "tags": ["only-here"]})
    assert client.get("/api/tags/all").json["tags"]

    res = client.post("/api/projects/create", json={"name": "Second"}).json
    assert res["success"]
    assert client.get("/api/tags/all").json["tags"] == []
    assert client.get("/api/history").json["history"] == []

    assert client.post("/api/projects/switch", json={"id": "default"}).json["success"]
    assert client.get("/api/tags/all").json["tags"][0]["tag"] == "only-here"
