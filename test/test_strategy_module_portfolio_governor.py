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


def facts(**overrides) -> EntryFacts:
    baseline = EntryFacts(
        intent="entry",
        mode="live",
        available_cash=Decimal("100000"),
        open_cash_positions=0,
        open_nifty_option_positions=0,
        entry_cash_positions=1,
        entry_nifty_option_positions=0,
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


def test_option_entry_after_1445_is_rejected():
    decision = evaluate_entry(
        facts(has_option_entry=True),
        DEFAULT_POLICY,
        NOW.replace(hour=14, minute=46),
    )

    assert decision.allowed is False
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


def test_sandbox_entry_bypasses_live_portfolio_facts():
    decision = evaluate_entry(facts(mode="sandbox", available_cash=None), DEFAULT_POLICY, NOW)

    assert decision.allowed is True
    assert decision.code == "sandbox_allowed"


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


def _broker_facts(monkeypatch, *, funds, positions, quote=None, runs=None):
    from database import auth_db, strategy_module_db
    from services import funds_service, positionbook_service, quotes_service

    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _key: ("token", "broker"))
    monkeypatch.setattr(funds_service, "get_funds", lambda **_kw: funds)
    monkeypatch.setattr(positionbook_service, "get_positionbook", lambda **_kw: positions)
    monkeypatch.setattr(
        quotes_service,
        "get_quotes",
        lambda *_args, **_kw: quote
        or (True, {"status": "success", "data": {"ask": "100", "ltp": "99"}}, 200),
    )
    monkeypatch.setattr(
        strategy_module_db,
        "list_strategies",
        lambda _user: [{"id": 7}],
    )
    monkeypatch.setattr(strategy_module_db, "list_runs", lambda _sid: runs or [])


@pytest.mark.parametrize("alias", ["availablecash", "available_cash", "cash"])
def test_fund_aliases_produce_the_same_available_cash(monkeypatch, alias):
    _broker_facts(
        monkeypatch,
        funds=(True, {"status": "success", "data": {alias: "100000.25"}}, 200),
        positions=(True, {"status": "success", "data": []}, 200),
    )

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg()], "api-key", "live"
    )

    assert result.available_cash == Decimal("100000.25")
    assert result.entry_cash_risk == Decimal("500")
    assert result.estimated_debit == Decimal("5000")


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

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg()], "api-key", "live"
    )

    assert result.open_cash_positions == 1
    assert result.open_nifty_option_positions == 0


def test_absent_ask_falls_back_to_a_positive_ltp(monkeypatch):
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        quote=(True, {"data": {"ltp": "101.50"}}, 200),
    )

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg(quantity=2)], "api-key", "live"
    )

    assert result.estimated_debit == Decimal("203.00")


def test_missing_quote_marks_debit_fact_unavailable(monkeypatch):
    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
        quote=(False, {"status": "error", "message": "feed unavailable"}, 503),
    )

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg()], "api-key", "live"
    )

    assert result.estimated_debit is None
    assert evaluate_entry(result, DEFAULT_POLICY, NOW).code == "risk_missing"


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

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg()], "api-key", "live"
    )

    assert evaluate_entry(result, DEFAULT_POLICY, NOW).code == "risk_missing"


def test_prior_strategy_runs_supply_session_loss_and_cooldown_facts(monkeypatch):
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

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg()], "api-key", "live"
    )

    assert result.session_pnl == Decimal("-2100")
    assert result.consecutive_stopped_runs == 2
    assert result.last_stopped_at == NOW - timedelta(minutes=10)


def test_open_signal_run_realized_loss_is_included_in_session_pnl(monkeypatch):
    from database import strategy_module_db
    from services.strategy_module import state

    _broker_facts(
        monkeypatch,
        funds=(True, {"data": {"availablecash": "100000"}}, 200),
        positions=(True, {"data": []}, 200),
    )
    monkeypatch.setattr(state, "active_run_ids", lambda: [99])
    monkeypatch.setattr(
        state,
        "get_run_state",
        lambda _run_id: {"pnl_realized": -500, "legs": {}},
    )
    monkeypatch.setattr(
        strategy_module_db,
        "get_run",
        lambda _run_id: SimpleNamespace(strategy_id=7),
    )
    monkeypatch.setattr(
        strategy_module_db,
        "get_strategy_unscoped",
        lambda _strategy_id: SimpleNamespace(user_id="governor-user"),
    )

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg()], "api-key", "live"
    )

    assert result.session_pnl == Decimal("-500")


def test_sandbox_fact_builder_never_reads_live_broker_state(monkeypatch):
    from database import auth_db

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sandbox entries must not read live broker state")

    monkeypatch.setattr(auth_db, "get_auth_token_broker", forbidden)

    result = build_entry_facts(
        "governor-user", _strategy(), [_cash_leg()], "api-key", "sandbox"
    )

    assert evaluate_entry(result, DEFAULT_POLICY, NOW).code == "sandbox_allowed"


def test_user_admission_serializes_evaluation_until_exposure_is_visible(monkeypatch):
    """A second strategy cannot pass on the first strategy's stale facts."""
    exposure = {"nifty_options": 0}
    second_started = Event()
    second_finished = Event()

    def current_facts(*_args, **_kwargs):
        return facts(
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
        "shared-user", {}, [], "key", "live", DEFAULT_POLICY, NOW
    )
    assert first_decision.allowed is True
    assert first_admission is not None

    def admit_second():
        second_started.set()
        result = portfolio_governor.acquire_entry_admission(
            "shared-user", {}, [], "key", "live", DEFAULT_POLICY, NOW
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
