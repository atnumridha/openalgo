from datetime import timedelta
from types import SimpleNamespace

from flask import Flask, session

from services.strategy_module import engine, lifecycle_events
from services.strategy_module import live_authorization as authz
from utils import auth_utils


def test_grant_expires_when_trading_session_day_changes(monkeypatch):
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")
    authz.grant("alice")
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-24")
    assert authz.status("alice").active is False


def test_expiry_uses_the_next_reset_even_when_reset_is_after_noon(monkeypatch):
    """A late reset belongs to the session day, not the following calendar day."""
    monkeypatch.setenv("SESSION_EXPIRY_TIME", "18:30")
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")

    granted = authz.grant("late-reset")

    assert granted.expires_at == "2026-09-23T18:30+05:30"


def test_revocation_blocks_new_entries():
    authz.grant("alice")
    authz.revoke("alice")
    assert authz.require_live_entry("alice") == (
        False,
        "Live automation is not authorized for this trading session",
    )


def test_reauthentication_revokes_the_process_local_live_authorization():
    """A broker reconnect must require a fresh explicit live-entry approval."""
    authz.grant("alice")

    authz.invalidate_for_reauthentication("alice")

    assert authz.status("alice").active is False


def test_authorization_grant_and_revoke_emit_each_transition_once(monkeypatch):
    """Repeated UI calls must not spam lifecycle alerts for unchanged state."""
    observed = []
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")
    monkeypatch.setattr(
        lifecycle_events,
        "record_user_and_notify",
        lambda user_id, kind, message, **fields: observed.append(
            (user_id, kind, message, fields)
        ),
    )

    authz.grant("transition-user")
    authz.grant("transition-user")
    authz.revoke("transition-user")
    authz.revoke("transition-user")

    assert [item[1] for item in observed] == [
        "live_authorization_granted",
        "live_authorization_revoked",
    ]
    assert all(item[0] == "transition-user" for item in observed)


def test_expiry_emits_once_when_the_session_day_changes(monkeypatch):
    """Polling inactive status after expiry must not repeat the alert."""
    session_day = {"value": "2026-09-23"}
    observed = []
    monkeypatch.setattr(
        authz, "get_trading_session_date", lambda: session_day["value"]
    )
    monkeypatch.setattr(
        lifecycle_events,
        "record_user_and_notify",
        lambda user_id, kind, message, **fields: observed.append(kind),
    )

    authz.grant("expiry-user")
    observed.clear()
    session_day["value"] = "2026-09-24"

    assert authz.status("expiry-user").active is False
    assert authz.status("expiry-user").active is False
    assert observed == ["live_authorization_expired"]


def test_lifecycle_persistence_failure_does_not_change_authorization(monkeypatch):
    """Audit/notification failure may be logged but cannot deny a confirmed grant."""
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")
    monkeypatch.setattr(
        lifecycle_events,
        "record_user_and_notify",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable")),
    )

    granted = authz.grant("failure-isolation-user")

    assert granted.active is True
    assert authz.status("failure-isolation-user").active is True
    authz.revoke("failure-isolation-user")


def test_successful_broker_reauthentication_revokes_old_and_new_username_grants(
    monkeypatch,
):
    """The real auth-success boundary resets both possible account identities."""
    from database import auth_db
    from extensions import socketio

    app = Flask(__name__)
    app.secret_key = "test-secret"
    monkeypatch.setattr(lifecycle_events, "record_user_and_notify", lambda *_a, **_k: None)
    monkeypatch.setattr(auth_utils, "get_session_expiry_time", lambda: timedelta(hours=1))
    monkeypatch.setattr(auth_utils, "set_session_login_time", lambda: None)
    monkeypatch.setattr(auth_utils, "get_real_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(auth_utils, "upsert_auth", lambda *_a, **_k: None)
    monkeypatch.setattr(auth_db, "register_session", lambda **_kwargs: None)
    monkeypatch.setattr(auth_db, "get_active_sessions", lambda _username: [])
    monkeypatch.setattr(auth_db, "log_login_attempt", lambda **_kwargs: None)
    monkeypatch.setattr(socketio, "emit", lambda *_a, **_k: None)

    with app.test_request_context(
        "/auth/callback",
        method="POST",
        headers={"X-Requested-With": "XMLHttpRequest", "User-Agent": "pytest"},
    ):
        session["user"] = "old-user"
        authz.grant("old-user")
        authz.grant("new-user")

        auth_utils.handle_auth_success("token", "new-user", "kotak")

        assert authz.status("old-user").active is False
        assert authz.status("new-user").active is False


def test_live_batch_start_requires_session_authorization(monkeypatch):
    """Removing the live gate must refuse the batch start before it claims."""
    strategy = SimpleNamespace(strategy_kind="batch", live_enabled=True)
    claims = []
    monkeypatch.setattr(engine.store, "get_strategy", lambda *_args: strategy)
    monkeypatch.setattr(engine.store, "strategy_to_dict", lambda *_args: {})
    monkeypatch.setattr(engine, "_api_key_for", lambda *_args: "test-key")
    monkeypatch.setattr(engine, "_resolve_all_legs", lambda *_args: ([], []))
    monkeypatch.setattr(
        engine.store,
        "claim_strategy_for_run",
        lambda *args: claims.append(args) or False,
    )

    result = engine.start_run(1, "alice", "live")

    assert result.error == (
        "Live automation is not authorized for this trading session"
    )
    assert claims == []
