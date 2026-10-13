"""Duplicates and unique prompts over the index."""

import os
import shutil

from PIL import Image

from tests.conftest import make_png, register_folder


def _distinct(path, seed):
    """A gradient with a few shapes: flat test images all hash alike, so the
    duplicate checks need pictures with real structure."""
    import random
    from PIL import ImageDraw
    rnd = random.Random(seed)
    im = Image.new("RGB", (160, 120))
    d = ImageDraw.Draw(im)
    for y in range(120):
        d.line([(0, y), (160, y)], fill=(y * 2 % 256, (seed * 40) % 256, 255 - y * 2 % 256))
    for _ in range(5):
        x, y, r = rnd.randint(0, 160), rnd.randint(0, 120), rnd.randint(10, 40)
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255), width=4)
    im.save(path)
    return str(path)


def test_duplicates_find_identical_and_near_copies(client, library, tmp_path):
    folder = library["folder"]
    a = _distinct(folder + "/uniq.png", 1)
    _distinct(folder + "/other.png", 2)
    # an exact copy, a re-encoded copy (same look, different bytes), and a downscale
    shutil.copy(a, folder + "/copy.png")
    with Image.open(a) as im:
        im.save(folder + "/resaved.jpg", "JPEG", quality=70)
        im.resize((80, 60)).save(folder + "/smaller.png")
    register_folder(client, folder)
    client.post("/api/images/scan", json={"folder": folder, "wait": True})
    client.post("/api/ratings", json={"paths": [a], "stars": 4})

    res = client.get("/api/duplicates?level=identical&folder=" + folder).json
    assert res["success"]
    group = next(g for g in res["groups"] if any(i["name"] == "uniq.png" for i in g["items"]))
    assert sorted(i["name"] for i in group["items"]) == ["copy.png", "uniq.png"]
    assert os.path.normpath(group["keep"]) == os.path.normpath(a)   # the rated one is the keeper
    assert "other.png" not in {i["name"] for g in res["groups"] for i in g["items"]}

    res = client.get("/api/duplicates?level=similar&folder=" + folder).json
    group = next(g for g in res["groups"] if any(i["name"] == "uniq.png" for i in g["items"]))
    names = {i["name"] for i in group["items"]}
    assert {"uniq.png", "copy.png", "resaved.jpg", "smaller.png"} <= names
    assert "other.png" not in names
    assert res["levels"][0]["key"] == "identical"
    assert res["stats"]["redundant"] >= 3


def test_duplicates_whole_library_and_refusals(client, library):
    assert client.get("/api/duplicates?folder=" + library["folder"]).status_code == 403
    register_folder(client, library["folder"])
    client.post("/api/images/scan", json={"folder": library["folder"], "wait": True})
    res = client.get("/api/duplicates?level=identical").json
    assert res["success"] and res["total"] == 7


def test_unique_prompts(client, library):
    folder = library["folder"]
    make_png(folder + "/twin.png", subject="subject 0", seed=5)
    register_folder(client, folder)
    client.post("/api/images/scan", json={"folder": folder, "wait": True})
    res = client.get("/api/prompts?folder=" + folder).json
    assert res["success"]
    top = res["prompts"][0]
    assert top["text"].startswith("subject 0") and top["count"] == 2
    assert any(p["text"] == "" and p["count"] == 1 for p in res["prompts"])     # plain.png
    assert client.get("/api/prompts").status_code == 403


def test_banding_finds_every_near_pair():
    """The 16-bit banding must surface every pair within the threshold; the
    small libraries above never leave the pairwise path, so plant pairs in a
    pool big enough to use the bands."""
    import random
    from ariadne.services import duplicates as dupes
    rnd = random.Random(7)
    hashes = [rnd.getrandbits(64) for _ in range(4000)]
    planted = []
    for k in range(60):
        base = hashes[k * 50]
        bits = rnd.sample(range(64), rnd.randint(0, 6))
        twin = base
        for b in bits:
            twin ^= 1 << b
        hashes.append(twin)
        planted.append((k * 50, len(hashes) - 1))
    found = set()
    for a, b in dupes._candidates(hashes, 6):
        if (hashes[a] ^ hashes[b]).bit_count() <= 6:
            found.add((min(a, b), max(a, b)))
    assert set(planted) <= found


def test_broad_levels_refuse_huge_pools(client, library, monkeypatch):
    from ariadne.services import duplicates as dupes
    register_folder(client, library["folder"])
    client.post("/api/images/scan", json={"folder": library["folder"], "wait": True})
    monkeypatch.setattr(dupes, "PAIRWISE_LIMIT", 3)
    res = client.get("/api/duplicates?level=wide").json
    assert res["success"] and res["groups"] == [] and "too slow" in res["error"]
    assert res["levels"][0]["key"] == "identical"
    res = client.get("/api/duplicates?level=similar").json       # banded levels still run
    assert res["success"] and "error" not in res
