"""Premium-domain plans; index setup prices are never used as option stops."""

from services.risk.cash_budget import trend_premium_stop

from .analysis import plan, snap
from .setups import indicators


def trend_plan(entry, candles, quantity, tick, lot, exchange, settings, ratio=2, day="2026-10-16"):
    if ratio not in (1.5, 2, 3, 4, 5, 6):
        raise ValueError("Reward multiple must be 1.5, 2, 3, 4, 5 or 6")
    distance = indicators(candles)["atr14"][-1] if candles else None
    if distance is None or distance <= 0:
        return {"fits": False, "reason": "Completed option candles are needed for Wilder ATR14"}
    lows = []
    for i in range(2, len(candles) - 2):
        window = candles[i - 2 : i + 3]
        if all(
            b["time"] - a["time"] == 60 for a, b in zip(window, window[1:], strict=False)
        ) and all(candles[i]["low"] < candles[j]["low"] for j in (i - 2, i - 1, i + 1, i + 2)):
            lows.append(candles[i]["low"])
    try:
        sl = trend_premium_stop(entry, distance, lows[-1] if lows else None, tick)
    except ValueError:
        return {"fits": False, "reason": "No valid structural premium stop below entry"}
    if sl <= 0 or sl >= entry:
        return {"fits": False, "reason": "No valid structural premium stop below entry"}
    target = snap(entry + ratio * (entry - sl), tick, True)
    p = plan(entry, sl, target, quantity, exchange, settings, tick, lot, day)
    p.update(
        option_atr=distance,
        option_swing_low=lows[-1] if lows else None,
        risk_policy={
            "kind": "structural_premium",
            "option_atr": distance,
            "option_swing_low": lows[-1] if lows else None,
        },
        preferred_net_rr=p["net_rr"] >= 1.5,
    )
    return p
