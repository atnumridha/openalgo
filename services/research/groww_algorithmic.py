"""Frozen, causal scalping adaptations of Groww's broad algorithmic families."""

import numpy as np
import pandas as pd

from services.research.ema_scalp import _validate

FAMILIES = ("mean_z20", "mean_daily10", "trend_50_200", "timing_50_200")


def daily_context(index, daily):
    if (
        not daily.index.is_monotonic_increasing
        or not daily.index.is_unique
        or daily.index.tz is None
    ):
        raise ValueError("Daily dates must be ordered, unique and timezone aware")
    if not np.isfinite(daily.close).all() or not daily.close.gt(0).all():
        raise ValueError("Daily closes must be positive and finite")
    d = pd.DataFrame(index=daily.index)
    d["daily_at"] = daily.index
    d["daily_close"] = daily.close
    d["daily_ma20"] = daily.close.rolling(20).mean()
    d["daily_ma200"] = daily.close.rolling(200).mean()
    d["daily_vol20"] = daily.close.pct_change(fill_method=None).rolling(20).std(ddof=0)
    d["daily_vol_median"] = d.daily_vol20.rolling(252).median()
    joined = pd.merge_asof(
        pd.DataFrame({"day": index.normalize()}),
        d.reset_index(drop=True),
        left_on="day",
        right_on="daily_at",
        direction="backward",
        allow_exact_matches=False,
    ).drop(columns="day")
    joined.index = index
    return joined


def features(bars, daily):
    _validate(bars)
    f = bars.copy()
    deviation = f.close.rolling(20).std(ddof=0).replace(0, np.nan)
    f["z20"] = (f.close - f.close.rolling(20).mean()) / deviation
    f["ema_diff"] = (
        f.close.ewm(span=50, adjust=False).mean() - f.close.ewm(span=200, adjust=False).mean()
    ).round(8)
    f["ready"] = f.index.to_series().diff().eq(pd.Timedelta(minutes=5)).rolling(3).sum().eq(3)
    f["observations"] = np.arange(1, len(f) + 1)
    return f.join(daily_context(f.index, daily))


def signals(frame, family):
    if family not in FAMILIES:
        raise ValueError(f"Unknown family: {family}")
    f = frame.copy()
    if family == "mean_z20":
        buy = f.z20.gt(-2) & f.z20.shift().le(-2) & f.close.gt(f.open)
        sell = f.z20.lt(2) & f.z20.shift().ge(2) & f.close.lt(f.open)
    elif family == "mean_daily10":
        buy = f.close.lt(0.9 * f.daily_ma20) & f.close.shift().ge(0.9 * f.daily_ma20)
        sell = f.close.gt(1.1 * f.daily_ma20) & f.close.shift().le(1.1 * f.daily_ma20)
    else:
        buy = f.ema_diff.gt(0) & f.ema_diff.shift().le(0)
        sell = f.ema_diff.lt(0) & f.ema_diff.shift().ge(0)
        if family == "timing_50_200":
            buy &= f.daily_close.gt(f.daily_ma200) & f.daily_vol20.le(f.daily_vol_median)
            sell &= f.daily_close.lt(f.daily_ma200) & f.daily_vol20.le(f.daily_vol_median)
    gate = f.ready & f.observations.ge(200 if "50_200" in family else 20)
    buy, sell = buy & gate, sell & gate
    f["direction"] = np.where(buy, "CE", np.where(sell, "PE", ""))
    f["stop_price"] = np.where(buy, f.low, np.where(sell, f.high, np.nan))
    return f
