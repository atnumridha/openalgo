"""Bounded native history parsing and causal close-time eligibility."""

from datetime import datetime, timedelta
from decimal import Decimal as D

from .types import IST, Candle


def should_evaluate(now, last_close):
    if now.tzinfo is None:
        return False
    clock = now.astimezone(IST)
    closed = clock.replace(second=0, microsecond=0)
    minute = clock.hour * 60 + clock.minute
    return (
        clock.weekday() < 5
        and 585 <= minute <= 915
        and minute % 15 == 0
        and (now - closed).total_seconds() <= 5
        and last_close != closed
    )


def closed_bars(data, now, minutes=15):
    result = []
    for row in data[-1000:]:
        try:
            stamp = datetime.fromtimestamp(float(row["timestamp"]), IST)
            values = [D(str(row[k])) for k in ("open", "high", "low", "close")]
            if (
                row.get("repaired")
                or row.get("confirmed") is False
                or stamp + timedelta(minutes=minutes) > now
                or not all(v.is_finite() and v > 0 for v in values)
            ):
                continue
            opening, high, low, closing = values
            if low > min(opening, closing) or high < max(opening, closing) or low > high:
                continue
            result.append(
                Candle(stamp, opening, high, low, closing, D(str(row.get("volume") or 0)))
            )
        except (ValueError, TypeError, KeyError):
            continue
    return sorted({b.time: b for b in result}.values(), key=lambda b: b.time)
