"""Ticks before an entry fill must not advance a position's profit floor."""

from copy import deepcopy

import pytest

from services.risk import BreachReason
from services.risk.profit_exit import profit_config
from services.strategy_module.risk_adapter import evaluate_leg


def protected_leg(**overrides):
    leg = {
        "leg_id": 1,
        "position": "B",
        "status": "open",
        "entry_status": "open",
        "entry_filled_qty": 0,
        "entry_avg": 0.0,
        "qty": 65,
        "sl_pts": 3,
        "effective_sl": None,
        "effective_target": None,
        "highest_price": None,
        "lowest_price": None,
        "ltp": None,
        "mtm": 0.0,
        "profit_protection": profit_config(
            {"tick_size": 0.05},
            {
                "brokerage_per_order": 0,
                "exchange_rate": 0,
                "sebi_rate": 0,
                "gst_rate": 0,
                "stamp_buy_rate": 0,
                "stt_sell_rate": 0,
                "slippage_bps": 0,
            },
            recipe="one-lot-fixed300-profit-lock-v6",
        ),
    }
    leg.update(overrides)
    return leg


@pytest.mark.parametrize("entry_status", ["pending", "open"])
def test_unfilled_entry_ignores_ticks_without_advancing_protection(entry_status):
    leg = protected_leg(entry_status=entry_status)
    before = deepcopy(leg)

    result = evaluate_leg(leg, 130)

    assert not result.evaluated
    assert not result.breached
    assert not result.trail_armed
    assert leg == before


def test_first_filled_tick_does_not_inherit_an_unfilled_price_peak():
    leg = protected_leg()
    evaluate_leg(leg, 130)
    # A completed sandbox fill can leave entry_filled_qty at its initial zero;
    # entry_avg and qty are the confirmed price and managed filled quantity.
    leg.update(entry_status="complete", entry_avg=100)

    result = evaluate_leg(leg, 101)

    assert result.evaluated
    assert result.pnl == 65
    assert result.highest_price == 101
    assert result.stop_price == 97
    assert not result.trail_armed
    assert not result.breached


def test_partial_fill_retains_protection_for_its_managed_quantity():
    # The engine changes qty to the actual partial fill while the entry order
    # remains open. Requiring entry_status=complete would lose this protection.
    leg = protected_leg(entry_avg=100, qty=25, entry_filled_qty=25)

    peak = evaluate_leg(leg, 112)
    assert peak.pnl == 300
    assert peak.stop_price == 104
    assert peak.trail_armed

    retreat = evaluate_leg(leg, 104)
    assert retreat.breached
    assert retreat.reason == BreachReason.STOP
    assert retreat.pnl == 100


@pytest.mark.parametrize(
    "fill_state", [{"entry_status": "complete"}, {"entry_filled_qty": 25, "qty": 25}]
)
def test_fill_evidence_with_missing_price_is_still_rejected(fill_state):
    # A real filled position with missing valuation is not a pending entry.
    leg = protected_leg(**fill_state)
    with pytest.raises(ValueError, match="requires a filled long option position"):
        evaluate_leg(leg, 110)
