"""Executable option prices, independent of last-traded-price optimism."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from services.strategy_module import executable_price as prices

NOW = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)
LEG = {"symbol": "NIFTYCE", "exchange": "NFO", "qty": 75, "position": "B"}


def quote(**overrides):
    return {
        "status": "success",
        "data": dict(
            ltp=120,
            bid=110,
            ask=111,
            bid_qty=75,
            ask_qty=75,
            timestamp=NOW.isoformat(),
            **overrides,
        ),
    }


def test_exit_uses_bid_not_higher_ltp():
    result = prices.executable_quote(LEG, quote(), now=NOW)
    assert result.bid == Decimal("110")
    assert result.ask == Decimal("111")


@pytest.mark.parametrize(
    "change",
    [
        {"timestamp": (NOW - timedelta(seconds=11)).isoformat()},
        {"timestamp": (NOW + timedelta(seconds=3)).isoformat()},
        {"timestamp": None},
        {"bid_qty": 74},
        {"ask_qty": 74},
        {"bid": float("nan")},
        {"ask": 113},
        {"ask": 109},
        {"bid_qty": True},
    ],
)
def test_unexecutable_book_is_rejected(change):
    response = quote()
    response["data"].update(change)
    with pytest.raises(ValueError):
        prices.executable_quote(LEG, response, now=NOW)


def test_price_cache_is_bounded_and_revalidates_native_age():
    responses = [quote()]

    class Client:
        calls = 0

        def get_quotes(self, *args):
            self.calls += 1
            return responses[0]

    client = Client()
    prices.clear_cache()
    a = prices.fetch_executable_quote(client, LEG, scope="fake", now=NOW, monotonic_now=0)
    b = prices.fetch_executable_quote(client, LEG, scope="fake", now=NOW, monotonic_now=0.5)
    assert a == b and client.calls == 1
    with pytest.raises(ValueError):
        prices.fetch_executable_quote(
            client, LEG, scope="fake", now=NOW + timedelta(seconds=11), monotonic_now=0.8
        )


def test_cached_quote_never_crosses_accounts_or_uses_wrong_quantity():
    class Client:
        calls = 0

        def get_quotes(self, *args):
            self.calls += 1
            return quote()

    client = Client()
    prices.clear_cache()
    prices.fetch_executable_quote(client, LEG, scope="one", now=NOW, monotonic_now=0)
    prices.fetch_executable_quote(client, LEG, scope="two", now=NOW, monotonic_now=0.1)
    assert client.calls == 2
    with pytest.raises(ValueError):
        prices.fetch_executable_quote(
            client, {**LEG, "qty": 150}, scope="one", now=NOW, monotonic_now=0.2
        )


@pytest.fixture
def tick_engine(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import Mock

    import restx_api  # noqa: F401
    from services.risk.profit_exit import TECHNICAL_PROFIT_RECIPE, profit_config
    from services.strategy_module import engine

    costs = {
        "brokerage_per_order": 0,
        "exchange_rate": 0,
        "sebi_rate": 0,
        "gst_rate": 0,
        "stamp_buy_rate": 0,
        "stt_sell_rate": 0,
        "slippage_bps": 0,
    }
    leg = {
        "leg_id": 1,
        "status": "open",
        "symbol": "NIFTYCE",
        "exchange": "NFO",
        "position": "B",
        "qty": 75,
        "entry_avg": 100,
        "sl_pts": 2,
        "effective_sl": 98,
        "highest_price": 100,
        "profit_protection": profit_config(
            {"tick_size": 0.05}, costs, recipe=TECHNICAL_PROFIT_RECIPE
        ),
    }
    run = {"legs": {"1": leg}}
    row = SimpleNamespace(
        strategy_id=1, mode="live", broker="kotak", stopped_at=None, broker_connection_id="test"
    )
    monkeypatch.setattr(engine.store, "get_run", lambda _: row)
    monkeypatch.setattr(
        engine.store, "get_strategy_unscoped", lambda _: SimpleNamespace(user_id="fake")
    )
    monkeypatch.setattr(engine.store, "strategy_to_dict", lambda _: {"id": 1})

    @contextmanager
    def locked(_):
        yield run

    monkeypatch.setattr(engine.state, "run_state", locked)
    monkeypatch.setattr(engine.state, "get_run_state", lambda _: run)
    monkeypatch.setattr(engine, "_api_key_for", lambda _: "fake-key")
    monkeypatch.setattr(engine, "_session_banked_pnl", lambda *args: None)
    monkeypatch.setattr(engine, "_daily_loss_breached", lambda *args: None)
    monkeypatch.setattr(
        engine.risk_adapter,
        "evaluate_run",
        lambda *args: SimpleNamespace(
            lock_armed_now=False, lock_floor_raised=False, breached=False
        ),
    )
    monkeypatch.setattr(engine, "_push_delta", Mock())
    monkeypatch.setattr(engine, "_emit", Mock())
    monkeypatch.setattr(engine, "_note_actionable_again", Mock())
    monkeypatch.setattr(engine, "stop_run", Mock(return_value={"ok": True}))
    monkeypatch.setattr(engine, "_exit_legs", Mock())
    return engine, leg


@pytest.mark.parametrize(
    "recipe,floor",
    [("one-lot-technical-profit-trail-v3", 100), ("one-lot-technical-profit-lock-v4", 101.35)],
)
def test_engine_raises_profit_floor_from_bid_instead_of_ltp(
    tick_engine, monkeypatch, recipe, floor
):
    from types import SimpleNamespace

    from services.strategy_module import live_protection

    engine, leg = tick_engine
    leg["profit_protection"]["version"] = recipe
    # LTP would report INR1500; full-lot bid reports only INR300.
    monkeypatch.setattr(
        engine,
        "_executable_tick_quote",
        lambda *args: prices.ExecutableQuote(Decimal(104), Decimal(105), NOW),
    )
    ratchets = []
    monkeypatch.setattr(
        live_protection,
        "ratchet_stop",
        lambda *args: ratchets.append(args[2]) or SimpleNamespace(status="verified"),
    )
    engine._process_tick_for_run(1, "NIFTYCE", "NFO", 120)
    assert leg["mtm"] == 300
    assert leg["effective_sl"] == floor
    assert leg["highest_price"] == 104
    assert ratchets[0]["effective_sl"] == floor


def test_engine_cannot_raise_stop_from_missing_executable_quote(tick_engine, monkeypatch):
    engine, leg = tick_engine

    def unavailable(*args):
        raise ValueError("stale quote")

    monkeypatch.setattr(engine, "_executable_tick_quote", unavailable)
    engine._process_tick_for_run(1, "NIFTYCE", "NFO", 120)
    assert leg["effective_sl"] == 98
    assert leg["highest_price"] == 100
    engine.stop_run.assert_called_once_with(1, "fake", reason="executable_quote_unavailable")
