"""Pure, causal analysis and premium-turnover cost estimates. No broker writes."""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DEFAULTS = {
    "risk": None,
    "daily_loss": None,
    "giveback": None,
    "premium": None,
    "spread": 2.0,
    "slippage": 0.1,
    "brokerage": 0.0,
    "cooldown": 300,
    "cutoff": "15:15",
}
FEE_SOURCES = {
    "NFO": "https://nsearchives.nseindia.com/content/circulars/FA73061.pdf",
    "BFO": "https://nsearchives.nseindia.com/corporate/BSE_27092024184037_NSEintimation.pdf",
    "tax": "https://www.kotakneo.com/calculator/brokerage-calculator/",
}


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Prices and limits must be finite")
    return result


def validate_settings(values):
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError("Unknown risk setting")
    s = {**DEFAULTS, **values}
    for key in (
        "risk",
        "daily_loss",
        "giveback",
        "premium",
        "spread",
        "slippage",
        "brokerage",
        "cooldown",
    ):
        if s[key] is None and key in ("risk", "daily_loss", "giveback", "premium"):
            continue
        s[key] = number(s[key])
        if s[key] < 0 or (
            key in ("risk", "daily_loss", "giveback", "premium", "spread") and s[key] == 0
        ):
            raise ValueError(f"{key} must be positive")
    if not 0 <= s["cooldown"] <= 86400 or not 0 < s["spread"] <= 20:
        raise ValueError("Invalid cooldown or spread limit")
    try:
        cutoff = datetime.strptime(s["cutoff"], "%H:%M").time()
    except (TypeError, ValueError):
        raise ValueError("Square-off time must be HH:MM") from None
    if not "09:20" <= cutoff.strftime("%H:%M") <= "15:15":
        raise ValueError("Square-off time must be between 09:20 and 15:15 IST")
    return s


def fees(buy, sell, exchange, brokerage=0, day="2026-10-14"):
    """Estimated non-exercise option charges. Brokerage is per order, two orders here."""
    if exchange not in ("NFO", "BFO") or not "2026-04-01" <= day <= "2026-12-31":
        raise ValueError("Verified option fee schedule unavailable for this exchange/date")
    buy, sell, brokerage = number(buy), number(sell), number(brokerage)
    if min(buy, sell, brokerage) < 0:
        raise ValueError("Negative turnover or brokerage")
    turnover = buy + sell
    tx = turnover * (3552.99 if exchange == "NFO" else 3250) / 10_000_000
    ipft = turnover * 0.01 / 10_000_000 if exchange == "NFO" else 0
    sebi = turnover / 1_000_000
    result = {
        "stt": sell * 0.0015,
        "stamp": buy * 0.00003,
        "exchange": tx,
        "sebi": sebi,
        "ipft": ipft,
        "brokerage": 2 * brokerage,
    }
    result["gst"] = 0.18 * (tx + sebi + ipft + result["brokerage"])
    result["total"] = round(sum(result.values()), 2)
    return {k: round(v, 2) for k, v in result.items()}


def snap(value, tick, up=False):
    tick = number(tick)
    if tick <= 0:
        raise ValueError("Tick size unavailable")
    return round((math.ceil if up else math.floor)(round(number(value) / tick, 8)) * tick, 8)


def plan(entry, sl, target, qty, exchange, settings, tick, lot, day="2026-10-14"):
    entry, sl, target = map(number, (entry, sl, target))
    if not 0 < sl < entry < target:
        raise ValueError("For bought CE/PE, SL must be below entry and target above entry")
    if (
        not isinstance(qty, int)
        or isinstance(qty, bool)
        or not isinstance(lot, int)
        or lot <= 0
        or qty <= 0
        or qty % lot
    ):
        raise ValueError("Quantity must be positive whole lots")
    for price in (entry, sl, target):
        if abs(price - snap(price, tick)) > 1e-7:
            raise ValueError("Prices must align with contract tick size")
    s = validate_settings(settings)
    loss_price = max(0, sl - s["slippage"])
    profit_price = max(0, target - s["slippage"])
    stop_fees = fees(entry * qty, loss_price * qty, exchange, s["brokerage"], day)
    target_fees = fees(entry * qty, profit_price * qty, exchange, s["brokerage"], day)
    risk = (entry - loss_price) * qty + stop_fees["total"]
    reward = (profit_price - entry) * qty - target_fees["total"]
    fits = (s["risk"] is None or risk <= s["risk"]) and (
        s["premium"] is None or entry * qty <= s["premium"]
    )
    lot_caps = []
    if s["risk"] is not None:
        lot_caps.append(int(s["risk"] / (risk / (qty / lot))))
    if s["premium"] is not None:
        lot_caps.append(int(s["premium"] / (entry * lot)))
    return {
        "entry": entry,
        "sl": sl,
        "target": target,
        "quantity": qty,
        "risk": round(risk, 2),
        "reward": round(reward, 2),
        "costs": target_fees["total"],
        "fee_breakdown": target_fees,
        "net_rr": round(reward / risk, 2),
        "fits": bool(fits),
        "reason": "" if fits else "Quantity exceeds configured risk or premium budget",
        "max_lots": max(0, min(lot_caps)) if lot_caps else None,
        "fee_verified": "2026-10-14",
        "fee_source": FEE_SOURCES[exchange],
    }


def completed(bars, now, seconds):
    out = {}
    for b in bars:
        try:
            t = number(b.get("time", b.get("timestamp")))
            if t > 1e12:
                t /= 1000
            v = {k: number(b[k]) for k in ("open", "high", "low", "close")}
            if (
                t + seconds <= now
                and min(v.values()) > 0
                and v["low"]
                <= min(v["open"], v["close"])
                <= max(v["open"], v["close"])
                <= v["high"]
            ):
                out[t] = dict(time=t, **v)
        except (ValueError, TypeError, KeyError):
            continue
    return [out[k] for k in sorted(out)]


def atr(bars, period=14):
    if len(bars) < period + 1:
        return None
    tr = [
        max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"]))
        for a, b in zip(bars, bars[1:], strict=False)
    ]
    return sum(tr[-period:]) / period


def zones(bars):
    z = []
    for i in range(2, len(bars) - 2):
        b = bars[i]
        for field, kind in (("high", "high"), ("low", "low")):
            others = [bars[j][field] for j in (i - 2, i - 1, i + 1, i + 2)]
            if b[field] > max(others) if kind == "high" else b[field] < min(others):
                z.append(
                    {
                        "price": b[field],
                        "kind": kind,
                        "known_at": bars[i + 2]["time"] + 300,
                        "source": "Confirmed 5m swing",
                        "touches": 1,
                    }
                )
    tolerance = (atr(bars) or 0) * 0.1
    grouped = []
    for point in z:
        match = next(
            (
                g
                for g in grouped
                if g["kind"] == point["kind"] and abs(g["price"] - point["price"]) <= tolerance
            ),
            None,
        )
        if match:
            match.update(
                touches=match["touches"] + 1,
                known_at=point["known_at"],
                source="Repeated highs/lows",
            )
        else:
            grouped.append(dict(point))
    return grouped


def analyse(one, five, now):
    one, five = completed(one, now, 60), completed(five, now, 300)
    checks = {
        "checked_at": now,
        "one_closed_at": one[-1]["time"] + 60 if one else None,
        "five_closed_at": five[-1]["time"] + 300 if five else None,
        "history": "insufficient",
        "state": "waiting_history",
        "trend": None,
        "pattern_confirmed": False,
        "target_available": False,
        "reward_risk": None,
    }
    levels = zones(five)
    today = datetime.fromtimestamp(now, IST).date()
    prior = [b for b in five if datetime.fromtimestamp(b["time"], IST).date() < today]
    if prior:
        prev_day = datetime.fromtimestamp(prior[-1]["time"], IST).date()
        prior = [b for b in prior if datetime.fromtimestamp(b["time"], IST).date() == prev_day]
        levels += [
            {
                "price": max(b["high"] for b in prior),
                "kind": "high",
                "known_at": prior[-1]["time"] + 300,
                "source": "Previous day high",
                "touches": 1,
            },
            {
                "price": min(b["low"] for b in prior),
                "kind": "low",
                "known_at": prior[-1]["time"] + 300,
                "source": "Previous day low",
                "touches": 1,
            },
        ]
    base = {
        "action": "WAIT",
        "reason": "Waiting for completed-candle confirmation",
        "zones": levels,
        "experimental": True,
        "checks": checks,
    }
    if len(one) < 30 or len(five) < 30 or atr(one) is None or atr(one) <= 0:
        return {**base, "reason": "Insufficient completed history"}
    if now - one[-1]["time"] > 125 or now - (five[-1]["time"] + 300) > 365:
        checks.update(history="stale", state="stale_history")
        return {**base, "reason": "History is stale"}
    if any(b["time"] - a["time"] != 60 for a, b in zip(one[-15:], one[-14:], strict=False)):
        checks.update(history="gap", state="history_gap")
        return {**base, "reason": "Gap in recent 1m candles"}
    checks["history"] = "fresh"
    ema = five[0]["close"]
    prev = ema
    for b in five[1:]:
        prev, ema = ema, ema + (b["close"] - ema) * 2 / 21
    direction = (
        "CALL"
        if five[-1]["close"] > ema > prev
        else "PUT"
        if five[-1]["close"] < ema < prev
        else None
    )
    checks.update(trend=direction or "NEUTRAL", state="waiting_trend")
    if direction is None:
        return {**base, "reason": "5m trend is mixed; waiting for a clear direction"}
    found = []
    c = one[-1]
    checks["target_available"] = any(
        z["kind"] == ("high" if direction == "CALL" else "low")
        and (z["price"] > c["close"] if direction == "CALL" else z["price"] < c["close"])
        for z in levels
    )
    buffer = atr(one) * 0.1
    for z in levels:
        if z["known_at"] > one[-6]["time"]:
            continue
        p = z["price"]
        for i in range(max(1, len(one) - 6), len(one) - 1):
            a = one[i]
            before = one[i - 1]
            if direction == "CALL":
                sweep = a["low"] < p < a["close"] and c["close"] > a["high"] and z["kind"] == "low"
                retest = (
                    before["close"] <= p < a["close"]
                    and c["low"] <= p <= c["close"]
                    and c["close"] > c["open"]
                )
                extreme = a["low"] if sweep else c["low"]
                stop = extreme - buffer
                target = min(
                    (v["price"] for v in levels if v["kind"] == "high" and v["price"] > c["close"]),
                    default=None,
                )
            elif direction == "PUT":
                sweep = a["high"] > p > a["close"] and c["close"] < a["low"] and z["kind"] == "high"
                retest = (
                    before["close"] >= p > a["close"]
                    and c["high"] >= p >= c["close"]
                    and c["close"] < c["open"]
                )
                extreme = a["high"] if sweep else c["high"]
                stop = extreme + buffer
                target = max(
                    (v["price"] for v in levels if v["kind"] == "low" and v["price"] < c["close"]),
                    default=None,
                )
            else:
                continue
            if not (sweep or retest):
                continue
            between = one[i + 1 :]
            if retest and any(
                (b["close"] < p if direction == "CALL" else b["close"] > p) for b in between
            ):
                continue
            if sweep and any(
                (b["close"] < a["low"] if direction == "CALL" else b["close"] > a["high"])
                for b in between
            ):
                continue
            checks["pattern_confirmed"] = True
            if target is None:
                continue
            risk = abs(c["close"] - stop)
            if risk <= 0:
                continue
            reward_risk = abs(target - c["close"]) / risk
            checks["reward_risk"] = max(checks["reward_risk"] or 0, reward_risk)
            if reward_risk < 2:
                continue
            found.append(
                {
                    "action": direction,
                    "reason": "Sweep confirmation" if sweep else "Break and retest",
                    "index_entry": c["close"],
                    "invalidation": stop,
                    "index_target": target,
                    "setup_id": f"{direction}:{p}:{c['time']}",
                    "expires": c["time"] + 120,
                }
            )
    identities = {(x["action"], x["invalidation"]) for x in found}
    if len(identities) > 1:
        checks["state"] = "conflict"
        return {**base, "reason": "Conflicting setups; wait"}
    if found:
        checks["state"] = "confirmed"
        return {**base, **found[0]}
    trend = "Uptrend" if direction == "CALL" else "Downtrend"
    if not checks["target_available"]:
        checks["state"] = "no_target"
        missing = "resistance above" if direction == "CALL" else "support below"
        return {**base, "reason": f"{trend} · no confirmed {missing} price for a 2:1 target"}
    if not checks["pattern_confirmed"]:
        checks["state"] = "waiting_trigger"
        return {**base, "reason": f"{trend} · waiting for a completed 1m sweep or break-and-retest"}
    checks["state"] = "low_reward"
    return {**base, "reason": f"{trend} · less than 2:1 reward/risk to the next confirmed level"}


def fill_time(value):
    if isinstance(value, (int, float)):
        return number(value) / 1000 if value > 1e12 else number(value)
    for fmt in (
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=IST).timestamp()
        except (ValueError, TypeError):
            pass
    try:
        return datetime.fromisoformat(value).replace(tzinfo=IST).timestamp()
    except (ValueError, TypeError):
        raise ValueError("Unrecognized fill timestamp") from None


def journal(fills, positions, day, brokerage=0):
    result = {
        "complete": True,
        "gross_realised": 0.0,
        "charges": 0.0,
        "net_realised": 0.0,
        "cycles": [],
        "fills": [],
        "reason": "",
    }
    inventory = {}
    seen = set()
    try:
        parsed = []
        for f in fills:
            if not f.get("tradeid") or not f.get("orderid"):
                raise ValueError("Missing stable fill IDs")
            identity = (str(f["orderid"]), str(f["tradeid"]))
            if identity in seen:
                continue
            seen.add(identity)
            t = fill_time(f["timestamp"])
            if datetime.fromtimestamp(t, IST).date().isoformat() != day:
                continue
            q = number(f["quantity"])
            p = number(f["average_price"])
            if q <= 0 or int(q) != q or p <= 0 or f.get("action") not in ("BUY", "SELL"):
                raise ValueError("Invalid fill data")
            parsed.append((t, {**f, "quantity": int(q), "average_price": p, "epoch": t}))
        for _, f in sorted(parsed, key=lambda x: (x[0], str(x[1]["tradeid"]))):
            key = (f["symbol"], f["exchange"], f["product"])
            s = inventory.setdefault(
                key, {"q": 0, "buy": 0, "sell": 0, "basis": 0, "start": f["epoch"], "orders": []}
            )
            q = f["quantity"]
            if f["action"] == "BUY":
                if not s["q"]:
                    s["start"] = f["epoch"]
                s["basis"] += q * f["average_price"]
                s["q"] += q
            else:
                if q > s["q"]:
                    raise ValueError(
                        "Carry-in or short position prevents full cycle reconciliation"
                    )
                avg = s["basis"] / s["q"]
                result["gross_realised"] += (f["average_price"] - avg) * q
                s["basis"] -= avg * q
                s["q"] -= q
            s["buy" if f["action"] == "BUY" else "sell"] += q * f["average_price"]
            if f["orderid"] not in s["orders"]:
                s["orders"].append(f["orderid"])
            result["fills"].append(f)
            charge = fees(
                q * f["average_price"] if f["action"] == "BUY" else 0,
                q * f["average_price"] if f["action"] == "SELL" else 0,
                f["exchange"],
                0,
                day,
            )["total"]
            result["charges"] += (
                charge + brokerage * 1.18
                if not any(x["orderid"] == f["orderid"] for x in result["fills"][:-1])
                else charge
            )
            if s["q"] < 0:
                raise ValueError("Carry-in or short position prevents full cycle reconciliation")
            if s["q"] == 0:
                gross = s["sell"] - s["buy"]
                costs = fees(s["buy"], s["sell"], f["exchange"], 0, day)[
                    "total"
                ] + brokerage * 1.18 * len(s["orders"])
                result["cycles"].append(
                    {
                        "symbol": f["symbol"],
                        "exchange": f["exchange"],
                        "gross": round(gross, 2),
                        "net": round(gross - costs, 2),
                        "start": s["start"],
                        "end": f["epoch"],
                        "duration": f["epoch"] - s["start"],
                        "setup": "unclassified",
                    }
                )
                inventory[key] = {
                    "q": 0,
                    "buy": 0,
                    "sell": 0,
                    "basis": 0,
                    "start": f["epoch"],
                    "orders": [],
                }
        actual = {
            (p["symbol"], p["exchange"], p["product"]): int(p["quantity"])
            for p in positions
            if int(p["quantity"]) != 0
        }
        expected = {k: v["q"] for k, v in inventory.items() if v["q"]}
        if actual != expected:
            raise ValueError("Fill quantities and position book do not reconcile")
        result["open_positions"] = [
            {
                "symbol": key[0],
                "exchange": key[1],
                "product": key[2],
                "quantity": value["q"],
                "average_price": value["basis"] / value["q"],
            }
            for key, value in inventory.items()
            if value["q"]
        ]
        result["charges"] = round(result["charges"], 2)
        result["net_realised"] = round(result["gross_realised"] - result["charges"], 2)
    except (ValueError, TypeError, KeyError) as e:
        result.update(
            complete=False, reason=str(e), gross_realised=None, charges=None, net_realised=None
        )
    return result
