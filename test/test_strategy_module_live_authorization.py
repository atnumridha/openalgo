from types import SimpleNamespace

from services.strategy_module import engine
from services.strategy_module import live_authorization as authz


def test_grant_expires_when_trading_session_day_changes(monkeypatch):
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")
    authz.grant("alice")
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-24")
    assert authz.status("alice").active is False


def test_revocation_blocks_new_entries():
    authz.grant("alice")
    authz.revoke("alice")
    assert authz.require_live_entry("alice") == (
        False,
        "Live automation is not authorized for this trading session",
    )


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
