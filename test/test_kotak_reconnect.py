"""A signed-in OpenAlgo session must still be able to reauthenticate Kotak."""

import inspect

from flask import Flask, session

from blueprints import brlogin


def reconnect_app():
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.add_url_rule("/dashboard", endpoint="dashboard_bp.dashboard", view_func=lambda: "dashboard")
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.broker_auth_functions = {"kotak_auth": lambda *_: (None, "TOTP rejected")}
    return app


def test_signed_in_kotak_reconnect_opens_totp_form():
    app = reconnect_app()
    with app.test_request_context("/kotak/callback"):
        session.update(user="alice", logged_in=True, broker="kotak")
        response = inspect.unwrap(brlogin.broker_callback)("kotak")
        assert response.location == "/broker/kotak/totp"


def test_signed_in_kotak_post_checks_credentials_instead_of_false_success():
    app = reconnect_app()
    with app.test_request_context("/kotak/callback", method="POST", data={}):
        session.update(user="alice", logged_in=True, broker="kotak")
        response, status = inspect.unwrap(brlogin.broker_callback)("kotak")
        assert status == 400
        assert response.json["status"] == "error"


def test_kotak_reconnect_still_requires_app_login():
    app = reconnect_app()
    with app.test_request_context("/kotak/callback"):
        response = inspect.unwrap(brlogin.broker_callback)("kotak")
        assert response.location == "/login"


def test_kotak_success_persists_account_used_for_authentication(monkeypatch):
    app = reconnect_app()
    app.broker_auth_functions["kotak_auth"] = lambda *_: ("authenticated-token", None)
    monkeypatch.setattr(brlogin, "get_broker_api_key", lambda: "test-ucc")
    received = []
    monkeypatch.setattr(
        brlogin, "handle_auth_success", lambda *args, **kwargs: received.append(kwargs) or "saved"
    )
    with app.test_request_context(
        "/kotak/callback",
        method="POST",
        data={"mobile": "0000000000", "totp": "000000", "mpin": "000000"},
    ):
        session.update(user="alice", logged_in=True, broker="kotak")
        assert inspect.unwrap(brlogin.broker_callback)("kotak") == "saved"
    assert received[0]["user_id"] == "test-ucc"


def test_kotak_account_change_during_login_refuses_to_store_mislabeled_token(monkeypatch):
    app = reconnect_app()
    account = "first-ucc"

    def authenticate(*args):
        nonlocal account
        account = "second-ucc"
        return "authenticated-first-account-token", None

    app.broker_auth_functions["kotak_auth"] = authenticate
    monkeypatch.setattr(brlogin, "get_broker_api_key", lambda: account)
    monkeypatch.setattr(
        brlogin,
        "handle_auth_success",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not persist")),
    )
    with app.test_request_context(
        "/kotak/callback",
        method="POST",
        data={"mobile": "0000000000", "totp": "000000", "mpin": "000000"},
    ):
        session.update(user="alice", logged_in=True, broker="kotak")
        response, code = inspect.unwrap(brlogin.broker_callback)("kotak")
    assert code == 409
    assert "changed" in response.json["message"]
