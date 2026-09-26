"""Deterministic entry decisions for the Strategy Module portfolio governor."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Event
from types import SimpleNamespace

import pytest
import pytz

from services.strategy_module import portfolio_governor
from services.strategy_module.portfolio_governor import (
    EntryFacts,
    GovernorPolicy,
    build_entry_facts,
    evaluate_entry,
)

IST = pytz.timezone("Asia/Kolkata")
NOW = IST.localize(datetime(2026, 9, 23, 10, 0))
DEFAULT_POLICY = GovernorPolicy()


@pytest.fixture(autouse=True)
def clear_reservations(monkeypatch):
    from database import market_calendar_db
    from database import strategy_module_db as store

    monkeypatch.setattr(market_calendar_db, "get_effective_session_window", lambda day, _exchange: {
        "start_ms": int(IST.localize(datetime(day.year, day.month, day.day, 9, 15)).timestamp() * 1000),
        "end_ms": int(IST.localize(datetime(day.year, day.month, day.day, 15, 30)).timestamp() * 1000),
    })

    portfolio_governor._entry_reservations.clear()
    portfolio_governor._reservation_cash_baselines.clear()
    store.init_db()
    store.db_session.query(store.SmRiskReservation).delete()
    if hasattr(store, "SmRiskSessionCapital"):
        store.db_session.query(store.SmRiskSessionCapital).delete()
    store.db_session.commit()
    yield
    portfolio_governor._entry_reservations.clear()
    portfolio_governor._reservation_cash_baselines.clear()
    store.db_session.query(store.SmRiskReservation).delete()
    if hasattr(store, "SmRiskSessionCapital"):
        store.db_session.query(store.SmRiskSessionCapital).delete()
    store.db_session.commit()


def facts(**overrides) -> EntryFacts:
    baseline = EntryFacts(
        intent="entry",
        mode="live",
        available_cash=Decimal("100000"),
        session_capital=Decimal("100000"),
        open_cash_positions=0,
        open_nifty_option_positions=0,
        open_sensex_option_positions=0,
        open_mcx_option_positions=0,
        open_derivative_positions=0,
        entry_cash_positions=1,
        entry_nifty_option_positions=0,
        entry_sensex_option_positions=0,
        entry_mcx_option_positions=0,
        entry_derivative_positions=0,
        entry_cash_risk=Decimal("1000"),
        entry_option_lot_risk=Decimal("0"),
        entry_risk=Decimal("1000"),
        open_risk=Decimal("0"),
        estimated_debit=Decimal("10000"),
        minimum_reward_risk=Decimal("2"),
        session_pnl=Decimal("0"),
        consecutive_stopped_runs=0,
        last_stopped_at=None,
        has_option_entry=False,
    )
    return replace(baseline, **overrides)


def test_managed_admission_requires_durable_budget_before_dispatch(monkeypatch):
    from services.strategy_module import trading_budget
    monkeypatch.setattr(trading_budget.ledger, "policy_enabled", lambda _user: True)
    from services.risk.budget import BudgetDecision

    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *a, **kw: facts())
    monkeypatch.setattr(portfolio_governor, "_reconstruct_recovered_entry_reservations", lambda *a: True)
    monkeypatch.setattr(trading_budget, "reserve_entry", lambda *a: (BudgetDecision(False, "later_budget_exhausted", "later", Decimal("0")), None))
    decision, admission = portfolio_governor.acquire_entry_admission(
        "budget-user", SimpleNamespace(id=1), [{"id": 1}], "key", "live", DEFAULT_POLICY, NOW,
        broker="kotak", managed_budget=True,
    )
    assert not decision.allowed
    assert decision.code == "later_budget_exhausted"
    assert admission is None
    assert not portfolio_governor._admission_lock("budget-user|live|kotak").locked()


def test_entry_before_the_intraday_window_is_rejected():
    decision = evaluate_entry(facts(), DEFAULT_POLICY, NOW.replace(hour=9, minute=19))

    assert decision.allowed is False
    assert decision.code == "outside_entry_window"


def test_positional_entry_is_not_subject_to_the_intraday_window():
    decision = evaluate_entry(
        facts(intraday=False),
        DEFAULT_POLICY,
        NOW.replace(hour=9, minute=19),
    )

    assert decision.allowed is True
    assert decision.code == "entry_allowed"


def test_positional_option_waits_for_venue_open(monkeypatch):
    decision = evaluate_entry(
        facts(intraday=False, has_option_entry=True, entry_exchanges=("NFO",)),
        DEFAULT_POLICY,
        NOW.replace(hour=9, minute=14),
    )
    assert decision.code == "outside_entry_window"


def test_option_entry_after_1445_is_rejected():
    decision = evaluate_entry(
        facts(has_option_entry=True),
        DEFAULT_POLICY,
        NOW.replace(hour=14, minute=46),
    )

    assert decision.allowed is False
    assert decision.code == "option_window_closed"


def test_mcx_evening_entry_uses_mcx_session(monkeypatch):
    from database import market_calendar_db

    monkeypatch.setattr(market_calendar_db, "get_effective_session_window", lambda _day, _exchange: {
        "start_ms": int(NOW.replace(hour=9, minute=0).timestamp() * 1000),
        "end_ms": int(NOW.replace(hour=23, minute=55).timestamp() * 1000),
    })
    evening = NOW.replace(hour=20, minute=0)
    decision = evaluate_entry(
        facts(has_option_entry=True, entry_exchanges=("MCX",)), DEFAULT_POLICY, evening
    )
    assert decision.code == "entry_allowed"


def test_exceptional_mcx_close_cuts_off_entry(monkeypatch):
    from database import market_calendar_db

    monkeypatch.setattr(market_calendar_db, "get_effective_session_window", lambda _day, _exchange: {
        "start_ms": int(NOW.replace(hour=9, minute=0).timestamp() * 1000),
        "end_ms": int(NOW.replace(hour=19, minute=0).timestamp() * 1000),
    })
    decision = evaluate_entry(
        facts(has_option_entry=True, entry_exchanges=("MCX",)),
        DEFAULT_POLICY,
        NOW.replace(hour=18, minute=6),
    )
    assert decision.code == "option_window_closed"


@pytest.mark.parametrize(
    "missing",
    [
        {"available_cash": None},
        {"open_risk": None},
        {"estimated_debit": None},
        {"minimum_reward_risk": None},
        {"minimum_reward_risk": Decimal("1.49")},
    ],
)
def test_missing_or_inadequate_protective_risk_fails_closed(missing):
    decision = evaluate_entry(facts(**missing), DEFAULT_POLICY, NOW)

    assert decision.allowed is False
    assert decision.code == "risk_missing"


def test_cash_trade_risk_is_capped_at_one_and_a_half_percent():
    decision = evaluate_entry(
        facts(entry_cash_risk=Decimal("1500.01"), entry_risk=Decimal("1500.01")),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "cash_trade_risk"
    assert decision.metrics["cash_risk_limit"] == Decimal("1500.00")


def test_long_option_minimum_lot_risk_is_capped_at_three_percent():
    decision = evaluate_entry(
        facts(
            entry_cash_positions=0,
            entry_nifty_option_positions=1,
            entry_cash_risk=Decimal("0"),
            entry_option_lot_risk=Decimal("3000.01"),
            entry_risk=Decimal("3000.01"),
            has_option_entry=True,
        ),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "option_lot_risk"
    assert decision.metrics["option_risk_limit"] == Decimal("3000.00")


def test_silverm_and_natgasmini_option_risk_is_capped_at_two_percent():
    decision = evaluate_entry(
        facts(
            entry_cash_positions=0,
            entry_mcx_option_positions=1,
            entry_derivative_positions=1,
            entry_cash_risk=Decimal("0"),
            entry_option_lot_risk=Decimal("2000.01"),
            entry_risk=Decimal("2000.01"),
            has_option_entry=True,
            high_volatility_option_entry=True,
        ),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "option_lot_risk"
    assert decision.metrics["option_risk_limit"] == Decimal("2000.00")
    assert decision.metrics["high_volatility_option_entry"] is True


def test_existing_and_new_configured_risk_share_the_combined_limit():
    decision = evaluate_entry(
        facts(open_risk=Decimal("3100"), entry_risk=Decimal("900.01")),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "combined_open_risk"
    assert decision.metrics["combined_risk"] == Decimal("4000.01")


def test_estimated_debit_must_leave_twenty_percent_cash():
    decision = evaluate_entry(
        facts(estimated_debit=Decimal("80000.01")),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "cash_buffer"
    assert decision.metrics["cash_buffer_required"] == Decimal("20000.00")


def test_four_percent_session_loss_locks_entries():
    decision = evaluate_entry(
        facts(session_pnl=Decimal("-4000")),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "daily_loss_lock"


def test_three_consecutive_stopped_runs_lock_entries():
    decision = evaluate_entry(
        facts(consecutive_stopped_runs=3, last_stopped_at=NOW - timedelta(hours=1)),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "consecutive_loss_lock"


def test_two_consecutive_stopped_runs_impose_a_thirty_minute_cooldown():
    decision = evaluate_entry(
        facts(consecutive_stopped_runs=2, last_stopped_at=NOW - timedelta(minutes=29)),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "cooldown"


@pytest.mark.parametrize(
    "limited",
    [
        {"open_cash_positions": 2},
        {
            "entry_cash_positions": 0,
            "entry_nifty_option_positions": 1,
            "open_nifty_option_positions": 1,
            "entry_cash_risk": Decimal("0"),
            "entry_option_lot_risk": Decimal("1000"),
            "has_option_entry": True,
        },
    ],
)
def test_position_limits_reject_an_additional_position(limited):
    decision = evaluate_entry(facts(**limited), DEFAULT_POLICY, NOW)

    assert decision.allowed is False
    assert decision.code == "position_limit"


@pytest.mark.parametrize(
    "bucket",
    [
        {
            "entry_cash_positions": 0,
            "open_sensex_option_positions": 1,
            "entry_sensex_option_positions": 1,
            "entry_derivative_positions": 1,
        },
        {
            "entry_cash_positions": 0,
            "open_mcx_option_positions": 1,
            "entry_mcx_option_positions": 1,
            "entry_derivative_positions": 1,
        },
        {
            "entry_cash_positions": 0,
            "open_derivative_positions": 2,
            "entry_derivative_positions": 1,
        },
    ],
)
def test_derivative_bucket_and_combined_limits_reject_extra_positions(bucket):
    decision = evaluate_entry(
        facts(
            entry_cash_risk=Decimal("0"),
            entry_option_lot_risk=Decimal("1000"),
            has_option_entry=True,
            **bucket,
        ),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "position_limit"


def test_one_sensex_and_one_mcx_position_fit_the_combined_derivative_limit():
    decision = evaluate_entry(
        facts(
            entry_cash_positions=0,
            open_sensex_option_positions=1,
            open_derivative_positions=1,
            entry_mcx_option_positions=1,
            entry_derivative_positions=1,
            entry_cash_risk=Decimal("0"),
            entry_option_lot_risk=Decimal("1000"),
            has_option_entry=True,
        ),
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is True


def test_a_complete_entry_inside_every_limit_is_allowed():
    decision = evaluate_entry(facts(), DEFAULT_POLICY, NOW)

    assert decision.allowed is True
    assert decision.code == "entry_allowed"


def test_exit_is_never_evaluated_as_an_entry():
    decision = evaluate_entry(facts(intent="exit", available_cash=None), DEFAULT_POLICY, NOW)

    assert decision.allowed is True
    assert decision.code == "exit_allowed"


def test_unknown_intent_cannot_bypass_entry_policy_as_an_exit():
    decision = evaluate_entry(facts(intent="typo", available_cash=None), DEFAULT_POLICY, NOW)

    assert decision.allowed is False
    assert decision.code == "risk_missing"


def test_missing_entry_venue_fails_closed():
    decision = evaluate_entry(facts(entry_exchanges=()), DEFAULT_POLICY, NOW)
    assert decision.code == "risk_missing"


def test_sandbox_entry_requires_portfolio_facts():
    decision = evaluate_entry(facts(mode="sandbox", available_cash=None), DEFAULT_POLICY, NOW)

    assert decision.allowed is False
    assert decision.code == "risk_missing"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"available_cash": Decimal("0")}, "risk_missing"),
        ({"open_cash_positions": 2}, "position_limit"),
        ({"open_risk": Decimal("3500")}, "combined_open_risk"),
        ({"estimated_debit": Decimal("81000")}, "cash_buffer"),
        ({"session_pnl": Decimal("-4000")}, "daily_loss_lock"),
    ],
)
def test_sandbox_entry_enforces_portfolio_limits(overrides, code):
    assert evaluate_entry(facts(mode="sandbox", **overrides), DEFAULT_POLICY, NOW).code == code


def test_daily_loss_uses_stable_session_capital_after_cash_increases():
    decision = evaluate_entry(
        facts(available_cash=Decimal("200000"), session_capital=Decimal("100000"), session_pnl=Decimal("-4500")),
        DEFAULT_POLICY,
        NOW,
    )
    assert decision.code == "daily_loss_lock"


def test_session_capital_is_durable_and_mode_broker_scoped():
    from database import strategy_module_db as store

    day = NOW.date()
    assert store.get_or_create_session_capital("owner", "live", "kotak", day, Decimal("100000")) == Decimal("100000")
    store.db_session.remove()
    assert store.get_or_create_session_capital("owner", "live", "kotak", day, Decimal("200000")) == Decimal("100000")
    assert store.get_or_create_session_capital("owner", "sandbox", "kotak", day, Decimal("250000")) == Decimal("250000")
    assert store.get_or_create_session_capital("owner", "live", "other", day, Decimal("300000")) == Decimal("300000")


def test_sandbox_capital_follows_execution_account_across_quote_broker_changes(monkeypatch):
    from database import auth_db
    from services import quotes_service

    quote_broker = {"name": "kotak"}
    cash = {"value": Decimal("100000")}
    monkeypatch.setattr(portfolio_governor, "_facts_now", lambda: NOW)
    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _key: ("token", quote_broker["name"]))
    monkeypatch.setattr(portfolio_governor, "_sandbox_account", lambda _user: (cash["value"], []))
    monkeypatch.setattr(quotes_service, "get_quotes", lambda *_a, **_kw: (
        True, {"data": {"bid": 99.5, "ask": 100, "bid_qty": 100, "ask_qty": 100,
                        "timestamp": NOW.isoformat()}}, 200,
    ))

    first = build_entry_facts("sandbox-capital-user", _strategy(), [_cash_leg(quantity=1)], "key", "sandbox")
    quote_broker["name"] = "other"
    cash["value"] = Decimal("200000")
    second = build_entry_facts("sandbox-capital-user", _strategy(), [_cash_leg(quantity=1)], "key", "sandbox")

    assert first.session_capital == second.session_capital == Decimal("100000")
    assert first.scope == second.scope == "sandbox-capital-user|sandbox|sandbox"


def test_sandbox_history_uses_execution_broker_and_counts_manual_losses(monkeypatch):
    from datetime import UTC

    from database import auth_db
    from database import strategy_module_db as store
    from services import quotes_service
    from services.strategy_module import state

    owner = "sandbox-history-user"
    monkeypatch.setattr(portfolio_governor, "_facts_now", lambda: NOW)
    monkeypatch.setattr(state, "active_run_ids", lambda: [])
    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _key: ("token", "kotak"))
    monkeypatch.setattr(portfolio_governor, "_sandbox_account", lambda _user: (Decimal("100000"), []))
    monkeypatch.setattr(quotes_service, "get_quotes", lambda *_a, **_kw: (
        True, {"data": {"bid": 99.5, "ask": 100, "bid_qty": 100, "ask_qty": 100,
                        "timestamp": NOW.isoformat()}}, 200,
    ))
    strategy = store.SmStrategy(
        user_id=owner, name="Sandbox history", universe_tab="weekly_monthly",
        underlying="NIFTY", underlying_exchange="NSE_INDEX",
        webhook_token_hash="sandbox-history-token",
    )
    store.db_session.add(strategy)
    store.db_session.flush()
    started = (NOW - timedelta(minutes=40)).astimezone(UTC).replace(tzinfo=None)
    stopped = (NOW - timedelta(minutes=10)).astimezone(UTC).replace(tzinfo=None)
    runs = [
        store.SmStrategyRun(strategy_id=strategy.id, mode="sandbox", broker="sandbox",
                            started_at=started, stopped_at=stopped,
                            stop_reason="manual", pnl_realized=-2500),
        store.SmStrategyRun(strategy_id=strategy.id, mode="sandbox", broker="sandbox",
                            started_at=started + timedelta(minutes=10),
                            stopped_at=stopped + timedelta(minutes=1),
                            stop_reason="manual", pnl_realized=-1500),
    ]
    store.db_session.add_all(runs)
    store.db_session.flush()
    for run, exit_price in zip(runs, (75, 85), strict=True):
        for kind, action, price in (("entry", "BUY", 100), ("exit", "SELL", exit_price)):
            store.db_session.add(store.SmStrategyOrder(
                run_id=run.id, leg_id=1, kind=kind, position_ref="owner-one",
                symbol="RELIANCE", exchange="NSE", action=action, qty=100,
                status="complete", filled_qty=100, avg_fill_price=price,
            ))
    store.db_session.commit()
    try:
        result = build_entry_facts(owner, _strategy(), [_cash_leg(quantity=1)], "key", "sandbox")
        assert result.session_pnl == Decimal("-4000")
        assert result.consecutive_stopped_runs == 2
        assert evaluate_entry(result, DEFAULT_POLICY, NOW).code == "daily_loss_lock"
    finally:
        for run in runs:
            store.db_session.query(store.SmStrategyOrder).filter_by(run_id=run.id).delete()
        store.db_session.query(store.SmStrategyRun).filter_by(strategy_id=strategy.id).delete()
        store.db_session.query(store.SmStrategy).filter_by(id=strategy.id).delete()
        store.db_session.commit()


def _strategy(**overrides):
    value = {
        "id": 7,
        "user_id": "governor-user",
        "name": "Governed",
        "product": "MIS",
        "legs": [],
    }
    value.update(overrides)
    return value


def _cash_leg(**overrides):
    value = {
        "leg_id": 1,
        "position": "B",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "quantity": 50,
        "lot_size": 1,
        "sl_pts": 10,
        "target_pts": 20,
        "risk_unit": "points",
    }
    value.update(overrides)
    return value


def _option_leg(**overrides):
    value = {
        "leg_id": 1,
        "position": "B",
        "symbol": "NIFTY28MAY2624000CE",
        "exchange": "NFO",
        "segment": "options",
        "underlying": "NIFTY",
        "quantity": 75,
        "lot_size": 75,
        "sl_pts": 10,
        "target_pts": 20,
        "risk_unit": "points",
    }
    value.update(overrides)
    return value


def _broker_facts(monkeypatch, *, funds, positions, quote=None, runs=None):
    from database import auth_db, strategy_module_db
    from services import funds_service, positionbook_service, quotes_service

    monkeypatch.setattr(portfolio_governor, "_facts_now", lambda: NOW)
    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _key: ("token", "broker"))
    monkeypatch.setattr(funds_service, "get_funds", lambda **_kw: funds)
    monkeypatch.setattr(positionbook_service, "get_positionbook", lambda **_kw: positions)
    monkeypatch.setattr(
        quotes_service,
        "get_quotes",
        lambda *_args, **_kw: (
            quote or (True, {"status": "success", "data": {
                "bid": "99.50", "ask": "100", "ltp": "99",
                "bid_qty": "1000", "ask_qty": "1000",
                "timestamp": NOW.isoformat(),
            }}, 200)
        ),
    )
    monkeypatch.setattr(
        strategy_module_db, "list_user_runs",
        lambda _user, limit=500, **_kwargs: [
            {"id": index + 1, "mode": "live", "broker": "broker", **run}
            for index, run in enumerate(runs or [])
        ],
    )
    monkeypatch.setattr(
        strategy_module_db, "filled_orders_have_usable_evidence", lambda _ids, **_kwargs: True
    )


@pytest.mark.parametrize("alias", ["availablecash", "available_cash", "cash"])
def test_fund_aliases_produce_the_same_available_cash(monkeypatch, alias):
    from database import token_db

    monkeypatch.setattr(token_db, "get_symbol_info", lambda *_args: SimpleNamespace(tick_size=0.05))
    _broker_facts(
        monkeypatch,
        funds=(True, {"status": "success", "data": {alias: "100000.25"}}, 200),
        positions=(True, {"status": "success", "data": []}, 200),
    )

    result = build_entry_facts("governor-user", _strategy(), [_cash_leg()], "api-key", "live")

    assert result.available_cash == Decimal("100000.25")
    assert result.entry_cash_risk == Decimal("500")
    assert result.estimated_debit == Decimal("5025.00")


@pytest.mark.parametrize("alias", ["netqty", "net_qty", "quantity"])
def test_position_quantity_aliases_count_nonzero_cash_positions(monkeypatch, alias):
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(
            True,
            {
                "status": "success",
                "data": [
                    {"symbol": "TCS", "exchange": "NSE", alias: "3"},
                    {"symbol": "INFY", "exchange": "NSE", alias: "0"},
                ],
            },
            200,
        ),
    )

    result = build_entry_facts("governor-user", _strategy(), [_cash_leg()], "api-key", "live")

    assert result.open_cash_positions == 1
    assert result.open_nifty_option_positions == 0


def test_absent_ask_does_not_fall_back_to_ltp(monkeypatch):
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        quote=(True, {"data": {"ltp": "101.50"}}, 200),
    )

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg(quantity=2)], "api-key", "live"
    )

    assert result.estimated_debit is None


@pytest.mark.parametrize(
    "quote_data",
    [
        {"bid": "1", "ask": "200", "bid_qty": "75", "ask_qty": "75", "timestamp": (NOW - timedelta(days=1)).isoformat()},
        {"bid": "99", "ask": "100", "bid_qty": "75", "ask_qty": "0", "timestamp": NOW.isoformat()},
        {"bid": "99", "ask": "100", "bid_qty": "75", "ask_qty": "75"},
        {"bid": "101", "ask": "100", "bid_qty": "75", "ask_qty": "75", "timestamp": NOW.isoformat()},
    ],
)
def test_incoherent_option_quote_rejects_live_entry(monkeypatch, quote_data):
    monkeypatch.setattr(portfolio_governor, "_facts_now", lambda: NOW)
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        quote=(True, {"data": quote_data}, 200),
    )
    result = build_entry_facts("governor-user", _strategy(), [_option_leg()], "api-key", "live")
    assert result.estimated_debit is None
    assert evaluate_entry(result, DEFAULT_POLICY, NOW).code == "risk_missing"


@pytest.mark.parametrize("timestamp", [str(int(NOW.timestamp())), str(int(NOW.timestamp() * 1000))])
def test_numeric_string_broker_timestamp_is_accepted(monkeypatch, timestamp):
    from database import token_db

    monkeypatch.setattr(token_db, "get_symbol_info", lambda *_args: SimpleNamespace(tick_size=0.05))
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        quote=(True, {"data": {"bid": "99", "ask": "100", "bid_qty": "75", "ask_qty": "75", "timestamp": timestamp}}, 200),
    )
    result = build_entry_facts("governor-user", _strategy(), [_option_leg()], "api-key", "live")
    assert result.estimated_debit == Decimal("7537.50")


@pytest.mark.parametrize("underlying", ["SILVERM", "NATGASMINI"])
def test_mini_commodity_options_select_the_tighter_risk_profile(monkeypatch, underlying):
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
    )

    result = build_entry_facts(
        "governor-user",
        _strategy(),
        [
            _option_leg(
                symbol=f"{underlying}30SEP261000CE",
                exchange="MCX",
                underlying=underlying,
            )
        ],
        "api-key",
        "live",
    )

    assert result.high_volatility_option_entry is True


def test_missing_quote_marks_debit_fact_unavailable(monkeypatch):
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        quote=(False, {"status": "error", "message": "feed unavailable"}, 503),
    )

    result = build_entry_facts("governor-user", _strategy(), [_cash_leg()], "api-key", "live")

    assert result.estimated_debit is None
    assert evaluate_entry(result, DEFAULT_POLICY, NOW).code == "risk_missing"


def test_short_option_requires_fresh_quote_even_without_cash_debit(monkeypatch):
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        quote=(False, {"status": "error"}, 503),
    )
    result = build_entry_facts(
        "governor-user", _strategy(), [_option_leg(position="S")], "api-key", "live"
    )
    assert result.entry_risk is None


def test_short_option_percent_risk_uses_sell_limit_floor(monkeypatch):
    from database import token_db

    monkeypatch.setattr(token_db, "get_symbol_info", lambda *_args: SimpleNamespace(tick_size=0.05))
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        quote=(True, {"data": {"bid": "98", "ask": "99", "bid_qty": "75", "ask_qty": "75", "timestamp": NOW.isoformat()}}, 200),
    )
    result = build_entry_facts(
        "governor-user", _strategy(),
        [_option_leg(position="S", quantity=75, sl_pts=10, target_pts=20, risk_unit="percent")],
        "api-key", "live",
    )
    assert result.entry_risk == Decimal("731.625")


@pytest.mark.parametrize("unavailable", ["auth", "funds", "positions"])
def test_unavailable_broker_state_fails_closed(monkeypatch, unavailable):
    from database import auth_db
    from services import funds_service, positionbook_service

    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
    )
    if unavailable == "auth":
        monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _key: (None, None))
    elif unavailable == "funds":
        monkeypatch.setattr(funds_service, "get_funds", lambda **_kw: (False, {}, 503))
    else:
        monkeypatch.setattr(
            positionbook_service, "get_positionbook", lambda **_kw: (False, {}, 503)
        )

    result = build_entry_facts("governor-user", _strategy(), [_cash_leg()], "api-key", "live")

    assert evaluate_entry(result, DEFAULT_POLICY, NOW).code == "risk_missing"


def test_prior_strategy_runs_supply_session_loss_and_cooldown_facts(monkeypatch):
    monkeypatch.setattr(portfolio_governor, "_facts_now", lambda: NOW)
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        runs=[
            {
                "started_at": (NOW - timedelta(minutes=20)).isoformat(),
                "stopped_at": (NOW - timedelta(minutes=10)).isoformat(),
                "stop_reason": "overall_sl",
                "pnl_realized": -1200,
            },
            {
                "started_at": (NOW - timedelta(minutes=40)).isoformat(),
                "stopped_at": (NOW - timedelta(minutes=30)).isoformat(),
                "stop_reason": "daily_loss_limit",
                "pnl_realized": -900,
            },
        ],
    )

    result = build_entry_facts("governor-user", _strategy(), [_cash_leg()], "api-key", "live")

    assert result.session_pnl == Decimal("-2100")
    assert result.consecutive_stopped_runs == 2
    assert result.last_stopped_at == NOW - timedelta(minutes=10)


def test_completed_history_is_mode_scoped_and_manual_losses_count(monkeypatch):
    from database import strategy_module_db as store
    from services.strategy_module import state

    monkeypatch.setattr(state, "active_run_ids", lambda: [])
    monkeypatch.setattr(store, "filled_orders_have_usable_evidence", lambda _ids, **_kwargs: True)
    monkeypatch.setattr(store, "list_user_runs", lambda _user, limit=500, **_kwargs: [
        {"id": 1, "mode": "sandbox", "broker": "broker", "started_at": NOW.isoformat(), "stopped_at": NOW.isoformat(), "stop_reason": "target", "pnl_realized": 10000},
        {"id": 2, "mode": "live", "broker": "other", "started_at": NOW.isoformat(), "stopped_at": NOW.isoformat(), "stop_reason": "target", "pnl_realized": 10000},
        {"id": 3, "mode": "live", "broker": "broker", "started_at": NOW.isoformat(), "stopped_at": NOW.isoformat(), "stop_reason": "manual", "pnl_realized": -700},
    ])

    pnl, streak, _stopped = portfolio_governor._session_history("governor-user", NOW, "live", "broker")
    assert pnl == Decimal("-700")
    assert streak == 1


def test_session_history_rejects_completed_unpriced_fill(monkeypatch):
    from datetime import UTC

    from database import strategy_module_db as store
    from services.strategy_module import state

    owner = "unpriced-history-user"
    strategy = store.SmStrategy(
        user_id=owner, name="Unpriced history", universe_tab="weekly_monthly",
        underlying="NIFTY", underlying_exchange="NSE_INDEX",
        webhook_token_hash="unpriced-history-token",
    )
    store.db_session.add(strategy)
    store.db_session.flush()
    instant = NOW.astimezone(UTC).replace(tzinfo=None)
    run = store.SmStrategyRun(
        strategy_id=strategy.id, mode="live", broker="broker",
        started_at=instant, stopped_at=instant, pnl_realized=0,
    )
    store.db_session.add(run)
    store.db_session.flush()
    store.db_session.add(store.SmStrategyOrder(
        run_id=run.id, leg_id=1, kind="entry", position_ref="owner-one",
        symbol="NIFTY28MAY2624000CE", exchange="NFO", action="BUY", qty=75,
        status="complete", filled_qty=75, avg_fill_price=None,
    ))
    store.db_session.commit()
    monkeypatch.setattr(state, "active_run_ids", lambda: [])
    try:
        pnl, streak, _stopped = portfolio_governor._session_history(owner, NOW, "live", "broker")
        assert pnl is None
        assert streak is None
    finally:
        store.db_session.query(store.SmStrategyOrder).filter_by(run_id=run.id).delete()
        store.db_session.query(store.SmStrategyRun).filter_by(id=run.id).delete()
        store.db_session.query(store.SmStrategy).filter_by(id=strategy.id).delete()
        store.db_session.commit()


def test_session_history_rejects_completed_pnl_conflicting_with_priced_fills(monkeypatch):
    from datetime import UTC

    from database import strategy_module_db as store
    from services.strategy_module import state

    owner = "mispriced-history-user"
    strategy = store.SmStrategy(
        user_id=owner, name="Mispriced history", universe_tab="weekly_monthly",
        underlying="NIFTY", underlying_exchange="NSE_INDEX",
        webhook_token_hash="mispriced-history-token",
    )
    store.db_session.add(strategy)
    store.db_session.flush()
    instant = NOW.astimezone(UTC).replace(tzinfo=None)
    run = store.SmStrategyRun(
        strategy_id=strategy.id, mode="live", broker="broker",
        started_at=instant, stopped_at=instant, pnl_realized=0,
    )
    store.db_session.add(run)
    store.db_session.flush()
    for kind, action, price in (("entry", "BUY", 100), ("exit", "SELL", 90)):
        store.db_session.add(store.SmStrategyOrder(
            run_id=run.id, leg_id=1, kind=kind, position_ref="owner-one",
            symbol="NIFTY28MAY2624000CE", exchange="NFO", action=action, qty=100,
            status="complete", filled_qty=100, avg_fill_price=price,
        ))
    store.db_session.commit()
    monkeypatch.setattr(state, "active_run_ids", lambda: [])
    try:
        pnl, streak, _stopped = portfolio_governor._session_history(owner, NOW, "live", "broker")
        assert pnl is None
        assert streak is None
    finally:
        store.db_session.query(store.SmStrategyOrder).filter_by(run_id=run.id).delete()
        store.db_session.query(store.SmStrategyRun).filter_by(id=run.id).delete()
        store.db_session.query(store.SmStrategy).filter_by(id=strategy.id).delete()
        store.db_session.commit()


@pytest.mark.parametrize("runs", [None, [{}] * 501])
def test_unavailable_or_truncated_run_history_fails_closed(monkeypatch, runs):
    from database import strategy_module_db as store

    monkeypatch.setattr(store, "list_user_runs", lambda _user, limit=500, **_kwargs: runs)
    pnl, streak, _stopped = portfolio_governor._session_history("governor-user", NOW, "live", "broker")
    assert pnl is None
    assert streak is None


def test_history_query_excludes_old_and_other_broker_runs_before_limit():
    from datetime import UTC

    from database import strategy_module_db as store

    owner = "session-query-user"
    strategy = store.SmStrategy(
        user_id=owner, name="Session query", universe_tab="weekly_monthly",
        underlying="NIFTY", underlying_exchange="NSE_INDEX",
        webhook_token_hash="session-query-token",
    )
    store.db_session.add(strategy)
    store.db_session.flush()
    current = NOW.astimezone(UTC).replace(tzinfo=None)
    store.db_session.add_all([
        store.SmStrategyRun(strategy_id=strategy.id, mode="live", broker="broker", started_at=current),
        store.SmStrategyRun(strategy_id=strategy.id, mode="live", broker="broker", started_at=current - timedelta(days=2), stopped_at=current - timedelta(days=2)),
        store.SmStrategyRun(strategy_id=strategy.id, mode="live", broker="broker", started_at=current - timedelta(days=2)),
        store.SmStrategyRun(strategy_id=strategy.id, mode="live", broker="other", started_at=current),
        store.SmStrategyRun(strategy_id=strategy.id, mode="sandbox", broker="broker", started_at=current),
    ])
    store.db_session.commit()
    try:
        rows = store.list_user_runs(owner, limit=3, since=current - timedelta(hours=1), mode="live", broker="broker")
        assert rows is not None
        assert len(rows) == 2
        assert all(row["broker"] == "broker" for row in rows)
    finally:
        store.db_session.query(store.SmStrategyRun).filter_by(strategy_id=strategy.id).delete()
        store.db_session.query(store.SmStrategy).filter_by(id=strategy.id).delete()
        store.db_session.commit()


def test_cross_session_completed_run_cannot_hide_unallocated_pnl(monkeypatch):
    from database import strategy_module_db as store

    monkeypatch.setattr(store, "list_user_runs", lambda _user, limit=500, **_kwargs: [{
        "mode": "live", "broker": "broker",
        "started_at": (NOW - timedelta(days=1)).isoformat(),
        "stopped_at": NOW.isoformat(), "pnl_realized": 5000,
    }])
    pnl, _streak, _stopped = portfolio_governor._session_history("governor-user", NOW, "live", "broker")
    assert pnl is None


def test_open_signal_run_realized_loss_is_included_in_session_pnl(monkeypatch):
    from database import strategy_module_db
    from services.strategy_module import state

    monkeypatch.setattr(portfolio_governor, "_facts_now", lambda: NOW)
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
    )
    monkeypatch.setattr(state, "active_run_ids", lambda: [99])
    monkeypatch.setattr(
        state,
        "get_run_state",
        lambda _run_id: {"pnl_realized": -500, "pnl_unrealized": 0, "legs": {}},
    )
    monkeypatch.setattr(
        strategy_module_db,
        "get_run",
        lambda _run_id: SimpleNamespace(strategy_id=7, mode="live", broker="broker", started_at=NOW),
    )
    monkeypatch.setattr(
        strategy_module_db,
        "get_strategy_unscoped",
        lambda _strategy_id: SimpleNamespace(user_id="governor-user"),
    )

    result = build_entry_facts("governor-user", _strategy(), [_cash_leg()], "api-key", "live")

    assert result.session_pnl == Decimal("-500")


def test_sandbox_fact_builder_uses_sandbox_account_and_broker_quote(monkeypatch):
    from database import auth_db
    from services import quotes_service

    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _key: ("token", "broker"))
    monkeypatch.setattr(portfolio_governor, "_facts_now", lambda: NOW)
    monkeypatch.setattr(quotes_service, "get_quotes", lambda *_a, **_k: (
        True, {"data": {"bid": "99.5", "ask": "100", "bid_qty": "100", "ask_qty": "100", "timestamp": NOW.isoformat()}}, 200,
    ))
    monkeypatch.setattr(
        portfolio_governor,
        "_sandbox_account",
        lambda _user_id: (Decimal("100000"), []),
    )

    result = build_entry_facts("governor-user", _strategy(), [_cash_leg()], "api-key", "sandbox")

    assert result.available_cash == Decimal("100000")
    assert result.estimated_debit is not None


def test_sandbox_option_requires_a_premium_quote_not_the_underlying_mark(monkeypatch):
    """An index LTP must never be used as an option debit in sandbox mode."""
    monkeypatch.setattr(
        portfolio_governor,
        "_sandbox_account",
        lambda _user_id: (Decimal("100000"), []),
    )

    result = build_entry_facts(
        "sandbox-quote-user",
        _strategy(),
        [{**_option_leg(), "underlying_ltp": 24010}],
        "api-key",
        "sandbox",
    )

    assert result.estimated_debit is None
    assert result.entry_risk is None


def test_sandbox_admission_fails_closed_when_facts_are_unavailable(monkeypatch):
    monkeypatch.setattr(
        portfolio_governor, "build_entry_facts", lambda *_args, **_kwargs: EntryFacts(mode="sandbox")
    )

    decision, admission = portfolio_governor.acquire_entry_admission(
        "sandbox-user",
        {},
        [_option_leg()],
        "key",
        "sandbox",
        DEFAULT_POLICY,
        NOW,
    )

    assert decision.allowed is False
    assert decision.code == "risk_missing"
    assert admission is None


def test_sandbox_acquisition_without_broker_uses_one_execution_account_scope(monkeypatch):
    from database import auth_db
    from database import strategy_module_db as store
    from services import quotes_service
    from services.strategy_module import state

    owner = "sandbox-implicit-broker-user"
    monkeypatch.setattr(portfolio_governor, "_facts_now", lambda: NOW)
    monkeypatch.setattr(state, "active_run_ids", lambda: [])
    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _key: ("token", "kotak"))
    monkeypatch.setattr(portfolio_governor, "_sandbox_account", lambda _user: (Decimal("100000"), []))
    monkeypatch.setattr(quotes_service, "get_quotes", lambda *_a, **_kw: (
        True, {"data": {"bid": 99.5, "ask": 100, "bid_qty": 100, "ask_qty": 100,
                        "timestamp": NOW.isoformat()}}, 200,
    ))

    decision, admission = portfolio_governor.acquire_entry_admission(
        owner, _strategy(user_id=owner), [_cash_leg(quantity=1)], "key", "sandbox",
        DEFAULT_POLICY, NOW,
    )
    assert decision.allowed is True
    assert admission is not None
    try:
        admission.commit(991, [{"leg_id": 1, "position_ref": "paper-991", "entry_order_id": 991}])
    finally:
        admission.release()
    assert len(store.list_risk_reservations(owner, scope=f"{owner}|sandbox|sandbox")) == 1
    assert store.list_risk_reservations(owner, scope=f"{owner}|sandbox|kotak") == []


def test_reservation_persistence_failure_is_not_treated_as_a_success(monkeypatch):
    from database import strategy_module_db as store

    monkeypatch.setattr(store, "upsert_risk_reservation", lambda *_a, **_k: False)
    reservation = portfolio_governor._EntryReservation(
        user_id="persistence-user",
        scope="persistence-user|live|broker",
        components=[],
        available_cash_at_admission=Decimal("100000"),
        committed=True,
    )

    with pytest.raises(portfolio_governor.ReservationPersistenceError):
        portfolio_governor._persist_reservation(reservation)


@pytest.mark.parametrize("mode", ["live", "sandbox"])
def test_user_admission_serializes_evaluation_until_exposure_is_visible(monkeypatch, mode):
    """A second strategy cannot pass on the first strategy's stale facts."""
    exposure = {"nifty_options": 0}
    second_started = Event()
    second_finished = Event()

    def current_facts(*_args, **_kwargs):
        return facts(
            mode=mode,
            entry_cash_positions=0,
            entry_nifty_option_positions=1,
            open_nifty_option_positions=exposure["nifty_options"],
            entry_cash_risk=Decimal("0"),
            entry_option_lot_risk=Decimal("100"),
            entry_risk=Decimal("100"),
            estimated_debit=Decimal("1000"),
            has_option_entry=True,
        )

    monkeypatch.setattr(portfolio_governor, "build_entry_facts", current_facts)
    first_decision, first_admission = portfolio_governor.acquire_entry_admission(
        "shared-user", {}, [], "key", mode, DEFAULT_POLICY, NOW
    )
    assert first_decision.allowed is True
    assert first_admission is not None

    def admit_second():
        second_started.set()
        result = portfolio_governor.acquire_entry_admission(
            "shared-user", {}, [], "key", mode, DEFAULT_POLICY, NOW
        )
        second_finished.set()
        return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(admit_second)
        assert second_started.wait(timeout=1)
        assert second_finished.wait(timeout=0.1) is False

        # This is the ordering production must preserve: state becomes visible
        # before the lease opens the admission gate for the next strategy.
        exposure["nifty_options"] = 1
        first_admission.release()
        second_decision, second_admission = pending.result(timeout=1)

    assert second_decision.allowed is False
    assert second_decision.code == "position_limit"
    assert second_admission is None


def test_rejected_admission_releases_the_user_gate(monkeypatch):
    attempts = iter([facts(available_cash=None), facts()])
    monkeypatch.setattr(
        portfolio_governor,
        "build_entry_facts",
        lambda *_args, **_kwargs: next(attempts),
    )

    rejected, rejected_admission = portfolio_governor.acquire_entry_admission(
        "release-user", {}, [], "key", "live", DEFAULT_POLICY, NOW
    )
    assert rejected.allowed is False
    assert rejected_admission is None

    with ThreadPoolExecutor(max_workers=1) as pool:
        allowed, admission = pool.submit(
            portfolio_governor.acquire_entry_admission,
            "release-user",
            {},
            [],
            "key",
            "live",
            DEFAULT_POLICY,
            NOW,
        ).result(timeout=1)

    assert allowed.allowed is True
    assert admission is not None
    admission.release()


def test_admission_released_by_caller_clears_original_context(monkeypatch):
    """A returned lease may be released outside the worker that acquired it."""
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_args, **_kwargs: facts())

    def acquire():
        return portfolio_governor.acquire_entry_admission(
            "handoff-user", {}, [], "key", "sandbox", DEFAULT_POLICY, NOW
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        first, first_admission = pool.submit(acquire).result(timeout=1)
        assert first.allowed is True
        assert first_admission is not None
        first_admission.release()

        second, second_admission = pool.submit(acquire).result(timeout=1)
        assert second.allowed is True
        assert second_admission is not None
        second_admission.release()


def test_admission_gate_releases_when_provisional_cleanup_raises(monkeypatch):
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_args, **_kwargs: facts())
    first, first_admission = portfolio_governor.acquire_entry_admission(
        "cleanup-user", {}, [], "key", "sandbox", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    assert first_admission is not None

    real_remove = portfolio_governor._remove_reservation

    def failed_cleanup(_reservation):
        raise RuntimeError("provisional cleanup failed")

    monkeypatch.setattr(portfolio_governor, "_remove_reservation", failed_cleanup)
    with pytest.raises(RuntimeError, match="provisional cleanup failed"):
        first_admission.release()
    monkeypatch.setattr(portfolio_governor, "_remove_reservation", real_remove)

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "cleanup-user", {}, [], "key", "sandbox", DEFAULT_POLICY, NOW
    )
    assert second.allowed is True
    assert second_admission is not None
    second_admission.release()


def test_pending_accepted_entry_is_reserved_against_unchanged_broker_facts(monkeypatch):
    unchanged = facts(
        entry_cash_positions=0,
        entry_nifty_option_positions=1,
        entry_cash_risk=Decimal("0"),
        entry_option_lot_risk=Decimal("750"),
        entry_risk=Decimal("750"),
        estimated_debit=Decimal("7500"),
        has_option_entry=True,
    )
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: unchanged)

    first, admission = portfolio_governor.acquire_entry_admission(
        "pending-position-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(41, [{"leg_id": 1, "position_ref": "pending-option"}])
    admission.release()

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "pending-position-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is False
    assert second.code == "position_limit"
    assert second_admission is None


def test_pending_reservation_adds_configured_risk(monkeypatch):
    unchanged = facts(
        open_risk=Decimal("2000"),
        entry_cash_risk=Decimal("1400"),
        entry_risk=Decimal("1400"),
        estimated_debit=Decimal("1000"),
    )
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: unchanged)

    first, admission = portfolio_governor.acquire_entry_admission(
        "pending-risk-user", {}, [_cash_leg(sl_pts=28)], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(42, [{"leg_id": 1, "position_ref": "pending-risk"}])
    admission.release()

    second, _ = portfolio_governor.acquire_entry_admission(
        "pending-risk-user", {}, [_cash_leg(sl_pts=28)], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is False
    assert second.code == "combined_open_risk"
    assert second.metrics["open_risk"] == Decimal("3400")


def test_pending_reservation_adds_estimated_debit(monkeypatch):
    unchanged = facts(
        entry_cash_risk=Decimal("500"),
        entry_risk=Decimal("500"),
        estimated_debit=Decimal("45000"),
    )
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: unchanged)

    first, admission = portfolio_governor.acquire_entry_admission(
        "pending-debit-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(43, [{"leg_id": 1, "position_ref": "pending-debit"}])
    admission.release()

    second, _ = portfolio_governor.acquire_entry_admission(
        "pending-debit-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is False
    assert second.code == "cash_buffer"
    assert second.metrics["estimated_debit"] == Decimal("90000")


def test_broker_visible_exposure_reconciles_its_pending_reservation(monkeypatch):
    first_facts = facts(
        broker_quantities=(("NSE", "RELIANCE", Decimal("0")),),
    )
    visible_facts = facts(
        open_cash_positions=1,
        broker_quantities=(("NSE", "RELIANCE", Decimal("50")),),
    )
    attempts = iter([first_facts, visible_facts])
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: next(attempts))

    first, admission = portfolio_governor.acquire_entry_admission(
        "visible-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(44, [{"leg_id": 1, "position_ref": "visible-entry"}])
    admission.release()

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "visible-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is True
    assert second_admission is not None
    second_admission.release()


def test_position_visibility_keeps_debit_reserved_until_funds_reflect_it(monkeypatch):
    first_facts = facts(
        estimated_debit=Decimal("60000"),
        broker_quantities=(("NSE", "RELIANCE", Decimal("0")),),
    )
    position_visible_funds_stale = facts(
        available_cash=Decimal("100000"),
        open_cash_positions=1,
        entry_cash_risk=Decimal("500"),
        entry_risk=Decimal("500"),
        estimated_debit=Decimal("25000"),
        broker_quantities=(("NSE", "RELIANCE", Decimal("50")),),
    )
    funds_visible = replace(position_visible_funds_stale, available_cash=Decimal("40000"))
    attempts = iter([first_facts, position_visible_funds_stale, funds_visible])
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: next(attempts))

    first, admission = portfolio_governor.acquire_entry_admission(
        "split-broker-facts-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(440, [{"leg_id": 1, "position_ref": "split-facts-entry"}])
    admission.release()

    stale, stale_admission = portfolio_governor.acquire_entry_admission(
        "split-broker-facts-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert stale.allowed is False
    assert stale.code == "cash_buffer"
    assert stale.metrics["estimated_debit"] == Decimal("85000")
    assert stale_admission is None

    reflected, reflected_admission = portfolio_governor.acquire_entry_admission(
        "split-broker-facts-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert reflected.allowed is True
    assert reflected.metrics["estimated_debit"] == Decimal("25000")
    assert reflected_admission is not None
    reflected_admission.release()


def test_unrelated_cash_decrease_cannot_settle_unfilled_entry_debit(monkeypatch):
    pending = facts(
        entry_cash_risk=Decimal("100"),
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("30000"),
        broker_quantities=(("NSE", "RELIANCE", Decimal("0")),),
    )
    unrelated_cash_decrease = facts(
        available_cash=Decimal("70000"),
        entry_cash_risk=Decimal("100"),
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("10000"),
        broker_quantities=(("NSE", "RELIANCE", Decimal("0")),),
    )
    attempts = iter([pending, unrelated_cash_decrease])
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: next(attempts))

    first, admission = portfolio_governor.acquire_entry_admission(
        "unrelated-cash-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(444, [{"leg_id": 1, "position_ref": "still-unfilled"}])
    admission.release()

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "unrelated-cash-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is True
    assert second.metrics["estimated_debit"] == Decimal("40000")
    assert second_admission is not None
    second_admission.release()


def test_partial_fill_cash_only_settles_after_broker_quantity_is_visible(monkeypatch):
    from database import strategy_module_db
    from services.strategy_module import state

    pending = facts(
        entry_cash_risk=Decimal("100"),
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("30000"),
        broker_quantities=(("NSE", "RELIANCE", Decimal("0")),),
    )
    cash_moved_before_position = facts(
        available_cash=Decimal("85000"),
        entry_cash_risk=Decimal("100"),
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("10000"),
        broker_quantities=(("NSE", "RELIANCE", Decimal("0")),),
    )
    partial_position_visible = replace(
        cash_moved_before_position,
        open_cash_positions=1,
        broker_quantities=(("NSE", "RELIANCE", Decimal("25")),),
    )
    partial_cash_settled = replace(
        partial_position_visible,
        available_cash=Decimal("70000"),
    )
    attempts = iter(
        [
            pending,
            cash_moved_before_position,
            partial_position_visible,
            partial_cash_settled,
        ]
    )
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: next(attempts))
    monkeypatch.setattr(state, "get_run_state", lambda _run_id: None)
    monkeypatch.setattr(
        strategy_module_db,
        "get_order",
        lambda order_id: (
            SimpleNamespace(status="cancelled", filled_qty=25) if order_id == 9444 else None
        ),
    )

    first, admission = portfolio_governor.acquire_entry_admission(
        "partial-debit-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(
        445,
        [
            {
                "leg_id": 1,
                "position_ref": "partial-debit-entry",
                "entry_order_id": 9444,
            }
        ],
    )
    admission.release()

    early, early_admission = portfolio_governor.acquire_entry_admission(
        "partial-debit-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert early.allowed is True
    assert early.metrics["estimated_debit"] == Decimal("25000")
    assert early_admission is not None
    early_admission.release()

    visible, visible_admission = portfolio_governor.acquire_entry_admission(
        "partial-debit-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert visible.allowed is True
    assert visible.metrics["estimated_debit"] == Decimal("25000")
    assert visible_admission is not None
    visible_admission.release()

    settled, settled_admission = portfolio_governor.acquire_entry_admission(
        "partial-debit-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert settled.allowed is True
    assert settled.metrics["estimated_debit"] == Decimal("10000")
    assert settled_admission is not None
    settled_admission.release()


def test_terminal_rejection_releases_reserved_debit_with_stale_funds(monkeypatch):
    attempts = iter(
        [
            facts(estimated_debit=Decimal("60000")),
            facts(estimated_debit=Decimal("25000")),
        ]
    )
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: next(attempts))
    first, admission = portfolio_governor.acquire_entry_admission(
        "terminal-debit-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(
        441,
        [
            {
                "leg_id": 1,
                "position_ref": "terminal-debit-entry",
                "entry_order_id": 9441,
            }
        ],
    )
    admission.release()

    portfolio_governor.release_terminal_entry_reservation(9441)
    second, second_admission = portfolio_governor.acquire_entry_admission(
        "terminal-debit-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is True
    assert second.metrics["estimated_debit"] == Decimal("25000")
    assert second_admission is not None
    second_admission.release()


def test_multiple_debits_reconcile_once_each_as_funds_catch_up(monkeypatch):
    permissive_positions = replace(DEFAULT_POLICY, max_cash_positions=10)
    first_facts = facts(
        entry_cash_risk=Decimal("100"),
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("30000"),
        broker_quantities=(("NSE", "RELIANCE", Decimal("0")),),
    )
    second_facts = replace(
        first_facts,
        open_cash_positions=1,
        broker_quantities=(("NSE", "RELIANCE", Decimal("50")),),
    )
    one_debit_visible = facts(
        available_cash=Decimal("70000"),
        open_cash_positions=2,
        entry_cash_risk=Decimal("100"),
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("10000"),
        broker_quantities=(
            ("NSE", "RELIANCE", Decimal("50")),
            ("NSE", "TCS", Decimal("50")),
        ),
    )
    both_debits_visible = replace(one_debit_visible, available_cash=Decimal("40000"))
    attempts = iter([first_facts, second_facts, one_debit_visible, both_debits_visible])
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: next(attempts))

    first, first_admission = portfolio_governor.acquire_entry_admission(
        "multiple-debits-user", {}, [_cash_leg()], "key", "live", permissive_positions, NOW
    )
    assert first.allowed is True
    first_admission.commit(442, [{"leg_id": 1, "position_ref": "first-debit"}])
    first_admission.release()

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "multiple-debits-user",
        {},
        [_cash_leg(symbol="TCS")],
        "key",
        "live",
        permissive_positions,
        NOW,
    )
    assert second.allowed is True
    assert second.metrics["estimated_debit"] == Decimal("60000")
    second_admission.commit(443, [{"leg_id": 1, "position_ref": "second-debit"}])
    second_admission.release()

    partly_reflected, partly_reflected_admission = portfolio_governor.acquire_entry_admission(
        "multiple-debits-user",
        {},
        [_cash_leg(symbol="INFY")],
        "key",
        "live",
        permissive_positions,
        NOW,
    )
    assert partly_reflected.allowed is True
    assert partly_reflected.metrics["estimated_debit"] == Decimal("40000")
    partly_reflected_admission.release()

    fully_reflected, fully_reflected_admission = portfolio_governor.acquire_entry_admission(
        "multiple-debits-user",
        {},
        [_cash_leg(symbol="INFY")],
        "key",
        "live",
        permissive_positions,
        NOW,
    )
    assert fully_reflected.allowed is True
    assert fully_reflected.metrics["estimated_debit"] == Decimal("10000")
    fully_reflected_admission.release()


def test_multiple_debits_only_consume_cash_for_broker_visible_components(monkeypatch):
    permissive_positions = replace(DEFAULT_POLICY, max_cash_positions=10)
    first_facts = facts(
        entry_cash_risk=Decimal("100"),
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("30000"),
        broker_quantities=(
            ("NSE", "RELIANCE", Decimal("0")),
            ("NSE", "TCS", Decimal("0")),
        ),
    )
    second_facts = replace(first_facts, estimated_debit=Decimal("20000"))
    only_second_visible = facts(
        available_cash=Decimal("75000"),
        open_cash_positions=1,
        entry_cash_risk=Decimal("100"),
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("10000"),
        broker_quantities=(
            ("NSE", "RELIANCE", Decimal("0")),
            ("NSE", "TCS", Decimal("50")),
        ),
    )
    attempts = iter([first_facts, second_facts, only_second_visible])
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: next(attempts))

    first, first_admission = portfolio_governor.acquire_entry_admission(
        "correlated-debits-user",
        {},
        [_cash_leg()],
        "key",
        "live",
        permissive_positions,
        NOW,
    )
    assert first.allowed is True
    first_admission.commit(446, [{"leg_id": 1, "position_ref": "older-unfilled"}])
    first_admission.release()

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "correlated-debits-user",
        {},
        [_cash_leg(symbol="TCS")],
        "key",
        "live",
        permissive_positions,
        NOW,
    )
    assert second.allowed is True
    second_admission.commit(447, [{"leg_id": 1, "position_ref": "younger-visible"}])
    second_admission.release()

    third, third_admission = portfolio_governor.acquire_entry_admission(
        "correlated-debits-user",
        {},
        [_cash_leg(symbol="INFY")],
        "key",
        "live",
        permissive_positions,
        NOW,
    )

    assert third.allowed is True
    assert third.metrics["estimated_debit"] == Decimal("40000")
    assert third_admission is not None
    third_admission.release()


def test_terminal_rejection_reconciles_its_pending_reservation(monkeypatch):
    from services.strategy_module import state

    unchanged = facts()
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: unchanged)

    first, admission = portfolio_governor.acquire_entry_admission(
        "terminal-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(45, [{"leg_id": 1, "position_ref": "terminal-entry"}])
    admission.release()
    monkeypatch.setattr(
        state,
        "get_run_state",
        lambda _run_id: {
            "legs": {
                "1": {
                    "position_ref": "terminal-entry",
                    "status": "rejected",
                    "entry_status": "rejected",
                }
            }
        },
    )

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "terminal-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is True
    assert second_admission is not None
    second_admission.release()


def test_terminal_cancellation_reconciles_after_run_state_is_gone(monkeypatch):
    from database import strategy_module_db
    from services.strategy_module import state

    unchanged = facts(
        entry_cash_positions=0,
        entry_nifty_option_positions=1,
        entry_cash_risk=Decimal("0"),
        entry_option_lot_risk=Decimal("750"),
        entry_risk=Decimal("750"),
        estimated_debit=Decimal("7500"),
        has_option_entry=True,
    )
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: unchanged)
    first, admission = portfolio_governor.acquire_entry_admission(
        "cancelled-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(
        46,
        [
            {
                "leg_id": 1,
                "position_ref": "cancelled-entry",
                "entry_order_id": 9001,
            }
        ],
    )
    admission.release()
    monkeypatch.setattr(state, "get_run_state", lambda _run_id: None)
    monkeypatch.setattr(
        strategy_module_db,
        "get_order",
        lambda order_id: SimpleNamespace(status="cancelled") if order_id == 9001 else None,
    )

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "cancelled-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is True
    assert second_admission is not None
    second_admission.release()


def test_terminal_entry_hook_releases_reservation_immediately(monkeypatch):
    unchanged = facts(
        entry_cash_positions=0,
        entry_nifty_option_positions=1,
        entry_cash_risk=Decimal("0"),
        entry_option_lot_risk=Decimal("750"),
        entry_risk=Decimal("750"),
        estimated_debit=Decimal("7500"),
        has_option_entry=True,
    )
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: unchanged)
    first, admission = portfolio_governor.acquire_entry_admission(
        "terminal-hook-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(
        47,
        [
            {
                "leg_id": 1,
                "position_ref": "terminal-hook-entry",
                "entry_order_id": 9002,
            }
        ],
    )
    admission.release()

    portfolio_governor.release_terminal_entry_reservation(9002)
    second, second_admission = portfolio_governor.acquire_entry_admission(
        "terminal-hook-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is True
    assert second_admission is not None
    second_admission.release()


def test_partial_terminal_entry_keeps_reservation_until_exposure_is_visible(monkeypatch):
    from database import strategy_module_db
    from services.strategy_module import state

    unchanged = facts(
        entry_cash_positions=0,
        entry_nifty_option_positions=1,
        entry_cash_risk=Decimal("0"),
        entry_option_lot_risk=Decimal("750"),
        entry_risk=Decimal("750"),
        estimated_debit=Decimal("7500"),
        has_option_entry=True,
    )
    visible = replace(
        unchanged,
        open_nifty_option_positions=1,
        broker_quantities=(("NFO", "NIFTY28MAY2624000CE", Decimal("25")),),
    )
    attempts = iter([unchanged, unchanged, visible])
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: next(attempts))
    first, admission = portfolio_governor.acquire_entry_admission(
        "partial-terminal-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(
        48,
        [
            {
                "leg_id": 1,
                "position_ref": "partial-terminal-entry",
                "entry_order_id": 9003,
            }
        ],
    )
    admission.release()
    monkeypatch.setattr(state, "get_run_state", lambda _run_id: None)
    monkeypatch.setattr(
        strategy_module_db,
        "get_order",
        lambda order_id: (
            SimpleNamespace(status="cancelled", filled_qty=25) if order_id == 9003 else None
        ),
    )

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "partial-terminal-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert second.allowed is False
    assert second.code == "position_limit"
    assert second_admission is None

    reflected, reflected_admission = portfolio_governor.acquire_entry_admission(
        "partial-terminal-user", {}, [_option_leg()], "key", "live", DEFAULT_POLICY, NOW
    )

    assert reflected.allowed is False
    assert reflected.code == "position_limit"
    assert reflected.metrics["open_nifty_option_positions"] == 1
    assert reflected_admission is None


@pytest.mark.parametrize("mode", ["live", "sandbox"])
def test_committed_reservation_survives_clearing_process_memory(monkeypatch, mode):
    from database import strategy_module_db as store

    unchanged = facts(
        mode=mode,
        entry_cash_positions=0,
        entry_nifty_option_positions=1,
        entry_cash_risk=Decimal("0"),
        entry_option_lot_risk=Decimal("750"),
        entry_risk=Decimal("750"),
        estimated_debit=Decimal("7500"),
        has_option_entry=True,
    )
    monkeypatch.setattr(portfolio_governor, "build_entry_facts", lambda *_a, **_k: unchanged)
    store.init_db()
    store.delete_risk_reservations("durable-user", [9101])

    first, admission = portfolio_governor.acquire_entry_admission(
        "durable-user", {}, [_option_leg()], "key", mode, DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    admission.commit(
        91,
        [{"leg_id": 1, "position_ref": "durable-option", "entry_order_id": 9101}],
    )
    admission.release()

    portfolio_governor._entry_reservations.pop(
        portfolio_governor._scope_key("durable-user", mode, None), None
    )

    second, second_admission = portfolio_governor.acquire_entry_admission(
        "durable-user", {}, [_option_leg()], "key", mode, DEFAULT_POLICY, NOW
    )

    assert second.allowed is False
    assert second.code == "position_limit"
    assert second_admission is None
    store.delete_risk_reservations("durable-user", [9101])


def test_live_authorization_is_rechecked_after_waiting_for_user_admission(monkeypatch):
    unchanged = facts()
    builds = []
    monkeypatch.setattr(
        portfolio_governor,
        "build_entry_facts",
        lambda *_a, **_k: builds.append("built") or unchanged,
    )
    first, first_admission = portfolio_governor.acquire_entry_admission(
        "revoked-user", {}, [_cash_leg()], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first.allowed is True
    started = Event()

    def wait_then_recheck():
        started.set()
        return portfolio_governor.acquire_entry_admission(
            "revoked-user",
            {},
            [_cash_leg()],
            "key",
            "live",
            DEFAULT_POLICY,
            NOW,
            authorization_check=lambda: (False, "Live authorization expired while waiting"),
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(wait_then_recheck)
        assert started.wait(timeout=1)
        first_admission.release()
        decision, admission = pending.result(timeout=1)

    assert decision.allowed is False
    assert decision.code == "live_authorization_required"
    assert decision.message == "Live authorization expired while waiting"
    assert admission is None
    assert builds == ["built"]
