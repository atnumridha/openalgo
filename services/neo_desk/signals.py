"""The established closed-bar rules; no clock, broker or execution side effects."""

from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR
from decimal import Decimal as D

from .indicators import compute_indicators
from .types import IST, Setup


def _retest(bars, points):
    pending = None
    signal = None
    day = bars[-1].time.astimezone(IST).date()
    for i, b in enumerate(bars):
        if b.time.astimezone(IST).date() != day:
            continue
        signal = None
        atr = points[i].atr
        recent = bars[max(0, i - 3) : i + 1]
        if (
            i < 20
            or not atr
            or len(recent) != 4
            or any(
                x.time.astimezone(IST).date() != day or not x.confirmed or x.repaired
                for x in recent
            )
            or any(
                y.time - x.time != timedelta(minutes=15)
                for x, y in zip(recent, recent[1:], strict=False)
            )
        ):
            pending = None
            continue
        if pending and i - pending[0] > 3:
            pending = None
        if pending:
            _, side, level = pending
            bull = side == "CE"
            tol = atr * D(".15")
            width = b.high - b.low
            loc = ((b.close - b.low) if bull else (b.high - b.close)) / width if width else D(0)
            touch = b.low <= level + tol if bull else b.high >= level - tol
            confirm = (
                (b.close > level + D(".05") and b.close > b.open)
                if bull
                else (b.close < level - D(".05") and b.close < b.open)
            )
            if touch and confirm and loc >= D(".65"):
                signal = (side, b.low - atr * D(".1") if bull else b.high + atr * D(".1"))
                pending = None
                continue
            if b.close < level - tol if bull else b.close > level + tol:
                pending = None
        hi = max(x.high for x in recent[:-1])
        lo = min(x.low for x in recent[:-1])
        side = "CE" if b.close > hi + D(".05") else "PE" if b.close < lo - D(".05") else None
        if side and pending is None:
            pending = (i, side, hi if side == "CE" else lo)
    return signal


def evaluate_setup(bars, preset):
    if len(bars) < max(201, preset.entry_length + 2):
        return None

    if any(
        b.time.tzinfo is None
        or not all(
            isinstance(v, D) and v.is_finite() and v > 0 for v in (b.open, b.high, b.low, b.close)
        )
        or b.low > min(b.open, b.close)
        or b.high < max(b.open, b.close)
        for b in bars
    ):
        return None
    b, prev = bars[-1], bars[-2]
    if b.time.tzinfo is None or any(x.time >= y.time for x, y in zip(bars, bars[1:], strict=False)):
        return None
    opening = b.time.astimezone(IST)
    execution = opening + timedelta(minutes=15)
    if (
        not b.confirmed
        or b.repaired
        or opening.weekday() >= 5
        or opening.hour * 60 + opening.minute < 570
        or not 585 <= execution.hour * 60 + execution.minute <= preset.last_entry_minute
    ):
        return None
    points = compute_indicators(bars, preset.entry_length)
    cur, prior = points[-1], points[-2]
    if not cur.atr or cur.atr <= 0:
        return None
    side = None
    structure = None
    if preset.model == "price_retest":
        found = _retest(bars, points)
        if found:
            side, structure = found
    elif preset.model == "orb15":
        start = opening.replace(hour=9, minute=15, second=0, microsecond=0)
        band = next((x for x in bars if x.time == start), None)
        if (
            not band
            or not band.confirmed
            or band.repaired
            or not prev.confirmed
            or prev.repaired
            or b.time - prev.time != timedelta(minutes=15)
        ):
            return None
        if b.close > band.high and prev.close <= band.high:
            side = "CE"
        elif b.close < band.low and prev.close >= band.low:
            side = "PE"
    else:
        if (
            cur.upper is not None
            and prior.upper is not None
            and b.close > cur.upper
            and prev.close <= prior.upper
        ):
            side = "CE"
        elif (
            cur.lower is not None
            and prior.lower is not None
            and b.close < cur.lower
            and prev.close >= prior.lower
        ):
            side = "PE"
    if not side:
        return None
    sign = D(1) if side == "CE" else D(-1)
    if preset.ema_filter:
        recent = bars[-21:]
        if any(not x.confirmed or x.repaired for x in recent) or any(
            x.time.date() == y.time.date() and y.time - x.time != timedelta(minutes=15)
            for x, y in zip(recent, recent[1:], strict=False)
        ):
            return None
        width = b.high - b.low
        loc = ((b.close - b.low) if side == "CE" else (b.high - b.close)) / width if width else D(0)
        if (
            sign * (cur.ema - points[-4].ema) / cur.atr < D(".10")
            or sign * (b.close - cur.ema) <= 0
            or loc < D(".65")
            or not 0 < width / cur.atr <= 2
        ):
            return None
    if structure is not None:
        risk = (b.close - structure) * sign
        if not 0 < risk <= cur.atr * 2:
            return None
        risk = (risk / D(".1")).to_integral_value(rounding=ROUND_CEILING) * D(".1")
    else:
        risk = max(
            2, int((cur.atr / D(".05") / 2).to_integral_value(rounding=ROUND_FLOOR)) * 2
        ) * D(".05")
    return Setup(
        preset.profile,
        opening,
        execution,
        side,
        b.close,
        b.close - sign * risk,
        b.close + sign * risk * preset.reward_risk,
        cur.atr,
        structure_stop=structure,
    )


def anchor_setup(setup, reference):
    """Execution uses a fresh index snapshot; chart previews retain the bar close."""
    from dataclasses import replace

    reference = D(str(reference))
    if not reference.is_finite() or reference <= 0:
        return None
    sign = D(1) if setup.direction == "CE" else D(-1)
    if setup.structure_stop is not None:
        risk = (reference - setup.structure_stop) * sign
        if not 0 < risk <= setup.atr * 2:
            return None
        risk = (risk / D(".1")).to_integral_value(rounding=ROUND_CEILING) * D(".1")
    else:
        risk = abs(setup.index_reference - setup.initial_stop)
    stop = reference - sign * risk
    target = reference + sign * risk * 6
    if risk <= 0 or min(stop, target) <= 0:
        return None
    return replace(setup, index_reference=reference, initial_stop=stop, target=target)
