"""Native local-owner login using configured Kotak details and a fresh TOTP."""

import os
import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, jsonify, request, session

from limiter import limiter
from services.kotak_saved_login import (
    authenticate_saved_kotak,
    cached_native_auth,
    legacy_access_is_valid,
    read_saved_kotak_settings,
    verify_saved_kotak_auth,
)
from utils.logging import get_logger

logger = get_logger(__name__)
neo_login_bp = Blueprint("neo_login", __name__, url_prefix="/auth")


def enabled():
    return os.getenv("NEO_SAVED_LOGIN", "false").lower() == "true"


def _local_request():
    if not enabled():
        abort(404)
    base = os.getenv("HOST_SERVER", "http://127.0.0.1:5001").rstrip("/")
    origins = {base, base.replace("127.0.0.1", "localhost")}
    if (
        request.remote_addr not in ("127.0.0.1", "::1")
        or request.headers.get("Origin") not in origins
    ):
        abort(403)
    if not request.is_json:
        abort(400)


def can_resume_owner():
    settings = read_saved_kotak_settings()
    if session.get("logged_in") and session.get("broker") == "kotak" and session.get("user"):
        from database.user_db import find_user_by_username
        from utils.session import is_session_valid

        owner = find_user_by_username()
        if owner and owner.username == session["user"] and is_session_valid():
            return True
    return legacy_access_is_valid(request.cookies.get("nifty_desk_session"), settings.access_secret)


def _saved_native_auth(settings):
    from database.auth_db import get_auth_token, get_auth_token_dbquery
    from database.user_db import find_user_by_username

    owner = find_user_by_username()
    if not owner:
        return None
    row = get_auth_token_dbquery(owner.username)
    if not row or row.is_revoked or row.broker != "kotak" or str(row.user_id or "") != settings.ucc:
        return None
    auth = get_auth_token(owner.username)
    parts = auth.split(":::") if auth else []
    return (
        auth if len(parts) >= 4 and secrets.compare_digest(parts[3], settings.api_token) else None
    )


def _verified_cached_auth():
    settings = read_saved_kotak_settings()
    source = Path(os.getenv("NEO_SOURCE_RUNTIME", ".")) / "broker-session.json"
    auth = _saved_native_auth(settings) or cached_native_auth(
        source, settings, datetime.now(ZoneInfo("Asia/Kolkata"))
    )
    if not auth:
        return None
    result = verify_saved_kotak_auth(auth)
    if result == "expired":
        return None
    if result != "valid":
        raise RuntimeError("Saved-session validation temporarily unavailable")
    return auth


def complete_verified_login(auth):
    """Only verified ownership reaches native user, broker and cookie storage."""
    from database.auth_db import get_api_key, get_api_key_for_tradingview, upsert_api_key
    from database.settings_db import get_analyze_mode
    from database.user_db import add_user, find_user_by_username
    from utils.auth_utils import handle_auth_success

    owner = find_user_by_username()
    if owner is None:
        owner = add_user("neo", "neo@localhost.invalid", secrets.token_urlsafe(48), is_admin=True)
    if owner is None:
        raise ValueError("Local account setup did not complete. Retry the connection.")
    username = owner.username
    session.clear()
    session["user"] = username
    handle_auth_success(auth, username, "kotak", user_id=read_saved_kotak_settings().ucc)
    if not get_api_key(username):
        upsert_api_key(username, secrets.token_hex(32))
    return {
        "status": "success",
        "username": username,
        "broker": "kotak",
        "redirect": "/dashboard",
        "analyze_mode": get_analyze_mode(),
        "api_key": get_api_key_for_tradingview(username),
    }


@neo_login_bp.post("/neo-kotak-login")
@limiter.limit("5 per minute")
@limiter.limit("25 per hour")
def login():
    _local_request()
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"totp"}:
        return jsonify(status="error", message="Enter only your current authenticator code."), 400
    auth, error = authenticate_saved_kotak(body["totp"])
    if error:
        return jsonify(status="error", message=error), 400
    try:
        return jsonify(complete_verified_login(auth))
    except Exception:
        logger.exception("Verified Kotak login could not establish the local session")
        return jsonify(
            status="error", message="Local session setup did not complete. Refresh and reconnect."
        ), 503


@neo_login_bp.post("/neo-resume")
@limiter.limit("5 per minute")
def resume():
    _local_request()
    if request.get_json(silent=True) != {} or not can_resume_owner():
        return jsonify(
            status="error",
            message="Verify this browser with your current authenticator code.",
            requires_totp=True,
        ), 401
    try:
        auth = _verified_cached_auth()
        if not auth:
            return jsonify(
                status="error",
                message="Your saved Kotak session expired or is no longer available. Enter a fresh authenticator code.",
                requires_totp=True,
            ), 401
        return jsonify(complete_verified_login(auth))
    except Exception:
        logger.exception("Verified owner session could not resume Kotak")
        return jsonify(
            status="error",
            message="Saved Kotak session validation is temporarily unavailable. Retry the saved connection.",
            requires_totp=False,
        ), 503


@neo_login_bp.before_app_request
def verified_owner_setup_only():
    if enabled() and request.method == "POST" and request.path in ("/auth/setup", "/setup"):
        return jsonify(
            status="error", message="Connect with Kotak to establish this terminal account."
        ), 403
