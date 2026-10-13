"""The local key file.

``ariadne.key`` beside the library's database holds a random secret that
signs the cookie other devices get after entering the PIN (services/auth.py).
It is created on first use. Deleting it signs every other device out, and
nothing else is lost.
"""

import os
import secrets

from ariadne import config


def _key():
    key_file = config.paths.key_file
    if key_file.exists():
        key = key_file.read_bytes().strip()
        if key:
            return key
    key = secrets.token_urlsafe(32).encode("ascii")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key
