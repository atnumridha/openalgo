"""Hand-built fills, 30-minute labels and account-risk tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml_signals.account import (
    AccountConfig,
    contracts_for_trade,
    monte_carlo_ruin,
    simulate_account,
)
from ml_signals.labels import FEE_PLANS, build_labels, simulate_trade


def candles(path, step=60, start=1_700_000_000):
    rows = []
    for i, (open_price, high_price, low_price, close_price) in enumerate(path):
        rows.append(
            {
                "time": start + i * step,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(rows)


def test_long_target_and_short_target_with_scalper_offer():
    long = candles([(100, 100, 100, 100), (100, 103.2, 99.9, 103.0), (103, 103, 103, 103)])
    short = candles([(100, 100, 100, 100), (100, 100.1, 96.8, 97), (97, 97, 97, 97)])
    a = simulate_trade(long, entry_index=0, side=1, stop_pct=0.2, target_pct=2, fee_plan="scalper")
    b = simulate_trade(
        short, entry_index=0, side=-1, stop_pct=0.2, target_pct=2, fee_plan="scalper"
    )
    assert a["exit_kind"] == "target" and a["net_pct"] > 0
    assert b["exit_kind"] == "target" and b["net_pct"] > 0
    assert a["exit_fee_pct"] == 0


def test_stop_wins_when_stop_and_target_are_both_inside_same_bar():
    b = candles([(100, 100, 100, 100), (100, 103, 97, 100), (100, 100, 100, 100)])
    trade = simulate_trade(b, entry_index=0, side=1, stop_pct=0.2, target_pct=2)
    assert trade["exit_kind"] == "stop"
    assert trade["net_pct"] < -0.2


def test_gap_through_stop_fills_at_open_and_market_slippage_is_charged():
    b = candles([(100, 100, 100, 100), (100, 100.1, 99.9, 100), (99.5, 99.8, 99.0, 99.3)])
    trade = simulate_trade(b, entry_index=0, side=1, stop_pct=0.2, target_pct=2)
    assert trade["exit_kind"] == "stop"
    assert trade["exit_price"] == 99.5
    assert trade["slippage_pct"] == 0.02


def test_timeout_exit_is_inside_scalper_window():
    rows = [(100, 100.1, 99.9, 100.0)] * 40
    b = candles(rows)
    trade = simulate_trade(
        b,
        entry_index=0,
        side=1,
        stop_pct=0.2,
        target_pct=2,
        max_hold_minutes=28,
        fee_plan="scalper",
    )
    assert trade["exit_kind"] == "time"
    assert trade["held_minutes"] <= 28
    assert trade["exit_fee_pct"] == 0


def test_limit_entry_waits_for_trade_through_or_is_not_filled():
    missed = candles(
        [(100, 100.1, 99.9, 100), (100.5, 101, 100.4, 100.8), (100.8, 101, 100.7, 100.9)]
    )
    assert (
        simulate_trade(
            missed,
            entry_index=0,
            side=1,
            stop_pct=0.2,
            target_pct=2,
            entry_order="limit",
            entry_offset_pct=0.1,
        )
        is None
    )
    filled = candles([(100, 100.1, 99.9, 100), (99.8, 100, 99.7, 99.8), (99.8, 102.5, 99.8, 102.2)])
    trade = simulate_trade(
        filled,
        entry_index=0,
        side=1,
        stop_pct=0.2,
        target_pct=2,
        entry_order="limit",
        entry_offset_pct=0.1,
    )
    assert trade is not None
    assert trade["entry_order"] if "entry_order" in trade else trade["entry_price"] < 100


def test_label_builder_has_long_short_wait_and_unlabelled_tail():
    rng = np.random.default_rng(3)
    n = 600
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.0008, n)))
    spread = close * 0.0007
    b = pd.DataFrame(
        {
            "time": 1_700_000_000 + np.arange(n) * 60,
            "open": close,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": 1.0,
        }
    )
    labels, trades = build_labels(
        b, stop_pct=0.2, target_pct=0.6, max_hold_minutes=28, fee_plan="scalper"
    )
    observed = set(labels[pd.notna(labels)])
    assert observed <= {"LONG", "SHORT", "WAIT"}
    assert "WAIT" in observed
    assert len(trades) > 0
    assert labels[-1] is None


def test_sizing_respects_account_risk_notional_cap_and_liquidation_buffer():
    cfg = AccountConfig(start_usd=100, max_leverage=25, risk_fraction=0.02, max_loss_fraction=0.002)
    sized = contracts_for_trade(equity=100, price=85_000, stop_pct=0.2, leverage=25, config=cfg)
    assert sized["contracts"] > 0
    assert sized["notional_usd"] <= 2500
    assert sized["risk_usd"] <= 2.0
    assert sized["effective_stop_pct"] < sized["liquidation_move_pct"]


def test_account_simulation_and_ruin_probability_are_bounded():
    returns = [0.1, -0.2, 0.3, -0.4] * 10
    result = simulate_account(returns, start_usd=100, leverage=5, risk_fraction=0.02)
    assert result["end_usd"] > 0
    assert result["max_drawdown_pct"] <= 0
    ruin = monte_carlo_ruin(returns, simulations=100, seed=2)
    assert 0 <= ruin <= 1


def test_scalper_fee_plan_is_cheaper_than_standard_for_target_fill():
    standard = FEE_PLANS["standard"].exit_fee_pct("target", 31)
    scalper = FEE_PLANS["scalper"].exit_fee_pct("target", 20)
    assert standard > scalper == 0
    assert FEE_PLANS["scalper"].exit_fee_pct("stop", 31) > 0


def test_standard_plan_pays_to_close_however_quick_the_trade():
    # The standard plan is an account that has not joined the Scalper Offer.
    # It used to get the free close too, which flattered every label.
    assert FEE_PLANS["standard"].exit_fee_pct("stop", 5) == pytest.approx(0.059)


def test_labels_charge_what_the_shared_fee_core_charges():
    from services.crypto_fees import ContractFees, FeeProfile, fee_pct

    plan = FEE_PLANS["scalper"].for_symbol("SOLUSD")
    # Other futures get a 15-minute window, not BTC's 30.
    assert plan.exit_fee_pct("stop", 20) == pytest.approx(
        fee_pct(ContractFees(symbol="SOLUSD"), FeeProfile(), closing=True, held_minutes=20)
    )
    assert plan.exit_fee_pct("stop", 20) > 0
    assert plan.exit_fee_pct("stop", 10) == 0
