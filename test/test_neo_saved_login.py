import json
from datetime import datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface

from services.kotak_saved_login import (
    SavedKotakSettings,
    authenticate_saved_kotak,
    cached_native_auth,
    legacy_access_is_valid,
    read_saved_kotak_settings,
)

NOW = datetime(2026, 10, 13, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def settings():
    return SavedKotakSettings(
        ucc="fixture-ucc",
        api_token="fixture-api-token",
        mobile="9999999999",
        mpin="123456",
        access_secret="fixture-legacy-secret",
    )


def session_file(tmp_path, **changes):
    s = settings()
    payload = {
        "version": 1,
        "binding": sha256((s.api_token + "\0" + s.ucc).encode()).hexdigest(),
        "issued_at": (NOW - timedelta(hours=1)).isoformat(),
        "valid_until": NOW.replace(hour=23, minute=59).isoformat(),
        "session": {
            "token": "fixture-token",
            "sid": "fixture-sid",
            "base_url": "https://cis.kotaksecurities.com",
            "data_center": "E43",
        },
    }
    payload.update(changes)
    path = tmp_path / "broker-session.json"
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    return path


def test_private_settings_mapping_never_displays_credentials(tmp_path):
    path = tmp_path / "settings.env"
    path.write_text(
        "KOTAK_UCC=fixture-ucc\nKOTAK_API_TOKEN=fixture-token\nKOTAK_MOBILE=9999999999\nKOTAK_MPIN=123456\nSCALPER_ACCESS_SECRET=fixture-secret\n"
    )
    s = read_saved_kotak_settings(path)
    assert s.ucc == "fixture-ucc" and s.api_token == "fixture-token"
    assert s.mobile == "9999999999" and s.mpin == "123456"
    assert "123456" not in repr(s) and "fixture-token" not in repr(s)


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", None])
def test_malformed_totp_never_reaches_broker(code):
    def forbidden(*args):
        pytest.fail("Malformed code reached broker")

    token, error = authenticate_saved_kotak(code, settings(), authenticate=forbidden)
    assert token is None and error


def test_verified_totp_uses_stored_mobile_and_mpin():
    def broker(mobile, code, mpin):
        assert (mobile, code, mpin) == ("9999999999", "654321", "123456")
        return "verified-native-token", None

    token, error = authenticate_saved_kotak("654321", settings(), authenticate=broker)
    assert token == "verified-native-token" and error is None


def test_failed_totp_has_no_secret_in_user_error():
    token, error = authenticate_saved_kotak(
        "654321", settings(), authenticate=lambda *args: (None, "fixture-api-token 123456")
    )
    assert token is None and error
    assert "fixture-api-token" not in error and "123456" not in error


def test_cached_same_day_session_translates_native_auth(tmp_path):
    path = session_file(tmp_path)
    assert cached_native_auth(path, settings(), NOW) == (
        "fixture-token:::fixture-sid:::https://cis.kotaksecurities.com:::fixture-api-token:::E43"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"binding": "another-account"},
        {"valid_until": (NOW - timedelta(seconds=1)).isoformat()},
        {"issued_at": (NOW + timedelta(seconds=1)).isoformat()},
        {"valid_until": "2026-10-13T23:59:00"},
    ],
)
def test_invalid_cached_session_is_not_restored(tmp_path, change):
    assert cached_native_auth(session_file(tmp_path, **change), settings(), NOW) is None


def test_cached_session_requires_safe_file_permissions(tmp_path):
    path = session_file(tmp_path)
    path.chmod(0o644)
    assert cached_native_auth(path, settings(), NOW) is None


def test_cached_session_cannot_choose_external_broker_endpoint(tmp_path):
    path = session_file(tmp_path)
    data = json.loads(path.read_text())
    data["session"]["base_url"] = "https://attacker.example"
    path.write_text(json.dumps(data))
    assert cached_native_auth(path, settings(), NOW) is None


def test_legacy_owner_cookie_is_verified_and_forgery_rejected():
    app = Flask(__name__)
    app.secret_key = settings().access_secret
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    owner = serializer.dumps({"local_access": True, "csrf": "fixture-csrf"})
    assert legacy_access_is_valid(owner, settings().access_secret)
    assert not legacy_access_is_valid(owner + "changed", settings().access_secret)
    assert not legacy_access_is_valid(owner, "wrong-secret")
    assert not legacy_access_is_valid(serializer.dumps({"local_access": False}), app.secret_key)
    assert not legacy_access_is_valid(None, app.secret_key)
