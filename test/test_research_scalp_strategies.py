"""Causal signal semantics for the two user-supplied transcript strategies."""

import numpy as np
import pandas as pd
import pytest

from services.research.ema_scalp import chart_outcome
from services.research.scalp_strategies import (
    aggregate_fifteen,
    confirmed_pivot,
    ema_reversal_signals,
    macd_features,
    macd_signals,
    trigger_alerts,
)


def candles(count=800, freq="5min"):
    idx = pd.date_range("2024-12-01 09:20", periods=count, freq=freq, tz="Asia/Kolkata")
    c = 100 + np.arange(count) * 0.03 + np.sin(np.arange(count) / 10)
    return pd.DataFrame({"open": c - 0.2, "high": c + 0.5, "low": c - 0.5, "close": c}, index=idx)


def test_macd_is_fast_minus_slow_and_features_are_causal():
    f = candles()
    actual = macd_features(f)
    expected = (
        f.close.ewm(span=12, adjust=False, min_periods=12).mean()
        - f.close.ewm(span=26, adjust=False, min_periods=26).mean()
    )
    pd.testing.assert_series_equal(actual.macd, expected, check_names=False)
    pd.testing.assert_frame_equal(actual.iloc[:750], macd_features(f.iloc[:750]))
    pd.testing.assert_frame_equal(
        macd_signals(actual).iloc[:750], macd_signals(macd_features(f.iloc[:750]))
    )


def test_pivot_is_not_available_until_two_right_candles_close():
    prices = pd.Series([5, 4, 1, 3, 4, 6, 7.0])
    pivot = confirmed_pivot(prices, low=True)
    assert pivot.iloc[:4].isna().all()
    assert pivot.iloc[4] == 1
    pd.testing.assert_series_equal(pivot.iloc[:5], confirmed_pivot(prices.iloc[:5], low=True))


def test_fifteen_minute_bars_are_session_aligned_and_never_partial():
    f = candles(6)
    result = aggregate_fifteen(f)
    assert result.index.strftime("%H:%M").tolist() == ["09:30", "09:45"]
    assert result.iloc[0].high == f.iloc[:3].high.max()
    assert aggregate_fifteen(f.drop(f.index[1])).index.strftime("%H:%M").tolist() == ["09:45"]
    off_grid = f.iloc[:3].copy()
    off_grid.index = pd.DatetimeIndex(
        [f.index[0], f.index[1] - pd.Timedelta(minutes=2), f.index[2]]
    )
    with pytest.raises(ValueError, match="five-minute grid"):
        aggregate_fifteen(off_grid)


def test_alert_waits_for_later_break_and_replacement_is_not_retroactive():
    index = pd.date_range("2025-01-01 10:00", periods=7, freq="min", tz="Asia/Kolkata")
    minute = pd.DataFrame({"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0}, index=index)
    alerts = pd.DataFrame(
        {"direction": ["PE", "PE"], "low": [99.0, 101.0], "high": [104.0, 103.0]},
        index=index[[0, 5]],
    )
    # The new 10:05 alert's low was crossed in its own candle. That is not an entry.
    result = trigger_alerts(alerts, minute)
    assert result.index.strftime("%H:%M").tolist() == ["10:06"]
    assert result.iloc[0].stop_price == 103
    minute.loc[index[3], "low"] = 98.0
    result = trigger_alerts(alerts, minute)
    assert result.index[0] == index[3] and result.iloc[0].stop_price == 104


def test_custom_stop_and_native_target_use_actual_next_open():
    minute = candles(20, "min")
    at = minute.index[0] - pd.Timedelta(minutes=1)
    signal = {
        "timestamp": at.isoformat(),
        "direction": "CE",
        "low": 98.0,
        "high": 102.0,
        "stop_price": 99.0,
        "reward_multiple": 1.5,
    }
    result = chart_outcome(signal, minute, 5)
    assert result["stop"] == 99 and result["target"] == pytest.approx(
        result["entry_price"] + 1.5 * (result["entry_price"] - 99)
    )


def test_reversal_signals_do_not_change_with_future_append():
    f = candles(100)
    m = candles(500, "min")
    full = ema_reversal_signals(f, m)
    until = f.index[80]
    prefix = ema_reversal_signals(f.loc[:until], m.loc[:until])
    pd.testing.assert_frame_equal(full.loc[:until], prefix)


def test_macd_cross_requires_correct_zero_side_trend_and_recent_retest():
    f = candles(4)
    f["ema200"] = 95.0
    f["macd"] = [-3.0, -2.0, -1.5, -0.5]
    f["macd_signal"] = [-2.0, -1.5, -1.0, -1.0]
    f["atr"] = 2.0
    f["support"] = f.low
    f["resistance"] = 120.0
    f["ready"] = True
    assert macd_signals(f).iloc[-1].direction == "CE"
    assert macd_signals(f).iloc[-1].stop_price == 94.8
    f["support"] = 80.0
    assert macd_signals(f).iloc[-1].direction == ""
    f["support"] = f.low
    f["ema200"] = 110.0
    assert macd_signals(f).iloc[-1].direction == ""


def test_alerts_clear_at_missing_minutes_and_never_trigger_on_touch():
    idx = pd.date_range("2025-01-01 10:00", periods=4, freq="min", tz="Asia/Kolkata")
    bars = pd.DataFrame({"open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0}, index=idx)
    alerts = pd.DataFrame({"direction": ["PE"], "low": [100.0], "high": [104.0]}, index=idx[:1])
    assert trigger_alerts(alerts, bars).empty
    bars.loc[idx[3], "low"] = 99.0
    assert not trigger_alerts(alerts, bars).empty
    assert trigger_alerts(alerts, bars.drop(idx[2])).empty
