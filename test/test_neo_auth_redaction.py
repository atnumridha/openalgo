import json
from types import SimpleNamespace

import pytest
from flask import Flask
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf


def test_kotak_failed_login_does_not_echo_private_response(caplog, monkeypatch):
    from broker.kotak.api import auth_api

    class Broker:
        def post(self, *args, **kwargs):
            return SimpleNamespace(
                status_code=424, text=json.dumps({"message": "PRIVATE-MPIN-RESPONSE"})
            )

    monkeypatch.setattr(auth_api, "get_httpx_client", lambda: Broker())
    monkeypatch.setattr("utils.config.get_broker_api_key", lambda: "fixture-ucc")
    monkeypatch.setattr("utils.config.get_broker_api_secret", lambda: "fixture-api-token")
    auth, error = auth_api.authenticate_broker("9999999999", "654321", "123456")
    assert auth is None
    assert "PRIVATE-MPIN-RESPONSE" not in error
    assert "PRIVATE-MPIN-RESPONSE" not in caplog.text


def test_saved_login_disables_anonymous_account_bootstrap(monkeypatch):
    from blueprints.neo_login import neo_login_bp
    from limiter import limiter

    monkeypatch.setenv("NEO_SAVED_LOGIN", "TRUE")
    app = Flask(__name__)
    app.secret_key = "fixture-native-key-01234567890123"
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    CSRFProtect(app)
    limiter.init_app(app)
    app.register_blueprint(neo_login_bp)

    @app.get("/auth/csrf-token")
    def nonce():
        return {"csrf_token": generate_csrf()}

    @app.post("/auth/setup")
    def setup():
        return {"status": "created"}

    client = app.test_client()
    csrf = client.get("/auth/csrf-token").json["csrf_token"]
    response = client.post(
        "/auth/setup", json={"username": "attacker"}, headers={"X-CSRFToken": csrf}
    )
    assert response.status_code == 403
