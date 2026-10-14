"""The backup zip: a readable copy of the database, the key file and the
JSON files, and nothing that can be rebuilt. (That watermark logos ride
along is checked in test_watermark.py.)"""

import io
import sqlite3
import zipfile

from ariadne import config
from ariadne.services import backup, crypto


def test_backup_zip_holds_the_irreplaceable_files(client, tmp_path):
    crypto._key()                                                # the key file appears with first use
    client.post("/api/settings", json={**client.get("/api/settings").json, "theme": 2})
    client.post("/api/history", json={"folder": str(tmp_path)})  # the sidebar file
    assert config.paths.key_file.exists() and config.paths.settings_file.exists()

    status = client.get("/api/system").json["backup"]
    assert status["key_exists"] is True and status["key_path"] == str(config.paths.key_file)
    assert {"organizer.db", "ariadne.key", "settings.json", "history.json"} <= set(status["files"])
    assert status["bytes"] > 0

    res = client.get("/api/backup")
    assert res.status_code == 200 and res.mimetype == "application/zip"
    assert "Ariadne-backup-" in res.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(res.data)) as z:
        names = set(z.namelist())
        assert {"README.txt", "organizer.db", "ariadne.key", "settings.json", "history.json"} <= names
        assert not any(n.startswith("cache") or n.startswith("backups") for n in names)
        assert z.read("ariadne.key") == config.paths.key_file.read_bytes()
        assert b"ariadne.key" in z.read("README.txt")
        assert b'"theme": 2' in z.read("settings.json")
        copy = tmp_path / "copy.db"
        copy.write_bytes(z.read("organizer.db"))
    # the copy is a whole database, not a torn one
    conn = sqlite3.connect(str(copy))
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT value FROM kv WHERE key='meta_cache_version'").fetchone() is not None
    conn.close()


def test_backup_before_anything_was_saved(client):
    # a fresh library: the database exists, the key and settings may not
    status = backup.status()
    assert "organizer.db" in status["files"]
    with zipfile.ZipFile(io.BytesIO(backup.build())) as z:
        assert "organizer.db" in z.namelist() and "README.txt" in z.namelist()
