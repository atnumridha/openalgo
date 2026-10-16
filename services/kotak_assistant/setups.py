"""Versioned, pure chart setup evaluators shared by live and causal replay.

Times are epoch seconds, and candle ``time`` is the opening time. Callers supply
the exchange calendar/session and observed prices; no broker, clock, or volume
is consulted here. Opening reversal state is JSON compatible and copy-on-write.
"""

import copy
import math
from bisect import bisect_right
from datetime import datetime
from zoneinfo import ZoneInfo

VERSION = "1.0"
IST = ZoneInfo("Asia/Kolkata")
SESSION_SECONDS = 22500


def observe_trend(setup, events, now):
    """Freeze a terminal intrabar invalidation/miss for this exact signal ID."""
    result = copy.deepcopy(setup)
    if result.get("stage") != "ready" or not result.get("entry_zone"):
        return result
    close = (result.get("signal_candle") or {}).get("closed_at", 0)
    for event in sorted(events, key=lambda e: e.get("time", 0)):
        if event.get("type") == "reset" or event.get("live_eligible") is False:
            continue
        at = event.get("time", 0)
        if not close <= at <= now or at >= result.get("expires", now + 1):
            continue
        price = event.get("price")
        if price is None:
            continue
        stop = result.get("invalidation")
        invalidated = stop is not None and (
            price <= stop if result.get("direction") == "CE" else price >= stop
        )
        if invalidated:
            result.update(
                stage="blocked",
                eligible=False,
                reason="Observed index price crossed the frozen invalidation",
                terminal_at=at,
            )
            break
        zone = result["entry_zone"]
        if not zone["lower"] <= price <= zone["upper"]:
            result.update(
                stage="missed",
                eligible=False,
                reason="Observed index price moved beyond the frozen entry zone",
                terminal_at=at,
            )
            break
    return result


def _finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Prices and timestamps must be finite")
    return value


def _completed(bars, now, seconds):
    valid = {}
    for bar in bars:
        try:
            time = _finite(bar.get("time", bar.get("timestamp")))
            if time > 1e12:
                time /= 1000
            values = {key: _finite(bar[key]) for key in ("open", "high", "low", "close")}
            if (
                time + seconds <= now
                and 0 < values["low"] <= min(values["open"], values["close"])
                and max(values["open"], values["close"]) <= values["high"]
            ):
                valid[time] = {"time": time, **values, "closed_at": time + seconds}
        except (TypeError, KeyError, ValueError, AttributeError):
            continue
    return [valid[time] for time in sorted(valid)]


def _pivots(bars, seconds):
    points = []
    counts = {"high": 0, "low": 0}
    for i in range(2, len(bars) - 2):
        window = bars[i - 2 : i + 3]
        if any(b["time"] - a["time"] != seconds for a, b in zip(window, window[1:], strict=False)):
            continue
        for kind in ("high", "low"):
            price = bars[i][kind]
            neighbours = [bars[j][kind] for j in (i - 2, i - 1, i + 1, i + 2)]
            strict = price > max(neighbours) if kind == "high" else price < min(neighbours)
            if strict:
                counts[kind] += 1
                points.append(
                    {
                        "kind": kind,
                        "ordinal": counts[kind],
                        "price": price,
                        "time": bars[i]["time"],
                        "known_at": bars[i + 2]["time"] + seconds,
                        "source": f"Confirmed {seconds // 60}m swing",
                    }
                )
    return points


def _base(strategy, mode, direction=None):
    return {
        "strategy": strategy,
        "version": VERSION,
        "mode": mode,
        "stage": "waiting_history",
        "direction": direction,
        "evidence": [],
        "reason": "Waiting for completed history",
        "setup_id": None,
        "index_entry": None,
        "trigger": None,
        "reference": None,
        "signal_candle": None,
        "expires": None,
        "entry_zone": None,
        "invalidation": None,
        "index_target": None,
        "eligible": False,
        "numbered_swings": [],
    }


def _opening_direction(direction):
    return {
        **_base("opening_reversal", "literal", direction),
        "stage": "waiting_reference",
        "reason": "Waiting for the second confirmed current-session swing",
        "consumed": False,
        "break_at": None,
        "triggered_at": None,
        "price_source": None,
        "rearm_needed": False,
        "reset_observed": False,
    }


def initial_opening_state(session_id):
    """Create an unarmed session state; historical OHLC cannot create breaks."""
    return {
        "strategy": "opening_reversal",
        "version": VERSION,
        "session_id": str(session_id),
        "session_start": None,
        "numbered_swings": [],
        "directions": {d: _opening_direction(d) for d in ("CE", "PE")},
        "last_event": None,
        "last_bar_time": None,
        "checked_at": None,
    }


def reset_observation(state, now, reason="Observed price continuity interrupted"):
    """Require a fresh observed recross after a feed gap, retaining one-shots."""
    result = copy.deepcopy(state)
    result.update(last_event=None, checked_at=_finite(now))
    for direction in result["directions"].values():
        if not direction["consumed"]:
            direction.update(
                stage="expired" if direction["reference"] else "waiting_reference",
                reason=f"{reason}; waiting for a fresh reference recross",
                rearm_needed=True,
                reset_observed=False,
                eligible=False,
            )
    return result


def _expire(direction, now):
    if (
        not direction["consumed"]
        and direction["expires"] is not None
        and now >= direction["expires"]
        and direction["stage"] != "expired"
    ):
        direction.update(
            stage="expired",
            reason="Five-minute signal window expired; waiting for a fresh reference recross",
            rearm_needed=True,
            reset_observed=False,
            eligible=False,
        )


def _opening_bar(direction, bar, session_id):
    if direction["stage"] != "waiting_signal" or bar["closed_at"] <= direction["break_at"]:
        return
    is_signal = (
        bar["close"] > bar["open"] if direction["direction"] == "CE" else bar["close"] < bar["open"]
    )
    if not is_signal:
        return
    trigger = bar["high"] if direction["direction"] == "CE" else bar["low"]
    direction.update(
        stage="waiting_trigger",
        reason="Waiting for a strictly later observed price beyond the frozen signal candle",
        signal_candle=dict(bar),
        trigger=trigger,
        expires=bar["closed_at"] + 300,
        invalidation=None,
        setup_id=(
            f"opening_reversal:{VERSION}:{session_id}:{direction['direction']}:"
            f"{direction['reference']['time']:.15g}:{direction['break_at']:.15g}:{bar['time']:.15g}"
        ),
    )
    direction["evidence"].append(
        f"First completed {'green' if direction['direction'] == 'CE' else 'red'} "
        f"candle frozen at {bar['closed_at']:.15g}; trigger {trigger:.15g}"
    )


def _opening_event(direction, event):
    if direction["consumed"] or direction["reference"] is None:
        return
    ref = direction["reference"]
    if event["time"] < ref["known_at"]:
        return
    price = event["price"]
    beyond = price < ref["price"] if direction["direction"] == "CE" else price > ref["price"]
    if direction["stage"] in ("waiting_break", "expired"):
        if direction["rearm_needed"]:
            if not beyond:
                direction["reset_observed"] = True
            if not direction["reset_observed"]:
                return
        if beyond:
            direction.update(
                stage="waiting_signal",
                reason="Reference break observed; waiting for the first completed signal candle",
                break_at=event["time"],
                price_source=event["source"],
                signal_candle=None,
                trigger=None,
                expires=None,
                setup_id=None,
                rearm_needed=False,
                reset_observed=False,
                evidence=[
                    f"{'L2' if direction['direction'] == 'CE' else 'H2'} {ref['price']:.15g} "
                    f"known at {ref['known_at']:.15g}",
                    f"Observed price {price:.15g} beyond reference at {event['time']:.15g} ({event['source']})",
                ],
            )
    elif direction["stage"] == "waiting_trigger":
        signal = direction["signal_candle"]
        crossed = (
            price > direction["trigger"]
            if direction["direction"] == "CE"
            else price < direction["trigger"]
        )
        if event["time"] > signal["closed_at"] and event["time"] < direction["expires"] and crossed:
            direction.update(
                stage="triggered",
                reason="Observed price strictly crossed the frozen signal candle after its close",
                consumed=True,
                triggered_at=event["time"],
                index_entry=price,
                price_source=event["source"],
                eligible=True,
            )
            direction["evidence"].append(
                f"Trigger observed at {event['time']:.15g}, index {price:.15g} ({event['source']})"
            )
    if event["source"] == "rest_snapshot" and not any(
        "sampled" in s for s in direction["evidence"]
    ):
        direction["evidence"].append(
            "REST price is a sampled snapshot; intervening ticks are unknown"
        )


def advance_opening(state, bars, event, now, session_id, session_start):
    """Advance observed-price state without mutating the supplied checkpoint.

    The initial completed history only seeds pivots. A current observation beyond
    an already-known reference can arm the initial break. After an expiry, an
    observation back at/inside the reference and a fresh strict recross are needed.
    """
    now, session_start = _finite(now), _finite(session_start)
    if (
        not isinstance(state, dict)
        or state.get("session_id") != str(session_id)
        or state.get("version") != VERSION
        or state.get("session_start") not in (None, session_start)
    ):
        result = initial_opening_state(session_id)
    else:
        result = copy.deepcopy(state)
    if isinstance(event, dict):
        try:
            event_time = _finite(event["time"])
            last = result["last_event"]
            if session_start <= event_time <= now and (last is None or event_time >= last["time"]):
                now = event_time
        except (KeyError, TypeError, ValueError):
            pass
    result.update(session_start=session_start, checked_at=now)
    closed = [
        b
        for b in _completed(bars, now, 60)
        if session_start <= b["time"] and b["closed_at"] <= session_start + SESSION_SECONDS
    ]
    # Retain confirmed identities when the caller supplies a rolling window.
    # Corrections to already-observed history cannot renumber frozen swings.
    seen = {(p["kind"], p["time"]) for p in result["numbered_swings"]}
    counts = {
        kind: sum(p["kind"] == kind for p in result["numbered_swings"]) for kind in ("high", "low")
    }
    for point in _pivots(closed, 60):
        if (point["kind"], point["time"]) in seen:
            continue
        if (
            result["last_bar_time"] is not None
            and point["known_at"] <= result["last_bar_time"] + 60
        ):
            continue
        counts[point["kind"]] += 1
        result["numbered_swings"].append({**point, "ordinal": counts[point["kind"]]})
    for direction in result["directions"].values():
        if direction["reference"] is None:
            kind = "low" if direction["direction"] == "CE" else "high"
            ref = next(
                (p for p in result["numbered_swings"] if p["kind"] == kind and p["ordinal"] == 2),
                None,
            )
            if ref:
                direction.update(
                    reference=dict(ref),
                    stage="waiting_break",
                    reason="Waiting for an observed price strictly beyond the second swing",
                )
        _expire(direction, now)

    observation = None
    if isinstance(event, dict):
        try:
            observation = {
                "time": _finite(event["time"]),
                "price": _finite(event["price"]),
                "id": str(event.get("id", "")),
                "source": str(event.get("source", "observed")),
            }
            last = result["last_event"]
            if (
                observation["price"] <= 0
                or not session_start <= observation["time"] <= now
                or observation["time"] >= session_start + SESSION_SECONDS
                or (last and observation["time"] < last["time"])
                or (last and observation["id"] and observation["id"] == last["id"])
            ):
                observation = None
        except (KeyError, TypeError, ValueError):
            observation = None

    # A delayed event must not observe a candle that had not yet closed. Iterate
    # the completed history around its actual event timestamp, not receipt time.
    new_bars = [
        b for b in closed if result["last_bar_time"] is None or b["time"] > result["last_bar_time"]
    ]
    if result["last_bar_time"] is not None and new_bars:
        times = [result["last_bar_time"]] + [b["time"] for b in new_bars]
        if any(b - a != 60 for a, b in zip(times, times[1:], strict=False)):
            result = reset_observation(result, now, "Gap in completed candidate candles")
    before = [b for b in new_bars if observation is None or b["closed_at"] <= observation["time"]]
    after = [
        b for b in new_bars if observation is not None and b["closed_at"] > observation["time"]
    ]
    for bar in before:
        for direction in result["directions"].values():
            _opening_bar(direction, bar, str(session_id))
    if observation:
        for direction in result["directions"].values():
            _opening_event(direction, observation)
        result["last_event"] = observation
    for bar in after:
        for direction in result["directions"].values():
            _opening_bar(direction, bar, str(session_id))
    if closed:
        result["last_bar_time"] = closed[-1]["time"]
    for direction in result["directions"].values():
        _expire(direction, now)
    return result


def opening_result(state, now):
    """Return a presentation DTO while retaining the session's one-shot event."""
    now = _finite(now)
    directions = copy.deepcopy(state["directions"])
    for item in directions.values():
        _expire(item, now)
        if item.get("reference") is None:
            kind = "low" if item["direction"] == "CE" else "high"
            count = sum(s["kind"] == kind for s in state["numbered_swings"])
            item["reason"] = (
                f"Waiting for second confirmed 1m swing {kind}: {min(count, 2)}/2 formed; two later candles confirm each swing"
            )
        elif item["stage"] == "waiting_break":
            relation = "below" if item["direction"] == "CE" else "above"
            item["reason"] = (
                f"Waiting for index strictly {relation} {item['reference']['price']:.2f} to start the {item['direction']} sequence"
            )
        elif item["stage"] == "waiting_signal":
            colour = "green" if item["direction"] == "CE" else "red"
            item["reason"] = (
                f"Reference break observed; waiting for the first completed {colour} 1m candle"
            )
        item["eligible"] = bool(
            item["consumed"] and item["expires"] is not None and now < item["expires"]
        )
        item["numbered_swings"] = copy.deepcopy(state["numbered_swings"])
    ranks = {
        "triggered": 5,
        "waiting_trigger": 4,
        "waiting_signal": 3,
        "expired": 2,
        "waiting_break": 1,
        "waiting_reference": 0,
    }
    selected = max(
        directions.values(),
        key=lambda d: (ranks.get(d["stage"], -1), d.get("triggered_at") or d.get("break_at") or 0),
    )
    result = copy.deepcopy(selected)
    if all(d["stage"] == "waiting_reference" for d in directions.values()):
        result["direction"] = None
        highs = min(2, sum(s["kind"] == "high" for s in state["numbered_swings"]))
        lows = min(2, sum(s["kind"] == "low" for s in state["numbered_swings"]))
        result["reason"] = (
            f"Waiting for confirmed opening swings: highs {highs}/2 · lows {lows}/2. Two following candles must confirm each swing."
        )
    result.update(
        directions=directions,
        numbered_swings=copy.deepcopy(state["numbered_swings"]),
        checked_at=now,
        session_id=state["session_id"],
    )
    return result


def indicators(bars, period=14):
    """Causal EMA20/50 and Wilder ATR, RSI, ADX arrays (None before seed)."""
    count = len(bars)
    values = {key: [None] * count for key in ("ema20", "ema50", "atr14", "rsi14", "adx14")}
    if not bars:
        return values
    for span in (20, 50):
        ema = bars[0]["close"]
        values[f"ema{span}"][0] = ema
        for i in range(1, count):
            ema += 2 / (span + 1) * (bars[i]["close"] - ema)
            values[f"ema{span}"][i] = ema
    tr, plus, minus, gain, loss = [], [], [], [], []
    smoothed = None
    dx = []
    adx = None
    for i in range(1, count):
        a, b = bars[i - 1], bars[i]
        up, down = b["high"] - a["high"], a["low"] - b["low"]
        change = b["close"] - a["close"]
        observations = (
            max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"])),
            up if up > down and up > 0 else 0,
            down if down > up and down > 0 else 0,
            max(change, 0),
            max(-change, 0),
        )
        for sequence, number in zip((tr, plus, minus, gain, loss), observations, strict=False):
            sequence.append(number)
        if i < period:
            continue
        if smoothed is None:
            smoothed = [sum(s) / period for s in (tr, plus, minus, gain, loss)]
        else:
            smoothed = [
                (previous * (period - 1) + current) / period
                for previous, current in zip(smoothed, observations, strict=False)
            ]
        atr, pos, neg, avg_gain, avg_loss = smoothed
        values["atr14"][i] = atr
        values["rsi14"][i] = (
            50
            if avg_gain == avg_loss == 0
            else 100
            if avg_loss == 0
            else 100 - 100 / (1 + avg_gain / avg_loss)
        )
        dx.append(100 * abs(pos - neg) / (pos + neg) if pos + neg else 0)
        if len(dx) == period:
            adx = sum(dx) / period
        elif len(dx) > period:
            adx = (adx * (period - 1) + dx[-1]) / period
        values["adx14"][i] = adx
    return values


def _session_start(now):
    return (
        datetime.fromtimestamp(now, IST)
        .replace(hour=9, minute=15, second=0, microsecond=0)
        .timestamp()
    )


def _history_gap(bars, seconds):
    for a, b in zip(bars, bars[1:], strict=False):
        if (
            datetime.fromtimestamp(a["time"], IST).date()
            == datetime.fromtimestamp(b["time"], IST).date()
            and b["time"] - a["time"] != seconds
        ):
            return True
    return False


def _trend_levels(one, five, session_start):
    levels = _pivots(five, 300)
    prior = [b for b in five if b["time"] < session_start]
    if prior:
        day = datetime.fromtimestamp(prior[-1]["time"], IST).date()
        prior = [b for b in prior if datetime.fromtimestamp(b["time"], IST).date() == day]
        for kind in ("high", "low"):
            extreme = (
                max(prior, key=lambda b: b[kind])
                if kind == "high"
                else min(prior, key=lambda b: b[kind])
            )
            levels.append(
                {
                    "price": extreme[kind],
                    "time": extreme["time"],
                    "known_at": prior[-1]["closed_at"],
                    "kind": kind,
                    "source": f"Previous session {kind}",
                }
            )
    opening = [b for b in five if session_start <= b["time"] < session_start + 900]
    seconds = 300
    if len(opening) != 3 or [b["time"] for b in opening] != [
        session_start + i * 300 for i in range(3)
    ]:
        opening = [b for b in one if session_start <= b["time"] < session_start + 900]
        seconds = 60
    if len(opening) == 900 // seconds and [b["time"] for b in opening] == [
        session_start + i * seconds for i in range(900 // seconds)
    ]:
        for kind in ("high", "low"):
            extreme = (
                max(opening, key=lambda b: b[kind])
                if kind == "high"
                else min(opening, key=lambda b: b[kind])
            )
            levels.append(
                {
                    "price": extreme[kind],
                    "time": extreme["time"],
                    "known_at": session_start + 900,
                    "kind": kind,
                    "source": f"Opening 15m {kind}",
                }
            )
    return sorted(levels, key=lambda level: (level["known_at"], level["price"], level["kind"]))


def _trend_direction(five, values, index):
    if index < 249 or values["adx14"][index] is None or values["adx14"][index] < 20:
        return None
    close = five[index]["close"]
    ema20, ema50 = values["ema20"][index], values["ema50"][index]
    slope = ema20 - values["ema20"][index - 1]
    return (
        "CE"
        if close > ema20 > ema50 and slope > 0
        else "PE"
        if close < ema20 < ema50 and slope < 0
        else None
    )


def _trend_candidate(pattern, reference, signal, extreme, atr, direction, levels, mode):
    sign = 1 if direction == "CE" else -1
    entry = signal["close"]
    stop = extreme - sign * 0.1 * atr
    risk = sign * (entry - stop)
    if risk <= 0:
        return None
    opposing = [
        level
        for level in levels
        if level["kind"] == ("high" if direction == "CE" else "low")
        and level["known_at"] <= signal["closed_at"]
        and sign * (level["price"] - entry) > 0
    ]
    target = min(opposing, key=lambda level: abs(level["price"] - entry)) if opposing else None
    target_price = target["price"] if target else entry + sign * 2 * risk
    room = sign * (target_price - entry) / risk
    result = _base("trend", mode, direction)
    result.update(
        stage="ready" if room >= 2 - 1e-10 else "blocked",
        reason=f"{'Early buffered break' if pattern == 'early_break' else 'Break and retest' if pattern == 'retest' else 'Sweep and confirmation'}; {'at least 2R opposing room' if room >= 2 - 1e-10 else 'nearest opposing level has less than 2R room'}",
        pattern=pattern,
        reference=dict(reference),
        signal_candle=dict(signal),
        index_entry=entry,
        trigger=entry,
        entry_zone={"lower": entry - atr * 0.25, "upper": entry + atr * 0.25},
        invalidation=stop,
        index_target=target_price,
        target_source=target["source"] if target else "projected_2r",
        reward_risk=room,
        signal_atr=atr,
        expires=signal["closed_at"] + 120,
        setup_id=f"trend:{VERSION}:{mode}:{direction}:{pattern}:{reference['time']:.15g}:{reference['price']:.15g}:{signal['time']:.15g}",
        eligible=room >= 2 - 1e-10,
        evidence=[
            f"{reference['source']} {reference['price']:.15g} known at {reference['known_at']:.15g}",
            f"{pattern} confirmed at {signal['closed_at']:.15g}; frozen index entry {entry:.15g}",
            f"Wilder ATR14 {atr:.6g}; entry zone 0.25 ATR; invalidation buffer 0.1 ATR",
            f"{'Known opposing level' if target else 'Projected target'} provides {room:.3f}R",
        ],
    )
    return result


def _trend_patterns(one, five, values, atr_values, levels, direction, mode, session_start):
    closed_times = [b["closed_at"] for b in five]
    sign = 1 if direction == "CE" else -1
    candidates = []

    def add(pattern, ref, index, extreme):
        signal, atr = one[index], atr_values[index]
        if index < 59 or atr is None or atr <= 0:
            return
        at = bisect_right(closed_times, signal["closed_at"]) - 1
        if _trend_direction(five, values, at) != direction:
            return
        candidate = _trend_candidate(pattern, ref, signal, extreme, atr, direction, levels, mode)
        if candidate:
            candidates.append(candidate)

    for ref in levels:
        price = ref["price"]
        break_kind = "high" if direction == "CE" else "low"
        if ref["kind"] == break_kind:
            first = None
            for i in range(1, len(one)):
                a, b = one[i - 1], one[i]
                atr = atr_values[i]
                if (
                    b["time"] < max(session_start, ref["known_at"])
                    or b["time"] - a["time"] != 60
                    or atr is None
                ):
                    continue
                buffer = 0.1 * atr if mode == "early" else 0
                if sign * (a["close"] - price) <= buffer and sign * (b["close"] - price) > buffer:
                    first = i
                    break
            if first is not None:
                if mode == "early":
                    add(
                        "early_break",
                        ref,
                        first,
                        one[first]["low"] if direction == "CE" else one[first]["high"],
                    )
                else:
                    for i in range(first + 1, min(first + 4, len(one))):
                        b = one[i]
                        if b["time"] - one[first]["time"] != (i - first) * 60:
                            break
                        if sign * (b["close"] - price) < 0:
                            break
                        touched = b["low"] <= price if direction == "CE" else b["high"] >= price
                        if (
                            touched
                            and sign * (b["close"] - price) > 0
                            and sign * (b["close"] - b["open"]) > 0
                        ):
                            add("retest", ref, i, b["low"] if direction == "CE" else b["high"])
                            break
        elif mode == "confirmed":
            # Each sweep must occur only after the reference is known. Freeze the
            # first following confirmation, never a later more convenient candle.
            for i in range(len(one) - 1):
                sweep = one[i]
                if sweep["time"] < max(session_start, ref["known_at"]):
                    continue
                swept = (
                    sweep["low"] < price < sweep["close"]
                    if direction == "CE"
                    else sweep["high"] > price > sweep["close"]
                )
                if not swept:
                    continue
                extreme = sweep["low"] if direction == "CE" else sweep["high"]
                boundary = sweep["high"] if direction == "CE" else sweep["low"]
                for j in range(i + 1, len(one)):
                    confirm = one[j]
                    if confirm["time"] - one[j - 1]["time"] != 60:
                        break
                    if sign * (confirm["close"] - extreme) <= 0:
                        break
                    if sign * (confirm["close"] - boundary) > 0:
                        add("sweep", ref, j, extreme)
                        break
    return candidates


def trend_setup(one, five, now, mode="confirmed", session_start=None):
    """Evaluate a completed-candle trend setup using the same inputs in replay."""
    if mode not in ("confirmed", "early"):
        raise ValueError("Trend mode must be confirmed or early")
    now = _finite(now)
    session_start = _session_start(now) if session_start is None else _finite(session_start)
    one, five = _completed(one, now, 60), _completed(five, now, 300)
    # The caller's exchange calendar filters holidays and valid session windows,
    # including exceptional evening sessions. Never replace it with clock hours.
    result = _base("trend", mode)
    result.update(checked_at=now, indicators={})
    if len(one) < 60 or len(five) < 250:
        result["reason"] = "Need 60 completed 1m and 250 completed 5m candles"
        return result
    if now - one[-1]["closed_at"] > 65 or now - five[-1]["closed_at"] > 365:
        result.update(stage="blocked", reason="Completed history is stale")
        return result
    if _history_gap(one[-60:], 60) or _history_gap(five[-250:], 300):
        result.update(stage="blocked", reason="Gap in completed session history")
        return result
    f = indicators(five)
    o = indicators(one)
    latest = {key: values[-1] for key, values in f.items()}
    latest["index_atr14"] = o["atr14"][-1]
    result["indicators"] = latest
    close, ema20, ema50 = five[-1]["close"], latest["ema20"], latest["ema50"]
    previous = f["ema20"][-2]
    direction = (
        "CE"
        if close > ema20 > ema50 and ema20 > previous
        else "PE"
        if close < ema20 < ema50 and ema20 < previous
        else None
    )
    result.update(
        direction=direction,
        stage="waiting_trend",
        reason="Waiting for directional EMA20/50 context and ADX14 at least 20",
    )
    result["evidence"] = [f"RSI14 {latest['rsi14']:.2f} is explanatory only"]
    if direction is None or latest["adx14"] is None or latest["adx14"] < 20:
        return result
    result.update(stage="waiting_pattern", reason="Waiting for a causal completed-candle setup")
    result["evidence"].append(f"{direction} EMA20/50 context; ADX14 {latest['adx14']:.2f}")
    levels = _trend_levels(one, five, session_start)
    result.update(
        levels=levels, numbered_swings=[dict(level) for level in levels if "ordinal" in level]
    )
    candidates = _trend_patterns(one, five, f, o["atr14"], levels, direction, mode, session_start)
    if not candidates:
        return result
    # Reconstruct the decision at each signal close. A later-known level or
    # pattern cannot replace a still-active selection in a stateless replay.
    selected = None
    for close_time in sorted({c["signal_candle"]["closed_at"] for c in candidates}):
        group = [c for c in candidates if c["signal_candle"]["closed_at"] == close_time]
        valid = [c for c in group if c["eligible"]]
        choice = min(
            valid or group,
            key=lambda c: (
                0 if c["pattern"] == "retest" else 1,
                abs(c["index_entry"] - c["reference"]["price"]),
                c["reference"]["known_at"],
            ),
        )
        if selected is None or close_time >= selected["expires"] or not selected["eligible"]:
            selected = choice
    selected.update(
        checked_at=now, indicators=latest, levels=levels, numbered_swings=result["numbered_swings"]
    )
    selected["evidence"] = result["evidence"] + selected["evidence"]
    if now >= selected["expires"]:
        selected.update(
            stage="expired", reason="Setup expired after two further 1m bars", eligible=False
        )
    else:
        subsequent = [b for b in one if b["time"] >= selected["signal_candle"]["closed_at"]]
        invalidated = any(
            b["low"] <= selected["invalidation"]
            if direction == "CE"
            else b["high"] >= selected["invalidation"]
            for b in subsequent
        )
        if invalidated:
            selected.update(
                stage="blocked",
                reason="Index invalidation crossed after setup confirmation",
                eligible=False,
            )
        elif (
            not selected["entry_zone"]["lower"]
            <= one[-1]["close"]
            <= selected["entry_zone"]["upper"]
        ):
            selected.update(
                stage="missed",
                reason="Index has moved beyond the frozen entry zone",
                eligible=False,
            )
    return selected
