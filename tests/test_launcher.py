"""The launcher's argument parsing and the LAN address helper."""

import app as launcher
from ariadne import config
from ariadne.services import system


def test_parse_args_defaults():
    opts = launcher.parse_args([])
    assert opts["port"] == config.DEFAULT_PORT and opts["host"] == "127.0.0.1"
    assert opts["launch"] is True and opts["reload"] is False and opts["tray"] is False


def test_parse_args_host_and_port_forms():
    opts = launcher.parse_args(["--host", "0.0.0.0", "--port=8080", "--no-browser", "--tray"])
    assert opts == {"port": 8080, "host": "0.0.0.0", "launch": False, "reload": False, "tray": True,
                    "app_dir": None}
    assert launcher.parse_args(["--app-dir", "D:/lib"])["app_dir"] == "D:/lib"
    assert launcher.parse_args(["--app-dir=D:/other"])["app_dir"] == "D:/other"
    assert launcher.parse_args(["--lan"])["host"] == "0.0.0.0"
    assert launcher.parse_args(["--host=192.168.1.20", "--port", "7000"])["host"] == "192.168.1.20"
    assert launcher.parse_args(["--port", "nope"])["port"] == config.DEFAULT_PORT


def test_lan_urls_only_when_exposed(monkeypatch):
    monkeypatch.setattr(config, "BIND_HOST", "127.0.0.1")
    assert system.lan_urls() == []
    monkeypatch.setattr(config, "BIND_HOST", "192.168.1.20")
    monkeypatch.setattr(config, "BIND_PORT", 7000)
    assert system.lan_urls() == ["http://192.168.1.20:7000"]
    monkeypatch.setattr(config, "BIND_HOST", "0.0.0.0")
    urls = system.lan_urls()
    assert all(u.startswith("http://") and u.endswith(":7000") for u in urls)
    assert "http://127.0.0.1:7000" not in urls
