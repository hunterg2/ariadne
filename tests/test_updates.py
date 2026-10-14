"""The update notice: version comparison, the once-a-day look, the setting
that turns it off, and a failed look that is remembered rather than
retried every pass. GitHub itself is never called."""

import time
import urllib.error

from ariadne.services import updates


def test_version_parsing_and_comparison():
    assert updates.parse_version("v2.1.0") == (2, 1, 0, 1)
    assert updates.parse_version("2.1.0-beta.1") == (2, 1, 0, 0, "beta.1")
    assert updates.parse_version("latest") is None and updates.parse_version("") is None
    assert updates.is_newer("v2.1.0", "2.0.0")
    assert updates.is_newer("2.0.1", "2.0.0") and updates.is_newer("3.0.0", "2.9.9")
    assert not updates.is_newer("2.0.0", "2.0.0")
    assert not updates.is_newer("2.0.0-rc1", "2.0.0")      # a pre-release is older than the release
    assert updates.is_newer("2.0.0", "2.0.0-rc1")
    assert not updates.is_newer("nope", "2.0.0")


def test_check_once_a_day_and_the_notice(client, monkeypatch):
    calls = []

    def fetch(repo):
        calls.append(repo)
        return {"version": "9.0.0", "url": "https://example.test/releases/v9.0.0", "published": ""}

    monkeypatch.setattr(updates, "_fetch", fetch)
    before = client.get("/api/updates").json
    assert before["latest"] == "" and before["newer"] is False and before["checked_at"] is None
    assert before["current"] == updates.current() and before["enabled"] is True

    now = time.time()
    st = updates.check(now)
    assert calls == [updates.config.UPDATE_REPO]
    assert st["latest"] == "9.0.0" and st["newer"] is True and st["url"].endswith("v9.0.0")
    assert st["error"] == "" and abs(st["checked_at"] - now) < 1
    # the next passes do not ask again until a day has gone by
    updates.check(now + 3600)
    assert len(calls) == 1
    updates.check(now + updates.EVERY + 1)
    assert len(calls) == 2
    # "Check now" always asks
    assert client.post("/api/updates/check").json["latest"] == "9.0.0"
    assert len(calls) == 3
    # the route shows the remembered answer
    assert client.get("/api/updates").json["newer"] is True


def test_setting_turns_the_look_off_and_failures_are_remembered(client, monkeypatch):
    calls = []

    def fetch(repo):
        calls.append(repo)
        raise urllib.error.HTTPError("https://api.github.test", 404, "Not Found", {}, None)

    monkeypatch.setattr(updates, "_fetch", fetch)
    client.post("/api/settings", json={**client.get("/api/settings").json, "check_updates": False})
    assert updates.check() ["enabled"] is False and calls == []
    # forced, it asks, and the failure is kept so a dead network is asked once a day
    st = updates.check(force=True)
    assert calls and st["error"] == "GitHub answered 404." and st["latest"] == "" and st["newer"] is False
    client.post("/api/settings", json={**client.get("/api/settings").json, "check_updates": True})
    assert updates.check()["error"] == "GitHub answered 404."
    assert len(calls) == 1

    def flaky(repo):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(updates, "_fetch", flaky)
    assert updates.check(force=True)["error"].startswith("Could not reach GitHub")
