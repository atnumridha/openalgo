import numpy as np
import pandas as pd
import pytest

from services.research.groww_algorithmic import daily_context, features, signals


def bars(n=350):
    index = pd.date_range("2025-01-02 09:20", periods=n, freq="5min", tz="Asia/Kolkata")
    close = 100 + np.random.default_rng(32).normal(size=n).cumsum()
    return pd.DataFrame(
        {"open": close - 0.1, "high": close + 1, "low": close - 1, "close": close}, index=index
    )


def daily():
    index = pd.date_range("2023-01-01", "2025-02-01", freq="B", tz="Asia/Kolkata")
    return pd.DataFrame({"close": np.linspace(90, 110, len(index))}, index=index)


def test_daily_context_is_strictly_earlier_and_ignores_current_close():
    d, b = daily(), bars(20)
    want = daily_context(b.index, d)
    d.loc[d.index >= b.index[0].normalize(), "close"] = 50000
    pd.testing.assert_frame_equal(want, daily_context(b.index, d))
    assert (pd.to_datetime(want.daily_at, utc=True) < b.index.normalize()).all()
    assert want.daily_ma20.iloc[0] == pytest.approx(
        d.loc[d.index < b.index[0].normalize(), "close"].iloc[-20:].mean()
    )


@pytest.mark.parametrize("family", ["mean_z20", "mean_daily10", "trend_50_200", "timing_50_200"])
def test_prefix_invariance_and_gap_gate(family):
    b = bars()
    full = signals(features(b, daily()), family)
    prefix = signals(features(b.iloc[:270], daily()), family)
    pd.testing.assert_frame_equal(full.iloc[:270], prefix)
    broken = signals(features(b.drop(b.index[270]), daily()), family)
    assert broken.loc[b.index[271] : b.index[273], "direction"].eq("").all()


def test_flat_prices_and_ema_warmup_have_no_signals():
    b = bars()
    b[["open", "close"]] = 100
    b.high, b.low = 101, 99
    for family in ("mean_z20", "trend_50_200"):
        assert signals(features(b, daily()), family).direction.eq("").all()
    assert signals(features(bars(190), daily()), "trend_50_200").direction.eq("").all()


@pytest.mark.parametrize("side", ["CE", "PE"])
def test_zscore_reentry_and_stop(side):
    f = features(bars(), daily())
    f.z20 = 0.0
    f.loc[f.index[250], "z20"] = -2.2 if side == "CE" else 2.2
    f.loc[f.index[251], "open"] = f.close.iloc[251] + (-0.2 if side == "CE" else 0.2)
    out = signals(f, "mean_z20")
    assert out.direction.iloc[251] == side
    assert out.stop_price.iloc[251] == (f.low.iloc[251] if side == "CE" else f.high.iloc[251])


def test_timing_filter_rejects_wrong_regime_and_high_volatility():
    f = features(bars(), daily())
    f.ema_diff = -1.0
    f.loc[f.index[251] :, "ema_diff"] = 1.0
    f.daily_close, f.daily_ma200, f.daily_vol20, f.daily_vol_median = 110, 100, 0.01, 0.02
    assert signals(f, "timing_50_200").direction.iloc[251] == "CE"
    f.daily_close = 90
    assert signals(f, "timing_50_200").direction.iloc[251] == ""
    f.daily_close, f.daily_vol20 = 110, 0.03
    assert signals(f, "timing_50_200").direction.iloc[251] == ""


def test_daily_ten_percent_cross_uses_same_known_mean_for_previous_bar():
    f = features(bars(), daily())
    f.daily_ma20 = 100.0
    f.loc[f.index[251], ["open", "high", "low", "close"]] = [90, 91, 88, 89]
    f.loc[f.index[250], ["open", "high", "low", "close"]] = [90, 92, 89, 91]
    assert signals(f, "mean_daily10").direction.iloc[251] == "CE"
