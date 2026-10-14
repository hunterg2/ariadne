"""Home-screen install: the manifest and its icons are served from the
built frontend with the right types, and a phone that has not entered the
PIN yet can still fetch them (they carry nothing from the library)."""

import json

import pytest

from ariadne import config

REMOTE = {"REMOTE_ADDR": "192.168.1.23"}

needs_dist = pytest.mark.skipif(not (config.WEB_DIST / "manifest.webmanifest").exists(),
                                reason="web/dist is not built")


@needs_dist
def test_manifest_and_icons_are_served(client):
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200 and res.mimetype == "application/manifest+json"
    manifest = json.loads(res.data)
    assert manifest["name"] == "Ariadne" and manifest["display"] == "standalone"
    assert manifest["start_url"] == "/" and manifest["theme_color"].startswith("#")
    purposes = {i["purpose"] for i in manifest["icons"]}
    assert {"any", "maskable"} <= purposes
    for icon in manifest["icons"]:
        got = client.get(icon["src"])
        assert got.status_code == 200 and got.mimetype == "image/png", icon["src"]
        assert got.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/icons/apple-touch-icon.png").status_code == 200
    page = client.get("/").data.decode("utf-8")
    assert 'rel="manifest"' in page and 'rel="apple-touch-icon"' in page and 'name="theme-color"' in page


@needs_dist
def test_phone_without_the_pin_still_gets_the_manifest(client):
    # exposed, no PIN set: everything is refused except the shell and these
    assert client.get("/api/settings", environ_base=REMOTE).status_code == 403
    assert client.get("/manifest.webmanifest", environ_base=REMOTE).status_code == 200
    assert client.get("/icons/icon-192.png", environ_base=REMOTE).status_code == 200
    assert client.get("/icons/../organizer.db", environ_base=REMOTE).status_code in (403, 404)
