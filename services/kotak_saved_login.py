"""Private configuration and staged Kotak login for a single local owner."""

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from flask.json.tag import TaggedJSONSerializer
from itsdangerous import BadSignature, URLSafeTimedSerializer


@dataclass(frozen=True, repr=False)
class SavedKotakSettings:
    ucc: str
    api_token: str
    mobile: str
    mpin: str
    access_secret: str = ""


def read_saved_kotak_settings(source: Path | None = None) -> SavedKotakSettings:
    """Read without exporting any private value to logs or the browser."""
    values = dotenv_values(source) if source else os.environ
    return SavedKotakSettings(
        ucc=str(values.get("KOTAK_UCC") or values.get("BROKER_API_KEY") or "").strip(),
        api_token=str(
            values.get("KOTAK_API_TOKEN") or values.get("BROKER_API_SECRET") or ""
        ).strip(),
        mobile=str(values.get("KOTAK_MOBILE") or "").strip(),
        mpin=str(values.get("KOTAK_MPIN") or "").strip(),
        access_secret=str(
            values.get("SCALPER_ACCESS_SECRET") or values.get("NEO_LEGACY_ACCESS_SECRET") or ""
        ),
    )


def authenticate_saved_kotak(totp, settings=None, *, authenticate=None):
    """Verify first; callers commit authentication only after success."""
    if not isinstance(totp, str) or not re.fullmatch(r"[0-9]{6}", totp):
        return None, "Enter the current six-digit authenticator code."
    settings = settings or read_saved_kotak_settings()
    if not all((settings.ucc, settings.api_token, settings.mobile, settings.mpin)):
        return None, "Kotak private settings are incomplete. Complete the local configuration."
    if authenticate is None:
        from broker.kotak.api.auth_api import authenticate_broker

        authenticate = authenticate_broker
    try:
        auth, error = authenticate(settings.mobile, totp, settings.mpin)
    except Exception:
        from utils.logging import get_logger

        get_logger(__name__).exception("Saved Kotak authentication did not complete")
        return None, "Kotak login did not complete. Retry with a fresh authenticator code."
    if error or not isinstance(auth, str) or not auth:
        return None, "Kotak could not verify this login. Retry with a fresh authenticator code."
    return auth, None


def _endpoint_allowed(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.hostname.endswith(".kotaksecurities.com")
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def cached_native_auth(source: Path, settings: SavedKotakSettings, now: datetime):
    """Translate a bound, private, unexpired cache; this does not sign in a browser."""
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            stat = os.fstat(stream.fileno())
            if stat.st_uid != os.getuid() or stat.st_mode & 0o077 or stat.st_size > 16384:
                return None
            data = json.load(stream)
        binding = hashlib.sha256((settings.api_token + "\0" + settings.ucc).encode()).hexdigest()
        if data.get("version") != 1 or not hmac.compare_digest(
            str(data.get("binding", "")), binding
        ):
            return None
        issued = datetime.fromisoformat(data["issued_at"])
        until = datetime.fromisoformat(data["valid_until"])
        if not all(v.tzinfo for v in (issued, until, now)) or issued > now:
            return None
        until = min(
            until, (issued + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        )
        cached = data["session"]
        token, sid, base = (cached.get(k) for k in ("token", "sid", "base_url"))
        if not all(isinstance(v, str) and v and ":::" not in v for v in (token, sid, base)):
            return None
        if not _endpoint_allowed(base):
            return None
        try:
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            until = min(until, datetime.fromtimestamp(float(claims["exp"]), now.tzinfo))
        except (ValueError, KeyError, IndexError, TypeError, OverflowError):
            pass
        if now >= until:
            return None
        center = cached.get("data_center", "")
        if not isinstance(center, str) or ":::" in center or ":::" in settings.api_token:
            return None
        return f"{token}:::{sid}:::{base}:::{settings.api_token}:::{center}"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def legacy_access_is_valid(cookie, secret):
    """Verify the current terminal's signed owner session during migration."""
    if not isinstance(cookie, str) or not cookie or len(cookie) > 8192 or not secret:
        return False
    serializer = URLSafeTimedSerializer(
        secret,
        salt="cookie-session",
        serializer=TaggedJSONSerializer(),
        signer_kwargs={"key_derivation": "hmac", "digest_method": hashlib.sha1},
    )
    try:
        return serializer.loads(cookie, max_age=31 * 86400).get("local_access") is True
    except (BadSignature, ValueError, TypeError, AttributeError):
        return False
