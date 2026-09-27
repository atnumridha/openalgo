"""Causal NIFTY adaptation of the four-hour range rejection transcript.

Minute indexes are bar CLOSE times. This is an offline signal study, not a
live strategy or a literal reproduction of New York cryptocurrency candles.
"""

import pandas as pd

from services.research.ema_scalp import _validate


COLUMNS = [
    "open", "high", "low", "close", "range_high", "range_low", "direction",
    "stop_price", "breakout_at", "reward_multiple",
]


def range_signals(minute_frame):
    """Return observed five-minute bars with closed re-entry signals and audit."""
    _validate(minute_frame)
    minute = minute_frame.copy()
    minute.index = minute.index.tz_convert("Asia/Kolkata")
    audit = {
        "observed_sessions": 0,
        "valid_range_sessions": 0,
        "excluded_range_sessions": 0,
        "incomplete_trigger_buckets": 0,
        "excluded_sessions": [],
        "signals": 0,
    }
    rows, timestamps = [], []
    for day, bars in minute.groupby(minute.index.date, sort=True):
        audit["observed_sessions"] += 1
        anchor = pd.Timestamp(f"{day} 09:15", tz="Asia/Kolkata")
        range_end = anchor + pd.Timedelta(hours=4)
        expected = pd.date_range(anchor + pd.Timedelta(minutes=1), range_end, freq="min")
        missing = expected.difference(bars.index)
        if len(missing):
            audit["excluded_range_sessions"] += 1
            audit["excluded_sessions"].append({"day": str(day), "missing_range_minutes": len(missing)})
            continue
        opening = bars.loc[expected]
        high, low = float(opening.high.max()), float(opening.low.min())
        audit["valid_range_sessions"] += 1
        side, extreme, breakout_at = "", 0.0, ""
        last_close = min(anchor + pd.Timedelta(hours=6, minutes=15), bars.index.max().floor("5min"))
        for at in pd.date_range(range_end + pd.Timedelta(minutes=5), last_close, freq="5min"):
            required = pd.date_range(at - pd.Timedelta(minutes=4), at, freq="min")
            if not required.isin(bars.index).all():
                audit["incomplete_trigger_buckets"] += 1
                side, extreme, breakout_at = "", 0.0, ""
                continue
            block = bars.loc[required]
            record = {
                "open": float(block.iloc[0].open),
                "high": float(block.high.max()),
                "low": float(block.low.min()),
                "close": float(block.iloc[-1].close),
                "range_high": high,
                "range_low": low,
                "direction": "",
                "stop_price": 0.0,
                "breakout_at": "",
                "reward_multiple": 2,
            }
            outside = "PE" if record["close"] > high else ("CE" if record["close"] < low else "")
            inside = low < record["close"] < high
            if side:
                extreme = max(extreme, record["high"]) if side == "PE" else min(extreme, record["low"])
                if inside:
                    record.update(direction=side, stop_price=extreme, breakout_at=breakout_at)
                    audit["signals"] += 1
                    side, extreme, breakout_at = "", 0.0, ""
            if outside and outside != side:
                side = outside
                extreme = record["high"] if side == "PE" else record["low"]
                breakout_at = at.isoformat()
            timestamps.append(at)
            rows.append(record)
    index = pd.DatetimeIndex(timestamps, tz="Asia/Kolkata", name="bar_close")
    return pd.DataFrame(rows, index=index, columns=COLUMNS), audit
