"""Versioned, causal long-option receiver rules; no orders or retained state."""

import pandas as pd

from services.research.ema_scalp import _validate

PROFILES = {
    "receiver_trend": "5/15-minute trend pullback",
    "receiver_retest": "Breakout followed by a later retest",
    "receiver_momentum": "Momentum range breakout",
}
RULE_VERSION = "receiver-closed-bars-v2"
RECEIVER_NAMES = {
    "NIFTY 5/15-Minute Trend Signal Receiver": "receiver_trend",
    "NIFTY Breakout and Retest Signal Receiver": "receiver_retest",
    "NIFTY Long-Option Momentum Signal Receiver": "receiver_momentum",
    "SENSEX 5/15-Minute Trend Signal Receiver": "receiver_trend",
    "SENSEX Breakout and Retest Signal Receiver": "receiver_retest",
    **{
        f"{root} Momentum and Breakout Signal Receiver": "receiver_momentum"
        for root in ("GOLDM", "CRUDEOILM", "SILVERM", "NATGASMINI")
    },
}


def diagnostics(signal):
    """Explain both sides from authoritative evaluator results, without re-evaluating.

    Missing warmup/confirmation leaves its unevaluated checks unknown. A setup
    that conflicts with the higher timeframe can therefore show one passed and
    one failed component for each direction without implying an entry signal.
    """
    observed = signal["checks"]
    setup = {
        "receiver_trend": "5-minute EMA trend and pullback setup",
        "receiver_retest": "5-minute breakout and subsequent valid retest",
        "receiver_momentum": "5-minute range breakout with strong, expanded candle",
    }[signal["profile"]]
    checks = []
    for side in ("CE", "PE"):
        for key, label in (
            ("setup", setup),
            ("confirmation", "15-minute body and close-to-close confirmation"),
        ):
            checks.append(
                {
                    "side": side,
                    "label": label,
                    "passed": observed[key] == side if key in observed else None,
                }
            )
    return {"data_ready": "setup" in observed and "confirmation" in observed, "checks": checks}


def _closed(frame, at, minutes):
    _validate(frame)
    if (
        (frame.index.minute % minutes != 0)
        | (frame.index.second != 0)
        | (frame.index.microsecond != 0)
    ).any():
        raise ValueError("Receiver candles must be aligned completed bars")
    return frame.loc[frame.index <= at].tail(500)


def _consecutive(frame, count, minutes):
    return (
        len(frame) >= count
        and frame.index[-count:].to_series().diff().iloc[1:].eq(pd.Timedelta(minutes=minutes)).all()
    )


def evaluate(profile, five, fifteen, expected):
    """Return a signal only on the current completed bar, with symmetric rules.

    The six-bar range excludes the breakout candle. A retest must follow its
    breakout by 1–3 full bars; only its first valid retest can signal. Prefix
    evaluation gives the same answer as a complete historical frame.
    """
    if profile not in PROFILES:
        raise ValueError("Unknown receiver profile")
    at = pd.Timestamp(expected)
    if at.tzinfo is None:
        raise ValueError("Receiver signal time must be timezone aware")
    f, h = _closed(five, at, 5), _closed(fifteen, at, 15)
    result = {
        "direction": "",
        "position": "B",
        "timestamp": at.isoformat(),
        "rule_version": RULE_VERSION,
        "profile": profile,
        "checks": {},
    }

    def waiting(reason):
        return result | {"reason": reason}

    if f.empty or f.index[-1] != at or not _consecutive(f, 10, 5):
        return waiting("Collecting ten contiguous completed five-minute candles")
    if (
        not _consecutive(h, 2, 15)
        or h.index[-1] != at.floor("15min")
        or h.index[-2].date() != at.date()
    ):
        return waiting("Waiting for fresh completed fifteen-minute confirmation")
    current, previous = h.iloc[-1], h.iloc[-2]
    confirmation = (
        "CE"
        if current.close > previous.close and current.close > current.open
        else ("PE" if current.close < previous.close and current.close < current.open else "")
    )
    result["checks"]["confirmation"] = confirmation or "flat"
    row = f.iloc[-1]
    direction = ""
    if profile == "receiver_trend":
        if len(f) < 35:
            return waiting("Trend needs 35 completed five-minute candles")
        fast, slow = (
            f.close.ewm(span=9, adjust=False).mean(),
            f.close.ewm(span=15, adjust=False).mean(),
        )
        touch = row.low <= max(fast.iloc[-1], slow.iloc[-1]) and row.high >= min(
            fast.iloc[-1], slow.iloc[-1]
        )
        up = (
            fast.iloc[-1] > slow.iloc[-1]
            and fast.iloc[-1] > fast.iloc[-4]
            and slow.iloc[-1] > slow.iloc[-4]
        )
        down = (
            fast.iloc[-1] < slow.iloc[-1]
            and fast.iloc[-1] < fast.iloc[-4]
            and slow.iloc[-1] < slow.iloc[-4]
        )
        if touch and up and row.close > fast.iloc[-1] and row.close > row.open:
            direction = "CE"
        elif touch and down and row.close < fast.iloc[-1] and row.close < row.open:
            direction = "PE"
        result["checks"].update(
            ema9=float(fast.iloc[-1]), ema15=float(slow.iloc[-1]), pullback=bool(touch)
        )
    elif profile == "receiver_momentum":
        prior = f.iloc[-7:-1]
        width = row.high - row.low
        strong = width > 0 and abs(row.close - row.open) >= 0.7 * width
        expanded = width >= 1.2 * (prior.high - prior.low).median()
        if strong and expanded and row.close > prior.high.max() and row.close > row.open:
            direction = "CE"
        elif strong and expanded and row.close < prior.low.min() and row.close < row.open:
            direction = "PE"
        result["checks"].update(strong_body=bool(strong), range_expansion=bool(expanded))
    else:
        # Earliest breakout wins; an earlier retest consumes that setup.
        for offset in (3, 2, 1):
            i = len(f) - 1 - offset
            prior, breakout = f.iloc[i - 6 : i], f.iloc[i]
            if len(prior) != 6 or prior.index[0].date() != at.date():
                continue
            high, low = float(prior.high.max()), float(prior.low.min())
            width = breakout.high - breakout.low
            if width <= 0 or abs(breakout.close - breakout.open) < 0.5 * width:
                continue
            side = (
                "CE"
                if breakout.close > high and breakout.close > breakout.open
                else ("PE" if breakout.close < low and breakout.close < breakout.open else "")
            )
            if not side:
                continue
            level = high if side == "CE" else low
            for j in range(i + 1, len(f)):
                candle = f.iloc[j]
                # A close through the level invalidates the setup.
                if (side == "CE" and candle.close < level) or (
                    side == "PE" and candle.close > level
                ):
                    break
                touched = candle.low <= level <= candle.high
                rejected = (
                    (candle.close > level and candle.close > candle.open)
                    if side == "CE"
                    else (candle.close < level and candle.close < candle.open)
                )
                if touched and rejected:
                    if j == len(f) - 1:
                        direction = side
                        result["checks"].update(
                            breakout_at=f.index[i].isoformat(), retest_level=level
                        )
                    break
            if direction:
                break
    result["checks"]["setup"] = direction or "none"
    if not direction or direction != confirmation:
        return waiting("No matching closed-bar setup and fifteen-minute confirmation")
    return result | {
        "direction": direction,
        "stop_price": float(row.low if direction == "CE" else row.high),
        "low": float(row.low),
        "high": float(row.high),
        "close": float(row.close),
        "reason": "Fresh confirmed setup; option affordability and risk checks remain",
    }
