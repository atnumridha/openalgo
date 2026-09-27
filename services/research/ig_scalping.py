"""Frozen IG-inspired NIFTY research rules; pure data transformations, no orders."""

import numpy as np
import pandas as pd

from services.research.ema_scalp import _validate

FAMILIES = ("stochastic", "ma", "sar", "rsi")


def bars_from_minutes(minutes, timeframe):
    _validate(minutes)
    if timeframe not in (3, 5):
        raise ValueError("Only registered 3/5-minute intervals are supported")
    f = minutes.copy()
    f.index = f.index.tz_convert("Asia/Kolkata")
    if ((f.index.second != 0) | (f.index.microsecond != 0)).any():
        raise ValueError("Minute closes must be aligned")
    clock = f.index.hour * 60 + f.index.minute
    f = f[(clock >= 556) & (clock <= 930)]
    elapsed = f.index.hour * 60 + f.index.minute - 555
    key = f.index.normalize() + pd.to_timedelta(
        555 + ((elapsed - 1) // timeframe + 1) * timeframe, unit="min"
    )
    groups = f.groupby(key)
    bars = groups.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    starts = f.index.to_series().groupby(key).min()
    ends = f.index.to_series().groupby(key).max()
    complete = (
        (groups.size() == timeframe)
        & (starts == bars.index - pd.Timedelta(minutes=timeframe - 1))
        & (ends == bars.index)
    )
    return bars[complete]


def wilder_rsi(prices, period=14):
    changes = prices.diff().to_numpy(dtype=float)
    values = np.full(len(prices), np.nan)
    if len(prices) <= period:
        return pd.Series(values, index=prices.index)
    gain = np.maximum(changes[1 : period + 1], 0).mean()
    loss = np.maximum(-changes[1 : period + 1], 0).mean()
    for i in range(period, len(prices)):
        if i > period:
            gain = (gain * (period - 1) + max(changes[i], 0)) / period
            loss = (loss * (period - 1) + max(-changes[i], 0)) / period
        values[i] = (
            50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
        )
    return pd.Series(values, index=prices.index)


def parabolic_sar(frame):
    _validate(frame)
    n = len(frame)
    values = np.full(n, np.nan)
    directions = np.zeros(n, dtype=bool)
    if n < 2:
        return pd.DataFrame({"sar": values, "sar_up": directions}, index=frame.index)
    high, low, close = (frame[k].to_numpy() for k in ("high", "low", "close"))
    up = bool(close[1] >= close[0])
    sar = float(min(low[:2]) if up else max(high[:2]))
    extreme = float(max(high[:2]) if up else min(low[:2]))
    acceleration = 0.02
    values[1], directions[:2] = sar, up
    for i in range(2, n):
        projected = sar + acceleration * (extreme - sar)
        projected = (
            min(projected, low[i - 1], low[i - 2])
            if up
            else max(projected, high[i - 1], high[i - 2])
        )
        reverse = low[i] < projected if up else high[i] > projected
        if reverse:
            sar, up = extreme, not up
            extreme = float(high[i] if up else low[i])
            acceleration = 0.02
        else:
            sar = float(projected)
            if (up and high[i] > extreme) or (not up and low[i] < extreme):
                extreme = float(high[i] if up else low[i])
                acceleration = min(0.2, acceleration + 0.02)
        values[i], directions[i] = sar, up
    return pd.DataFrame({"sar": values, "sar_up": directions}, index=frame.index)


def features(frame, timeframe):
    _validate(frame)
    if timeframe not in (3, 5):
        raise ValueError("Unsupported interval")
    f = frame.copy()
    for period in (5, 20, 50, 100, 200):
        f[f"sma{period}"] = f.close.rolling(period).mean()
        f[f"slope{period}"] = f[f"sma{period}"].diff(3)
    low, high = f.low.rolling(14).min(), f.high.rolling(14).max()
    raw = (100 * (f.close - low) / (high - low)).where(high != low, 50.0)
    f["k"] = raw.rolling(5).mean()
    f["d"] = f.k.rolling(3).mean()
    f["rsi"] = wilder_rsi(f.close)
    sar = parabolic_sar(f)
    f["sar"], f["sar_up"] = sar.sar, sar.sar_up
    f["sar_ready"] = np.arange(len(f)) >= 19
    f["stop_low"], f["stop_high"] = f.low.rolling(5).min(), f.high.rolling(5).max()
    contiguous = f.index.to_series().diff().eq(pd.Timedelta(minutes=timeframe))
    f["ready"] = contiguous.rolling(3).sum().eq(3)
    return f


def ig_signals(f, family):
    if family not in FAMILIES:
        raise ValueError("Unknown IG family")
    cross_up = (f.k > f.d) & (f.k.shift() <= f.d.shift())
    cross_down = (f.k < f.d) & (f.k.shift() >= f.d.shift())
    out = f[["open", "high", "low", "close"]].copy()
    out["exit_ce"], out["exit_pe"] = False, False
    if family == "stochastic":
        buy = (
            cross_up & ((f.k <= 20) | (f.k.shift() <= 20)) & (f.sma50 > f.sma200) & (f.slope200 > 0)
        )
        sell = (
            cross_down
            & ((f.k >= 80) | (f.k.shift() >= 80))
            & (f.sma50 < f.sma200)
            & (f.slope200 < 0)
        )
        out["exit_ce"] = (f.k >= 80) | cross_down
        out["exit_pe"] = (f.k <= 20) | cross_up
    elif family == "ma":
        buy = (f.sma5 > f.sma20) & (f.sma5.shift() <= f.sma20.shift()) & (f.slope200 > 0)
        sell = (
            (f.close < f.sma5)
            & (f.close.shift() >= f.sma5.shift())
            & (f.sma5 < f.sma20)
            & (f.slope200 < 0)
        )
    elif family == "rsi":
        slopes = f[["slope20", "slope50", "slope100"]]
        buy = (f.rsi > 30) & (f.rsi.shift() <= 30) & slopes.gt(0).all(axis=1)
        sell = (f.rsi < 70) & (f.rsi.shift() >= 70) & slopes.lt(0).all(axis=1)
    else:
        buy = f.sar_up & f.sar_up.shift().eq(False) & f.sar_ready
        sell = ~f.sar_up & f.sar_up.shift().eq(True) & f.sar_ready
        out["exit_ce"], out["exit_pe"] = sell, buy
    out["direction"] = np.where(buy & f.ready, "CE", np.where(sell & f.ready, "PE", ""))
    out["stop_price"] = (
        f.sar if family == "sar" else np.where(out.direction == "CE", f.stop_low, f.stop_high)
    )
    out["reward_multiple"] = 2
    return out
