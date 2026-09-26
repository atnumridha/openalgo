"""Shadow comparisons attach to confirmed sandbox fills only."""

from datetime import UTC, datetime, time
from types import SimpleNamespace
from unittest.mock import patch

from services.strategy_module import comparison_lifecycle


def _fixtures(mode="sandbox", legs=None):
    leg = {
        "leg_id": 1, "status": "open", "entry_status": "complete",
        "position_ref": "position-1", "position": "B", "symbol": "SBIN",
        "exchange": "NSE", "entry_avg": 100.0, "qty": 10,
        "sl_pts": 5.0, "target_pts": 10.0,
    }
    run = {"legs": legs or {"1": leg}, "pnl_total": 0, "pnl_realized": 0}
    run_row = SimpleNamespace(id=42, mode=mode, strategy_id=7,
                              broker_connection_id="kotak-connection")
    strategy = SimpleNamespace(
        user_id="owner", strategy_type="intraday", exit_time=time(15, 15),
        overall_sl_mtm=1000, daily_loss_limit_inr=1000,
    )
    return run, run_row, strategy


def test_confirmed_sandbox_entry_attaches_three_shadow_profiles(monkeypatch):
    run, run_row, strategy = _fixtures()
    now = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
    monkeypatch.setattr(comparison_lifecycle, "_now", lambda: now)
    monkeypatch.setattr(comparison_lifecycle.state, "get_run_state", lambda _: run)
    monkeypatch.setattr(comparison_lifecycle.store, "get_run", lambda _: run_row)
    monkeypatch.setattr(comparison_lifecycle.store, "get_strategy_unscoped", lambda _: strategy)
    monkeypatch.setattr(
        comparison_lifecycle.store, "strategy_to_dict",
        lambda _: {"overall_sl_mtm": 1000, "overall_target_mtm": None, "lock_profit": None},
    )
    monkeypatch.setattr(comparison_lifecycle, "_remaining_session_allowance", lambda *_: 900)
    with patch.object(comparison_lifecycle.comparison_store, "create_if_absent",
                      side_effect=lambda value: value) as create:
        snapshot = comparison_lifecycle.attach_confirmed_entry(42, 1)
    assert snapshot["risk_budget"] == 50
    assert set(snapshot["profiles"]) == {"baseline", "early", "room"}
    assert snapshot["entry_timestamp_source"] == "local_confirmation"
    create.assert_called_once()


def test_live_and_multiple_positions_never_create_comparison(monkeypatch):
    run, run_row, strategy = _fixtures(mode="live")
    monkeypatch.setattr(comparison_lifecycle.state, "get_run_state", lambda _: run)
    monkeypatch.setattr(comparison_lifecycle.store, "get_run", lambda _: run_row)
    monkeypatch.setattr(comparison_lifecycle.store, "get_strategy_unscoped", lambda _: strategy)
    with patch.object(comparison_lifecycle.comparison_store, "create_if_absent") as create:
        assert comparison_lifecycle.attach_confirmed_entry(42, 1) is None
        run_row.mode = "sandbox"
        run["legs"]["2"] = {**run["legs"]["1"], "leg_id": 2, "position_ref": "second"}
        assert comparison_lifecycle.attach_confirmed_entry(42, 1) is None
    create.assert_not_called()


def test_market_observation_requires_pinned_native_quote_and_fresh_book(monkeypatch):
    from datetime import timedelta

    market_at = datetime.now(UTC).replace(microsecond=0)
    snapshot = {
        "run_id": 42, "position_ref": "position-1",
        "broker_connection_id": "kotak-connection", "symbol": "SBIN", "exchange": "NSE",
        "last_observed_at": None,
    }
    monkeypatch.setattr(comparison_lifecycle, "_verified_kotak_connection", lambda _: "kotak-connection")
    monkeypatch.setattr(comparison_lifecycle.comparison_store, "list_pending", lambda _: [snapshot])
    with patch.object(comparison_lifecycle.comparison_store, "observe") as observed:
        packet = {
            "symbol": "SBIN", "exchange": "NSE",
            "data": {"ltp": 100, "ltt": market_at.isoformat(), "bid": 99,
                     "ask": 101, "bid_qty": 10, "ask_qty": 10, "book_fresh": False},
        }
        assert comparison_lifecycle.observe_market_packet(
            packet, market_at + timedelta(seconds=1), "websocket", "api-key"
        ) == 1
        assert observed.call_args.kwargs["quote_at"] is None

        packet["data"]["book_fresh"] = True
        assert comparison_lifecycle.observe_market_packet(
            packet, market_at + timedelta(seconds=1), "websocket", "api-key"
        ) == 1
        assert observed.call_args.kwargs["quote_at"] is not None

        packet["data"].pop("ltt")
        assert comparison_lifecycle.observe_market_packet(
            packet, market_at + timedelta(seconds=1), "websocket", "api-key"
        ) == 0


def test_stopped_run_comparison_keeps_polling_only_verified_read_only_quotes(monkeypatch):
    from database import auth_db
    from services import quotes_service

    snapshot = {
        "run_id": 42, "broker_connection_id": "kotak-connection",
        "symbol": "SBIN", "exchange": "NSE",
    }
    monkeypatch.setattr(comparison_lifecycle.comparison_store, "list_pending", lambda _: [snapshot])
    monkeypatch.setattr(comparison_lifecycle.comparison_store, "finalize_due", lambda _: 0)
    monkeypatch.setattr(
        comparison_lifecycle.store, "get_run",
        lambda _: SimpleNamespace(strategy_id=7, broker_connection_id="kotak-connection"),
    )
    monkeypatch.setattr(
        comparison_lifecycle.store, "get_strategy_unscoped",
        lambda _: SimpleNamespace(user_id="owner"),
    )
    monkeypatch.setattr(auth_db, "get_api_key_for_tradingview", lambda _: "api-key")
    monkeypatch.setattr(comparison_lifecycle, "_verified_kotak_connection", lambda _: "kotak-connection")
    seen = []
    monkeypatch.setattr(
        quotes_service, "get_multiquotes",
        lambda symbols, api_key: (True, {"results": [{**symbols[0], "data": {"ltp": 100}}]}, 200),
    )
    monkeypatch.setattr(
        comparison_lifecycle, "observe_market_packet",
        lambda packet, **kwargs: seen.append((packet, kwargs)) or 1,
    )
    assert comparison_lifecycle.poll_pending_comparisons() == {
        "quotes": 1, "observations": 1, "cutoff": 0,
    }
    assert seen[0][1]["source"] == "rest"
