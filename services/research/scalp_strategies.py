"""Causal, explicit approximations of the two user-supplied video transcripts."""

import numpy as np
import pandas as pd

from services.research.ema_scalp import _validate, indicators


def confirmed_pivot(prices, *, low=True):
    """A strict 2-left/2-right pivot, published only at confirmation time."""
    center = prices.shift(2)
    other = pd.concat([prices.shift(n) for n in (0, 1, 3, 4)], axis=1)
    valid = other.notna().all(axis=1)
    valid &= center < other.min(axis=1) if low else center > other.max(axis=1)
    return center.where(valid).ffill(limit=50)


def macd_features(frame):
    f = indicators(frame)
    fast = f.close.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = f.close.ewm(span=26, adjust=False, min_periods=26).mean()
    f["macd"] = fast - slow
    f["macd_signal"] = f.macd.ewm(span=9, adjust=False, min_periods=9).mean()
    f["ema200"] = f.close.ewm(span=200, adjust=False, min_periods=600).mean()
    f["support"] = confirmed_pivot(f.low)
    f["resistance"] = confirmed_pivot(f.high, low=False)
    return f


def macd_signals(features):
    f = features
    crossed_up = (f.macd > f.macd_signal) & (f.macd.shift() <= f.macd_signal.shift())
    crossed_down = (f.macd < f.macd_signal) & (f.macd.shift() >= f.macd_signal.shift())
    support_retest = (
        (f.low <= f.support + 0.25 * f.atr)
        & (f.low >= f.support - 0.25 * f.atr)
        & (f.close > f.support)
        & (f.close > f.open)
    )
    resistance_retest = (
        (f.high >= f.resistance - 0.25 * f.atr)
        & (f.high <= f.resistance + 0.25 * f.atr)
        & (f.close < f.resistance)
        & (f.close < f.open)
    )
    recent_support = support_retest.rolling(3).max().eq(1)
    recent_resistance = resistance_retest.rolling(3).max().eq(1)
    buy = (
        crossed_up
        & (f.macd < 0)
        & (f.macd_signal < 0)
        & (f.close > f.ema200)
        & recent_support
        & f.ready
    )
    sell = (
        crossed_down
        & (f.macd > 0)
        & (f.macd_signal > 0)
        & (f.close < f.ema200)
        & recent_resistance
        & f.ready
    )
    out = f[["open", "high", "low", "close", "macd", "macd_signal", "ema200", "atr"]].copy()
    out["direction"] = np.where(buy, "CE", np.where(sell, "PE", ""))
    out["stop_price"] = np.where(buy, f.ema200 - 0.1 * f.atr, f.ema200 + 0.1 * f.atr)
    return out


def aggregate_fifteen(frame):
    _validate(frame)
    if (
        (frame.index.minute % 5 != 0) | (frame.index.second != 0) | (frame.index.microsecond != 0)
    ).any():
        raise ValueError("Input candles must use a five-minute grid")
    key = frame.index.ceil("15min")
    groups = frame.groupby(key)
    aggregated = groups.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    count = groups.size()
    starts = frame.index.to_series().groupby(key).min()
    ends = frame.index.to_series().groupby(key).max()
    valid = (
        (count == 3)
        & (starts == aggregated.index - pd.Timedelta(minutes=10))
        & (ends == aggregated.index)
    )
    return aggregated[valid]


def trigger_alerts(alerts, minutes):
    """Observe a subsequent minute's range before entering at the following open.

    Old alerts are checked first. A newly closed alert cannot retrospectively
    trigger inside its own candle. Gaps and session changes clear pending alerts.
    """
    _validate(minutes)
    by_time = dict(iter(alerts.groupby(level=0)))
    active, records, previous = {}, [], None
    for at, row in minutes.iterrows():
        if (
            previous is None
            or at.date() != previous.date()
            or at - previous != pd.Timedelta(minutes=1)
        ):
            active.clear()
        triggered = []
        for side, alert in list(active.items()):
            breached = row.low < alert["low"] if side == "PE" else row.high > alert["high"]
            if breached:
                triggered.append((side, alert))
                del active[side]
        if len(triggered) == 1:
            side, alert = triggered[0]
            records.append(
                {
                    "timestamp": at,
                    "direction": side,
                    **row[["open", "high", "low", "close"]].to_dict(),
                    "stop_price": alert["high"] if side == "PE" else alert["low"],
                    "alert_at": alert["alert_at"],
                }
            )
        if at in by_time:
            for _, alert in by_time[at].iterrows():
                active[alert.direction] = {
                    "low": alert.low,
                    "high": alert.high,
                    "alert_at": at.isoformat(),
                }
        previous = at
    columns = ["direction", "open", "high", "low", "close", "stop_price", "alert_at"]
    if not records:
        return pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], tz=minutes.index.tz))
    return pd.DataFrame(records).set_index("timestamp")[columns]


def ema_reversal_signals(five_minutes, minutes):
    alerts = []
    for frame, direction in ((five_minutes, "PE"), (aggregate_fifteen(five_minutes), "CE")):
        ema = frame.close.ewm(span=5, adjust=False, min_periods=25).mean()
        condition = frame.low > ema if direction == "PE" else frame.high < ema
        subset = frame.loc[condition, ["low", "high"]].copy()
        subset["direction"] = direction
        alerts.append(subset)
    return trigger_alerts(pd.concat(alerts).sort_index(kind="stable"), minutes)
