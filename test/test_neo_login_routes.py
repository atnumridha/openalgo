import pytest
from flask import Flask, session
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf

from blueprints.neo_login import neo_login_bp
from limiter import limiter


@pytest.fixture
def login_client(monkeypatch):
    monkeypatch.setenv("NEO_SAVED_LOGIN", "TRUE")
    monkeypatch.setenv("HOST_SERVER", "http://127.0.0.1:5001")
    app = Flask(__name__)
    app.secret_key = "fixture-app-secret-0123456789012345"
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    CSRFProtect(app)
    limiter.init_app(app)
    app.register_blueprint(neo_login_bp)

    @app.get("/auth/csrf-token")
    def csrf():
        return {"csrf_token": generate_csrf()}

    client = app.test_client()
    token = client.get("/auth/csrf-token").json["csrf_token"]
    return app, client, {"Origin": "http://127.0.0.1:5001", "X-CSRFToken": token}


def test_failed_totp_preserves_existing_owner_session(login_client, monkeypatch):
    _, client, headers = login_client
    with client.session_transaction() as current:
        current["user"] = "existing-owner"
        current["logged_in"] = True
        current["broker"] = "kotak"
    monkeypatch.setattr(
        "blueprints.neo_login.authenticate_saved_kotak", lambda *a: (None, "Use a fresh code.")
    )
    monkeypatch.setattr(
        "blueprints.neo_login.complete_verified_login",
        lambda *a: pytest.fail("Failed code committed auth"),
    )
    result = client.post("/auth/neo-kotak-login", json={"totp": "654321"}, headers=headers)
    assert result.status_code == 400 and result.json["message"] == "Use a fresh code."
    with client.session_transaction() as current:
        assert current["user"] == "existing-owner" and current["logged_in"] is True


def test_foreign_origin_and_missing_csrf_cannot_sign_in(login_client):
    _, client, headers = login_client
    assert (
        client.post(
            "/auth/neo-kotak-login",
            json={"totp": "654321"},
            headers={**headers, "Origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/auth/neo-kotak-login", json={"totp": "654321"}, headers={"Origin": headers["Origin"]}
        ).status_code
        == 400
    )


def test_browser_cannot_override_private_mobile_or_mpin(login_client, monkeypatch):
    _, client, headers = login_client
    monkeypatch.setattr(
        "blueprints.neo_login.authenticate_saved_kotak",
        lambda *a: pytest.fail("Unexpected credentials reached broker"),
    )
    result = client.post(
        "/auth/neo-kotak-login", json={"totp": "654321", "mpin": "000000"}, headers=headers
    )
    assert result.status_code == 400


def test_server_cache_alone_does_not_authenticate_unknown_browser(login_client, monkeypatch):
    _, client, headers = login_client
    monkeypatch.setattr("blueprints.neo_login.can_resume_owner", lambda: False)
    monkeypatch.setattr(
        "blueprints.neo_login.complete_verified_login",
        lambda *a: pytest.fail("Unknown browser authenticated"),
    )
    result = client.post("/auth/neo-resume", json={}, headers=headers)
    assert result.status_code == 401


def test_login_response_excludes_verified_broker_secret(login_client, monkeypatch):
    _, client, headers = login_client
    monkeypatch.setattr(
        "blueprints.neo_login.authenticate_saved_kotak", lambda *a: ("secret-native-token", None)
    )

    def commit(auth):
        assert auth == "secret-native-token"
        session["user"] = "neo"
        session["logged_in"] = True
        return {"status": "success", "username": "neo", "broker": "kotak"}

    monkeypatch.setattr("blueprints.neo_login.complete_verified_login", commit)
    result = client.post("/auth/neo-kotak-login", json={"totp": "654321"}, headers=headers)
    assert result.status_code == 200 and result.json["username"] == "neo"
    assert "secret-native-token" not in result.get_data(as_text=True)


def test_verified_callback_returns_authoritative_mode_and_native_sdk_key(login_client, monkeypatch):
    from types import SimpleNamespace

    from blueprints.neo_login import complete_verified_login
    monkeypatch.setattr("database.user_db.find_user_by_username", lambda: SimpleNamespace(username="owner"))
    monkeypatch.setattr("database.auth_db.get_api_key", lambda user: "existing")
    monkeypatch.setattr("database.auth_db.get_api_key_for_tradingview", lambda user: "native-sdk-key")
    monkeypatch.setattr("database.settings_db.get_analyze_mode", lambda: True)
    monkeypatch.setattr("utils.auth_utils.handle_auth_success", lambda *a, **kw: None)
    monkeypatch.setattr("blueprints.neo_login.read_saved_kotak_settings", lambda: SimpleNamespace(ucc="fixture-ucc"))
    app, _, _ = login_client
    with app.test_request_context():
        result = complete_verified_login("broker-secret")
    assert result["analyze_mode"] is True
    assert result["api_key"] == "native-sdk-key"
    assert "broker-secret" not in str(result)
