"""The PIN other devices enter. The computer running Ariadne never needs it;
the gate in ``services/auth.py`` decides who does."""

from flask import Blueprint, jsonify, request

from ariadne.services import auth

bp = Blueprint("auth", __name__)


@bp.route("/api/auth/status")
def auth_status():
    return jsonify({"success": True, **auth.status()})


@bp.route("/api/auth/pin", methods=["POST"])
def enter_pin():
    if not auth.has_pin():
        return jsonify({"success": False, "error": "No PIN has been set yet.", "pin": "unset"}), 403
    ok, message = auth.verify((request.json or {}).get("pin"), request.remote_addr)
    if not ok:
        return jsonify({"success": False, "error": message, "pin": True}), 401
    # the status is computed from the request, which had no cookie yet
    return auth.set_cookie(jsonify({"success": True, **auth.status(), "authenticated": True}))


@bp.route("/api/settings/pin", methods=["POST", "DELETE"])
def manage_pin():
    """Set, change or remove the PIN. The gate already keeps other devices
    out until they have entered the current one, so anyone reaching this has
    the right to change it."""
    if request.method == "DELETE":
        auth.clear_pin()
        return jsonify({"success": True, **auth.status()})
    try:
        auth.set_pin((request.json or {}).get("pin"))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    # the device that set it stays signed in
    return auth.set_cookie(jsonify({"success": True, **auth.status(), "authenticated": True}))
