from dataclasses import asdict
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import Flask, session
from sqlalchemy import select, text

from database import auth_db
from database import live_authorization_db as durable
from database.engine_factory import create_db_engine
from services.strategy_module import engine, lifecycle_events
from services.strategy_module import live_authorization as authz
from utils import auth_utils


@pytest.fixture(autouse=True)
def authorization_database(tmp_path, monkeypatch):
    """Real durable state; no broker session or application database is touched."""
    db = create_db_engine(f"sqlite:///{tmp_path / 'authorizations.db'}")
    monkeypatch.setattr(durable, "engine", db)
    durable.init_db()
    auth_db.Auth.__table__.create(db)
    monkeypatch.setattr(authz, "_revocation_failed", False)
    monkeypatch.setattr(authz, "_revocation_epoch", 0)
    monkeypatch.setattr(authz, "_revocations_inflight", 0)
    monkeypatch.setattr(authz, "_grants_inflight", 0)
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")
    monkeypatch.setattr(authz, "_now", lambda: authz.IST.localize(datetime(2026, 9, 23, 10)))
    monkeypatch.setattr(lifecycle_events, "record_user_and_notify", lambda *_a, **_k: None)
    monkeypatch.setenv("SESSION_EXPIRY_TIME", "03:00")
    monkeypatch.setenv("BROKER_API_KEY", "account-1")
    for name in (
        "alice", "late-reset", "transition-user", "expiry-user", "failure-isolation-user",
        "old-user", "new-user", "restart-user",
    ):
        with db.begin() as connection:
            connection.execute(auth_db.Auth.__table__.insert().values(
                name=name, broker="kotak", user_id="account-1",
                auth=auth_db.encrypt_token("test-session-token"), is_revoked=False,
            ))
    yield db
    db.dispose()


def _fresh_authorization_module(monkeypatch):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("fresh_live_authorization", authz.__file__)
    fresh = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, fresh)
    spec.loader.exec_module(fresh)
    monkeypatch.setattr(fresh, "get_trading_session_date", authz.get_trading_session_date)
    monkeypatch.setattr(fresh, "_now", authz._now)
    return fresh


def _change_identity(db, **values):
    with db.begin() as connection:
        connection.execute(auth_db.Auth.__table__.update().where(
            auth_db.Auth.name == "alice"
        ).values(**values))


def _fail(*_args, **_kwargs):
    raise RuntimeError("persistence unavailable")

def test_grant_expires_when_trading_session_day_changes(monkeypatch):
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")
    authz.grant("alice")
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-24")
    assert authz.status("alice").active is False


def test_expiry_uses_the_reset_after_the_session_start_date(monkeypatch):
    """Session dates name their start, so expiry is always the next date."""
    monkeypatch.setenv("SESSION_EXPIRY_TIME", "18:30")
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")

    granted = authz.grant("late-reset")

    assert granted.expires_at == "2026-09-24T18:30+05:30"


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
    assert _fresh_authorization_module(monkeypatch).status("failure-isolation-user").active is True
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


def test_grant_survives_a_fresh_authorization_module(monkeypatch):
    """Only losing process memory must not erase an unexpired explicit grant."""
    granted = authz.grant("restart-user")
    assert granted.active
    fresh = _fresh_authorization_module(monkeypatch)

    assert asdict(fresh.peek_status("restart-user")) == asdict(granted)
    assert fresh.require_live_entry("restart-user") == (True, None)


def test_explicit_revocation_survives_restart(monkeypatch):
    assert authz.grant("alice").active
    authz.revoke("alice")

    assert not _fresh_authorization_module(monkeypatch).status("alice").active


@pytest.mark.parametrize("changed", [
    {"auth": "replacement-token"},
    {"feed_token": "replacement-feed"},
    {"broker": "other-broker"},
    {"user_id": "other-account"},
    {"is_revoked": True},
])
def test_restoration_denied_after_broker_binding_changes(authorization_database, monkeypatch, changed):
    assert authz.grant("alice").active
    changed = {key: auth_db.encrypt_token(value) if key in {"auth", "feed_token"} else value
               for key, value in changed.items()}
    _change_identity(authorization_database, **changed)

    fresh = _fresh_authorization_module(monkeypatch)
    assert not fresh.peek_status("alice").active
    assert not fresh.require_live_entry("alice")[0]


def test_same_token_reencrypted_on_session_resume_preserves_grant(authorization_database, monkeypatch):
    granted = authz.grant("alice")
    _change_identity(authorization_database, auth=auth_db.encrypt_token("test-session-token"))

    assert asdict(_fresh_authorization_module(monkeypatch).status("alice")) == asdict(granted)


def test_reauthentication_is_durable_even_when_broker_returns_the_same_token(monkeypatch):
    assert authz.grant("alice").active
    authz.invalidate_for_reauthentication("alice")

    assert not _fresh_authorization_module(monkeypatch).status("alice").active


def test_grant_without_authenticated_broker_is_denied():
    assert not authz.grant("no-broker").active
    assert not authz.status("no-broker").active


def test_original_expiry_cannot_be_extended_by_reset_configuration(monkeypatch):
    original = authz.grant("alice")
    monkeypatch.setenv("SESSION_EXPIRY_TIME", "06:00")
    assert authz.grant("alice").expires_at == original.expires_at
    monkeypatch.setattr(authz, "_now", lambda: authz.IST.localize(datetime(2026, 9, 24, 3)))
    fresh = _fresh_authorization_module(monkeypatch)

    assert not fresh.peek_status("alice").active
    assert not fresh.require_live_entry("alice")[0]


def test_read_persistence_outage_denies_even_previously_loaded_grant(monkeypatch):
    assert authz.grant("alice").active
    assert authz.status("alice").active
    monkeypatch.setattr(durable, "read", _fail)

    assert not authz.peek_status("alice").active
    assert not authz.status("alice").active
    assert not _fresh_authorization_module(monkeypatch).require_live_entry("alice")[0]


def test_failed_grant_write_does_not_authorize(monkeypatch):
    monkeypatch.setattr(durable, "grant", _fail)

    assert not authz.grant("alice").active
    assert not authz.status("alice").active


def test_failed_revoke_is_not_acknowledged_and_latches_entry_denial(monkeypatch):
    assert authz.grant("alice").active
    original = durable.revoke
    monkeypatch.setattr(durable, "revoke", _fail)

    with pytest.raises(RuntimeError, match="revocation could not be persisted"):
        authz.revoke("alice")
    monkeypatch.setattr(durable, "revoke", original)
    assert not authz.status("alice").active
    assert not authz.peek_status("alice").active
    assert not authz.require_live_entry("alice")[0]
    assert authz.grant("alice").active  # explicit recovery persists a new approval
    assert authz.status("alice").active


def test_peek_after_expiry_does_not_write_or_notify(authorization_database, monkeypatch):
    assert authz.grant("alice").active
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-24")
    monkeypatch.setattr(authz, "_notify_transition", lambda *_a: pytest.fail("read notified"))

    assert not authz.peek_status("alice").active
    with authorization_database.connect() as connection:
        assert connection.scalar(select(durable.authorizations.c.active)) is True


def test_audit_events_never_restore_permission(authorization_database, monkeypatch):
    with authorization_database.begin() as connection:
        connection.execute(text("CREATE TABLE sm_automation_event (user_id TEXT, kind TEXT, ts TEXT)"))
        connection.execute(text(
            "INSERT INTO sm_automation_event VALUES ('alice', 'live_authorization_granted', '2026-09-23T09:00:00')"
        ))

    assert not _fresh_authorization_module(monkeypatch).status("alice").active


def test_durable_record_never_stores_broker_credentials(authorization_database):
    assert authz.grant("alice").active
    with authorization_database.connect() as connection:
        row = connection.execute(select(durable.authorizations)).mappings().one()
    assert "test-session-token" not in str(dict(row))
    assert "account-1" not in str(dict(row))
    assert len(row["binding_digest"]) == 64


def test_revoke_racing_before_grant_write_cannot_resurrect_authorization(monkeypatch):
    original = durable.grant

    def revoked_before_write(*args, **kwargs):
        authz.revoke("alice")
        return original(*args, **kwargs)

    monkeypatch.setattr(durable, "grant", revoked_before_write)
    assert not authz.grant("alice").active
    assert not authz.status("alice").active


def test_grant_in_flight_cannot_be_read_as_confirmed(monkeypatch):
    original = durable.grant
    observed = []

    def read_before_acknowledgment(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(authz.status("alice").active)
        return result

    monkeypatch.setattr(durable, "grant", read_before_acknowledgment)
    assert authz.grant("alice").active
    assert observed == [False]
    assert authz.status("alice").active


def test_binding_mismatch_invalidates_old_grant_permanently(authorization_database):
    assert authz.grant("alice").active
    _change_identity(authorization_database, user_id="replacement-account")
    assert not authz.status("alice").active
    _change_identity(authorization_database, user_id="account-1")
    assert not authz.status("alice").active


def test_connection_pin_switch_denies_restoration(authorization_database, monkeypatch):
    with authorization_database.begin() as connection:
        connection.execute(text("CREATE TABLE api_keys (user_id TEXT, broker_connection_id TEXT)"))
        connection.execute(text(
            "CREATE TABLE broker_connections (id TEXT, user_id TEXT, broker TEXT, status TEXT, is_revoked BOOLEAN)"
        ))
        connection.execute(text("INSERT INTO api_keys VALUES ('alice', 'first')"))
        connection.execute(text(
            "INSERT INTO broker_connections VALUES ('first','alice','kotak','authenticated',0),"
            "('second','alice','kotak','authenticated',0)"
        ))
    assert authz.grant("alice").active
    with authorization_database.begin() as connection:
        connection.execute(text("UPDATE api_keys SET broker_connection_id='second'"))

    assert not _fresh_authorization_module(monkeypatch).status("alice").active


def test_failed_binding_invalidation_cannot_resurrect_old_permission(authorization_database, monkeypatch):
    assert authz.grant("alice").active
    _change_identity(authorization_database, user_id="replacement-account")
    monkeypatch.setattr(durable, "revoke", _fail)
    assert not authz.status("alice").active
    _change_identity(authorization_database, user_id="account-1")

    assert not authz.status("alice").active


@pytest.mark.parametrize("account", [None, "", "   "])
def test_missing_broker_account_identity_blocks_grants(authorization_database, account):
    _change_identity(authorization_database, user_id=account)

    assert not authz.grant("alice").active
    assert not authz.status("alice").active


def test_ambiguous_account_pins_block_grants(authorization_database):
    with authorization_database.begin() as connection:
        connection.execute(text("CREATE TABLE api_keys (user_id TEXT, broker_connection_id TEXT)"))
        connection.execute(text(
            "CREATE TABLE broker_connections (id TEXT, user_id TEXT, broker TEXT, status TEXT, is_revoked BOOLEAN)"
        ))
        connection.execute(text("INSERT INTO api_keys VALUES ('alice', 'first'), ('alice', 'second')"))
        connection.execute(text(
            "INSERT INTO broker_connections VALUES ('first','alice','kotak','authenticated',0),"
            "('second','alice','kotak','authenticated',0)"
        ))

    assert not authz.grant("alice").active



def test_configured_kotak_account_change_blocks_saved_grant(monkeypatch):
    assert authz.grant("alice").active
    monkeypatch.setenv("BROKER_API_KEY", "replacement-ucc")

    assert not _fresh_authorization_module(monkeypatch).status("alice").active


@pytest.mark.parametrize("hour, expected_day, expected_expiry", [
    (10, "2026-09-22", "2026-09-23T18:30+05:30"),
    (19, "2026-09-23", "2026-09-24T18:30+05:30"),
])
def test_late_reset_uses_real_session_date_before_and_after_reset(
    monkeypatch, hour, expected_day, expected_expiry,
):
    from utils import session as platform_session

    moment = authz.IST.localize(datetime(2026, 9, 23, hour))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    monkeypatch.setenv("SESSION_EXPIRY_TIME", "18:30")
    monkeypatch.setattr(platform_session, "datetime", Clock)
    monkeypatch.setattr(authz, "get_trading_session_date", platform_session.get_trading_session_date)
    monkeypatch.setattr(authz, "_now", lambda: moment)

    granted = authz.grant("alice")
    assert granted.session_day == expected_day
    assert granted.expires_at == expected_expiry
    assert authz.status("alice").active
