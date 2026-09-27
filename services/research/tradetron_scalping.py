"""Frozen Tradetron-inspired research signals; no orders, I/O or tuning."""

import numpy as np
import pandas as pd

from services.research.ema_scalp import _validate
from services.research.ig_scalping import wilder_rsi

FAMILIES = ("ema", "divergence", "squeeze", "pinbar", "range")
TIMEFRAMES = {family: 1 if family == "ema" else 5 for family in FAMILIES}
EXCLUDED_SESSIONS = ("2025-10-21",)


def regular_sessions(frame):
    """Exclude the documented Muhurat day from the regular-session study."""
    _validate(frame)
    day = frame.index.tz_convert("Asia/Kolkata").strftime("%Y-%m-%d")
    return frame[~day.isin(EXCLUDED_SESSIONS)].copy()


def confirmed_divergence(frame):
    """Compare consecutive strict pivots only after both right-hand bars close."""
    n = len(frame)
    bull, bear = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    low, high, rsi, segment = (frame[k].to_numpy() for k in ("low", "high", "rsi", "segment"))
    prior = {"low": None, "high": None}
    for i in range(4, n):
        j = i - 2
        if segment[i] != segment[i - 4]:
            prior = {"low": None, "high": None}
            continue
        for kind, values, direction in (("low", low, 1), ("high", high, -1)):
            if not all(
                direction * values[j] < direction * values[k] for k in (j - 2, j - 1, j + 1, j + 2)
            ):
                continue
            p = prior[kind]
            if p is not None and segment[p] == segment[j] and 5 <= j - p <= 60:
                divergent = (
                    np.isfinite(rsi[p])
                    and np.isfinite(rsi[j])
                    and direction * values[j] < direction * values[p]
                    and direction * rsi[j] > direction * rsi[p]
                )
                if kind == "low":
                    bull[i] = divergent
                else:
                    bear[i] = divergent
            prior[kind] = j
    return pd.DataFrame({"bull": bull, "bear": bear}, index=frame.index)


def features(frame, timeframe):
    _validate(frame)
    if timeframe not in (1, 5):
        raise ValueError("Only registered one/five-minute intervals are supported")
    f = frame.copy()
    for p in (5, 10):
        f[f"ema{p}"] = f.close.ewm(span=p, adjust=False).mean()
    f["ema_ready"] = np.arange(len(f)) >= 49
    contiguous = f.index.to_series().diff().eq(pd.Timedelta(minutes=timeframe))
    f["segment"] = (~contiguous).cumsum()
    age = f.groupby("segment").cumcount()
    f["ready"], f["recent_five"], f["level_ready"] = age >= 3, age >= 5, age >= 20
    f["rsi"] = wilder_rsi(f.close)
    pivots = confirmed_divergence(f)
    f["bull"], f["bear"] = pivots.bull, pivots.bear
    center = f.close.rolling(20).mean()
    sigma = f.close.rolling(20).std(ddof=0)
    f["upper"], f["lower"] = center + 2 * sigma, center - 2 * sigma
    f["bandwidth"] = 4 * sigma / center
    f["squeeze_threshold"] = f.bandwidth.shift().rolling(120).quantile(0.1)
    f["squeezed"] = f.bandwidth <= f.squeeze_threshold
    f["recent_squeeze"] = f.squeezed.shift().rolling(5).max().eq(1)
    f["support"] = f.groupby("segment").low.transform(lambda s: s.shift().rolling(20).min())
    f["resistance"] = f.groupby("segment").high.transform(lambda s: s.shift().rolling(20).max())
    tr = pd.concat(
        [f.high - f.low, (f.high - f.close.shift()).abs(), (f.low - f.close.shift()).abs()], axis=1
    ).max(axis=1)
    atr = pd.Series(np.nan, index=f.index)
    if len(f) >= 14:
        seed = tr.iloc[13:].copy()
        seed.iloc[0] = tr.iloc[:14].mean()
        atr.loc[seed.index] = seed.ewm(alpha=1 / 14, adjust=False).mean()
    f["atr_prev"] = atr.shift()
    return f


def tradetron_signals(f, family):
    if family not in FAMILIES:
        raise ValueError("Unknown Tradetron family")
    if family == "ema":
        gap = (f.ema5 - f.ema10).round(8)
        buy = (gap > 0) & (gap.shift() <= 0) & f.ema_ready
        sell = (gap < 0) & (gap.shift() >= 0) & f.ema_ready
    elif family == "divergence":
        buy, sell = f.bull & ~f.bear, f.bear & ~f.bull
    elif family == "squeeze":
        gate = f.recent_squeeze & f.recent_five
        buy = gate & (f.close > f.upper.shift()) & (f.close.shift() <= f.upper.shift())
        sell = gate & (f.close < f.lower.shift()) & (f.close.shift() >= f.lower.shift())
    else:
        buy = f.level_ready & (f.low <= f.support) & (f.close > f.support) & (f.close > f.open)
        sell = (
            f.level_ready & (f.high >= f.resistance) & (f.close < f.resistance) & (f.close < f.open)
        )
        if family == "range":
            width = f.resistance - f.support
            middle = (f.resistance + f.support) / 2
            buy = buy & (width <= 4 * f.atr_prev) & (f.close < middle)
            sell = sell & (width <= 4 * f.atr_prev) & (f.close > middle)
        else:
            body, span = (f.close - f.open).abs(), f.high - f.low
            bottom = f[["open", "close"]].min(axis=1) - f.low
            top = f.high - f[["open", "close"]].max(axis=1)
            gate = (span > 0) & (body <= span / 3)
            buy = buy & gate & (bottom >= 2 * body) & (bottom >= span / 2) & (top <= span / 4)
            sell = sell & gate & (top >= 2 * body) & (top >= span / 2) & (bottom <= span / 4)
    out = f[["open", "high", "low", "close"]].copy()
    out["direction"] = np.where(buy & f.ready, "CE", np.where(sell & f.ready, "PE", ""))
    out["stop_price"] = f.close + np.where(out.direction == "CE", -15, 15)
    out["reward_multiple"] = 2
    out["exit_ce"], out["exit_pe"] = False, False
    return out
