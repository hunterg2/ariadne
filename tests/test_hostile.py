"""Hostile and clumsy input: JSON of the wrong shape, paths outside the
library, a settings file edited by hand. Each case here once broke later
requests, lost data or let a path through."""

import io
import json
import os
import shutil
import sqlite3
import struct
import threading
import zlib

import pytest
from PIL import Image

from ariadne.services import auth
from tests.conftest import make_png, register_folder, scan_rows

# --------------------------------------------------------------------------
# request shapes and error answers
# --------------------------------------------------------------------------

def test_non_object_bodies_are_refused(client):
    good = client.get("/api/settings").json
    good["theme"] = 2
    assert client.post("/api/settings", json=good).json["success"]
    for body in ([], "str", 123, True):
        res = client.post("/api/settings", json=body)
        assert res.status_code == 400 and res.json["success"] is False
    # an empty list used to reset every setting to its default
    assert client.get("/api/settings").json["theme"] == 2


def test_api_errors_are_json(app):
    @app.route("/api/_boom")
    def boom():
        raise RuntimeError("kaboom")

    client = app.test_client()
    res = client.get("/api/no/such/route")
    assert res.status_code == 404 and res.json["success"] is False
    res = client.post("/api/settings", data="{not json", content_type="application/json")
    assert res.status_code == 400 and "JSON" in res.json["error"]
    res = client.post("/api/settings", data="hello", content_type="text/plain")
    assert res.status_code == 415 and res.json["success"] is False
    # the page shell keeps the plain 404
    assert "json" not in client.get("/nope").headers["Content-Type"]
    # an exception nothing caught answers JSON once pytest's propagation is off
    app.config["TESTING"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    res = client.get("/api/_boom")
    assert res.status_code == 500 and res.json["error"] == "RuntimeError: kaboom"


def test_query_numbers_that_are_not(client):
    assert client.get("/api/images?offset=99999999999999999999&stars_min=1e400").status_code == 200
    assert client.get("/api/browse?path=%00").status_code == 400


# --------------------------------------------------------------------------
# the path guard
# --------------------------------------------------------------------------

def test_tags_only_for_library_files(client, library, tmp_path):
    register_folder(client, library["folder"])
    outside = make_png(tmp_path / "outside.png")
    assert client.post("/api/tags", json={"paths": [outside, 5, None], "tags": ["smuggled"]}).json["success"]
    # a tagged path counts as a library file, so the tag must never be written
    assert client.get("/image?path=" + outside).status_code == 404
    assert client.get("/api/tags/all").json["tags"] == []


def test_recursive_toggle_only_indexes_listed_folders(client, library, tmp_path):
    from ariadne.services.index import indexer

    other = tmp_path / "other"
    other.mkdir()
    secret = make_png(other / "x.png")
    register_folder(client, library["folder"])
    res = client.post("/api/history/update", json={"path": str(other), "action": "recursive", "value": True})
    assert res.status_code == 200
    indexer.stop()
    assert client.get("/api/images/one?path=" + secret).status_code == 404
    assert client.get("/image?path=" + secret).status_code == 404


def test_trash_takes_files_not_folders(client, library):
    register_folder(client, library["folder"])
    sub = os.path.join(library["folder"], "sub")
    os.makedirs(sub)
    res = client.post("/api/action", json={"paths": [sub, 5, None], "action": "trash"}).json
    assert res["success"] and res["trashed"] == []
    assert os.path.isdir(sub)


def test_image_routes_refuse_folders(client, library):
    register_folder(client, library["folder"])
    assert client.get("/image?path=" + library["folder"]).status_code == 404
    assert client.get("/thumb?path=" + library["folder"]).status_code == 404


# --------------------------------------------------------------------------
# settings and the sidebar list
# --------------------------------------------------------------------------

def test_bad_settings_shapes_do_not_break_later_requests(client, library):
    register_folder(client, library["folder"])
    first = library["paths"][0]
    good = client.get("/api/settings").json
    for bad in ({"thumb_quality": "abc"}, {"auto_folders": "abc"}, {"auto_folders": [{"path": 5}, "x", None]},
                {"extra_roots": [5, None]}, {"extra_roots": "C:\\"}, {"hotkeys": None}, {"ui": []},
                {"tagger": 5}, {"thumb_quality": 1e9}):
        assert client.post("/api/settings", json={**good, **bad}).status_code == 200, bad
        settings = client.get("/api/settings").json
        assert client.get("/thumb?path=" + first).status_code == 200, bad
        assert client.get("/api/history").status_code == 200, bad
        assert client.get("/api/images?folder=" + library["folder"]).status_code == 200, bad
    assert settings["tagger"]["backend"] == "prompt" and settings["ui"]["grid_size"] == 250
    # a string where a list belongs is not a root ("C:\" would have been one per character)
    assert settings["extra_roots"] == []
    # a number written as text is the number; 0 and 1 are the booleans
    client.post("/api/settings", json={**good, "thumb_quality": "90", "warm_thumbs": 0, "theme": "2"})
    settings = client.get("/api/settings").json
    assert settings["thumb_quality"] == 90 and settings["warm_thumbs"] is False and settings["theme"] == 2
    # keys the defaults do not know pass through
    client.post("/api/settings", json={**good, "ui": {**good["ui"], "mine": [1, 2]}})
    assert client.get("/api/settings").json["ui"]["mine"] == [1, 2]


def test_settings_file_edited_by_hand(client, tmp_path):
    from ariadne import config

    root = str(tmp_path / "pics")
    config.paths.settings_file.write_text(json.dumps({
        "auto_folders": "oops", "thumb_quality": "high", "extra_roots": [1, root]}),
        encoding="utf-8")
    settings = client.get("/api/settings").json
    assert settings["auto_folders"] == [] and settings["thumb_quality"] == 82
    assert settings["extra_roots"] == [root]


def test_bad_sidebar_sync_is_cleaned(client, library):
    register_folder(client, library["folder"])
    first = library["paths"][0]
    assert client.post("/api/history/sync", json={"history": "abc"}).status_code == 400
    assert client.post("/api/history/sync", json={"history": None}).status_code == 400
    ok = client.post("/api/history/sync", json={"history": [
        {"type": "folder", "path": library["folder"]}, {"type": "folder", "path": 5}, 7, None,
        {"type": "group", "id": "g", "name": "G", "items": "abc"}]})
    assert ok.status_code == 200
    history = client.get("/api/history").json["history"]
    assert [h["type"] for h in history] == ["folder", "group"]
    assert history[1]["items"] == []
    assert client.get("/image?path=" + first).status_code == 200


def test_repath_normalises_the_new_path(client, library, tmp_path):
    register_folder(client, library["folder"])
    moved = str(tmp_path / "moved")
    shutil.move(library["folder"], moved)
    odd = os.path.join(str(tmp_path), "nowhere", "..", "moved")
    res = client.post("/api/history/repath", json={"old": library["folder"], "new": odd}).json
    assert res["success"] and res["path"] == moved
    assert client.get("/api/history").json["history"][0]["path"] == moved
    assert client.post("/api/history/repath", json={"old": 5, "new": []}).status_code == 400


# --------------------------------------------------------------------------
# projects and the import
# --------------------------------------------------------------------------

def test_project_delete_removes_its_folder(client):
    pid = client.post("/api/projects/create", json={"name": "Temp"}).json["id"]
    folder = next(p["folder"] for p in client.get("/api/projects").json["projects"] if p["id"] == pid)
    assert os.path.isdir(folder)
    # the open database used to survive the delete on Windows
    assert client.post("/api/projects/delete", json={"id": pid}).json["success"]
    assert not os.path.exists(folder)
    assert client.get("/api/projects").json["active"] == "default"
    assert client.post("/api/projects/create", json={"name": 5}).status_code == 400


def test_malformed_import_keeps_the_library(client, library, monkeypatch):
    from ariadne.api import projects as projects_api

    register_folder(client, library["folder"])
    first = library["paths"][0]
    client.post("/api/ratings", json={"paths": [first], "stars": 4})
    client.post("/api/tags", json={"paths": [first], "tags": ["precious"]})

    # entries that make no sense are skipped, the rest goes in
    res = client.post("/api/library/import", json={"mode": "merge", "data": {
        "format": "ariadne-library",
        "ratings": {"p": {"stars": "abc"}, "q": {"stars": 1e400}, "r": {"stars": "3", "label": 5}, "s": 7},
        "tags": {"p": [None, {}, "ok", 5], "t": "abc"}}}).json
    assert res["success"] and res["ratings"] == 1 and res["tag_links"] == 2
    assert client.get("/api/library/export").json["ratings"]["r"]["stars"] == 3
    assert client.post("/api/library/import", json={"mode": "merge", "data": []}).status_code == 400

    # a write that fails half-way leaves the library as it was: "replace"
    # used to have its deletes committed by the next request and its
    # inserts never made
    real_db = projects_api.db

    class Flaky:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def executemany(self, *args):
            raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(projects_api, "db", lambda: Flaky(real_db()))
    res = client.post("/api/library/import", json={"mode": "replace", "data": {
        "format": "ariadne-library", "ratings": {"p": {"stars": 1}}, "tags": {}}})
    assert res.status_code == 500
    monkeypatch.undo()
    client.post("/api/ratings", json={"paths": [library["paths"][1]], "stars": 1})   # commits
    row = client.get("/api/images/one?path=" + first).json["image"]
    assert row["stars"] == 4 and row["user_tags"] == ["precious"]


# --------------------------------------------------------------------------
# the PIN and the Host check
# --------------------------------------------------------------------------

def test_pin_typed_as_a_number(client, monkeypatch):
    monkeypatch.setattr(auth, "MISS_DELAY", 0)
    assert client.post("/api/settings/pin", json={"pin": 1234}).status_code == 200
    assert client.post("/api/settings/pin", json={"pin": [1, 2, 3, 4]}).status_code == 400
    remote = {"REMOTE_ADDR": "10.0.0.9"}
    assert client.post("/api/auth/pin", json={"pin": 1234}, environ_base=remote).status_code == 200
    assert client.post("/api/auth/pin", json={"pin": {}}, environ_base=remote).status_code == 401
    assert client.post("/api/auth/pin", json={"pin": "9999"}, environ_base=remote).status_code == 401
    client.delete("/api/settings/pin")


@pytest.mark.parametrize("host", ["localhost.", "LOCALHOST:5000", "127.0.0.1.", "[::1]:5000"])
def test_host_spellings_of_this_computer(client, host):
    assert client.get("/api/stats", headers={"Host": host}).status_code == 200


# --------------------------------------------------------------------------
# half an emoji
# --------------------------------------------------------------------------

def test_lone_surrogates_become_replacement_characters(client, library):
    """A JSON string can carry an unpaired UTF-16 surrogate; SQLite and
    UTF-8 files cannot. It used to be a 500 from whichever table it reached."""
    register_folder(client, library["folder"])
    first = library["paths"][0]
    assert client.post("/api/tags", json={"paths": [first], "tags": ["half \ud83e", "\U0001f98a whole"]}).json["success"]
    assert {t["tag"] for t in client.get("/api/tags/all").json["tags"]} == {"\U0001f98a whole", "half �"}
    good = client.get("/api/settings").json
    assert client.post("/api/settings", json={**good, "last_folder": "\ud83e"}).status_code == 200
    assert client.get("/api/settings").json["last_folder"] == "�"
    assert client.post("/api/collections", json={"name": "\udd8a"}).json["collection"]["name"] == "�"


def test_file_named_with_half_an_emoji_is_skipped(client, library):
    """NTFS allows an unpaired surrogate in a name; one such file used to
    fail the scan of the whole folder."""
    bad = os.path.join(library["folder"], "bad\ud83e.png")
    try:
        make_png(bad)
    except (OSError, UnicodeEncodeError):
        pytest.skip("this file system refuses the name")
    register_folder(client, library["folder"])
    res = client.post("/api/images/scan", json={"folder": library["folder"], "wait": True}).json
    assert res["success"] and res["total"] == 7
    names = {os.path.basename(r["path"]) for r in client.get("/api/images?folder=" + library["folder"]).json["rows"]}
    assert "plain.png" in names and len(names) == 7


# --------------------------------------------------------------------------
# a network share that does not answer
# --------------------------------------------------------------------------

def test_dead_root_is_resolved_once(client, library, tmp_path, monkeypatch):
    """The allowed roots are re-read every 5 s and each was realpath'ed
    again, which for a share that does not answer is seconds per attempt."""
    from ariadne import safety

    register_folder(client, library["folder"])
    first = library["paths"][0]
    dead = str(tmp_path / "share-that-is-gone")
    calls = []
    real = os.path.realpath

    def counting(path, *args, **kwargs):
        if path == dead:
            calls.append(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(safety.os.path, "realpath", counting)
    assert client.post("/api/history/sync", json={"history": [
        {"type": "folder", "path": library["folder"]}, {"type": "folder", "path": dead}]}).status_code == 200
    # the sync queued a scan, whose thread reads the roots too: count from
    # a clean slate on this thread alone
    from ariadne.services.index import indexer
    indexer.stop()
    calls.clear()
    safety._real.pop(dead, None)
    for _ in range(3):
        safety._roots_cache["ts"] = 0          # as if 5 s had passed
        assert client.get("/image?path=" + first).status_code == 200
    assert len(calls) == 1
    assert dead in safety.allowed_roots()


# --------------------------------------------------------------------------
# a decompression bomb in the library
# --------------------------------------------------------------------------

def test_huge_image_is_refused_not_decoded(client, library, monkeypatch):
    """A 300 KB PNG claiming 50,000 x 50,000 pixels used to make the indexer
    and every thumbnail request allocate the whole picture. Pillow's ceiling
    is on (one place, ariadne/__init__.py) and a refusal reads as a file
    that cannot be read. Lowered here so a small test image trips it."""
    from PIL import Image

    from ariadne import metadata
    from ariadne.services.index import indexer

    assert Image.MAX_IMAGE_PIXELS == 1_000_000_000      # metadata.py no longer switches it off
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)   # the test PNGs are 64 x 48
    register_folder(client, library["folder"])
    first = library["paths"][0]
    res = client.post("/api/images/scan", json={"folder": library["folder"], "wait": True})
    assert res.status_code == 200 and res.json["success"]
    indexer.stop()
    meta = metadata.extract(first)
    assert meta["source"] == "unreadable (DecompressionBombError)"
    assert client.get("/api/images/one?path=" + first).status_code == 200
    thumb = client.get("/thumb?path=" + first)
    assert thumb.status_code == 200 and thumb.mimetype == "image/png"   # the original, no thumbnail


# --------------------------------------------------------------------------
# second pass: requests from other web pages, files that are not images,
# uploads, deep bodies, long searches, spellings, the database under a switch
# --------------------------------------------------------------------------

CROSS = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site",
         "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}


def _bomb_png(width=100_000, height=100_000):
    """A hundred-byte PNG whose header claims ten gigapixels."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b""))


def _tiny_png():
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, "PNG")
    buf.seek(0)
    return buf


def test_requests_from_other_web_pages_are_refused(client, library):
    """A page on another site cannot read this server's answers, but a GET
    with a side effect, a form post (no preflight for those) or a
    navigation to /image would still act. Browsers say where a request
    came from, and those are turned away at the gate."""
    register_folder(client, library["folder"])
    first = library["paths"][0]
    before = open(first, "rb").read()
    # a form post that would have replaced the original
    res = client.post("/api/edit/save", content_type="multipart/form-data", headers=CROSS, data={
        "payload": json.dumps({"source_path": first, "format": "png", "dest": "overwrite"}),
        "image": (_tiny_png(), "x.png")})
    assert res.status_code == 403 and res.json["success"] is False
    assert open(first, "rb").read() == before
    assert client.get("/api/tag/auto?path=" + first, headers=CROSS).status_code == 403
    assert client.get("/image?path=" + first, headers=CROSS).status_code == 403
    assert client.get("/thumb?path=" + first, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    for origin in ("https://evil.example", "null", "http://127.0.0.1.evil.example"):
        res = client.post("/api/ratings", json={"paths": [first], "stars": 4}, headers={"Origin": origin})
        assert res.status_code == 403, origin
    assert client.get("/api/images/one?path=" + first).json["image"]["stars"] == 0
    # the app's own requests: its origin, the dev server's port, a typed
    # address, a tool that sends neither header
    own = {"Sec-Fetch-Site": "same-origin", "Origin": "http://localhost"}
    assert client.post("/api/ratings", json={"paths": [first], "stars": 4}, headers=own).status_code == 200
    dev = {"Sec-Fetch-Site": "same-origin", "Origin": "http://localhost:5173"}
    assert client.post("/api/ratings", json={"paths": [first], "stars": 3}, headers=dev).status_code == 200
    assert client.get("/image?path=" + first, headers={"Sec-Fetch-Site": "none"}).status_code == 200
    assert client.get("/image?path=" + first).status_code == 200


def test_tag_stream_takes_the_tagger_from_settings_alone(client, library, monkeypatch):
    """``/api/tag/auto?url=...`` sent the request wherever the query said,
    with the stored key in its headers, and ``api_key=`` replaced the key."""
    from ariadne import tagger

    register_folder(client, library["folder"])
    first = library["paths"][0]
    settings = client.get("/api/settings").json
    settings["tagger"] = {**settings["tagger"], "backend": "openai", "api_key": "sk-secret"}
    assert client.post("/api/settings", json=settings).json["success"]
    calls = []

    def fake_post(url, body, headers, timeout):
        calls.append((url, headers.get("Authorization")))
        return {"choices": [{"message": {"content": "a, b"}}]}

    monkeypatch.setattr(tagger, "_post", fake_post)
    res = client.get(f"/api/tag/auto?path={first}&url=http://evil.example/v1&api_key=theirs&backend=anthropic")
    assert res.status_code == 200
    assert '"tags": ["a", "b"]' in res.get_data(as_text=True)
    assert calls == [("https://api.openai.com/v1/chat/completions", "Bearer sk-secret")]


def test_image_routes_serve_image_types_only(client, library):
    """A library folder can hold an .html or an .svg as well; served from
    this origin that was a page with the app's rights."""
    register_folder(client, library["folder"])
    folder = library["folder"]
    for name in ("page.html", "drawing.svg", "notes.txt", "page.xhtml"):
        with open(os.path.join(folder, name), "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>")
        for route in ("/image", "/thumb"):
            assert client.get(f"{route}?path={os.path.join(folder, name)}").status_code == 404, name
    res = client.get("/image?path=" + library["paths"][0])
    assert res.status_code == 200 and res.mimetype == "image/png"
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get("/api/stats").headers["X-Content-Type-Options"] == "nosniff"


def test_deeply_nested_bodies_are_refused(client):
    good = client.get("/api/settings").json
    for depth in (300, 5000, 50000):
        body = '{"auto_folders":' + "[" * depth + "]" * depth + "}"
        res = client.post("/api/settings", data=body, content_type="application/json")
        assert res.status_code == 400 and "deeply" in res.json["error"], depth
    assert client.get("/api/settings").json == good


def test_bomb_uploads_are_refused(client, library):
    """A PNG whose header claims ten gigapixels as the editor's canvas
    answered 500; Pillow's refusal is a 400 now."""
    register_folder(client, library["folder"])
    res = client.post("/api/edit/save", content_type="multipart/form-data", data={
        "payload": json.dumps({"source_path": library["paths"][0], "format": "png"}),
        "image": (io.BytesIO(_bomb_png()), "b.png")})
    assert res.status_code == 400 and "too large" in res.json["error"]


def test_long_searches_are_cut_not_failed(client, library):
    """SQLite refuses a LIKE pattern past 50,000 bytes ("pattern too
    complex"), which a pasted novel in the search box turned into a
    database error."""
    register_folder(client, library["folder"])
    long = "a" * 100_000
    assert client.get(f"/api/images/facets?field=model&q={long}").status_code == 200
    for q in (f"prompt:...{long}...", f"prompt:{long}", f"tag:{long}; model:...{long}"):
        res = client.get(f"/api/images?q={q}")
        assert res.status_code == 200 and res.json["total"] == 0
    assert len(scan_rows(client, library["folder"], "prompt:...subject 1...")) == 1


def test_a_folder_spelled_differently_is_the_same_folder(client, library):
    """``C:\\Pics``, ``c:/pics/`` and ``C:\\PICS`` used to be three sidebar
    entries, every file was indexed once under each spelling, and a folder
    scope asked with another spelling found nothing."""
    folder = library["folder"]
    variants = [folder + os.sep, folder.upper(), folder.replace(os.sep, "/"), os.path.join(folder, ".")]
    history = register_folder(client, folder)
    for v in variants:
        history = register_folder(client, v)
    assert [h["path"] for h in history if h["type"] == "folder"] == [folder]
    for v in [folder] + variants:
        assert client.post("/api/images/scan", json={"folder": v, "wait": True}).json["success"]
    assert client.get("/api/images").json["total"] == 7
    for v in variants:
        assert client.get(f"/api/images?folder={v}").json["total"] == 7, v
    # a sync cannot respell a folder either: the rows are spelled like the list
    res = client.post("/api/history/sync", json={"history": [
        {"type": "folder", "path": folder.upper()}, {"type": "folder", "path": folder + os.sep}]})
    assert [h["path"] for h in res.json["history"]] == [folder]
    assert client.get(f"/api/images?folder={folder.upper()}").json["total"] == 7


def test_a_switch_never_closes_another_threads_handle(client, library):
    """Closing a thread's SQLite handle from another thread while it is
    inside a query crashed the process (an access violation, seen during
    a project switch under load). A switch interrupts the other thread's
    query and waits for that thread to let go; it closes only its own."""
    from ariadne import db as database

    held = {}
    opened = threading.Event()
    go = threading.Event()

    def holder():
        conn = database.db()
        held["conn"] = conn
        opened.set()
        go.wait(5)
        held["after"] = conn.execute("SELECT 1").fetchone()[0]    # still open: nobody closed it
        database.release()

    t = threading.Thread(target=holder)
    t.start()
    assert opened.wait(5)
    assert database.retire_connections(wait=0.2) is False       # the holder has not let go yet
    go.set()
    t.join(5)
    assert held["after"] == 1
    assert held["conn"] not in database._open
    assert client.get("/api/stats").status_code == 200           # this thread reopened


def test_request_threads_leave_no_handle_behind(app):
    """Each request thread used to leave its handle in the registry for the
    life of the process: a file handle per request served."""
    from ariadne import db as database
    from ariadne.services.index import indexer

    def one():
        app.test_client().get("/api/stats")

    threads = [threading.Thread(target=one) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    indexer.stop()
    assert database._open == {}
    assert app.test_client().get("/api/stats").status_code == 200
    assert database._local.conn is None       # let go of when the request ended


def test_switching_projects_under_load(client, library):
    """The crash's reproduction: writers on six threads while the project
    switches back and forth. A request caught by a switch answers 409 at
    worst, and the process lives."""
    register_folder(client, library["folder"])
    paths = library["paths"]
    two = client.post("/api/projects/create", json={"name": "Two", "switch": False}).json["id"]
    failures = []

    def worker(n):
        c = client.application.test_client()
        for i in range(20):
            if (n + i) % 2:
                r = c.post("/api/ratings", json={"paths": [paths[i % 7]], "stars": i % 6})
            else:
                r = c.get("/api/images?limit=20")
            if r.status_code >= 500:
                failures.append((r.status_code, r.get_data(as_text=True)[:120]))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for i in range(8):
        assert client.post("/api/projects/switch", json={"id": two if i % 2 == 0 else "default"}).json["success"]
    for t in threads:
        t.join()
    assert failures == []
    assert client.post("/api/projects/switch", json={"id": "default"}).json["success"]
    assert client.get("/api/images").json["total"] >= 0
