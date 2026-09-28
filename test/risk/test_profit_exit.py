from dataclasses import replace
from decimal import Decimal

import pytest

from services.risk import BreachReason, PositionRisk
from services.risk.profit_exit import evaluate_profit, profit_bar, profit_config

COSTS = {
    "brokerage_per_order": 10,
    "exchange_rate": 0,
    "sebi_rate": 0,
    "gst_rate": 0,
    "stamp_buy_rate": 0,
    "stt_sell_rate": 0,
    "slippage_bps": 0,
}


def CONFIG():
    return profit_config({"tick_size": 0.05}, COSTS)


def risk(**kw):
    return PositionRisk(
        entry_price=100, quantity=75, stop_price=96, initial_stop_price=96, target_price=112, **kw
    )


def carry(r, d):
    return replace(r, stop_price=d.stop_price, highest_price=d.highest_price)


def test_profit_arms_only_after_300_and_covers_both_fees():
    r = risk()
    before = evaluate_profit(r, 103.95, CONFIG())
    assert before.stop_price == 96
    at = evaluate_profit(r, 104, CONFIG())
    assert at.stop_price == 100.30  # 22.50 gross covers two 10-rupee orders
    assert at.trail_armed and not at.breached
    reversal = evaluate_profit(carry(r, at), 100.30, CONFIG())
    assert reversal.reason == BreachReason.STOP
    assert reversal.pnl == pytest.approx(22.5)


def test_900_is_not_a_hard_exit_and_trail_never_loosens():
    r = risk()
    for price, floor in [(108, 104), (112, 108), (120, 116), (124, 120), (122, 120)]:
        d = evaluate_profit(r, price, CONFIG())
        assert not d.breached
        assert d.stop_price == floor
        assert d.target_price is None
        r = carry(r, d)
    assert evaluate_profit(r, 120, CONFIG()).reason == BreachReason.STOP
    assert evaluate_profit(r, 120, CONFIG()).pnl == 1500


def test_gap_does_not_claim_stop_fill_or_profit():
    d = evaluate_profit(risk(highest_price=112), 95, CONFIG())
    assert d.stop_price == 108
    assert d.reason == BreachReason.STOP
    assert d.pnl == -375


def test_large_fees_cannot_create_a_stop_beyond_observed_peak():
    config = profit_config({"tick_size": 0.05}, COSTS | {"brokerage_per_order": 200})
    d = evaluate_profit(risk(), 104, config)
    assert d.stop_price <= 104
    assert not d.trail_armed  # a fee-aware break-even is not yet attainable


def test_bar_does_not_use_unordered_high_to_award_a_profit_floor():
    r, price, why = profit_bar(
        risk(), {"open": 100, "high": 120, "low": 99, "close": 102}, CONFIG()
    )
    assert price is None and why is None
    assert r.stop_price == 96 and r.highest_price == 102
    r, price, why = profit_bar(r, {"open": 108, "high": 112, "low": 103, "close": 110}, CONFIG())
    assert price == 104 and why == "profit_stop"


def test_break_even_includes_tick_rounded_sell_slippage():
    config = profit_config({"tick_size": 0.05}, COSTS | {"slippage_bps": 10})
    d = evaluate_profit(risk(), 104, config)
    assert d.stop_price == 100.45
    fill = (Decimal(str(d.stop_price)) * Decimal(".999") / Decimal(".05")).to_integral_value(
        rounding="ROUND_FLOOR"
    ) * Decimal(".05")
    assert (fill - 100) * 75 - 20 >= 0


@pytest.mark.parametrize("recipe", ["one-lot-option-structure-runner-v5", "one-lot-fixed300-profit-lock-v6"])
def test_fixed_risk_profit_ratchet_keeps_user_floors_and_unlimited_runner(recipe):
    config = profit_config({"tick_size": .05}, COSTS, recipe=recipe)
    current = PositionRisk(entry_price=100, quantity=100, stop_price=97, initial_stop_price=97)
    for price, floor in [(103, 101), (106, 103), (109, 106), (115, 112), (130, 127), (129, 127)]:
        decision = evaluate_profit(current, price, config)
        assert not decision.breached
        assert decision.stop_price == floor
        assert decision.target_price is None
        current = carry(current, decision)
