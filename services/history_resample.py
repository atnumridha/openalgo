"""Causal OHLC aggregation from observed minute bars, never snapshot expansion."""

import math
import time
from collections import defaultdict

HISTORY_CONTEXT_VERSION = "minute-ohlc-2-session-close"
IST_OFFSET = 19800


def aggregate_history_minutes(records, interval, now=None, *, session_end=None):
    """Aggregate only observed minutes, including a verified shortened session close.

    session_end is the configured exchange closing minute after IST midnight.
    Without verified timing, historical partial buckets remain excluded.
    """
    if interval not in ("5m", "15m"):
        raise ValueError("Minute aggregation supports 5m and 15m only")
    count = int(interval[:-1])
    seconds = count * 60
    now = time.time() if now is None else float(now)
    end_minute = (
        int(session_end)
        if isinstance(session_end, (int, float))
        and not isinstance(session_end, bool)
        and math.isfinite(session_end)
        and 0 < session_end <= 1440
        and session_end == int(session_end)
        else None
    )
    groups = defaultdict(dict)
    for row in records:
        try:
            timestamp = float(row["timestamp"])
            if (
                not math.isfinite(timestamp)
                or timestamp % 60
                or timestamp > now
                or row.get("repaired")
            ):
                continue
            timestamp = int(timestamp)
            o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            volume = float(row.get("volume", 0) or 0)
            oi = float(row.get("oi", 0) or 0)
            if (
                not all(math.isfinite(x) for x in (o, h, low, c, volume, oi))
                or not 0 < low <= min(o, c) <= max(o, c) <= h
                or volume < 0
            ):
                continue
            bucket = ((timestamp + IST_OFFSET) // seconds) * seconds - IST_OFFSET
            groups[bucket][timestamp] = {
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": volume,
                "oi": oi,
            }
        except (KeyError, ValueError, TypeError):
            continue
    current = ((int(now) + IST_OFFSET) // seconds) * seconds - IST_OFFSET
    out = []
    for bucket, minutes in sorted(groups.items()):
        times = sorted(minutes)
        bucket_end = bucket + seconds
        if end_minute is not None:
            midnight = ((bucket + IST_OFFSET) // 86400) * 86400 - IST_OFFSET
            close = midnight + end_minute * 60
            # Only relax completeness when the observed source itself ends
            # before this close. Later real minutes may belong to an extended
            # session: preserve their original full/forming bucket semantics.
            if bucket < close < bucket_end and times[-1] < close:
                bucket_end = close
        if not times:
            continue
        complete = bucket_end <= now and times == list(range(bucket, bucket_end, 60))
        forming = (
            bucket == current
            and times == list(range(bucket, times[-1] + 60, 60))
            and 0 <= int(now) // 60 * 60 - times[-1] <= 60
        )
        if not complete and not forming:
            continue
        rows = [minutes[t] for t in times]
        out.append(
            {
                "timestamp": bucket,
                "open": rows[0]["open"],
                "high": max(r["high"] for r in rows),
                "low": min(r["low"] for r in rows),
                "close": rows[-1]["close"],
                "volume": sum(r["volume"] for r in rows),
                "oi": rows[-1]["oi"],
            }
        )
    return out
