from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from services.research.ig_scalping import (
    bars_from_minutes,
    features,
    ig_signals,
    parabolic_sar,
    wilder_rsi,
)


def frame(closes, frequency="5min", start="2025-01-02 09:20"):
    close = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close},
        index=pd.date_range(start, periods=len(close), freq=frequency, tz="Asia/Kolkata"),
    )


def test_aggregation_requires_all_minutes_and_uses_session_grid():
    f = frame(range(100, 115), "min", "2025-01-02 09:16")
    assert list(bars_from_minutes(f, 3).index.minute) == [18, 21, 24, 27, 30]
    assert list(bars_from_minutes(f, 5).index.minute) == [20, 25, 30]
    r = bars_from_minutes(f.drop(f.index[1]), 5)
    assert list(r.index.minute) == [25, 30]
    assert r.iloc[0].open == 105 and r.iloc[0].close == 109
    with pytest.raises(ValueError):
        bars_from_minutes(pd.concat([f, f.iloc[:1]]), 3)


def test_rsi_wilder_seed_and_flat_and_one_sided_series():
    assert wilder_rsi(pd.Series([100.0] * 20)).iloc[-1] == 50
    assert wilder_rsi(pd.Series(np.arange(100.0, 120.0))).iloc[-1] == 100
    assert wilder_rsi(pd.Series(np.arange(120.0, 100.0, -1))).iloc[-1] == 0
    prices = pd.Series(
        [
            100.0,
            101.0,
            100.0,
            102.0,
            101.0,
            104.0,
            103.0,
            105.0,
            104.0,
            108.0,
            107.0,
            109.0,
            108.0,
            111.0,
            110.0,
            109.0,
        ]
    )
    values = wilder_rsi(prices)
    assert values.iloc[:14].isna().all()
    assert values.iloc[14] == pytest.approx(100 - 100 / (1 + 17 / 7))
    assert values.iloc[15] == pytest.approx(100 - 100 / (1 + (17 * 13 / 14) / (7 * 13 / 14 + 1)))


def test_sar_uses_prior_extreme_on_reversal_and_no_future_prices():
    f = frame([10, 11, 12, 13, 8, 7])
    result = parabolic_sar(f)
    assert result.iloc[2].sar == 9
    assert result.iloc[3].sar == pytest.approx(9.16)
    assert result.iloc[4].sar == 14
    assert not result.iloc[4].sar_up
    pd.testing.assert_frame_equal(result.iloc[:4], parabolic_sar(f.iloc[:4]))


def fixture_features():
    f = frame([100] * 6)
    for p in (5, 20, 50, 100, 200):
        f[f"sma{p}"] = 100.0
        f[f"slope{p}"] = 1.0
    f["ready"] = True
    f["k"], f["d"], f["rsi"] = 50.0, 50.0, 50.0
    f["sar"], f["sar_up"] = 90.0, True
    f["sar_ready"] = True
    f["stop_low"], f["stop_high"] = 99.0, 101.0
    return f


def test_stochastic_requires_extreme_crossover_and_trend():
    f = fixture_features()
    f["sma50"] = 110.0
    f["k"] = [10, 18, 35, 10, 18, 25]
    f["d"] = [15, 16, 30, 15, 16, 24]
    f.loc[f.index[4], "slope200"] = -1
    r = ig_signals(f, "stochastic")
    assert list(r.direction) == ["", "CE", "", "", "", ""]
    assert r.iloc[3].exit_ce


def test_ma_short_rule_is_price_cross_not_new_ma_cross():
    f = fixture_features()
    f["sma5"] = 101.0
    f["sma20"] = 102.0
    f["slope200"] = -1.0
    f["close"] = [103, 100, 99, 98, 97, 96]
    r = ig_signals(f, "ma")
    assert list(r.direction) == ["", "PE", "", "", "", ""]


def test_rsi_cross_requires_all_three_ma_slopes():
    f = fixture_features()
    f["rsi"] = [29, 31, 29, 31, 71, 69]
    f.loc[f.index[3], "slope20"] = -1
    f.loc[f.index[5], ["slope20", "slope50", "slope100"]] = -1
    r = ig_signals(f, "rsi")
    assert list(r.direction) == ["", "CE", "", "", "", "PE"]


def test_sar_only_new_flip_is_entry():
    f = fixture_features()
    f["sar_up"] = [True, True, False, False, True, True]
    r = ig_signals(f, "sar")
    assert list(r.direction) == ["", "", "PE", "", "CE", ""]
    assert r.iloc[2].stop_price == 90


def test_features_and_signals_are_prefix_invariant_and_wait_after_gap():
    f = frame(1000 + np.random.default_rng(7).normal(size=300).cumsum())
    a, b = features(f, 5), features(f.iloc[:250], 5)
    pd.testing.assert_frame_equal(a.iloc[:250], b)
    for family in ("ma", "rsi", "sar", "stochastic"):
        pd.testing.assert_frame_equal(ig_signals(a, family).iloc[:250], ig_signals(b, family))
    gap = features(f.drop(f.index[230]), 5)
    assert not gap.loc[f.index[231:234], "ready"].any()
    with pytest.raises(ValueError):
        ig_signals(a, "unknown")


@pytest.mark.parametrize("same_bar_stop", [False, True])
def test_indicator_exit_is_causal_and_stop_has_same_bar_priority(same_bar_stop):
    from scripts.research_ig_scalping import outcome

    f = frame([100] * 15, "min", "2025-01-02 09:21")
    f.loc[f.index[4], ["close", "high"]] = [102, 103]
    if same_bar_stop:
        f.loc[f.index[4], "low"] = 94
    f.loc[f.index[9], "high"] = 111
    exits = pd.DataFrame(
        {"exit_ce": [False, True, False, False], "exit_pe": False},
        index=pd.date_range("2025-01-02 09:20", periods=4, freq="5min", tz="Asia/Kolkata"),
    )
    signal = {
        "timestamp": exits.index[0].isoformat(),
        "direction": "CE",
        "low": 95,
        "high": 101,
        "close": 100,
    }
    result = outcome(signal, f, 15, exits)
    assert result["reason"] == ("sl" if same_bar_stop else "indicator")
    assert result["exit_price"] == (95 if same_bar_stop else 102)
    assert result["exit_at"] == exits.index[1].isoformat()


def test_indicator_exit_cannot_hide_missing_prices_before_it():
    from scripts.research_ig_scalping import outcome

    f = frame([100] * 15, "min", "2025-01-02 09:21")
    exits = pd.DataFrame({"exit_ce": [True], "exit_pe": False}, index=[f.index[4]])
    signal = {
        "timestamp": (f.index[0] - timedelta(minutes=1)).isoformat(),
        "direction": "CE",
        "low": 95,
        "high": 101,
        "close": 100,
    }
    result = outcome(signal, f.drop(f.index[2]), 15, exits)
    assert result["r"] is None and result["reason"] == "missing_minute"
    # A missing observation AFTER the completed indicator exit is irrelevant.
    result = outcome(signal, f.drop(f.index[9]), 15, exits)
    assert result["reason"] == "indicator" and result["r"] == 0
