"""The editor's save (what the copy carries), camera EXIF reading, and the
library export and import."""

import io
import json
import os

from PIL import Image

from ariadne import metadata
from tests.conftest import register_folder


def _save(client, payload, png, name="edit.png"):
    return client.post("/api/edit/save", data={"payload": json.dumps(payload), "image": (io.BytesIO(png), name)},
                       content_type="multipart/form-data")


def test_edit_save_writes_copy_with_tag(client, library):
    register_folder(client, library["folder"])
    src = library["paths"][2]
    # the browser sends the rendered canvas; here a cropped 30x20 picture stands in
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 200, 30)).save(buf, "PNG")
    png = buf.getvalue()              # the client closes the stream it is handed
    payload = {"source_path": src, "format": "png", "quality": 92, "metadata": "generation",
               "dest": "suffix", "dest_dir": "", "background": "#000000"}
    res = _save(client, payload, png).json
    assert res["success"] and res["name"] == "gen_02_edit.png" and res["tagged"]
    assert os.path.exists(src)                                   # a copy; the original is untouched
    with Image.open(res["path"]) as im:
        assert im.size == (30, 20)
        chunks = metadata.read_chunks(im)
    assert "parameters" in chunks                                # generation data carried across
    row = client.get("/api/images/one?path=" + res["path"]).json["image"]
    assert "edited" in row["user_tags"]

    # strip everything: no prompt in the copy
    res = _save(client, dict(payload, metadata="none"), png).json
    with Image.open(res["path"]) as im:
        assert "parameters" not in metadata.read_chunks(im)

    # jpeg into a chosen folder
    out = os.path.join(library["folder"], "out")
    os.mkdir(out)
    res = _save(client, dict(payload, format="jpeg", quality=80, dest="folder", dest_dir=out), png, "edit.jpg").json
    assert res["success"] and res["path"].startswith(out) and res["path"].endswith("gen_02.jpg")

    # a file outside the registered roots is refused
    assert _save(client, dict(payload, source_path="C:/nowhere/x.png"), png).status_code == 404


def test_read_camera_and_photo_kind(client, library):
    """A JPEG with camera EXIF reads back as text and is indexed as a photo;
    the position comes through as decimal degrees."""
    from PIL.TiffImagePlugin import IFDRational
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0110] = "Canon EOS R5"
    sub = exif.get_ifd(0x8769)
    sub[0x829A] = IFDRational(1, 250)        # exposure time
    sub[0x829D] = IFDRational(28, 10)        # f/2.8
    sub[0x8827] = 200                        # ISO
    sub[0x9003] = "2026:03:04 10:11:12"      # DateTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[0x0001] = "N"
    gps[0x0002] = (IFDRational(51, 1), IFDRational(30, 1), IFDRational(0, 1))
    gps[0x0003] = "W"
    gps[0x0004] = (IFDRational(0, 1), IFDRational(7, 1), IFDRational(30, 1))
    path = os.path.join(library["folder"], "shot.jpg")
    Image.new("RGB", (40, 30), (90, 90, 90)).save(path, "JPEG", exif=exif.tobytes())

    cam = metadata.read_camera(path)
    assert cam["make"] == "Canon" and cam["model"] == "Canon EOS R5"
    assert cam["exposure"] == "1/250" and cam["aperture"] == "2.8" and cam["iso"] == "200"
    assert cam["date_taken"] == "2026:03:04 10:11:12"
    assert cam["latitude"] == "51.5" and cam["longitude"] == "-0.125"
    assert metadata.read_camera(library["paths"][0]) == {}      # a generated PNG has none

    register_folder(client, library["folder"])
    client.post("/api/images/scan", json={"folder": library["folder"], "wait": True})
    row = client.get("/api/images/one?path=" + path).json["image"]
    assert row["kind"] == "photo" and row["camera"]["model"] == "Canon EOS R5"
    assert row["camera"]["lat"] == 51.5 and row["camera"]["lon"] == -0.125


def test_library_export_and_import_both_formats(client, library, tmp_path):
    register_folder(client, library["folder"])
    a, b = library["paths"][:2]
    client.post("/api/ratings", json={"paths": [a], "stars": 4, "label": "red"})
    client.post("/api/ratings", json={"paths": [b], "rejected": True})
    client.post("/api/tags", json={"paths": [a], "tags": ["one", "two"]})

    exported = json.loads(client.get("/api/library/export").get_data(as_text=True))
    assert exported["format"] == "ariadne-library"
    assert exported["ratings"][a] == {"stars": 4, "rejected": 0, "label": "red"}
    assert exported["ratings"][b]["rejected"] == 1
    assert exported["tags"][a] == ["one", "two"]

    # wipe, then restore from the export
    client.post("/api/ratings", json={"paths": [a, b], "stars": 0, "rejected": False, "label": None})
    client.post("/api/tags", json={"paths": [a], "tags": []})
    res = client.post("/api/library/import", json={"data": exported, "mode": "replace"}).json
    assert res["success"] and res["ratings"] == 2 and res["tag_links"] == 2
    row = client.get("/api/images/one?path=" + a).json["image"]
    assert row["stars"] == 4 and row["label"] == "red" and row["user_tags"] == ["one", "two"]

    # an export from the previous build still imports
    legacy = {"format": "image-organizer-library", "version": 1,
              "categories": {a: "loved", b: "liked"}, "tags": {b: ["old"]}}
    res = client.post("/api/library/import", json={"data": legacy, "mode": "merge"}).json
    assert res["success"] and res["ratings"] == 2
    assert client.get("/api/images/one?path=" + b).json["image"]["stars"] == 3
    assert client.post("/api/library/import", json={"data": {"format": "nope"}}).status_code == 400
