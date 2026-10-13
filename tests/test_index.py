"""The image index: scanning, enrichment, kinds, paging, filters and search."""

import os
import time
from urllib.parse import quote

from PIL import Image

from tests.conftest import make_png, register_folder


def _scan(client, folder):
    res = client.post("/api/images/scan", json={"folder": folder, "wait": True})
    assert res.status_code == 200 and res.json["success"], res.json
    return res.json


def _photo(path):
    """A JPEG carrying camera EXIF and no generation chunk."""
    im = Image.new("RGB", (80, 60), (30, 120, 90))
    exif = Image.Exif()
    exif[0x010F] = "Canon"                 # Make
    exif[0x0110] = "EOS R6"                # Model
    exif[0x0131] = "Darktable"             # Software
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = "2024:05:01 10:20:30"    # DateTimeOriginal
    sub[0x8827] = 200                      # ISO
    im.save(path, "JPEG", exif=exif.tobytes())
    return str(path)


def test_scan_and_enrich_assigns_kinds(client, library, tmp_path):
    photo = _photo(tmp_path / "images" / "camera.jpg")
    register_folder(client, library["folder"])
    result = _scan(client, library["folder"])
    # registering the folder also queues it for the background indexer, which
    # may list it first on a slow machine; "added" then belongs to that pass
    assert result["total"] == 8 and result["summary"]["pending"] == 0

    page = client.get("/api/images?folder=" + library["folder"]).json
    assert page["total"] == 8
    kinds = {r["name"]: r["kind"] for r in page["rows"]}
    assert kinds["gen_00.png"] == "generated"
    assert kinds["plain.png"] == "other"
    assert kinds["camera.jpg"] == "photo"
    cam = next(r for r in page["rows"] if r["path"] == photo)["camera"]
    assert cam["make"] == "Canon" and cam["model"] == "EOS R6"
    assert cam["taken_at"].startswith("2024")
    assert cam["iso"] == "200"
    assert all(r["indexed"] for r in page["rows"])


def _remove(path):
    """Windows refuses to delete a file another thread still has open; the
    background indexer may be reading it, so give it a moment."""
    from ariadne.services.index import indexer
    indexer.stop()
    for attempt in range(20):
        try:
            os.remove(path)
            return
        except PermissionError:
            time.sleep(0.1)
    os.remove(path)


def test_rescan_tracks_changes_and_missing_files(client, library):
    register_folder(client, library["folder"])
    _scan(client, library["folder"])
    victim = library["paths"][0]
    _remove(victim)
    make_png(os.path.join(library["folder"], "new.png"), subject="brand new", seed=7)
    result = _scan(client, library["folder"])
    assert result["added"] == 1 and result["missing"] == 1
    page = client.get("/api/images?folder=" + library["folder"]).json
    names = {r["name"] for r in page["rows"]}
    assert "new.png" in names and os.path.basename(victim) not in names
    assert page["total"] == 7


def test_paging_sorting_and_filters(client, library):
    register_folder(client, library["folder"])
    _scan(client, library["folder"])
    base = "/api/images?folder=" + library["folder"]

    first = client.get(base + "&sort=name_asc&limit=3&offset=0").json
    second = client.get(base + "&sort=name_asc&limit=3&offset=3").json
    assert [r["name"] for r in first["rows"]] == ["gen_00.png", "gen_01.png", "gen_02.png"]
    assert [r["name"] for r in second["rows"]] == ["gen_03.png", "gen_04.png", "gen_05.png"]
    assert first["total"] == 7

    paths = library["paths"]
    client.post("/api/ratings", json={"paths": paths[:2], "stars": 4})
    client.post("/api/ratings", json={"paths": [paths[2]], "rejected": True})
    client.post("/api/tags", json={"paths": [paths[3]], "add_tags": ["hero"]})

    assert client.get(base + "&stars_min=4").json["total"] == 2
    assert client.get(base + "&rejected=1").json["total"] == 1
    assert client.get(base + "&rejected=0").json["total"] == 6
    assert client.get(base + "&tag=hero").json["total"] == 1
    assert client.get(base + "&kind=other").json["total"] == 1
    top = client.get(base + "&sort=stars_desc&limit=2").json["rows"]
    assert {r["path"] for r in top} == set(paths[:2])
    assert top[0]["stars"] == 4


def test_search_language_runs_in_sql(client, library):
    register_folder(client, library["folder"])
    _scan(client, library["folder"])
    client.post("/api/tags", json={"paths": library["paths"][:2], "add_tags": ["portrait"]})
    client.post("/api/ratings", json={"paths": library["paths"][:1], "stars": 5})

    def names(q):
        page = client.get("/api/images?q=" + quote(q)).json
        return sorted(r["name"] for r in page["rows"])

    assert names('prompt: "subject 3..."') == ["gen_03.png"]
    assert names("tag: portrait") == ["gen_00.png", "gen_01.png"]
    assert names("#portrait; prompt: ...detailed") == ["gen_00.png", "gen_01.png"]
    assert names("prompt: ...detailed & subject 1...") == ["gen_01.png"]
    assert names('prompt: "subject 1..." || "subject 2..."') == ["gen_01.png", "gen_02.png"]
    assert names("steps: 20...30") == [f"gen_{i:02d}.png" for i in range(6)]
    assert names("steps: 40...") == []
    assert names("stars: 5") == ["gen_00.png"]
    assert names("model: testmodel_v1; title: gen_0...") == [f"gen_{i:02d}.png" for i in range(6)]
    assert names("kind: other") == ["plain.png"]
    assert names("seed: 1001 || 1002") == ["gen_01.png", "gen_02.png"]


def test_whole_library_query_spans_folders(client, library, tmp_path):
    other = tmp_path / "more"
    other.mkdir()
    make_png(other / "extra.png", subject="extra one", seed=99)
    register_folder(client, library["folder"])
    register_folder(client, str(other))
    _scan(client, library["folder"])
    _scan(client, str(other))
    everything = client.get("/api/images?limit=50").json
    assert everything["total"] == 8
    assert client.get("/api/images?folder=" + str(other)).json["total"] == 1


def test_one_image_indexes_on_demand(client, library):
    register_folder(client, library["folder"])
    res = client.get("/api/images/one?path=" + library["paths"][4]).json
    assert res["success"]
    assert res["image"]["name"] == "gen_04.png"
    assert res["image"]["kind"] == "generated"
    assert res["image"]["seed"] == "1004"


def test_unregistered_folder_is_refused(client, library):
    res = client.get("/api/images?folder=" + library["folder"])
    assert res.status_code == 403
    res = client.post("/api/images/scan", json={"folder": library["folder"]})
    assert res.status_code == 403


def test_ratings_mirror_into_the_index(client, library):
    """Stars and the reject flag live in ratings but are copied onto images by
    triggers, so sorts and filters never join. Both directions: rate after
    the scan, and scan after rating."""
    from ariadne.db import db
    register_folder(client, library["folder"])
    paths = library["paths"]
    client.post("/api/ratings", json={"paths": [paths[3]], "stars": 2})     # before the scan
    _scan(client, library["folder"])
    client.post("/api/ratings", json={"paths": [paths[0]], "stars": 5})     # after the scan
    client.post("/api/ratings", json={"paths": [paths[1]], "rejected": True})
    mirrored = {r["path"]: (r["stars"], r["rejected"]) for r in
                db().execute("SELECT path, stars, rejected FROM images")}
    assert mirrored[paths[0]] == (5, 0) and mirrored[paths[3]] == (2, 0) and mirrored[paths[1]] == (0, 1)
    base = "/api/images?folder=" + library["folder"]
    top = client.get(base + "&sort=stars_desc&limit=2").json["rows"]
    assert [r["name"] for r in top] == ["gen_00.png", "gen_03.png"]
    assert client.get(base + "&rejected=0").json["total"] == 6
    assert client.get(base + "&stars_min=2").json["total"] == 2
    client.post("/api/ratings", json={"paths": [paths[0]], "stars": 0})
    assert db().execute("SELECT stars FROM images WHERE path=?", (paths[0],)).fetchone()[0] == 0


def test_prompt_search_uses_the_text_index(client, library):
    from ariadne import db as dbmod
    from ariadne.services.search import prepare_query, to_sql
    register_folder(client, library["folder"])
    _scan(client, library["folder"])
    sql, params, match = to_sql(prepare_query('prompt: "...subject 2..." || "...subject 4..." & night'))
    assert "meta_fts" not in sql and match == 'prompt: "subject 2" OR prompt: "subject 4"'
    assert to_sql(prepare_query('prompt: "ab..."'))[2] == ""        # too short for trigrams
    assert to_sql(prepare_query('title: "gen..."'))[2] == ""        # not an indexed column
    assert to_sql(prepare_query('title: gen...; negative: "...blur..."'))[2] == 'negative: "blur"'
    assert dbmod.db().execute("SELECT COUNT(*) FROM meta_fts").fetchone()[0] == 7
    hits = client.get("/api/images?q=" + quote('prompt: "...subject 2..." || "...subject 4..."')).json
    assert sorted(r["name"] for r in hits["rows"]) == ["gen_02.png", "gen_04.png"]
    # a re-read of a file updates the index in place
    make_png(os.path.join(library["folder"], "gen_02.png"), subject="renamed thing", seed=1002)
    _scan(client, library["folder"])
    assert client.get("/api/images?q=" + quote('prompt: "renamed..."')).json["total"] == 1
    assert client.get("/api/images?q=" + quote('prompt: "subject 2..."')).json["total"] == 0


def test_folder_summaries_in_one_call(client, library, tmp_path):
    register_folder(client, library["folder"])
    other = tmp_path / "other"
    other.mkdir()
    make_png(other / "x.png")
    register_folder(client, str(other))
    _scan(client, library["folder"])
    _scan(client, str(other))
    client.post("/api/ratings", json={"paths": library["paths"][:2], "stars": 3})
    client.post("/api/ratings", json={"paths": library["paths"][2:3], "rejected": True})
    res = client.post("/api/images/summaries", json={"folders": [library["folder"], str(other), "C:/nowhere"]}).json
    assert res["summaries"][library["folder"]] == {"total": 7, "unrated": 4, "rejected": 1, "pending": 0}
    assert res["summaries"][str(other)]["total"] == 1
    assert "C:/nowhere" not in res["summaries"]


def _nested(tmp_path):
    """root/{a,b}.png, root/sub/c.png, root/sub/deeper/d.png, plus images in
    root/trash and root/.hidden that a recursive scan must skip."""
    root = tmp_path / "tree"
    (root / "sub" / "deeper").mkdir(parents=True)
    (root / "trash").mkdir()
    (root / ".hidden").mkdir()
    make_png(root / "a.png", seed=1)
    make_png(root / "b.png", seed=2)
    make_png(root / "sub" / "c.png", seed=3)
    make_png(root / "sub" / "deeper" / "d.png", seed=4)
    make_png(root / "trash" / "t.png", seed=5)
    make_png(root / ".hidden" / "h.png", seed=6)
    return str(root)


def test_subfolders_scan_query_and_summaries(client, tmp_path):
    root = _nested(tmp_path)
    register_folder(client, root)
    assert _scan(client, root)["total"] == 2

    res = client.post("/api/images/scan", json={"folder": root, "wait": True, "recursive": True}).json
    assert res["success"] and res["recursive"] is True
    assert res["total"] == 4 and res["added"] == 2 and res["summary"]["total"] == 4

    flat = client.get("/api/images?folder=" + quote(root)).json
    deep = client.get("/api/images?folder=" + quote(root) + "&recursive=1").json
    assert flat["total"] == 2 and deep["total"] == 4
    assert {r["name"] for r in deep["rows"]} == {"a.png", "b.png", "c.png", "d.png"}
    # rows keep their real parent, so a subfolder can be opened on its own
    assert {r["folder"] for r in deep["rows"]} == {root, os.path.join(root, "sub"),
                                                   os.path.join(root, "sub", "deeper")}
    sub = client.get("/api/images?folder=" + quote(os.path.join(root, "sub")) + "&recursive=1").json
    assert sub["total"] == 2
    # a sibling whose name merely starts with the root is not inside it
    sibling = tmp_path / "tree2"
    sibling.mkdir()
    make_png(sibling / "z.png", seed=9)
    register_folder(client, str(sibling))
    _scan(client, str(sibling))
    assert client.get("/api/images?folder=" + quote(root) + "&recursive=1").json["total"] == 4

    plain = client.post("/api/images/summaries", json={"folders": [root]}).json["summaries"]
    summed = client.post("/api/images/summaries", json={"folders": [root], "recursive": [root]}).json["summaries"]
    assert plain[root]["total"] == 2 and summed[root]["total"] == 4
    assert client.get("/api/images/summary?folder=" + quote(root) + "&recursive=1").json["total"] == 4

    # the sidebar remembers the choice per folder
    hist = client.post("/api/history/update", json={"path": root, "action": "recursive", "value": True}).json["history"]
    assert next(i for i in hist if i.get("path") == root)["recursive"] is True
    hist = client.post("/api/history/update", json={"path": root, "action": "recursive", "value": False}).json["history"]
    assert "recursive" not in next(i for i in hist if i.get("path") == root)


def test_scan_warms_thumbnails(client, library):
    from ariadne.services import thumbs

    register_folder(client, library["folder"])
    _scan(client, library["folder"])
    assert all(thumbs.thumb_path_for(p).exists() for p in library["paths"])

    client.post("/api/settings", json={"warm_thumbs": False})
    later = make_png(os.path.join(library["folder"], "later.png"), seed=99)
    _scan(client, library["folder"])
    assert not thumbs.thumb_path_for(later).exists()
