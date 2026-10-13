"""The PIN gate: the computer itself is always open, other addresses need
the PIN, and guessing is slow and finite."""

import pytest

from ariadne import config
from ariadne.services import auth

REMOTE = {"REMOTE_ADDR": "192.168.1.23"}


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(auth, "MISS_DELAY", 0)
    auth._misses.clear()
    yield
    auth._misses.clear()


def test_loopback_detection(monkeypatch):
    assert auth.is_loopback("127.0.0.1") and auth.is_loopback("127.5.0.9")
    assert auth.is_loopback("::1") and auth.is_loopback("::ffff:127.0.0.1")
    assert auth.is_loopback("localhost")
    assert not auth.is_loopback("192.168.1.2") and not auth.is_loopback("") and not auth.is_loopback("nope")
    monkeypatch.setattr(config, "BIND_HOST", "127.0.0.1")
    assert auth.exposed() is False
    monkeypatch.setattr(config, "BIND_HOST", "0.0.0.0")
    assert auth.exposed() is True


def test_loopback_never_needs_a_pin(client):
    assert client.get("/api/settings").status_code == 200
    st = client.get("/api/auth/status").json
    assert st["required"] is False and st["authenticated"] is True and st["has_pin"] is False


def test_other_devices_are_turned_away_without_a_pin(client):
    res = client.get("/api/settings", environ_base=REMOTE)
    assert res.status_code == 403 and res.json["pin"] == "unset"
    assert client.get("/thumb?path=x", environ_base=REMOTE).status_code == 403
    # the PIN routes stay open so the page can say why
    st = client.get("/api/auth/status", environ_base=REMOTE).json
    assert st["required"] is True and st["has_pin"] is False and st["authenticated"] is False
    assert client.post("/api/auth/pin", json={"pin": "1234"}, environ_base=REMOTE).status_code == 403


def test_pin_round_trip(client):
    assert client.post("/api/settings/pin", json={"pin": "12"}).status_code == 400
    res = client.post("/api/settings/pin", json={"pin": "2468"})
    assert res.status_code == 200 and res.json["has_pin"] is True
    client.delete_cookie(auth.COOKIE)        # a device that has not entered it yet

    res = client.get("/api/settings", environ_base=REMOTE)
    assert res.status_code == 401 and res.json["pin"] is True
    assert client.get("/thumb?path=x", environ_base=REMOTE).status_code == 401
    assert client.get("/api/auth/status", environ_base=REMOTE).json["authenticated"] is False

    bad = client.post("/api/auth/pin", json={"pin": "0000"}, environ_base=REMOTE)
    assert bad.status_code == 401 and bad.json["error"].startswith("Wrong PIN")
    good = client.post("/api/auth/pin", json={"pin": " 2468 "}, environ_base=REMOTE)
    assert good.status_code == 200 and good.json["authenticated"] is True
    cookie = good.headers.get("Set-Cookie", "")
    assert auth.COOKIE in cookie and "HttpOnly" in cookie
    # the test client kept the cookie: the device is in
    assert client.get("/api/settings", environ_base=REMOTE).status_code == 200

    # changing the PIN signs every other device out
    old = cookie.split(";")[0].split("=", 1)[1]
    client.post("/api/settings/pin", json={"pin": "1357"})
    client.set_cookie(auth.COOKIE, old)
    assert client.get("/api/settings", environ_base=REMOTE).status_code == 401
    assert client.post("/api/auth/pin", json={"pin": "1357"}, environ_base=REMOTE).status_code == 200
    assert client.get("/api/settings", environ_base=REMOTE).status_code == 200


def test_lockout_after_ten_misses(client):
    client.post("/api/settings/pin", json={"pin": "2468"})
    res = None
    for _ in range(auth.LOCK_AFTER):
        res = client.post("/api/auth/pin", json={"pin": "0000"}, environ_base=REMOTE)
    assert res.status_code == 401 and "locked out" in res.json["error"]
    res = client.post("/api/auth/pin", json={"pin": "2468"}, environ_base=REMOTE)
    assert res.status_code == 401 and res.json["error"].startswith("Too many")
    assert client.get("/api/auth/status", environ_base=REMOTE).json["locked"] is True
    # another device is not affected
    other = {"REMOTE_ADDR": "192.168.1.99"}
    assert client.post("/api/auth/pin", json={"pin": "2468"}, environ_base=other).status_code == 200


def test_removing_the_pin(client):
    client.post("/api/settings/pin", json={"pin": "2468"})
    assert client.delete("/api/settings/pin").json["has_pin"] is False
    assert client.get("/api/settings", environ_base=REMOTE).status_code == 403
    assert auth.cookie_value() == ""
