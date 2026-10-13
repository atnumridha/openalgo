from types import SimpleNamespace

import pytest
from flask import Flask, session
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from test_native_entries import OWNER, boundary, isolated, prepare
from test_ownership import owned

from blueprints.neo_desk import neo_desk_bp
from database import neo_desk_db as desk
from services.neo_desk.service import NeoDeskService
from test.neo_desk.conftest import when


class Host:
    def start(self, owner):
        return True, None

    def stop(self, owner):
        return True, None

    def status(self, owner):
        return {"running": False}


class Market:
    def snapshot(self, *a):
        raise AssertionError("Unarmed state requested market inputs")


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr("services.neo_desk.service.get_analyze_mode", lambda: True)
    return NeoDeskService(market=Market(), host=Host())


@pytest.fixture
def client(service, monkeypatch):
    monkeypatch.setenv("NEO_SAVED_LOGIN", "TRUE")
    monkeypatch.setattr("blueprints.neo_desk.get_service", lambda: service)
    app = Flask(__name__)
    app.secret_key = "fixture-key"
    app.config.update(TESTING=True)
    CSRFProtect(app)
    app.register_blueprint(neo_desk_bp)

    @app.get("/csrf")
    def csrf():
        return {"csrf_token": generate_csrf()}

    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = OWNER
        s["logged_in"] = True
        s["broker"] = "kotak"
    token = c.get("/csrf").json["csrf_token"]
    return c, {"X-CSRFToken": token}


def test_one_profile_and_flat_only_switch(service, monkeypatch):
    desk.configure(OWNER, activation="Stopped")
    service.change_settings(OWNER, {"profile": "orb_controls"})
    assert service.state(OWNER)["profile"] == "orb_controls"
    desk.configure(OWNER, profile="orb_trail", activation="Active")
    owned(monkeypatch)
    with pytest.raises(ValueError):
        service.change_settings(OWNER, {"profile": "donchian_controls"})


def test_stop_retains_exit_management(service, monkeypatch):
    from decimal import Decimal as D

    from services.neo_desk.lifecycle import manage_once

    rid, orders = owned(monkeypatch)
    service.command(OWNER, "stop", "stop-1")
    assert desk.view(OWNER)["activation"] == "Stopped" and desk.view(OWNER)["run_id"] == rid
    manage_once(
        OWNER,
        now=when(),
        quote_provider=lambda symbol, exchange: D(1) if exchange == "NSE_INDEX" else D(50),
    )
    assert len(orders) == 2


def test_research_live_rejection_visible(client, monkeypatch):
    c, headers = client
    desk.configure(OWNER, profile="price_retest", activation="Stopped")
    monkeypatch.setattr("services.neo_desk.service.get_analyze_mode", lambda: False)
    result = c.post(
        "/neodesk/api/execution/start",
        json={"request_id": "start-1", "confirm_live": True},
        headers=headers,
    )
    assert result.status_code == 400 and "Sandbox" in result.json["message"]
    assert desk.view(OWNER)["activation"] == "Stopped"


def test_runner_cannot_arm_live(service):
    desk.configure(OWNER, mode="live", activation="Stopped")
    result = service.poll(OWNER, now=when())
    assert not result["acted"] and desk.view(OWNER)["activation"] == "Stopped"


def test_browser_auth_and_csrf_required(client):
    c, headers = client
    assert c.post("/neodesk/api/execution/stop", json={"request_id": "stop"}).status_code == 400
    with c.session_transaction() as s:
        s.clear()
    assert c.get("/neodesk/api/state").status_code == 401


def test_start_does_not_submit_a_broker_order(service, monkeypatch):
    orders = []
    boundary(monkeypatch, "CE", orders)
    result = service.command(OWNER, "start", "start-once")
    assert result["activation"] == "Active" and orders == []
    assert service.command(OWNER, "start", "start-once")["activation"] == "Active"


def test_push_subscription_cannot_use_body_to_impersonate_an_owner(client, monkeypatch):
    import flask

    from blueprints.neo_desk import subscribe_desk
    from extensions import socketio

    c, _ = client
    app = c.application
    joined = []
    monkeypatch.setattr("blueprints.neo_desk.join_room", lambda room: joined.append(room))
    with app.test_request_context():
        assert not subscribe_desk({"owner": OWNER})["ok"] and joined == []
        flask.session["user"] = OWNER
        flask.session["logged_in"] = True
        flask.session["broker"] = "kotak"
        assert subscribe_desk({"owner": "foreign"})["ok"]
    from services.neo_desk.views import room_for_owner

    assert joined == [room_for_owner(OWNER)]


def test_optional_provider_routes_are_disabled_in_a_normal_instance(client, monkeypatch):
    monkeypatch.setenv("NEO_SAVED_LOGIN", "FALSE")
    c, headers = client
    assert c.get("/neodesk/api/state").status_code == 404
    assert (
        c.post(
            "/neodesk/api/execution/start", json={"request_id": "start"}, headers=headers
        ).status_code
        == 404
    )


@pytest.mark.parametrize("profile", ["orb_trail", "orb_controls", "donchian_controls"])
def test_supported_live_presets_start_via_authenticated_native_controls_without_placing_an_order(client, monkeypatch, profile):
    c, headers = client
    desk.configure(OWNER, profile=profile, activation="Stopped")
    monkeypatch.setattr("services.neo_desk.service.get_analyze_mode", lambda: False)
    sent = []
    monkeypatch.setattr("services.strategy_module.order_dispatch.dispatch_order", lambda **kwargs: sent.append(kwargs))
    refused = c.post("/neodesk/api/execution/start", json={"request_id": "live-unconfirmed"}, headers=headers)
    assert refused.status_code == 400 and desk.view(OWNER)["activation"] == "Stopped"
    response = c.post("/neodesk/api/execution/start", json={"request_id": "live-start-confirmed", "confirm_live": True}, headers=headers)
    assert response.status_code == 200
    assert response.json["mode"] == "live" and response.json["activation"] == "Active"
    assert sent == []
    stopped = c.post("/neodesk/api/execution/stop", json={"request_id": "live-stop"}, headers=headers)
    assert stopped.status_code == 200 and stopped.json["activation"] == "Stopped"
