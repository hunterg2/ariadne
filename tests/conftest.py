"""Shared fixtures: an app pointed at a temp directory, and a folder of small
PNGs carrying A1111-style generation metadata so the extractor has something
real to read."""

import random

import pytest
from PIL import Image, ImageDraw, PngImagePlugin

from ariadne import create_app


def make_png(path, width=64, height=48, subject="a red fox", seed=None, params=True):
    seed = seed if seed is not None else random.randint(10**6, 10**7)
    im = Image.new("RGB", (width, height), (120, 80, 200))
    ImageDraw.Draw(im).rectangle([4, 4, width - 5, height - 5], outline=(255, 255, 255))
    info = PngImagePlugin.PngInfo()
    if params:
        info.add_text("parameters",
                      f"{subject}, highly detailed\nNegative prompt: blurry\n"
                      f"Steps: 25, Sampler: Euler a, CFG scale: 7, Seed: {seed}, "
                      f"Size: {width}x{height}, Model: testmodel_v1")
    im.save(path, pnginfo=info)
    return str(path)


@pytest.fixture
def library(tmp_path):
    """A folder with six generated PNGs and one plain PNG."""
    folder = tmp_path / "images"
    folder.mkdir()
    paths = [make_png(folder / f"gen_{i:02d}.png", subject=f"subject {i}", seed=1000 + i)
             for i in range(6)]
    paths.append(make_png(folder / "plain.png", params=False))
    return {"folder": str(folder), "paths": paths}


@pytest.fixture
def app(tmp_path):
    from ariadne.services.index import indexer

    indexer.stop()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    application = create_app(app_dir=data_dir)
    application.config["TESTING"] = True
    yield application
    # the background indexer must not outlive the library it was reading
    indexer.stop()


@pytest.fixture
def client(app):
    return app.test_client()


def register_folder(client, folder):
    res = client.post("/api/history", json={"folder": folder})
    assert res.status_code == 200 and res.json["success"]
    return res.json["history"]


def scan_rows(client, folder, query=""):
    """Index a folder synchronously and return its rows from the paged API."""
    res = client.post("/api/images/scan", json={"folder": folder, "wait": True})
    assert res.status_code == 200 and res.json["success"]
    q = f"&q={query}" if query else ""
    page = client.get(f"/api/images?folder={folder}&limit=500{q}").json
    return page["rows"]
