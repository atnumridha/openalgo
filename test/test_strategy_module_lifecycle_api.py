"""The /strategy lifecycle routes: the ones that move money.

The engine is mocked throughout. What is asserted here is the layer above it:
what the API refuses, what status code it refuses with, what it records, and
that a route which is not yours is invisible rather than forbidden.

Shares the isolated-store fixtures from test_strategy_module_api.py's approach
so a failing test cannot leave rows behind for the next one.
"""

import sys
from contextlib import nullcontext
from datetime import datetime, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytz
from flask import Flask, session

sys.path.insert(0, str(Path(__file__).parents[1]))

from blueprints import strategy_module  # noqa: E402
from database import strategy_module_db as store  # noqa: E402
from database.engine_factory import create_db_engine  # noqa: E402
from limiter import limiter  # noqa: E402
from services.strategy_module import live_authorization as authz  # noqa: E402
from services.strategy_module.automation_control import (  # noqa: E402
    ControlResult,
    WorkflowLink,
    require_automation_entry,
)
from services.strategy_module.engine import StartResult  # noqa: E402

USER = "lifecycle-tester"
OTHER = "somebody-else"


@pytest.fixture(scope="session", autouse=True)
def isolated_store(tmp_path_factory):
    path = tmp_path_factory.mktemp("strategy-lifecycle") / "lifecycle-test.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    store.db_session.remove()
    store.db_session.configure(bind=engine)
    store.engine = engine
    store.Base.metadata.create_all(bind=engine)
    yield engine
    store.db_session.remove()
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(isolated_store):
    authz.revoke(USER)
    store.db_session.remove()
    with isolated_store.begin() as connection:
        for table in reversed(store.Base.metadata.sorted_tables):
            connection.execute(table.delete())
    yield
    authz.revoke(USER)
    store.db_session.remove()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    application = Flask(__name__)
    application.config.update(TESTING=True, SECRET_KEY="k", PROPAGATE_EXCEPTIONS=True)
    application.register_blueprint(strategy_module.strategy_module_bp)
    test_client = application.test_client()
    with test_client.session_transaction() as flask_session:
        flask_session["logged_in"] = True
        flask_session["user"] = USER
        flask_session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    return test_client


def _make(user=USER, name="Lifecycle", running_run_id=None):
    created, error = store.create_strategy(
        user,
        {
            "name": name,
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "universe_tab": "weekly_monthly",
            "strategy_type": "intraday",
            "entry_time": time(9, 20),
            "exit_time": time(15, 10),
            # A complete leg. The store does no validation, but PATCH
            # re-validates the whole merged configuration, so a fixture that
            # wrote an incomplete one here would make every edit a 400.
            "legs": [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "strike_mode": "atm",
                    "atm_offset": "ATM",
                    "expiry": "weekly",
                    "trail": {"x": 0, "y": 0},
                }
            ],
        },
    )
    assert error is None, error
    if running_run_id is not None:
        store.set_strategy_status(created["id"], "running", running_run_id)
    return created["id"]


def _make_signal(user=USER, name="Signal", *, live=False, stop=5):
    created, error = store.create_strategy(user, {
        "name": name, "strategy_kind": "signal", "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX", "universe_tab": "weekly_monthly",
        "strategy_type": "intraday", "entry_time": time(9, 20),
        "exit_time": time(15, 10), "live_enabled": live,
        "legs": [{"id": 1, "symbol": "NIFTY", "exchange": "NFO",
                  "side": "both", "qty": 1, "qty_mode": "lots",
                  "segment": "futures", "sl_pts": stop}],
    })
    assert error is None, error
    if live:
        ok, message = store.set_live_enabled(created["id"], user, True)
        assert ok, message
    return created["id"]


def test_automation_individual_routes_are_session_scoped_and_itemized(client):
    owned = _make_signal(name="Owned")
    foreign = _make_signal(user=OTHER)
    for action in ("enable", "disable"):
        with patch.object(strategy_module, "_api_key_for", return_value="secret-key") as key, patch(
            "services.strategy_module.automation_control.enable_sandbox",
            return_value=ControlResult(True, "armed", 17, None),
        ) as enable, patch(
            "services.strategy_module.automation_control.disable_and_close",
            return_value=ControlResult(True, "closing", 17, 23, True),
        ) as disable:
            path = f"/strategy/api/strategies/{owned}/automation/{action}"
            response = client.post(path)
            expected = {"strategy_id": owned, "name": "Owned",
                        "state": "armed" if action == "enable" else "closing",
                        "outcome": "armed" if action == "enable" else "close_pending",
                        "workflow_id": 17, "run_id": None if action == "enable" else 23,
                        "close_pending": action == "disable", "reason": None}
            assert response.status_code == 200
            assert response.get_json() == {"status": "success", "data": expected}
            assert client.post(f"/strategy/api/strategies/{foreign}/automation/{action}").status_code == 404
            assert client.post(f"/strategy/api/strategies/999999/automation/{action}").status_code == 404
            if action == "enable":
                enable.assert_called_once_with(owned, USER, "secret-key")
                key.assert_called_once_with(USER)
                disable.assert_not_called()
            else:
                disable.assert_called_once_with(owned, USER)
                enable.assert_not_called()
                key.assert_not_called()


def test_automation_enable_maps_validation_conflict_and_engine_failure(client):
    sid = _make_signal()
    path = f"/strategy/api/strategies/{sid}/automation/enable"
    cases = [
        (ControlResult(False, "disabled", error="API key not configured"), 400),
        (ControlResult(False, "disabled", error="No Flow workflow is explicitly linked"), 400),
        (ControlResult(False, "disabled", error="Flow workflow 7 is not in sandbox mode"), 400),
        (ControlResult(False, "disabled", error="Strategy not found"), 404),
        (ControlResult(False, "closing", close_pending=True,
                       error="Close/reconciliation must finish before enabling"), 409),
        (ControlResult(False, "disabled", error="Flow activation failed"), 409),
    ]
    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"):
        for result, status in cases:
            with patch("services.strategy_module.automation_control.enable_sandbox", return_value=result):
                response = client.post(path)
            assert response.status_code == status
            if status == 404:
                assert response.get_json() == {"status": "error", "message": "Strategy not found"}
                continue
            assert response.get_json()["data"] == {
                "strategy_id": sid, "name": "Signal", "state": result.state,
                "outcome": "failed", "workflow_id": None, "run_id": None,
                "close_pending": result.close_pending, "reason": result.error,
            }


def test_automation_routes_require_session(client):
    sid = _make_signal()
    client.application.add_url_rule("/test-login", endpoint="auth.login", view_func=lambda: "login")
    with client.session_transaction() as flask_session:
        flask_session.clear()
    for path in (f"/strategy/api/strategies/{sid}/automation/enable",
                 f"/strategy/api/strategies/{sid}/automation/disable",
                 "/strategy/api/automation/strategies/enable-all-sandbox"):
        assert client.post(path).status_code in (302, 401)


def test_automation_routes_follow_global_csrf_protection():
    from flask_wtf import CSRFProtect
    from flask_wtf.csrf import generate_csrf

    application = Flask(__name__)
    application.config.update(SECRET_KEY="csrf-test-key", WTF_CSRF_ENABLED=True)
    application.register_blueprint(strategy_module.strategy_module_bp)
    application.add_url_rule("/csrf", view_func=generate_csrf)
    CSRFProtect(application)
    client = application.test_client()
    with client.session_transaction() as flask_session:
        flask_session["logged_in"] = True
        flask_session["user"] = USER
        flask_session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    paths = ("/strategy/api/strategies/999999/automation/enable",
             "/strategy/api/strategies/999999/automation/disable",
             "/strategy/api/automation/strategies/enable-all-sandbox")
    for path in paths:
        assert client.post(path).status_code == 400
    token = client.get("/csrf").get_data(as_text=True)
    for path in paths[:2]:
        assert client.post(path, headers={"X-CSRFToken": token}).status_code == 404
    with patch.object(strategy_module, "_api_key_for", return_value=None):
        assert client.post(paths[2], headers={"X-CSRFToken": token}).status_code == 200


def test_real_enable_transition_is_audited_once_and_idempotent(client):
    from database import flow_db
    from services import flow_lifecycle_service as flow
    from services.strategy_module import automation_control, recovery

    sid = _make_signal()
    active = {"value": False}
    def link(_row, _workflow_id=None):
        return WorkflowLink(7, active["value"], "sandbox", USER, None), None
    def activate(_workflow_id, _key):
        active["value"] = True
        return {"status": "success"}, 200
    workflow = SimpleNamespace(nodes=[], is_active=False)
    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"), patch.object(
        automation_control, "resolve_workflow_link", side_effect=link
    ), patch.object(automation_control, "_exclusive_link_under_lease", side_effect=link), patch.object(
        flow_db, "workflow_mutation_lease", return_value=nullcontext()
    ), patch.object(flow_db, "get_workflow", return_value=workflow), patch.object(
        flow, "execution_blocked", return_value=None
    ), patch.object(flow, "activate_workflow", side_effect=activate), patch.object(
        recovery, "verify_automation_flatness", return_value=(True, None)
    ), patch.object(store, "has_unresolved_order_outcomes", return_value=False), patch(
        "services.strategy_module.engine.start_run"
    ) as start:
        first = client.post(f"/strategy/api/strategies/{sid}/automation/enable")
        second = client.post(f"/strategy/api/strategies/{sid}/automation/enable")
    assert first.status_code == second.status_code == 200
    assert first.get_json()["data"]["state"] == "armed"
    assert second.get_json()["data"]["state"] == "armed"
    store.db_session.expire_all()
    assert store.get_strategy(sid, USER).automation_state == "armed"
    assert len([event for event in store.list_events(sid) if event["kind"] == "automation_armed"]) == 1
    start.assert_not_called()


def test_bulk_automation_arms_signal_and_batch_rows_and_keeps_partial_success(client):
    good = _make_signal(name="Good")
    failed = _make_signal(name="Failed")
    batch = _make(name="Batch")
    live = _make_signal(name="Live", live=True)
    unlinked = _make_signal(name="Unlinked")
    invalid = _make_signal(name="Invalid", stop=0)
    foreign = _make_signal(user=OTHER, name="Foreign")
    def enable(sid, owner, key):
        assert owner == USER and key == "secret-key"
        if sid == failed:
            return ControlResult(False, "disabled", error="Flow activation failed")
        if sid == batch:
            ok, message = store.set_automation_state(sid, owner, "armed")
            assert ok, message
            return ControlResult(True, "armed", 8)
        if sid == live:
            return ControlResult(False, "disabled", error="Live-enabled strategies cannot use sandbox automation")
        if sid == unlinked:
            return ControlResult(False, "disabled", error="No Flow workflow is explicitly linked")
        if sid == invalid:
            return ControlResult(False, "disabled", error="Every signal leg requires a configured positive stop loss")
        ok, message = store.set_automation_state(sid, owner, "armed")
        assert ok, message
        return ControlResult(True, "armed", 7)
    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"), patch(
        "services.strategy_module.automation_control.enable_sandbox", side_effect=enable
    ) as armed, patch(
        "services.strategy_module.engine.start_run"
    ) as start:
        response = client.post("/strategy/api/automation/strategies/enable-all-sandbox")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    items = {item["strategy_id"]: item for item in body["data"]["items"]}
    assert set(items) == {good, failed, batch, live, unlinked, invalid}
    assert foreign not in items
    assert items[good] == {"strategy_id": good, "name": "Good", "state": "armed",
                           "outcome": "armed", "workflow_id": 7, "run_id": None,
                           "close_pending": False, "reason": None}
    assert items[failed]["outcome"] == "failed"
    assert items[batch]["outcome"] == "armed"
    assert items[batch]["workflow_id"] == 8
    for sid in (live, unlinked, invalid):
        assert items[sid]["outcome"] == "skipped"
        assert items[sid]["reason"]
    assert {call.args[0] for call in armed.call_args_list} == {good, failed, batch, live, unlinked, invalid}
    store.db_session.expire_all()
    assert store.get_strategy(good, USER).automation_state == "armed"
    start.assert_not_called()
    events = store.list_events(good)
    summary = [event for event in events if event["kind"] == "automation_bulk_summary"]
    assert len(summary) == 1
    assert all("secret-key" not in str(event) for event in summary)


def test_bulk_automation_skips_unresolved_account_outcomes(client):
    sid = _make_signal()
    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"), patch(
        "database.strategy_module_db.has_unresolved_order_outcomes", return_value=True
    ), patch("services.strategy_module.automation_control.enable_sandbox",
             return_value=ControlResult(False, "disabled", error="An order outcome is unresolved; reconcile before enabling")) as armed:
        response = client.post("/strategy/api/automation/strategies/enable-all-sandbox")
    assert response.status_code == 200
    item = response.get_json()["data"]["items"][0]
    assert item["strategy_id"] == sid
    assert item["outcome"] == "skipped"
    assert "unresolved" in item["reason"]
    armed.assert_called_once_with(sid, USER, "secret-key")


def test_bulk_rechecks_armed_signal_and_blocks_entries_when_stop_is_missing(client):
    sid = _make_signal(stop=0)
    ok, message = store.set_automation_state(sid, USER, "armed")
    assert ok, message
    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"):
        response = client.post("/strategy/api/automation/strategies/enable-all-sandbox")
    assert response.status_code == 200
    item = response.get_json()["data"]["items"][0]
    assert item["strategy_id"] == sid
    assert item["state"] == "close_failed"
    assert item["close_pending"] is True
    assert "stop loss" in item["reason"]
    store.db_session.expire_all()
    assert store.get_strategy(sid, USER).automation_state == "close_failed"
    assert require_automation_entry(sid, USER)[0] is False


def test_bulk_rechecks_armed_batch_and_fails_closed_without_a_link(client):
    from services.strategy_module import order_dispatch

    sid = _make(name="Legacy armed batch")
    row = store.get_strategy(sid, USER)
    row.legs = [{**row.legs[0], "sl_pts": 5}]
    store.db_session.commit()
    ok, message = store.set_automation_state(sid, USER, "armed")
    assert ok, message
    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"), patch(
        "services.strategy_module.engine.start_run"
    ) as start, patch.object(order_dispatch, "dispatch_order") as order:
        response = client.post("/strategy/api/automation/strategies/enable-all-sandbox")
    assert response.status_code == 200
    item = response.get_json()["data"]["items"][0]
    assert item["strategy_id"] == sid
    assert item["outcome"] == "skipped"
    assert item["state"] == "close_failed"
    assert item["close_pending"] is True
    assert "Flow workflow" in item["reason"]
    store.db_session.expire_all()
    assert store.get_strategy(sid, USER).automation_state == "close_failed"
    assert require_automation_entry(sid, USER)[0] is False
    start.assert_not_called()
    order.assert_not_called()


def test_bulk_automation_returns_503_when_no_row_can_be_processed_safely(client):
    sid = _make_signal()
    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"), patch(
        "services.strategy_module.automation_control.enable_sandbox", side_effect=RuntimeError("store unavailable")
    ) as armed:
        response = client.post("/strategy/api/automation/strategies/enable-all-sandbox")
    assert response.status_code == 503
    armed.assert_called_once()
    summary = [event for event in store.list_events(sid) if event["kind"] == "automation_bulk_summary"]
    assert len(summary) == 1


def test_automation_audit_events_contain_no_credentials(client):
    sid = _make_signal()
    results = [
        ("enable", ControlResult(True, "armed", 7), "automation_armed"),
        ("disable", ControlResult(True, "closing", 7, 8, True), "automation_closing"),
        ("disable", ControlResult(True, "disabled", 7, 8), "automation_disabled"),
        ("disable", ControlResult(False, "close_failed", 7, 8, True,
                                  "close refused"), "automation_close_failed"),
    ]
    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"):
        for action, result, expected_kind in results:
            function = ("enable_sandbox" if action == "enable" else "disable_and_close")
            with patch(f"services.strategy_module.automation_control.{function}", return_value=result):
                response = client.post(f"/strategy/api/strategies/{sid}/automation/{action}")
            assert response.status_code == (200 if result.ok else 409)
            events = store.list_events(sid)
            assert events[0]["kind"] == expected_kind
            assert all("secret-key" not in str(event) for event in events)


def test_profit_comparison_list_is_scoped_to_owner_runs(client):
    from database import profit_comparison_db

    owned = _make()
    foreign = _make(user=OTHER)
    with patch.object(profit_comparison_db, "list_for_runs", return_value=[]) as listed:
        response = client.get(f"/strategy/api/strategies/{owned}/profit-comparisons")
        assert response.status_code == 200
        assert response.get_json()["data"] == []
        listed.assert_called_once_with([], limit=100)

        hidden = client.get(f"/strategy/api/strategies/{foreign}/profit-comparisons")
        assert hidden.status_code == 404
        listed.assert_called_once()


def test_account_lifecycle_socket_room_is_derived_only_from_authenticated_user(client):
    """A caller cannot name another account when subscribing to auth events."""
    with (
        client.application.test_request_context("/socket.io"),
        patch.object(strategy_module, "join_room") as join,
        patch.object(strategy_module, "leave_room") as leave,
    ):
        session["user"] = USER

        assert strategy_module._strategy_user_subscribe({"user_id": OTHER}) == {"status": "success"}
        assert strategy_module._strategy_user_unsubscribe({"user_id": OTHER}) == {
            "status": "success"
        }

    join.assert_called_once_with(f"strategy-user:{USER}")
    leave.assert_called_once_with(f"strategy-user:{USER}")


def test_account_critical_alert_status_is_owner_scoped_after_strategy_deletion(client):
    sid = _make()
    assert store.record_event(
        sid, USER, "protective_stop_uncovered", "Uncovered position",
        severity="critical",
    ) is not None
    assert store.record_automation_event(
        USER, "live_authorization_revoked", "Authorization revoked",
        severity="critical",
    ) is not None
    assert store.record_automation_event(
        OTHER, "live_authorization_revoked", "Other account",
        severity="critical",
    ) is not None
    assert store.delete_strategy(sid, USER) == (True, None)

    response = client.get(f"/strategy/api/automation/critical-alerts?user_id={OTHER}")
    assert response.status_code == 200
    rows = response.json["data"]
    assert len(rows) == 2
    assert {row["user_id"] for row in rows} == {USER}
    assert any(row["strategy_id"] == sid and row["status"] == "pending" for row in rows)
    assert any(row["strategy_id"] is None for row in rows)


def test_account_critical_alert_status_requires_authenticated_session(client):
    client.application.add_url_rule(
        "/test-login", endpoint="auth.login", view_func=lambda: "Login"
    )
    assert store.record_automation_event(
        USER, "live_authorization_revoked", "Private safety event",
        severity="critical",
    ) is not None
    with client.session_transaction() as browser_session:
        browser_session.pop("logged_in", None)
        browser_session.pop("user", None)
    response = client.get("/strategy/api/automation/critical-alerts")
    assert response.status_code != 200
    assert b"Private safety event" not in response.data


# ---------------------------------------------------------------------------
# Live authorization
# ---------------------------------------------------------------------------


def test_live_authorization_requires_confirmation_and_mirrors_only_safe_state(client):
    """The browser may display authorization state but never hold credentials."""
    url = "/strategy/api/automation/live-authorization"

    assert client.post(url, json={"confirm": False}).status_code == 400

    granted = client.post(url, json={"confirm": True})
    assert granted.status_code == 200
    authorization = granted.get_json()["live_authorization"]
    assert authorization["active"] is True
    with client.session_transaction() as flask_session:
        assert flask_session["live_authorization"] == {
            "username": USER,
            "session_day": authorization["session_day"],
            "expires_at": authorization["expires_at"],
        }

    assert client.get(url).get_json()["live_authorization"]["active"] is True
    assert client.delete(url).get_json()["live_authorization"]["active"] is False
    with client.session_transaction() as flask_session:
        assert "live_authorization" not in flask_session

    events = store.list_automation_events(USER)
    assert [event["kind"] for event in events] == [
        "live_authorization_revoked",
        "live_authorization_granted",
    ]
    assert all("strategy_id" not in event for event in events)


def test_account_event_store_refuses_a_strategy_scoped_kind():
    assert store.record_automation_event(USER, "run_started", "wrong owner") is None
    assert store.list_automation_events(USER) == []


@pytest.mark.parametrize("kind", store.AUTOMATION_EVENT_KINDS)
def test_strategy_event_store_refuses_an_account_scoped_kind(kind):
    sid = _make()

    assert store.record_event(sid, USER, kind, "wrong owner") is None
    assert store.list_events(sid) == []


@pytest.mark.parametrize("confirm", [1, 1.0])
def test_live_authorization_rejects_numeric_confirmation_lookalikes(client, confirm):
    """Python equality must not turn a numeric JSON value into confirmation."""
    response = client.post(
        "/strategy/api/automation/live-authorization",
        json={"confirm": confirm},
    )

    assert response.status_code == 400
    assert authz.status(USER).active is False


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


def test_start_requires_a_mode_and_never_defaults_one(client):
    # Defaulting would mean a caller that forgot the field placing real orders
    # on a strategy the operator believed was on paper.
    sid = _make()

    assert client.post(f"/strategy/api/strategies/{sid}/start", json={}).status_code == 400
    assert (
        client.post(f"/strategy/api/strategies/{sid}/start", json={"mode": "real"}).status_code
        == 400
    )


def test_start_hands_the_mode_through_and_returns_the_run(client):
    sid = _make()

    with patch(
        "services.strategy_module.engine.start_run",
        return_value=StartResult(ok=True, run_id=42, legs=[{"leg_id": 1, "ok": True}]),
    ) as start:
        response = client.post(f"/strategy/api/strategies/{sid}/start", json={"mode": "sandbox"})

    assert response.status_code == 200
    assert response.get_json()["run_id"] == 42
    assert start.call_args[0][2] == "sandbox"
    assert start.call_args[1]["trigger_source"] == "manual"


def test_starting_something_already_running_is_a_conflict_not_a_bad_request(client):
    # The UI shows these differently: a 409 means "somebody beat you to it",
    # a 400 means "your configuration is wrong".
    sid = _make()

    with patch(
        "services.strategy_module.engine.start_run",
        return_value=StartResult(ok=False, error="This strategy is already running"),
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/start", json={"mode": "sandbox"})

    assert response.status_code == 409


def test_a_refused_start_reports_which_leg_failed(client):
    sid = _make()

    with patch(
        "services.strategy_module.engine.start_run",
        return_value=StartResult(
            ok=False,
            error="Leg 1: No option contract found",
            legs=[{"leg_id": 1, "ok": False, "error": "Leg 1: No option contract found"}],
        ),
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/start", json={"mode": "sandbox"})

    assert response.status_code == 400
    assert "No option contract found" in response.get_json()["message"]


def test_start_all_sandbox_starts_batch_runs_and_arms_signal_receivers(client):
    first = _make(name="First batch")
    failed = _make(name="Failed batch")
    signal = _make_signal(name="Signal receiver")
    foreign = _make(user=OTHER, name="Foreign")

    def start(sid, owner, mode, *, trigger_source):
        assert owner == USER
        assert mode == "sandbox"
        assert trigger_source == "manual"
        if sid == failed:
            return StartResult(ok=False, error="Risk blocked")
        return StartResult(ok=True, run_id=41, legs=[{"leg_id": 1, "ok": True}])

    with patch.object(strategy_module, "_api_key_for", return_value="secret-key"), patch(
        "services.strategy_module.engine.start_run", side_effect=start
    ) as started, patch(
        "services.strategy_module.automation_control.enable_sandbox",
        return_value=ControlResult(True, "armed", workflow_id=17),
    ) as armed:
        response = client.post("/strategy/api/strategies/start-all-sandbox")

    assert response.status_code == 200
    items = {item["strategy_id"]: item for item in response.get_json()["data"]["items"]}
    assert set(items) == {first, failed, signal}
    assert foreign not in items
    assert items[first]["outcome"] == "started"
    assert items[first]["run_id"] == 41
    assert items[failed]["outcome"] == "failed"
    assert items[failed]["reason"] == "Risk blocked"
    assert items[signal]["outcome"] == "armed"
    assert items[signal]["reason"] == "Waiting for a valid signal"
    assert [call.args[0] for call in started.call_args_list] == [first, failed]
    armed.assert_called_once_with(signal, USER, "secret-key")


def test_start_all_live_requires_exact_confirmation_and_active_authorization(client):
    sid = _make(name="Live batch")
    ok, message = store.set_live_enabled(sid, USER, True)
    assert ok, message
    with patch("services.strategy_module.engine.start_run") as started:
        missing = client.post("/strategy/api/strategies/start-all-live", json={})
        wrong = client.post(
            "/strategy/api/strategies/start-all-live", json={"confirmation": "start live"}
        )
        confirmed_without_authorization = client.post(
            "/strategy/api/strategies/start-all-live", json={"confirmation": "START LIVE"}
        )

    assert missing.status_code == 400
    assert wrong.status_code == 400
    assert confirmed_without_authorization.status_code == 403
    assert "not authorized" in confirmed_without_authorization.get_json()["message"].lower()
    started.assert_not_called()
    assert store.get_strategy(sid, USER).status == "stopped"


def test_start_all_live_starts_only_live_enabled_batch_strategies(client):
    live = _make(name="Live batch")
    ok, message = store.set_live_enabled(live, USER, True)
    assert ok, message
    sandbox_only = _make(name="Sandbox only")
    signal = _make_signal(name="Live signal", live=True)
    authz.grant(USER)

    with patch(
        "services.strategy_module.engine.start_run",
        return_value=StartResult(ok=True, run_id=73, legs=[{"leg_id": 1, "ok": True}]),
    ) as started:
        response = client.post(
            "/strategy/api/strategies/start-all-live", json={"confirmation": "START LIVE"}
        )

    assert response.status_code == 200
    items = {item["strategy_id"]: item for item in response.get_json()["data"]["items"]}
    assert items[live]["outcome"] == "started"
    assert items[live]["run_id"] == 73
    assert items[sandbox_only]["outcome"] == "skipped"
    assert "not live-enabled" in items[sandbox_only]["reason"]
    assert items[signal]["outcome"] == "skipped"
    assert "valid live signal" in items[signal]["reason"]
    started.assert_called_once_with(live, USER, "live", trigger_source="manual")


# ---------------------------------------------------------------------------
# Stop and close
# ---------------------------------------------------------------------------


def test_stopping_a_strategy_that_is_not_running_is_a_conflict(client):
    sid = _make()

    response = client.post(f"/strategy/api/strategies/{sid}/stop", json={})

    assert response.status_code == 409
    assert "not running" in response.get_json()["message"]


def test_stop_exits_the_current_run(client):
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run", return_value={"ok": True, "exits": []}
    ) as stop:
        response = client.post(f"/strategy/api/strategies/{sid}/stop", json={})

    assert response.status_code == 200
    assert stop.call_args[0][0] == 7
    assert stop.call_args[1]["reason"] == "manual"


@pytest.mark.parametrize("route", ["stop", "close_all"])
def test_stop_endpoints_report_accepted_but_still_pending_exits(client, route):
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={"ok": True, "stop_pending": True, "exits": [{"ok": True}]},
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/{route}", json={})

    assert response.status_code == 200
    body = response.get_json()
    assert body["stop_pending"] is True
    assert body["exits"] == [{"ok": True}]


@pytest.mark.parametrize("route", ["stop", "close_all"])
def test_stop_endpoint_failures_preserve_pending_and_per_exit_detail(client, route):
    sid = _make(running_run_id=7)
    exits = [{"leg_id": 1, "ok": False, "error": "No API key"}]

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={
            "ok": False,
            "stop_pending": True,
            "error": "No API key is configured for this user",
            "exits": exits,
        },
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/{route}", json={})

    assert response.status_code == 409
    body = response.get_json()
    assert body["stop_pending"] is True
    assert body["exits"] == exits


def test_close_all_records_the_operator_intent_separately_from_the_stop(client):
    # This event is recorded before the broker exits settle, so it must preserve
    # operator intent without claiming that the account is already flat.
    sid = _make(running_run_id=7)

    with patch("services.strategy_module.engine.stop_run", return_value={"ok": True, "exits": []}):
        response = client.post(f"/strategy/api/strategies/{sid}/close_all", json={})

    assert response.status_code == 200
    events = store.list_events(sid)
    close_request = next(event for event in events if event["kind"] == "close_all_manual")
    assert close_request["message"] == "Operator requested closure of all held legs"


def test_closing_one_leg_reports_whether_the_run_is_now_flat(client):
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.close_leg",
        return_value={"ok": True, "exits": [], "run_stopped": False},
    ) as close:
        response = client.post(f"/strategy/api/strategies/{sid}/legs/1/close", json={})

    assert response.status_code == 200
    body = response.get_json()
    assert body["run_stopped"] is False
    assert body["leg_id"] == "1"
    assert close.call_args[0][1] == "1"


def test_closing_a_leg_on_a_stopped_strategy_is_a_conflict(client):
    sid = _make()

    response = client.post(f"/strategy/api/strategies/{sid}/legs/1/close", json={})

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def test_the_kill_switch_flattens_an_active_run_not_just_the_webhook(client):
    # A lock that leaves a live position open is not a kill switch.
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run", return_value={"ok": True, "exits": []}
    ) as stop:
        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch", json={})

    assert response.status_code == 200
    body = response.get_json()
    assert body["webhook_locked"] is True
    assert body["run_stopped"] is True
    assert stop.call_count == 1
    assert store.get_strategy(sid, USER).webhook_locked is True


def test_the_kill_switch_does_not_report_stopped_while_exit_fills_are_pending(client):
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={"ok": True, "stop_pending": True, "exits": [{"ok": True}]},
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch", json={})

    assert response.status_code == 200
    body = response.get_json()
    assert body["webhook_locked"] is True
    assert body["run_stopped"] is False
    assert body["stop_pending"] is True
    assert "closed" not in body["message"].lower()


def test_the_kill_switch_locks_even_when_there_is_nothing_to_flatten(client):
    sid = _make()

    with patch("services.strategy_module.engine.stop_run") as stop:
        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch", json={})

    assert response.status_code == 200
    assert response.get_json()["run_stopped"] is False
    assert stop.call_count == 0
    assert store.get_strategy(sid, USER).webhook_locked is True


def test_the_kill_switch_still_locks_when_flattening_fails(client):
    # If the broker is unreachable the position stays open, but the webhook must
    # still be shut so nothing new can be added on top of it.
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={"ok": False, "stop_pending": True, "error": "Broker unreachable"},
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch", json={})

    assert response.status_code == 200
    assert response.get_json()["run_stopped"] is False
    assert response.get_json()["stop_pending"] is True
    assert "exit fills pending" not in response.get_json()["message"].lower()
    events = store.list_events(sid)
    assert "exit fills pending" not in events[-1]["message"].lower()
    assert store.get_strategy(sid, USER).webhook_locked is True


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["start", "stop", "close_all", "kill_switch", "unlock_webhook", "legs/1/close"],
)
def test_somebody_elses_strategy_is_invisible_on_every_lifecycle_route(client, path):
    # 404, never 403: a 403 confirms the id is real and lets the space be probed.
    sid = _make(user=OTHER, name="Not yours", running_run_id=7)

    response = client.post(f"/strategy/api/strategies/{sid}/{path}", json={"mode": "sandbox"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Scheduler sync
#
# The job store is in memory so the database stays the single source of truth,
# which only holds if every write syncs. Without these calls the scheduler
# reflects the configuration as it stood at boot: a schedule saved today would
# not fire until the next restart, an edited start time would keep firing at
# the old one, and a deleted strategy would leave its jobs behind.
# ---------------------------------------------------------------------------


def _payload(**overrides):
    body = {
        "name": "Scheduled",
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "strategy_type": "intraday",
        "entry_time": "09:20",
        "exit_time": "15:10",
        "legs": [
            {
                "segment": "options",
                "position": "S",
                "lots": 1,
                "option_type": "CE",
                "strike_mode": "atm",
                "atm_offset": "ATM",
                "expiry": "weekly",
            }
        ],
    }
    body.update(overrides)
    return body


def test_creating_a_strategy_installs_its_jobs_now_not_at_the_next_restart(client):
    with patch("services.strategy_module.scheduler.sync_strategy_jobs") as sync:
        response = client.post("/strategy/api/strategies", json=_payload())

    assert response.status_code in (200, 201)
    assert sync.call_count == 1


def test_editing_a_strategy_resyncs_its_jobs(client):
    sid = _make(name="Editable")

    with patch("services.strategy_module.scheduler.sync_strategy_jobs") as sync:
        response = client.patch(f"/strategy/api/strategies/{sid}", json={"name": "Renamed"})

    assert response.status_code == 200
    assert sync.call_count == 1


def test_deleting_a_strategy_removes_its_jobs(client):
    sid = _make(name="Deletable")

    with patch("services.strategy_module.scheduler.remove_strategy_jobs") as remove:
        response = client.delete(f"/strategy/api/strategies/{sid}")

    assert response.status_code == 200
    assert remove.call_count == 1


def test_a_scheduler_that_is_not_running_does_not_fail_the_request(client):
    # The configuration is saved either way, and the next boot re-derives every
    # job from it. Losing the save because a background scheduler was down
    # would be the worse failure.
    sid = _make(name="Resilient")

    with patch(
        "services.strategy_module.scheduler.sync_strategy_jobs",
        side_effect=RuntimeError("scheduler down"),
    ):
        response = client.patch(f"/strategy/api/strategies/{sid}", json={"name": "Still saved"})

    assert response.status_code == 200
    assert store.get_strategy(sid, USER).name == "Still saved"


# ---------------------------------------------------------------------------
# Broker-backed views
#
# These read the broker rather than the stored order rows. The stored rows
# record what was placed; the broker knows what happened to it, and for money
# that difference is the point.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "fn"),
    [
        ("orderbook", "strategy_orderbook"),
        ("tradebook", "strategy_tradebook"),
        ("positions", "strategy_positions"),
    ],
)
def test_a_broker_backed_view_passes_the_brokers_answer_through(client, path, fn):
    sid = _make(name=f"Book {path}")
    payload = {"status": "success", "data": {"orders": [{"orderid": "1"}]}}

    with (
        patch(f"services.strategy_module.views.{fn}", return_value=payload) as view,
        patch("database.auth_db.get_api_key_for_tradingview", return_value="k"),
    ):
        response = client.get(f"/strategy/api/strategies/{sid}/{path}")

    assert response.status_code == 200
    assert response.get_json() == payload
    assert view.call_args[0][0] == sid


def test_a_broker_failure_is_reported_as_an_upstream_error(client):
    # Passed through rather than reshaped: the broker's own message is more
    # useful than anything this layer could invent.
    sid = _make(name="Book fail")

    with (
        patch(
            "services.strategy_module.views.strategy_orderbook",
            return_value={"status": "error", "message": "Broker unreachable"},
        ),
        patch("database.auth_db.get_api_key_for_tradingview", return_value="k"),
    ):
        response = client.get(f"/strategy/api/strategies/{sid}/orderbook")

    assert response.status_code == 502
    assert "Broker unreachable" in response.get_json()["message"]


def test_a_broker_backed_view_needs_an_api_key(client):
    sid = _make(name="Book nokey")

    with (
        patch("database.auth_db.get_api_key_for_tradingview", return_value=None),
        patch("services.strategy_module.views.strategy_orderbook") as view,
    ):
        response = client.get(f"/strategy/api/strategies/{sid}/orderbook")

    assert response.status_code == 400
    assert view.call_count == 0


@pytest.mark.parametrize("path", ["orderbook", "tradebook", "positions"])
def test_somebody_elses_book_is_invisible(client, path):
    sid = _make(user=OTHER, name=f"Not yours {path}")

    response = client.get(f"/strategy/api/strategies/{sid}/{path}")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Public webhook route
#
# Unauthenticated and CSRF exempt by design: the URL token is the credential.
# Every decision lives in the pipeline; this route only reads the request and
# turns the outcome into a response.
# ---------------------------------------------------------------------------


def _webhook_client():
    """A client with no session at all: the webhook must not need one."""
    application = Flask(__name__)
    application.config.update(TESTING=True, SECRET_KEY="k", PROPAGATE_EXCEPTIONS=True)
    application.register_blueprint(strategy_module.strategy_module_bp)
    return application.test_client()


def test_the_webhook_needs_no_session(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    client = _webhook_client()

    with patch("services.strategy_module.webhook.handle_webhook") as handle:
        handle.return_value.as_response.return_value = ({"status": "success"}, 200)
        response = client.post("/strategy/webhook/oaws_token", json={"action": "stop"})

    assert response.status_code == 200
    assert handle.call_count == 1


def test_an_unknown_token_answers_json_rather_than_reaching_the_404_handler(monkeypatch):
    # An unauthenticated 404 feeds Error404Tracker and counts toward an IP ban.
    # A scanner walking the token space must not be able to get the owner's own
    # address banned, so this is answered by the view, not by aborting.
    monkeypatch.setattr(limiter, "enabled", False)
    client = _webhook_client()

    with patch("services.strategy_module.webhook.handle_webhook") as handle:
        handle.return_value.as_response.return_value = (
            {"status": "error", "result": "rejected_token", "message": "Not found"},
            404,
        )
        response = client.post("/strategy/webhook/oaws_nope", json={"action": "stop"})

    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["result"] == "rejected_token"


def test_the_raw_body_is_handed_over_rather_than_a_parsed_dict(monkeypatch):
    # The pipeline enforces its own size cap and accepts several shapes, so it
    # needs what actually arrived rather than Flask's interpretation of it.
    monkeypatch.setattr(limiter, "enabled", False)
    client = _webhook_client()

    with patch("services.strategy_module.webhook.handle_webhook") as handle:
        handle.return_value.as_response.return_value = ({"status": "success"}, 200)
        client.post(
            "/strategy/webhook/oaws_token",
            data=b'{"action":"start","mode":"sandbox"}',
            content_type="application/json",
        )

    body = handle.call_args[0][1]
    assert isinstance(body, bytes)
    assert b"sandbox" in body


def test_the_caller_address_and_agent_are_passed_for_the_audit_row(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    client = _webhook_client()

    with patch("services.strategy_module.webhook.handle_webhook") as handle:
        handle.return_value.as_response.return_value = ({"status": "success"}, 200)
        client.post(
            "/strategy/webhook/oaws_token",
            json={"action": "stop"},
            headers={"User-Agent": "TradingView"},
        )

    assert handle.call_args[1]["user_agent"] == "TradingView"
    assert handle.call_args[1]["ip"] is not None
