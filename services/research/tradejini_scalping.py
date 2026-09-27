"""Offline Tradejini adaptations with native long-option premium barriers."""

from decimal import Decimal

import numpy as np
import pandas as pd

from services.research.costs import order_cost
from services.research.ema_scalp import _validate
from services.research.ig_scalping import bars_from_minutes
from services.research.replay import _slipped
from services.risk.models import PositionRisk
from services.risk.position import evaluate_position


def tradejini_signals(minutes, timeframe, family):
    _validate(minutes)
    if timeframe not in (1, 3) or family not in ("ema921", "box"):
        raise ValueError("Unregistered timeframe or family")
    f = minutes.copy() if timeframe == 1 else bars_from_minutes(minutes, timeframe)
    f["direction"] = ""
    body = f.close - f.open
    strong = body.abs().ge((f.high - f.low) * 0.5) & f.high.gt(f.low)
    ready = f.index.to_series().diff().eq(pd.Timedelta(minutes=timeframe)).rolling(3).sum().eq(3)
    if family == "ema921":
        f["ema9"] = f.close.ewm(span=9, adjust=False).mean()
        f["ema21"] = f.close.ewm(span=21, adjust=False).mean()
        gap = (f.ema9 - f.ema21).round(8)
        gate = ready & strong & (np.arange(len(f)) >= 104)
        buy = gap.gt(0) & gap.shift().le(0) & f.close.gt(f.ema9) & f.close.gt(f.ema21)
        sell = gap.lt(0) & gap.shift().ge(0) & f.close.lt(f.ema9) & f.close.lt(f.ema21)
        f.loc[gate & buy & body.gt(0), "direction"] = "CE"
        f.loc[gate & sell & body.lt(0), "direction"] = "PE"
    else:
        # Only closed range minutes and the first subsequent breakout are observable.
        for day, part in minutes.groupby(minutes.index.tz_convert("Asia/Kolkata").date):
            start = pd.Timestamp(f"{day} 09:16", tz="Asia/Kolkata")
            expected = pd.date_range(start, periods=15, freq="min")
            if not expected.isin(part.index).all():
                continue
            box = part.loc[expected]
            high, low = float(box.high.max()), float(box.low.min())
            if high - low < 20:
                continue
            end = start + pd.Timedelta(minutes=14)
            window = f.loc[(f.index > end) & (f.index <= end + pd.Timedelta(minutes=15))]
            broken = window[(window.close > high) | (window.close < low)]
            if broken.empty:
                continue
            at, row = broken.index[0], broken.iloc[0]
            prefix = pd.date_range(
                end + pd.Timedelta(minutes=timeframe), at, freq=f"{timeframe}min"
            )
            if not prefix.isin(f.index).all():
                continue
            if ready.loc[at] and strong.loc[at]:
                if row.close > high and body.loc[at] > 0:
                    f.loc[at, "direction"] = "CE"
                elif row.close < low and body.loc[at] < 0:
                    f.loc[at, "direction"] = "PE"
    return f


def select_atm(quotes, listing, spot, direction, day):
    """Rank only observed, listed contracts; caller supplies completed quotes."""
    candidates = []
    for row in quotes.to_dict("records"):
        key = (row["expiry"], float(row["strike"]), row["option_type"])
        record = listing.get(key)
        if not record or row["option_type"] != direction:
            continue
        dte = (pd.Timestamp(row["expiry"]) - pd.Timestamp(day)).days
        lot = int(record["lot_size"])
        if not 0 <= dte <= 7 or lot <= 0:
            continue
        if not np.isfinite(row["close"]) or row["close"] <= 0 or not np.isfinite(row["volume"]):
            continue
        if row["volume"] < lot * 10:
            continue
        candidates.append(row | {"lot_size": lot})
    return min(
        candidates, key=lambda r: (r["expiry"], abs(r["strike"] - spot), r["strike"]), default=None
    )


def _valid(row):
    values = [float(row[c]) for c in ("open", "high", "low", "close", "volume")]
    opening, high, low, closing, volume = values
    return (
        all(np.isfinite(values))
        and min(values) > 0
        and low <= min(opening, closing) <= max(opening, closing) <= high
    )


def premium_outcome(bars, at, hold, units, costs, *, premium_budget=20000, risk_budget=1000):
    """Bars indexed by option minute OPEN. Entry/exit fees and adverse slippage."""
    at = pd.Timestamp(at)
    if hold not in (5, 10, 15) or units <= 0 or at.tzinfo is None:
        raise ValueError("Invalid registered execution inputs")
    base = {"entered": False, "affordable": False, "net_pnl": None}
    if at not in bars.index or isinstance(bars.loc[at], pd.DataFrame) or not _valid(bars.loc[at]):
        return base | {"reason": "missing_entry"}
    contract = {"tick_size": 0.05}
    slip = costs["slippage_bps"] / 10000
    entry = Decimal(str(_slipped(bars.loc[at, "open"], slip, contract, buy=True)))
    stop, target = entry - Decimal(10), entry + Decimal(20)
    if stop <= 0:
        return base | {"reason": "nonpositive_stop"}
    entry_fee = order_cost(entry * units, "BUY", costs)
    funding = entry * units + entry_fee
    stopped = Decimal(str(_slipped(stop, slip, contract)))
    planned_loss = (
        (entry - stopped) * units + entry_fee + order_cost(stopped * units, "SELL", costs)
    )
    base |= {
        "entry_price": float(entry),
        "stop": float(stop),
        "target": float(target),
        "units": int(units),
        "premium_with_entry_fees": float(funding),
        "planned_loss": float(planned_loss),
        "entry_fee": float(entry_fee),
    }
    if funding > premium_budget:
        return base | {"reason": "unaffordable"}
    if planned_loss > risk_budget:
        return base | {"reason": "planned_risk_exceeded"}
    base |= {"entered": True, "affordable": True}
    risk = PositionRisk(
        side="BUY",
        entry_price=float(entry),
        quantity=units,
        stop_price=float(stop),
        target_price=float(target),
    )
    deadline = at + pd.Timedelta(minutes=hold)
    for when in pd.date_range(at, deadline, freq="min"):
        if (
            when not in bars.index
            or isinstance(bars.loc[when], pd.DataFrame)
            or not _valid(bars.loc[when])
        ):
            return base | {"reason": "missing_path", "locked_until": deadline.isoformat()}
        row = bars.loc[when]
        ambiguous = False
        exit_at = when
        opening = evaluate_position(risk, row.open)
        if opening.breached:
            reason = opening.reason.value
            price = float(target) if reason == "target" else float(row.open)
        elif when == deadline:
            reason, price = "time", float(row.open)
        else:
            low, high = evaluate_position(risk, row.low), evaluate_position(risk, row.high)
            if low.breached:
                reason, price = low.reason.value, float(stop)
                ambiguous = high.breached
            elif high.breached:
                reason, price = high.reason.value, float(target)
            else:
                continue
            exit_at = when + pd.Timedelta(minutes=1)
        exit_price = Decimal(str(_slipped(price, slip, contract)))
        exit_fee = order_cost(exit_price * units, "SELL", costs)
        gross = (exit_price - entry) * units
        return base | {
            "reason": "priced",
            "exit_reason": reason,
            "exit_at": exit_at.isoformat(),
            "exit_bar": when.isoformat(),
            "exit_price": float(exit_price),
            "exit_fee": float(exit_fee),
            "gross_pnl": float(gross),
            "net_pnl": float(gross - entry_fee - exit_fee),
            "ambiguous": bool(ambiguous),
        }
    raise AssertionError("Deadline exit was not evaluated")
