"""Our SMA-seeded EMA9/15/21 engine. Local arithmetic only; no account or order access."""
import math
from functools import lru_cache


@lru_cache(maxsize=8)
def _calculate(candles):
    states = {p: {"points": [], "count": 0, "sum": 0.0, "value": None} for p in (9, 15, 21)}
    crosses, direction = [], 0
    for stamp, close in candles:
        for period, state in states.items():
            state["count"] += 1
            if state["value"] is None:
                state["sum"] += close
                if state["count"] == period:
                    state["value"] = state["sum"] / period
            else:
                state["value"] += (2 / (period + 1)) * (close - state["value"])
            if state["value"] is not None:
                state["points"].append({"time": stamp, "value": state["value"]})
        fast, slow = states[9]["value"], states[15]["value"]
        if fast is not None and slow is not None:
            sign = 1 if fast > slow else -1 if fast < slow else 0
            if sign and direction and sign != direction:
                crosses.append({"time": stamp, "value": (fast + slow) / 2, "side": "up" if sign > 0 else "down"})
            if sign:
                direction = sign
    return {**{str(p): state for p, state in states.items()}, "crosses": crosses,
            "direction": "up" if direction > 0 else "down" if direction < 0 else "sideways",
            "algorithm": "sma-seeded-ema-9-15-v1"}


def ema_backfill(candles):
    if not isinstance(candles, list) or len(candles) > 10000:
        raise ValueError("Expected at most 10000 candles")
    source, previous = [], -math.inf
    for candle in candles:
        if not isinstance(candle, dict):
            raise ValueError("Invalid candle")
        try:
            stamp, close = float(candle["time"]), float(candle["close"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Invalid candle") from None
        if not math.isfinite(stamp) or not math.isfinite(close) or stamp < 0 or close <= 0 or stamp <= previous:
            raise ValueError("Candles must have ordered times and positive finite closes")
        previous = stamp
        source.append((stamp, close))
    cached = _calculate(tuple(source))
    # Never let callers mutate a cached result shared by other chart requests.
    return {**cached, **{p: {**cached[p], "points": [dict(v) for v in cached[p]["points"]]} for p in ("9", "15", "21")},
            "crosses": [dict(v) for v in cached["crosses"]]}
