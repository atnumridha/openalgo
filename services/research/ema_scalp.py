"""Offline EMA9/15 hypothesis evaluation, not an order or portfolio engine.

All candle indexes denote bar CLOSE in IST. Discretionary video rules are
quantified in the registered plan; index R is distinct from option money P&L.
"""

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from services.research.costs import decimal_value, order_cost
from services.research.replay import _slipped
from services.risk import BreachReason, PositionRisk, evaluate_position


def _validate(frame):
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or frame.index.tz is None
        or not frame.index.is_unique
        or not frame.index.is_monotonic_increasing
    ):
        raise ValueError("Candles require ordered, unique, timezone-aware close timestamps")
    prices = frame[["open", "high", "low", "close"]]
    if (
        not np.isfinite(prices).all().all()
        or (prices <= 0).any().any()
        or (frame.low > frame[["open", "close"]].min(axis=1)).any()
        or (frame.high < frame[["open", "close"]].max(axis=1)).any()
    ):
        raise ValueError("Invalid candle OHLC")


def indicators(frame):
    _validate(frame)
    f = frame.copy()
    previous = f.close.shift()
    tr = pd.concat(
        [f.high - f.low, (f.high - previous).abs(), (f.low - previous).abs()], axis=1
    ).max(axis=1)
    f["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    f["prior_atr"] = f.atr.shift()
    for length in (9, 15):
        f[f"ema{length}"] = f.close.ewm(span=length, adjust=False, min_periods=75).mean()
        f[f"slope{length}"] = f[f"ema{length}"].diff(3) / (3 * f.atr)
    f["prior_high"] = f.high.shift().rolling(20).max()
    f["prior_low"] = f.low.shift().rolling(20).min()
    delta = f.index.to_series().diff() == pd.Timedelta(minutes=5)
    f["ready"] = (delta.rolling(3).sum() == 3) & f.slope15.notna()
    return f


def signals(nifty, bank, *, slope=0.1, confirm=True):
    if slope not in (0.1, 0.2):
        raise ValueError("Only registered slope thresholds are supported")
    f, other = nifty, bank.reindex(nifty.index)
    body, span = f.close - f.open, f.high - f.low
    body_abs = body.abs()
    full = body_abs >= 0.6 * span
    big = (span >= 1.5 * f.prior_atr) & (body_abs >= 0.5 * span)
    lower = f[["open", "close"]].min(axis=1) - f.low
    upper = f.high - f[["open", "close"]].max(axis=1)
    bullish_pin = (lower >= 2 * body_abs) & (f.close >= f.low + 0.75 * span)
    bearish_pin = (upper >= 2 * body_abs) & (f.close <= f.low + 0.25 * span)
    touch = (f.low <= f[["ema9", "ema15"]].max(axis=1)) & (
        f.high >= f[["ema9", "ema15"]].min(axis=1)
    )
    up = (f.ema9 > f.ema15) & (f.slope9 >= slope) & (f.slope15 >= slope)
    down = (f.ema9 < f.ema15) & (f.slope9 <= -slope) & (f.slope15 <= -slope)
    buy = up & touch & (body > 0) & (f.close > f.ema9) & (full | big | bullish_pin)
    sell = down & touch & (body < 0) & (f.close < f.ema9) & (full | big | bearish_pin)
    if confirm:
        resistance = other.prior_high - other.close
        support = other.close - other.prior_low
        bank_ready = other.ready.eq(True) & other.prior_high.notna() & other.prior_low.notna()
        buy &= (
            bank_ready
            & (other.ema9 > other.ema15)
            & (other.slope9 >= slope)
            & (other.slope15 >= slope)
            & ~resistance.between(0, 0.5 * other.atr)
        )
        sell &= (
            bank_ready
            & (other.ema9 < other.ema15)
            & (other.slope9 <= -slope)
            & (other.slope15 <= -slope)
            & ~support.between(0, 0.5 * other.atr)
        )
    out = f[["open", "high", "low", "close", "ema9", "ema15", "slope9", "slope15", "atr"]].copy()
    out["direction"] = np.where(buy & f.ready, "CE", np.where(sell & f.ready, "PE", ""))
    return out


def chart_outcome(signal, minute_bars, hold_minutes):
    """One hypothetical index trade, with shared risk-core stop/target decisions."""
    if hold_minutes not in (5, 10, 15) or signal["direction"] not in ("CE", "PE"):
        raise ValueError("Unsupported scalp direction or duration")
    at = pd.Timestamp(signal["timestamp"])
    deadline = at + pd.Timedelta(minutes=hold_minutes)
    result = dict(
        signal,
        day=at.strftime("%Y-%m-%d"),
        hold_minutes=hold_minutes,
        r=None,
        points=None,
        ambiguous=False,
        entered=False,
    )
    if at.tzinfo is None or deadline.strftime("%H:%M") > "15:25" or at.date() != deadline.date():
        return result | {"reason": "outside_session"}
    expected = pd.date_range(at + pd.Timedelta(minutes=1), deadline, freq="min")
    if expected[0] not in minute_bars.index:
        return result | {"reason": "missing_entry"}
    sign = 1 if signal["direction"] == "CE" else -1
    entry = float(minute_bars.loc[expected[0], "open"])
    stop = float(signal.get("stop_price", signal["low"] if sign == 1 else signal["high"]))
    reward = signal.get("reward_multiple", 2)
    if reward not in (1.5, 2, 3) or not np.isfinite(stop) or stop <= 0:
        raise ValueError("Unsupported reward multiple or stop")
    distance = sign * (entry - stop)
    if distance <= 0:
        return result | {"reason": "entry_through_stop"}
    target = entry + sign * reward * distance
    risk = PositionRisk(
        entry_price=entry,
        quantity=1,
        side="BUY" if sign == 1 else "SELL",
        stop_price=stop,
        target_price=target,
    )
    result.update(
        entry_at=at.isoformat(), entry_price=entry, stop=stop, target=target, entered=True
    )
    for timestamp in expected:
        if timestamp not in minute_bars.index:
            return result | {"reason": "missing_minute"}
        bar = minute_bars.loc[timestamp]
        reason = evaluate_position(risk, bar.open).reason
        price, ambiguous = float(bar.open), False
        if reason not in (BreachReason.STOP, BreachReason.TARGET):
            adverse, favorable = (bar.low, bar.high) if sign == 1 else (bar.high, bar.low)
            stopped = evaluate_position(risk, adverse).reason == BreachReason.STOP
            won = evaluate_position(risk, favorable).reason == BreachReason.TARGET
            if stopped:
                price, reason, ambiguous = stop, "sl", won
            elif won:
                price, reason = target, "target"
            elif timestamp == deadline:
                price, reason = float(bar.close), "time"
            else:
                continue
        points = sign * (price - entry)
        return result | {
            "reason": str(reason),
            "exit_at": timestamp.isoformat(),
            "exit_price": price,
            "points": points,
            "r": points / distance,
            "ambiguous": bool(ambiguous),
        }
    raise AssertionError("A complete horizon must terminate")


def summarize(records):
    completed = [r for r in records if r["r"] is not None]
    n = len(completed)
    wins = sum(r["r"] > 0 for r in completed)
    ambiguous = sum(r["ambiguous"] for r in completed)
    result = {
        "attempts": len(records),
        "completed": n,
        "unresolved": len(records) - n,
        "wins": wins,
        "win_rate": wins / n if n else None,
        "target_hits": sum(r["reason"] == "target" for r in completed),
        "target_rate": sum(r["reason"] == "target" for r in completed) / n if n else None,
        "time_exits": sum(r["reason"] == "time" for r in completed),
        "stop_exits": sum(r["reason"] == "sl" for r in completed),
        "ambiguous": ambiguous,
        "ambiguity_optimistic_win_rate": (wins + ambiguous) / n if n else None,
        "wins_over_all_attempts": wins / len(records) if records else None,
        "mean_r": float(np.mean([r["r"] for r in completed])) if n else None,
        "gross_index_points": sum(r["points"] for r in completed),
        "win_rate_day_block_95": None,
    }
    if n:
        table = pd.DataFrame(completed)
        daily = (
            table.assign(win=table.r > 0).groupby("day").agg(wins=("win", "sum"), n=("win", "size"))
        )
        count, length = len(daily), 5
        if count < 10:
            result["interval_unavailable_reason"] = "fewer_than_two_five_day_blocks"
            return result
        rng = np.random.default_rng(42)
        starts = rng.integers(0, count - length + 1, size=(2000, int(np.ceil(count / length))))
        indexes = (starts[..., None] + np.arange(length)).reshape(2000, -1)[:, :count]
        samples = daily.wins.to_numpy()[indexes].sum(axis=1) / daily.n.to_numpy()[indexes].sum(
            axis=1
        )
        result["win_rate_day_block_95"] = np.quantile(samples, [0.025, 0.975]).tolist()
    return result


def select_itm(quotes, listing, *, spot, direction, day):
    candidates = []
    for row in quotes.to_dict("records"):
        expiry, strike, kind = str(row["expiry"]), float(row["strike"]), row["option_type"]
        metadata = listing.get((expiry, strike, kind))
        if kind != direction or not metadata or not metadata.get("lot_size"):
            continue
        if not 1 <= (date.fromisoformat(expiry) - date.fromisoformat(day)).days <= 7:
            continue
        if not (strike < spot if direction == "CE" else strike > spot):
            continue
        lot = int(metadata["lot_size"])
        if row["volume"] < 10 * lot or row["close"] <= 0:
            continue
        candidates.append(row | {"lot_size": lot, "multiplier": 1, "tick_size": 0.05})
    return (
        min(candidates, key=lambda r: (r["expiry"], abs(r["strike"] - spot), r["strike"]))
        if candidates
        else None
    )


def option_outcome(trade, minutes, contract, costs, *, capital=10000):
    available = decimal_value(capital, "capital", minimum=1) * Decimal(".80")
    if trade["r"] is None:
        return {"reason": "unresolved_index_exit"}
    start, end = pd.Timestamp(trade["timestamp"]), pd.Timestamp(trade["exit_at"])
    expected = pd.date_range(
        start + pd.Timedelta(minutes=1), end + pd.Timedelta(minutes=1), freq="min"
    )
    if not minutes.index.is_unique or not expected.isin(minutes.index).all():
        return {"reason": "missing_or_untradeable_minute"}
    bars = minutes.loc[expected]
    try:
        _validate(bars)
    except ValueError:
        return {"reason": "missing_or_untradeable_minute"}
    if not np.isfinite(bars.volume).all() or (bars.volume <= 0).any():
        return {"reason": "missing_or_untradeable_minute"}
    slip = costs["slippage_bps"] / 10000
    entry = _slipped(bars.iloc[0].open, slip, contract, buy=True)
    exit_price = _slipped(bars.iloc[-1].open, slip, contract)
    units = contract["lot_size"] * contract["multiplier"]
    premium = Decimal(str(entry)) * units
    proceeds = Decimal(str(exit_price)) * units
    entry_fees = order_cost(premium, "BUY", costs)
    fees = entry_fees + order_cost(proceeds, "SELL", costs)
    net = (proceeds - premium - fees).quantize(Decimal(".01"))
    return {
        "reason": "priced",
        "entry_price": entry,
        "exit_price": exit_price,
        "entry_fill_at": start.isoformat(),
        "exit_fill_at": end.isoformat(),
        "units": units,
        "premium_with_entry_fees": float(premium + entry_fees),
        "affordable": premium + entry_fees <= available,
        "gross_pnl": float(proceeds - premium),
        "costs": float(fees),
        "net_pnl": float(net),
    }
