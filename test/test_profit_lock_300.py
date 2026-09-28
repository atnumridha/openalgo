"""Gross profit protection starts at INR300, independently of initial stop risk."""

from dataclasses import replace
from decimal import Decimal

import pytest
from test_trading_research import fees

from services.risk import PositionRisk
from services.risk.cash_exit import CASH_RISK_RECIPE, recipe_exit, recipe_policy
from services.risk.profit_exit import evaluate_profit, profit_config

NEW = "one-lot-technical-profit-lock-v4"
OLD = "one-lot-technical-profit-trail-v3"


@pytest.mark.parametrize(
    "peak,floor",
    [
        (299, -200),
        (300, 100),
        (350, 100),
        (500, 200),
        (600, 300),
        (750, 450),
        (900, 600),
        (1000, 700),
        (1200, 900),
        (1500, 1200),
        (1800, 1500),
        (5000, 4700),
    ],
)
def test_gross_floor_starts_at_300_then_limits_giveback(peak, floor):
    config = profit_config(
        {"tick_size": 0.01}, fees(slippage_bps=0, brokerage_per_order=0), recipe=NEW
    )
    risk = PositionRisk(entry_price=100, quantity=100, stop_price=98, target_price=109)
    result = evaluate_profit(risk, 100 + peak / 100, config)
    assert round((result.stop_price - 100) * 100, 6) == floor
    assert result.target_price is None
    assert not result.breached
    if peak >= 300:
        carried = replace(risk, stop_price=result.stop_price, highest_price=result.highest_price)
        retreated = evaluate_profit(carried, 100 + (floor + 1) / 100, config)
        assert retreated.stop_price == result.stop_price
        assert not retreated.breached
        exit_ = evaluate_profit(carried, result.stop_price, config)
        assert exit_.breached


def test_new_version_is_default_without_rewriting_previous_rule():
    assert CASH_RISK_RECIPE == NEW
    assert recipe_policy(NEW).version == "equity-1pct-v2"
    assert recipe_exit(100, 10, {"tick_size": 0.05, "lot_size": 75}, NEW)[0] == Decimal("90")
    risk = PositionRisk(entry_price=100, quantity=100, stop_price=98)
    config = profit_config(
        {"tick_size": 0.01},
        fees(
            slippage_bps=0,
            brokerage_per_order=0,
            exchange_rate=0,
            sebi_rate=0,
            gst_rate=0,
            stamp_buy_rate=0,
            stt_sell_rate=0,
        ),
        recipe=OLD,
    )
    assert evaluate_profit(risk, 103, config).stop_price == 100
    assert evaluate_profit(risk, 110, config).stop_price == 109


def test_whole_lot_tick_rounding_protects_at_least_gross_floor():
    config = profit_config(
        {"tick_size": 0.05}, fees(slippage_bps=0, brokerage_per_order=0), recipe=NEW
    )
    risk = PositionRisk(entry_price=100, quantity=75, stop_price=98)
    decision = evaluate_profit(risk, 104, config)
    assert decision.stop_price == 101.35
    assert round((decision.stop_price - 100) * 75, 2) >= 100


def test_modeled_break_even_can_tighten_but_never_weaken_gross_floor():
    config = profit_config(
        {"tick_size": 0.05}, fees(slippage_bps=0, brokerage_per_order=100), recipe=NEW
    )
    risk = PositionRisk(entry_price=100, quantity=100, stop_price=98)
    decision = evaluate_profit(risk, 103, config)
    assert decision.stop_price >= 102
    assert decision.stop_price <= 103
