"""Causal, close-confirmed adaptation of the supplied Groww Supertrend video."""

import numpy as np
import pandas as pd

from services.research.ema_scalp import _validate


def supertrend_features(minutes):
    _validate(minutes)
    f = minutes.copy()
    n = len(f)
    close, high, low = (f[c].to_numpy(dtype=float) for c in ("close", "high", "low"))
    tr = high - low
    if n > 1:
        tr[1:] = np.maximum(
            tr[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1]))
        )
    atr, upper, lower, line = (np.full(n, np.nan) for _ in range(4))
    trend = np.zeros(n, dtype=int)
    for i in range(9, n):
        atr[i] = float(tr[:10].mean()) if i == 9 else (atr[i - 1] * 9 + tr[i]) / 10
        mid = (high[i] + low[i]) / 2
        up, down = mid + 3 * atr[i], mid - 3 * atr[i]
        if i == 9:
            upper[i], lower[i], trend[i] = up, down, -1
        else:
            upper[i] = up if up < upper[i - 1] or close[i - 1] > upper[i - 1] else upper[i - 1]
            lower[i] = down if down > lower[i - 1] or close[i - 1] < lower[i - 1] else lower[i - 1]
            if trend[i - 1] == -1:
                trend[i] = 1 if close[i] > upper[i] else -1
            else:
                trend[i] = -1 if close[i] < lower[i] else 1
        line[i] = lower[i] if trend[i] == 1 else upper[i]
    f["atr"], f["upper"], f["lower"], f["supertrend"], f["trend"] = atr, upper, lower, line, trend
    consecutive = f.index.to_series().diff().eq(pd.Timedelta(minutes=1))
    f["ready"] = consecutive.rolling(3).sum().eq(3) & (np.arange(n) >= 99)
    return f


def pullback_signals(features):
    """A setup expires after the immediately following closed minute."""
    _validate(features)
    f = features.copy()
    stable = f.trend.eq(f.trend.shift())
    touch = f.low.le(f.supertrend) & f.high.ge(f.supertrend) & stable & f.ready
    buy_setup = touch & f.trend.eq(1) & f.close.gt(f.supertrend)
    sell_setup = touch & f.trend.eq(-1) & f.close.lt(f.supertrend)
    consecutive = f.index.to_series().diff().eq(pd.Timedelta(minutes=1))
    gate = consecutive & stable & f.ready
    buy = (
        gate
        & buy_setup.shift(fill_value=False)
        & f.close.gt(f.high.shift())
        & f.low.gt(f.low.shift())
    )
    sell = (
        gate
        & sell_setup.shift(fill_value=False)
        & f.close.lt(f.low.shift())
        & f.high.lt(f.high.shift())
    )
    f["direction"] = np.where(buy, "CE", np.where(sell, "PE", ""))
    f["stop_price"] = np.where(buy, f.low.shift(), np.where(sell, f.high.shift(), np.nan))
    f["setup_at"] = ""
    selected = f.direction.ne("")
    prior = f.index.to_series().shift()
    f.loc[selected, "setup_at"] = prior[selected].map(lambda t: t.isoformat())
    return f
