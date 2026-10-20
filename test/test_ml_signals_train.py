"""Profit-aware training: decision rules, scoring, promotion and no-leak calibration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml_signals import train
from ml_signals.decision import (
    DecisionParams,
    Payoff,
    choose,
    decide,
    expected_values,
    levels_pct,
    take_non_overlapping,
)

# ---------------------------------------------------------------------------
# Decision rules
# ---------------------------------------------------------------------------


def test_expected_value_uses_the_measured_payoff():
    params = DecisionParams(
        interval="5m",
        long=Payoff(avg_win_pct=0.5, avg_loss_pct=0.25),
        short=Payoff(avg_win_pct=0.3, avg_loss_pct=0.3),
    )
    ev_long, ev_short = expected_values(0.4, 0.6, params)
    assert ev_long == pytest.approx(0.4 * 0.5 - 0.6 * 0.25)
    assert ev_short == pytest.approx(0.6 * 0.3 - 0.4 * 0.3)


def test_a_side_is_taken_only_above_the_minimum_edge():
    assert choose(0.04, 0.01, 0.05) == 0
    assert choose(0.06, 0.01, 0.05) == 1
    assert choose(0.01, 0.07, 0.05) == -1
    assert choose(np.nan, np.nan, 0.05) == 0
    assert choose(np.asarray([0.1, 0.0]), np.asarray([0.0, 0.2]), 0.05).tolist() == [1, -1]


def test_levels_scale_with_volatility_inside_the_caps():
    params = DecisionParams(interval="1m", hold_minutes=25, stop_atr_mult=1.0, reward_risk=2.0)
    # 0.02% ATR x sqrt(25 bars) = 0.1% stop, 0.2% target.
    assert levels_pct(params, 0.02) == pytest.approx((0.1, 0.2))
    # Wild volatility is held to the operator's stop cap; the target follows it.
    assert levels_pct(params, 1.0) == pytest.approx((0.2, 0.4))
    # A warm-up bar with no ATR still gets the floor.
    assert levels_pct(params, np.nan) == pytest.approx((0.05, 0.1))


def test_the_target_never_exceeds_its_cap():
    params = DecisionParams(interval="15m", reward_risk=20.0, target_cap_pct=2.0)
    assert levels_pct(params, 0.5)[1] == pytest.approx(2.0)


def test_decide_says_wait_when_nothing_clears_the_edge():
    params = DecisionParams(interval="5m", long=Payoff(0.2, 0.2), short=Payoff(0.2, 0.2))
    assert decide(0.5, 0.5, 0.05, params)["action"] == "WAIT"


def test_params_round_trip_through_json():
    params = DecisionParams(interval="3m", min_edge_pct=0.1, long=Payoff(0.4, 0.2, 0.33))
    assert DecisionParams.from_dict(params.to_dict()) == params


# ---------------------------------------------------------------------------
# Non-overlapping scoring
# ---------------------------------------------------------------------------


def test_signals_inside_an_open_trade_are_not_counted():
    # A signal on bar i enters on bar i + 1, so bar 5 can follow a trade that
    # exited during bar 5.
    exits = {1: np.asarray([5] * 5 + [11] * 7), -1: np.full(12, 11)}
    taken = take_non_overlapping(np.arange(10), exits, np.ones(10, dtype=int))
    assert taken == [0, 5]


def test_overlapping_trades_used_to_be_summed():
    # Every bar signals the same long and every trade loses 0.1%. Summed over
    # all bars that is -1.0; held one at a time it is two trades and -0.2.
    net = {1: np.full(12, -0.1), -1: np.full(12, -0.1)}
    exits = {1: np.asarray([5] * 5 + [11] * 7), -1: np.full(12, 11)}
    score = train.score_trades(np.arange(10), np.ones(10, dtype=int), net, exits)
    assert score["trades"] == 2
    assert score["net_pct"] == pytest.approx(-0.2)


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------

CONFIG = train.TrainConfig(min_test_trades=30)


def test_too_few_trades_is_not_promoted():
    ok, reason = train.promotion_decision(
        {"trades": 12, "net_pct": 5.0}, {"p95_net_pct": 0.0}, CONFIG
    )
    assert not ok and "12 trades" in reason


def test_a_loss_after_fees_is_not_promoted():
    ok, reason = train.promotion_decision(
        {"trades": 80, "net_pct": -3.1}, {"p95_net_pct": -1.0}, CONFIG
    )
    assert not ok and "Lost 3.10%" in reason


def test_a_profit_random_entries_also_reach_is_not_promoted():
    ok, reason = train.promotion_decision(
        {"trades": 80, "net_pct": 2.0}, {"p95_net_pct": 2.5}, CONFIG
    )
    assert not ok and "luck" in reason


def test_a_profit_above_the_random_baseline_is_promoted():
    ok, reason = train.promotion_decision(
        {"trades": 80, "net_pct": 4.0}, {"p95_net_pct": 2.5}, CONFIG
    )
    assert ok and "4.00%" in reason


def test_random_baseline_is_reproducible():
    rng = np.random.default_rng(1)
    net = {1: rng.normal(0, 0.2, 500), -1: rng.normal(0, 0.2, 500)}
    exits = {1: np.arange(500) + 3, -1: np.arange(500) + 3}
    a = train.random_baseline(np.arange(490), 40, net, exits, draws=50, seed=3)
    b = train.random_baseline(np.arange(490), 40, net, exits, draws=50, seed=3)
    assert a == b
    assert a["p95_net_pct"] >= a["mean_net_pct"]


# ---------------------------------------------------------------------------
# Splits and calibration
# ---------------------------------------------------------------------------


def test_split_slices_are_ordered_and_gapped():
    split = train.chronological_split(10_000, 30, CONFIG)
    parts = [split.train, split.calibration, split.validation, split.test]
    for earlier, later in zip(parts, parts[1:], strict=False):
        assert later.start - earlier.stop >= 30
    assert split.test.stop == 10_000


def test_too_little_history_gives_no_split():
    assert train.chronological_split(300, 30, CONFIG) is None


def test_calibration_never_sees_the_rows_it_is_scored_on(monkeypatch):
    """The old trainer fitted the calibrator on the test fold and then scored it.

    Recorded here: every calibrator fit is on rows strictly before the test
    slice, so the reported test result is out of sample.
    """
    seen: list[np.ndarray] = []
    original = train.ProbabilityCalibrator.fit

    def spy(self, X, y):
        seen.append(np.asarray(X))
        return original(self, X, y)

    monkeypatch.setattr(train.ProbabilityCalibrator, "fit", spy)

    n = 3000
    rng = np.random.default_rng(5)
    close = 50_000 * np.exp(np.cumsum(rng.normal(0, 0.0015, n)))
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, 0.0004, n))
    bars = pd.DataFrame(
        {
            "time": 1_780_000_000 + np.arange(n) * 900,
            "open": open_,
            "high": np.maximum(open_, close) * (1 + wick),
            "low": np.minimum(open_, close) * (1 - wick),
            "close": close,
            "volume": rng.uniform(1, 10, n),
        }
    )
    # Tag each row with its index so a fit's rows can be traced back.
    from ml_signals import features as features_module

    real_build = features_module.build_features

    def tagged(*args, **kwargs):
        frame = real_build(*args, **kwargs)
        frame["row_tag"] = np.arange(len(frame), dtype=float)
        return frame

    monkeypatch.setattr(train, "build_features", tagged)
    config = train.TrainConfig(
        intervals=("15m",),
        stop_pct=2.0,
        target_pct=4.0,
        hold_minutes=120,
        stop_atr_mults=(0.5,),
        reward_risks=(1.0,),
        # Any edge at all, so a random walk still trades and the run reaches
        # the test fold.
        min_edges=(-100.0,),
        min_test_trades=1,
        baseline_draws=5,
        sentiment_enabled=False,
        fee_plan="scalper",
    )
    from ml_signals.labels import FEE_PLANS

    result = train.train_interval(bars, "15m", config=config, plan=FEE_PLANS["scalper"])
    assert result is not None
    _, card, columns, _ = result
    tag = columns.index("row_tag")
    split = train.chronological_split(n, 9, config)
    assert seen, "no calibrator was fitted"
    for X in seen:
        assert X[:, tag].max() < split.test.start
    assert card["test"]["trades"] >= 0
    assert set(card["decision"]) >= {"stop_atr_mult", "reward_risk", "min_edge_pct", "long"}
