"""A PIN for other devices.

Ariadne has no accounts: on the computer running it, it is simply open.
Started with ``--host`` or ``--lan`` it can be reached by anything on the
network, so a request from a non-loopback address has to carry a cookie
earned by entering the PIN. The PIN is kept as a salted hash in the ``kv``
table (never in settings.json); the cookie is an HMAC over that stored hash
keyed with the local key file, so changing or removing the PIN signs every
device out at once.
"""

import hashlib
import hmac
import ipaddress
import secrets
import threading
import time

from flask import jsonify, request

from ariadne import config, db
from ariadne.services import crypto

COOKIE = "ariadne_pin"
COOKIE_DAYS = 30
KV_KEY = "lan_pin"
MIN_LENGTH = 4
MAX_LENGTH = 64
ITERATIONS = 200_000
MISS_DELAY = 1.0            # seconds a wrong guess costs
LOCK_AFTER = 10             # wrong guesses before an address is locked out
LOCK_SECONDS = 15 * 60

# what a device may fetch before it has entered the PIN: the page shell, its
# bundle and icon, and the PIN routes themselves
OPEN_PATHS = {"/", "/index.html", "/icon.png", "/favicon.ico"}
OPEN_PREFIXES = ("/assets/", "/api/auth/")

_misses = {}
_lock = threading.Lock()


def is_loopback(addr):
    if not addr:
        return False
    if addr == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def exposed():
    """Was the server started so that other devices can reach it?"""
    return not is_loopback(config.BIND_HOST)


def has_pin():
    return bool(db.kv_get(KV_KEY))


def _digest(salt, pin):
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("utf-8"),
                               ITERATIONS).hex()


def set_pin(pin):
    pin = (pin or "").strip()
    if len(pin) < MIN_LENGTH:
        raise ValueError(f"Use at least {MIN_LENGTH} characters.")
    if len(pin) > MAX_LENGTH:
        raise ValueError(f"Keep it under {MAX_LENGTH} characters.")
    salt = secrets.token_hex(16)
    db.kv_set(KV_KEY, f"{salt}${_digest(salt, pin)}")
    with _lock:
        _misses.clear()


def clear_pin():
    d = db.db()
    d.execute("DELETE FROM kv WHERE key=?", (KV_KEY,))
    d.commit()


def _matches(pin):
    stored = db.kv_get(KV_KEY) or ""
    if "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    return hmac.compare_digest(_digest(salt, (pin or "").strip()), digest)


def locked_until(addr):
    with _lock:
        entry = _misses.get(addr)
    if entry and entry["until"] > time.time():
        return entry["until"]
    return 0


def verify(pin, addr):
    """(ok, message). A wrong guess costs a second, ten in a row lock the
    address out for a while, and a right one clears the slate."""
    until = locked_until(addr)
    if until:
        minutes = int((until - time.time()) / 60) + 1
        return False, f"Too many wrong tries. Wait {minutes} minute{'s' if minutes != 1 else ''}."
    if _matches(pin):
        with _lock:
            _misses.pop(addr, None)
        return True, "ok"
    with _lock:
        entry = _misses.setdefault(addr, {"count": 0, "until": 0})
        entry["count"] += 1
        left = LOCK_AFTER - entry["count"]
        if left <= 0:
            entry["until"] = time.time() + LOCK_SECONDS
            entry["count"] = 0
    if MISS_DELAY:
        time.sleep(MISS_DELAY)
    if left <= 0:
        return False, f"Too many wrong tries. This device is locked out for {LOCK_SECONDS // 60} minutes."
    return False, f"Wrong PIN. {left} more tr{'y' if left == 1 else 'ies'} before a lock-out."


# --------------------------------------------------------------------------
# the cookie
# --------------------------------------------------------------------------

def cookie_value():
    stored = db.kv_get(KV_KEY) or ""
    if not stored:
        return ""
    return hmac.new(crypto._key(), stored.encode("utf-8"), hashlib.sha256).hexdigest()


def cookie_ok(value):
    want = cookie_value()
    return bool(want) and bool(value) and hmac.compare_digest(str(value), want)


def set_cookie(response):
    response.set_cookie(COOKIE, cookie_value(), max_age=COOKIE_DAYS * 86400,
                        httponly=True, samesite="Lax", path="/")
    return response


def authenticated(req=None):
    req = req or request
    return cookie_ok(req.cookies.get(COOKIE))


def required(req=None):
    """Does this request need the PIN? Only the computer itself is exempt."""
    req = req or request
    return not is_loopback(req.remote_addr)


def status(req=None):
    req = req or request
    need = required(req)
    return {
        "exposed": exposed(), "required": need, "has_pin": has_pin(),
        "authenticated": (not need) or authenticated(req),
        "locked": bool(locked_until(req.remote_addr)),
    }


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

def gate():
    """Flask ``before_request``: None lets the request through."""
    if not required():
        return None
    path = request.path
    if path in OPEN_PATHS or path.startswith(OPEN_PREFIXES):
        return None
    if not has_pin():
        return _refuse(403, "Ariadne can be reached from other devices but has no PIN yet. "
                            "Set one in Settings, under Other devices, on the computer "
                            "running it.", "unset")
    if authenticated():
        return None
    return _refuse(401, "Enter the PIN to use Ariadne from this device.", True)


def _refuse(code, message, pin):
    resp = jsonify({"success": False, "error": message, "pin": pin})
    resp.status_code = code
    return resp
