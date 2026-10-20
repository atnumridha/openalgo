"""Transcript-inspired, explicitly parameterized extra-confirmation rules.

Pure functions shared by server analysis, recorded-event replay and execution.
No account calls, side effects or implied probability of success.
"""

import hashlib
import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR
from decimal import Decimal as D

VERSION = "liquidity-extra-confirmation-v1"
ACTIVE = {"FIRST_BUYER", "COUNTERATTACK", "RENEWED_CONFIRMATION", "WATCHING", "TRIGGERED"}


@dataclass(frozen=True)
class Config:
    leverage: int = 5
    max_quantity: int = 1
    max_risk: float = 1
    max_margin: float = 25
    max_notional: float = 1000
    daily_loss: float = 3
    max_trades: int = 3
    slippage: float = 0.10
    min_net_rr: float = 1.5
    counter_atr: float = 0.5
    expiry_bars: int = 10
    shorts: bool = False
    entry_mode: str = "review"
    mode: str = "paper"
    manual_level: float = 0
    manual_side: str = "Low"
    manual_target: float = 0
    max_hold_seconds: int = 1740

    def __post_init__(self):
        for k, v in self.__dict__.items():
            if isinstance(v, (int, float)) and not math.isfinite(v):
                raise ValueError(f"{k} must be finite")
        for k, lo, hi in [
            ("leverage", 1, 200),
            ("max_quantity", 1, 1000),
            ("max_trades", 1, 100),
            ("expiry_bars", 3, 60),
            ("max_hold_seconds", 60, 1740),
        ]:
            v = getattr(self, k)
            if type(v) is not int or not lo <= v <= hi:
                raise ValueError(f"{k} must be a whole number between {lo} and {hi}")
        if not (
            0 < self.max_risk <= 100
            and 0 < self.max_margin <= 1000
            and 0 < self.max_notional <= 10000
            and 0 < self.daily_loss <= 500
            and 0.1 <= self.slippage <= 100
            and 1 <= self.min_net_rr <= 10
            and 0.1 <= self.counter_atr <= 3
            and self.manual_level >= 0
            and self.manual_target >= 0
        ):
            raise ValueError("Risk, costs or strategy settings are outside supported bounds")
        if (
            self.entry_mode not in ("review", "auto")
            or self.mode not in ("paper", "live")
            or type(self.shorts) is not bool
            or self.manual_side not in ("Low", "High")
        ):
            raise ValueError("Invalid direction or execution mode")


def valid(b):
    return (
        all(math.isfinite(float(b[k])) for k in ("time", "open", "high", "low", "close"))
        and b["time"] % 60 == 0
        and 0 < b["low"] <= min(b["open"], b["close"])
        and b["high"] >= max(b["open"], b["close"])
    )


def advance(state, bars, references, quote, cfg, now):
    """Consume closed bars once and trigger only on consecutive observed quotes.

    A cold start seeds the cursor at the latest closed bar. Historical crossings
    are never submitted as new entries. Reconnects longer than five seconds
    invalidate a candidate; the next poll cannot manufacture a crossing.
    """
    bars = [b for b in bars if b["time"] + 60 <= now]
    if not bars or any(not valid(b) for b in bars):
        raise ValueError("Valid completed one-minute candles required")
    if any(b["time"] != a["time"] + 60 for a, b in zip(bars, bars[1:], strict=False)):
        if state.get("candidate"):
            state["candidate"]["stage"] = "DATA_GAP"
        state["last_bar"] = bars[-1]["time"]
        state.pop("previous_price", None)
        return state
    if "last_bar" not in state:
        state["last_bar"] = bars[-1]["time"]
    c = state.get("candidate")
    if c and c["stage"] in ACTIVE and state.get("observed_at") is not None:
        if not 0 <= now - state["observed_at"] <= 5:
            c["stage"] = "DATA_GAP"
    used = state.setdefault("used", [])
    for i, b in enumerate(bars):
        if b["time"] <= state["last_bar"]:
            continue
        if b["time"] != state["last_bar"] + 60 and c and c["stage"] in ACTIVE:
            c["stage"] = "DATA_GAP"
        state["last_bar"] = b["time"]
        if c and c["stage"] in ACTIVE and b["time"] + 60 >= c["expires"]:
            c["stage"] = "EXPIRED"
        if not c or c["stage"] not in ACTIVE:
            candidates = [
                r
                for r in references
                if r["id"] not in used
                and r["known"] <= b["time"]
                and (r.get("retired_at") is None or b["time"] <= r["retired_at"])
                and (r["side"] == "Low" or cfg.shorts)
                and i > 0
                and (
                    bars[i - 1]["close"] >= r["price"] >= b["low"]
                    if r["side"] == "Low"
                    else bars[i - 1]["close"] <= r["price"] <= b["high"]
                )
            ]
            candidates.sort(key=lambda r: (abs(r["price"] - b["open"]), -r["known"], r["id"]))
            if candidates:
                r = candidates[0]
                ident = f"{VERSION}:{r['id']}:{b['time']}"
                c = {
                    "id": hashlib.sha256(ident.encode()).hexdigest()[:24],
                    "reference": dict(r),
                    "direction": "LONG" if r["side"] == "Low" else "SHORT",
                    "stage": "FIRST_BUYER",
                    "touched_at": b["time"],
                    "expires": b["time"] + (cfg.expiry_bars + 1) * 60,
                    "extreme": b["low"] if r["side"] == "Low" else b["high"],
                    "version": VERSION,
                }
                state["candidate"] = c
                used.append(r["id"])
                state["used"] = used[-256:]
        if not c or c["stage"] not in ACTIVE:
            continue
        long = c["direction"] == "LONG"
        sign = 1 if long else -1
        if c["stage"] in ("WATCHING", "TRIGGERED") and b["time"] >= c["confirmed_at"]:
            if b["low"] <= c["extreme"] if long else b["high"] >= c["extreme"]:
                c["stage"] = "INVALIDATED"
                continue
            if b["high"] >= c["target"] if long else b["low"] <= c["target"]:
                c["stage"] = "TARGET_TAKEN"
                continue
        if c["stage"] not in ("WATCHING", "TRIGGERED"):
            c["extreme"] = (min if long else max)(c["extreme"], b["low"] if long else b["high"])
        prior = bars[max(1, i - 14) : i]
        if len(prior) < 13:
            continue
        tr = [
            max(
                x["high"] - x["low"],
                abs(x["high"] - bars[j - 1]["close"]),
                abs(x["low"] - bars[j - 1]["close"]),
            )
            for j, x in enumerate(bars[:i])
            if j >= max(1, i - 14)
        ]
        atr = sum(tr) / len(tr)
        directional = sign * (b["close"] - b["open"]) > 0
        if c["stage"] == "FIRST_BUYER" and directional:
            c.update(stage="COUNTERATTACK", first=dict(b), atr=atr)
        elif c["stage"] == "COUNTERATTACK" and b["time"] > c["first"]["time"]:
            if (
                sign * (b["close"] - b["open"]) < 0
                and sign * (b["close"] - c["first"]["open"]) < 0
                and abs(b["close"] - b["open"]) >= cfg.counter_atr * atr
            ):
                c.update(stage="RENEWED_CONFIRMATION", counter=dict(b))
        elif c["stage"] == "RENEWED_CONFIRMATION" and directional:
            boundary = c["counter"]["high" if long else "low"]
            if sign * (b["close"] - boundary) > 0:
                trigger = b["high" if long else "low"]
                opposing = [
                    r["price"]
                    for r in references
                    if r["known"] <= b["time"] + 60
                    and (r.get("retired_at") is None or r["retired_at"] > b["time"])
                    and r["side"] == ("High" if long else "Low")
                    and sign * (r["price"] - trigger) > 0
                ]
                if cfg.manual_target > 0 and sign * (cfg.manual_target - trigger) > 0:
                    opposing.append(cfg.manual_target)
                target = (min if long else max)(opposing) if opposing else None
                c.update(
                    stage="WATCHING" if target else "NO_TARGET",
                    trigger=trigger,
                    target=target,
                    confirmed_at=b["time"] + 60,
                    signal=dict(b),
                    atr=atr,
                )
    bid, ask = float(quote["bid"]), float(quote["ask"])
    fresh = (
        all(math.isfinite(v) for v in (bid, ask, quote["time"]))
        and 0 < bid < ask
        and 0 <= now - quote["time"] <= 3
    )
    if not fresh or now - (bars[-1]["time"] + 60) > 75:
        state.pop("previous_price", None)
        if c and c["stage"] in ACTIVE:
            c["stage"] = "DATA_GAP"
        return state
    price = bid if not c or c["direction"] == "LONG" else ask
    if c and c["stage"] in ("WATCHING", "TRIGGERED"):
        sign = 1 if c["direction"] == "LONG" else -1
        if now >= c["expires"]:
            c["stage"] = "EXPIRED"
        elif sign * (price - c["extreme"]) <= 0:
            c["stage"] = "INVALIDATED"
        elif sign * (price - c["target"]) >= 0:
            c["stage"] = "TARGET_TAKEN"
        elif c["stage"] == "WATCHING" and now >= c["confirmed_at"]:
            previous = state.get("previous_price")
            if (
                previous is not None
                and state.get("quote_candidate") == c["id"]
                and sign * (previous - c["trigger"]) <= 0
                and sign * (price - c["trigger"]) > 0
            ):
                c.update(stage="TRIGGERED", triggered_at=now)
    state.update(previous_price=price, observed_at=now, quote_candidate=c["id"] if c else None)
    return state


def plan_order(c, q, product, cfg, now, collateral):
    """Fees include GST. No promotional fee waiver is assumed."""

    def blocked(reason):
        return {"blocked": reason}

    if not c or c["stage"] != "TRIGGERED":
        return blocked("Waiting for a fresh trigger")
    if not 0 <= now - c["triggered_at"] <= 15 or now >= c["expires"]:
        return blocked("Entry window expired")
    if not 0 <= now - q["time"] <= 3:
        return blocked("Executable quote is stale")
    cv, tick, maker, taker = (
        D(str(product[k]))
        for k in ("contract_value", "tick_size", "maker_commission_rate", "taker_commission_rate")
    )
    if (
        not all(x.is_finite() for x in (cv, tick, maker, taker))
        or min(cv, tick) <= 0
        or min(maker, taker) < 0
    ):
        return blocked("Product metadata unavailable")
    sign = 1 if c["direction"] == "LONG" else -1

    def rounded(x, up=False):
        return (D(str(x)) / tick).to_integral_value(
            rounding=ROUND_CEILING if up else ROUND_FLOOR
        ) * tick

    bid, ask = D(str(q["bid"])), D(str(q["ask"]))
    if not (bid.is_finite() and ask.is_finite() and 0 < bid < ask):
        return blocked("Invalid spread")
    if ask - bid > max(tick * 2, D(str(c["atr"])) * D(".15")):
        return blocked("Spread is too wide")
    entry = rounded(bid if sign > 0 else ask, sign < 0)
    if not 0 < sign * (entry - D(str(c["trigger"]))) <= D(str(c["atr"])) * D(".25"):
        return blocked("Price left the entry zone; do not chase")
    stop = rounded(D(str(c["extreme"])) - sign * tick, sign < 0)
    target = rounded(c["target"], sign < 0)
    risk = sign * (entry - stop)
    if min(stop, target) <= 0 or risk <= 0 or sign * (target - entry) <= risk:
        return blocked("Insufficient target room")
    reserve = D(str(cfg.slippage))
    available = D(str(collateral))
    if not available.is_finite() or available <= 0:
        return blocked("Available collateral unverified")
    for qty in range(cfg.max_quantity, 0, -1):
        units = cv * qty
        notion = entry * units
        margin = notion / cfg.leverage
        try:
            mm = D(str(product["maintenance_margin"])) / 100
            scale = D(str(product["maintenance_margin_scaling_factor"])) / 100
            im = D(str(product["initial_margin"]))
            penalty = D(str(product["product_specs"]["isolated_liq_penalty_factor"]))
            if not all(x.is_finite() and x >= 0 for x in (mm, scale, im, penalty)) or im <= 0:
                return blocked("Liquidation metadata unavailable")
            headroom = entry * (
                D(1) / cfg.leverage - mm - scale * notion - maker * D("1.18") - penalty
            )
            if cfg.leverage > 100 / im or headroom <= 0 or risk > headroom / 2:
                return blocked("Stop lacks conservative liquidation room at this leverage")
        except (KeyError, TypeError):
            return blocked("Liquidation metadata unavailable")
        entry_cost = notion * maker * D("1.18")
        loss = risk * units + entry_cost + stop * units * taker * D("1.18") + reserve
        partial = qty // 2
        first = rounded(entry + sign * risk, sign > 0)
        if sign * (target - first) <= 0:
            partial = 0
        partial_net = (
            sign * (first - entry) * cv * partial
            - (entry * maker + first * taker) * D("1.18") * cv * partial
            - reserve
        )
        if partial_net <= 0:
            partial = 0
        revenue = sign * ((first - entry) * partial + (target - entry) * (qty - partial)) * cv
        fees = entry_cost + (first * partial + target * (qty - partial)) * cv * taker * D("1.18")
        reward = revenue - fees - reserve
        if (
            loss <= D(str(cfg.max_risk))
            and margin <= D(str(cfg.max_margin))
            and margin + entry_cost <= available
            and notion <= D(str(cfg.max_notional))
            and reward >= loss * D(str(cfg.min_net_rr))
        ):
            return {
                "setup_id": c["id"],
                "side": "buy" if sign > 0 else "sell",
                "quantity": qty,
                "leverage": cfg.leverage,
                "entry": float(entry),
                "stop": float(stop),
                "target": float(target),
                "partial_quantity": partial,
                "partial_target": float(first),
                "net_risk": float(loss),
                "net_target": float(reward),
                "margin": float(margin),
                "estimated_fees": float(fees),
                "slippage_reserve": float(reserve),
            }
    return blocked("No whole-contract size fits loss, margin and net reward/risk limits")
