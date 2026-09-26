"""Qualification review uses session ownership and accepts no evidence uploads."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from flask import Flask
from flask_wtf.csrf import CSRFProtect

from blueprints import strategy_qualification
from limiter import limiter


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="qualification-test")
    app.register_blueprint(strategy_qualification.strategy_qualification_bp)
    return app.test_client()


def login(client):
    with client.session_transaction() as session:
        session.update(
            logged_in=True,
            user="alice",
            login_time=datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
        )


def test_authentication_and_session_owner(api, monkeypatch):
    monkeypatch.setattr(
        strategy_qualification.qualification, "overview", lambda owner: {"owner": owner}
    )
    assert api.get("/strategy/api/qualification").status_code == 401
    login(api)
    assert api.get("/strategy/api/qualification").json["data"]["owner"] == "alice"


@pytest.mark.parametrize(
    "action,payload",
    [
        (
            "reconcile",
            {
                "reason": "Reviewed fees",
                "costs_confirmed": True,
                "expected_revision": 1,
                "evidence_digest": "viewed",
            },
        ),
        (
            "approve",
            {
                "reason": "Reviewed evidence",
                "acknowledged": True,
                "expected_revision": 1,
                "evidence_digest": "viewed",
            },
        ),
        ("revoke", {"reason": "Withdraw release"}),
    ],
)
def test_review_actions_are_explicit_and_owner_scoped(api, monkeypatch, action, payload):
    login(api)
    calls = []

    def action_fn(owner, campaign_id, data):
        calls.append((owner, campaign_id, data))
        return {"id": campaign_id}

    monkeypatch.setattr(strategy_qualification.qualification, action, action_fn)
    assert (
        api.post(f"/strategy/api/qualification/campaigns/7/{action}", json=payload).status_code
        == 200
    )
    assert calls == [("alice", 7, payload)]


def test_input_limits_errors_and_no_evidence_endpoint(api, monkeypatch):
    login(api)
    assert api.post("/strategy/api/qualification/campaigns", json=[]).status_code == 400
    assert (
        api.post(
            "/strategy/api/qualification/campaigns", data="{", content_type="application/json"
        ).status_code
        == 400
    )
    assert (
        api.post("/strategy/api/qualification/campaigns", json={"padding": "x" * 70000}).status_code
        == 413
    )

    def missing(owner, campaign_id):
        raise LookupError("private owner information")

    monkeypatch.setattr(strategy_qualification.qualification, "detail", missing)
    response = api.get("/strategy/api/qualification/campaigns/1")
    assert response.status_code == 404 and "private" not in response.text
    assert api.post("/strategy/api/qualification/campaigns/1/trades", json={}).status_code == 404
    assert api.post("/strategy/api/qualification/campaigns/1/quotes", json={}).status_code == 404


def test_review_routes_inherit_application_csrf(api):
    CSRFProtect(api.application)
    login(api)
    assert (
        api.post(
            "/strategy/api/qualification/campaigns/1/approve",
            json={"reason": "Review", "acknowledged": True},
        ).status_code
        == 400
    )
