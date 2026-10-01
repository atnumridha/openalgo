"""Local-only, causal 3-minute EMA option paper research.

Input candles are minute OPEN timestamps. Signals use completed 3-minute
candles and execute at the immediately following observed minute open. These
are modeled fills, not broker executions or evidence of executable liquidity.
"""

from dataclasses import dataclass
from datetime import time
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import numpy as np
import pandas as pd
from openalgo import ta

from services.research.costs import (
    decimal_value,
    order_cost,
    validate_cost_dates,
    validate_cost_schedule,
)

IST = "Asia/Kolkata"
MINUTE = pd.Timedelta(minutes=1)
THREE_MINUTES = pd.Timedelta(minutes=3)
OHLCV = ["open", "high", "low", "close", "volume"]
SIGNAL_COLUMNS = ["stop", "ema9", "ema20", "direction", "close"]


def _clock(value, name):
    try:
        result = time.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be HH:MM") from None
    if len(value) != 5 or result.second or result.tzinfo:
        raise ValueError(f"{name} must be HH:MM")
    return result


@dataclass(frozen=True)
class PaperConfig:
    lot_size: int
    tick_size: float
    capital: float = 15000
    max_trade_loss: float = 500
    max_daily_loss: float = 1500
    cooldown_minutes: int = 5
    entry_start: str = "09:30"
    entry_cutoff: str = "15:00"
    flatten_at: str = "15:20"

    def __post_init__(self):
        if (
            isinstance(self.lot_size, bool)
            or not isinstance(self.lot_size, int)
            or self.lot_size < 1
        ):
            raise ValueError("lot_size must be a positive integer")
        for name in ("tick_size", "capital", "max_trade_loss", "max_daily_loss"):
            decimal_value(getattr(self, name), name, minimum="0.000001")
        if (
            isinstance(self.cooldown_minutes, bool)
            or not isinstance(self.cooldown_minutes, int)
            or self.cooldown_minutes < 0
        ):
            raise ValueError("cooldown_minutes must be a nonnegative integer")
        opening = _clock(self.entry_start, "entry_start")
        cutoff = _clock(self.entry_cutoff, "entry_cutoff")
        flatten = _clock(self.flatten_at, "flatten_at")
        if not time(9, 15) <= opening < cutoff <= flatten <= time(15, 40):
            raise ValueError("Entry window and flatten time must fit the regular session")


def _frame(frame):
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("Candles require a DataFrame with a DatetimeIndex")
    if frame.index.tz is None or frame.index.hasnans:
        raise ValueError("Candle timestamps must be timezone aware")
    if frame.index.has_duplicates:
        raise ValueError("duplicate candle timestamps")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("Candle timestamps must be ordered")
    if not set(OHLCV) <= set(frame.columns):
        raise ValueError("Candles require open, high, low, close and volume")
    result = frame[OHLCV].copy()
    result.index = result.index.tz_convert(IST)
    if any(at.second or at.microsecond or at.nanosecond for at in result.index):
        raise ValueError("Candle timestamps must be minute aligned")
    return result


def prepare_minutes(frame, as_of):
    """Validate closed regular-session candles; never complete a forming bar."""
    result = _frame(frame)
    at = pd.Timestamp(as_of)
    if at.tzinfo is None or pd.isna(at):
        raise ValueError("as_of must be a timezone-aware timestamp")
    at = at.tz_convert(IST)
    closed = result.index + MINUTE <= at
    regular = np.array([time(9, 15) <= t.time() < time(15, 40) for t in result.index], dtype=bool)
    quality = {
        "input_minutes": len(result),
        "forming_minutes": int((~closed).sum()),
        "non_regular_minutes": int((~regular).sum()),
    }
    result = result.loc[closed & regular].copy()
    for column in OHLCV:
        if result[column].map(lambda value: isinstance(value, (bool, np.bool_))).any():
            raise ValueError(f"{column} must be numeric")
        try:
            result[column] = pd.to_numeric(result[column], errors="raise").astype(float)
        except (TypeError, ValueError):
            raise ValueError(f"{column} must contain finite positive values") from None
        if not np.isfinite(result[column]).all() or (result[column] <= 0).any():
            raise ValueError(f"{column} must contain finite positive values")
    if (result["high"] < result[["open", "close", "low"]].max(axis=1)).any() or (
        result["low"] > result[["open", "close", "high"]].min(axis=1)
    ).any():
        raise ValueError("Invalid OHLC bounds")
    quality["closed_regular_minutes"] = len(result)
    quality["missing_minutes"] = sum(
        max(0, int((b - a) / MINUTE) - 1)
        for a, b in zip(result.index[:-1], result.index[1:], strict=True)
        if a.date() == b.date()
    )
    result.attrs["quality"] = quality
    return result


def _all_closed(frame):
    # Replay's caller has already fixed as_of; this validates the supplied slice.
    end = frame.index[-1] + MINUTE if len(frame) else pd.Timestamp("2000-01-01", tz=IST)
    return prepare_minutes(frame, end)


def aggregate_3m(frame):
    """Return exact, contiguous 3m buckets indexed by their CLOSE timestamp."""
    frame = _all_closed(frame)
    groups = {}
    for at, row in frame.iterrows():
        opening = at.normalize() + pd.Timedelta(hours=9, minutes=15)
        bucket = opening + (int((at - opening) / MINUTE) // 3) * THREE_MINUTES
        groups.setdefault(bucket, []).append((at, row))
    rows, index = [], []
    for opening, bucket in groups.items():
        if len(bucket) != 3 or [item[0] for item in bucket] != [
            opening + n * MINUTE for n in range(3)
        ]:
            continue
        values = [item[1] for item in bucket]
        rows.append(
            [
                values[0]["open"],
                max(r["high"] for r in values),
                min(r["low"] for r in values),
                values[-1]["close"],
                sum(r["volume"] for r in values),
            ]
        )
        index.append(opening + THREE_MINUTES)
    return pd.DataFrame(
        rows, columns=OHLCV, index=pd.DatetimeIndex(index, tz=IST, name="timestamp"), dtype=float
    )


def _indicators(frame):
    bars = aggregate_3m(frame)
    for column in ("ema9", "ema20", "stop", "direction"):
        bars[column] = np.nan
    segments, segment = [], []
    previous = None
    for at in bars.index:
        broken = previous is not None and (
            (previous.date() == at.date() and at - previous != THREE_MINUTES)
            or (
                previous.date() != at.date()
                and (previous.time() != time(15, 39) or at.time() != time(9, 18))
            )
        )
        if broken:
            segments.append(segment)
            segment = []
        segment.append(at)
        previous = at
    if segment:
        segments.append(segment)
    bars["ready"] = False
    bars["segment"] = -1
    for number, timestamps in enumerate(segments):
        chunk = bars.loc[timestamps]
        bars.loc[timestamps, "segment"] = number
        if len(timestamps) < 20:
            continue
        bars.loc[timestamps, "ema9"] = np.asarray(ta.ema(chunk["close"], 9))
        bars.loc[timestamps, "ema20"] = np.asarray(ta.ema(chunk["close"], 20))
        stop, direction = ta.supertrend(chunk["high"], chunk["low"], chunk["close"], 10, 3)
        bars.loc[timestamps, "stop"] = np.asarray(stop)
        bars.loc[timestamps, "direction"] = np.asarray(direction)
        finite = np.isfinite(bars.loc[timestamps, ["ema9", "ema20", "stop", "direction"]]).all(
            axis=1
        )
        bars.loc[timestamps, "ready"] = finite & (np.arange(len(timestamps)) >= 19)
    return bars


def make_signals(minute_frame, variant="pullback"):
    """Frozen EMA9/20 crossover or three-bar pullback/reclaim hypothesis."""
    if variant not in {"crossover", "pullback"}:
        raise ValueError("variant must be crossover or pullback")
    bars = _indicators(minute_frame)
    rows, timestamps = [], []
    previous = None
    setup = None
    for number, (at, row) in enumerate(bars.iterrows()):
        fresh = (
            previous is None
            or at.date() != previous[0].date()
            or row["segment"] != previous[1]["segment"]
        )
        if fresh:
            setup = None
        valid = row["ready"] and row["direction"] == -1 and 0 < row["stop"] < row["close"]
        emit = False
        if variant == "crossover":
            if previous is not None and not fresh:
                prior = previous[1]
                emit = (
                    valid
                    and prior["ready"]
                    and prior["ema9"] <= prior["ema20"]
                    and row["ema9"] > row["ema20"]
                    and row["close"] > max(row["ema9"], row["ema20"])
                )
        elif setup is not None:
            age = number - setup["number"]
            if age > 3 or not row["ready"] or row["ema9"] <= row["ema20"]:
                setup = None
            elif (
                valid
                and row["close"] > row["open"]
                and row["close"] > row["ema9"]
                and row["close"] > setup["high"]
            ):
                emit = True
                setup = None
        if (
            variant == "pullback"
            and setup is None
            and not emit
            and previous is not None
            and not fresh
        ):
            prior = previous[1]
            if (
                row["ready"]
                and prior["ready"]
                and prior["ema9"] > prior["ema20"]
                and prior["close"] > prior["ema9"]
                and row["ema9"] > row["ema20"]
                and row["low"] <= row["ema9"]
                and row["close"] >= row["ema20"]
            ):
                setup = {"number": number, "high": row["high"]}
        if emit:
            rows.append([row[column] for column in SIGNAL_COLUMNS])
            timestamps.append(at)
        previous = (at, row)
    result = pd.DataFrame(
        rows, columns=SIGNAL_COLUMNS, index=pd.DatetimeIndex(timestamps, tz=IST, name="timestamp")
    )
    result.attrs["features"] = bars
    return result


def _tick(price, step, *, up=False):
    return (Decimal(str(price)) / step).to_integral_value(
        rounding=ROUND_CEILING if up else ROUND_FLOOR
    ) * step


def _fill(price, step, slip, *, buy=False):
    return _tick(Decimal(str(price)) * (1 + slip if buy else 1 - slip), step, up=buy)


def _summary(trades, complete):
    pnls = [Decimal(str(t["net_pnl"])) for t in trades]
    gross = sum((Decimal(str(t["gross_pnl"])) for t in trades), Decimal(0))
    net = sum(pnls, Decimal(0))
    profits = sum((p for p in pnls if p > 0), Decimal(0))
    losses = -sum((p for p in pnls if p < 0), Decimal(0))
    equity = peak = drawdown = Decimal(0)
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    wins = sum(p > 0 for p in pnls)
    return {
        "trade_count": len(trades),
        "wins": wins,
        "losses": sum(p < 0 for p in pnls),
        "win_rate": wins / len(trades) if trades and complete else (0 if complete else None),
        "gross_pnl": float(gross) if complete else None,
        "net_pnl": float(net) if complete else None,
        "closed_gross_pnl": float(gross),
        "closed_net_pnl": float(net),
        "total_costs": float(gross - net),
        "profit_factor": float(profits / losses) if losses and complete else None,
        "max_closed_drawdown": float(drawdown),
    }


def simulate(minute_frame, signals, config, costs):
    """Conservative one-lot paper fills; unresolved exposure halts the replay."""
    if not isinstance(config, PaperConfig):
        raise ValueError("config must be PaperConfig")
    frame = _all_closed(minute_frame)
    schedule = validate_cost_schedule(costs)
    validate_cost_dates(schedule, sorted({at.date().isoformat() for at in frame.index}))
    if not isinstance(signals, pd.DataFrame) or not isinstance(signals.index, pd.DatetimeIndex):
        raise ValueError("signals must be a DataFrame with a DatetimeIndex")
    if signals.index.tz is None or signals.index.hasnans:
        raise ValueError("Signal timestamps must be timezone aware")
    if signals.index.has_duplicates:
        raise ValueError("duplicate signal timestamps")
    if not signals.index.is_monotonic_increasing:
        raise ValueError("Signal timestamps must be ordered")
    if "stop" not in signals:
        raise ValueError("Signal stop is required")
    signals = signals.copy()
    signals.index = signals.index.tz_convert(IST)
    if any(at.second or at.microsecond or at.nanosecond for at in signals.index):
        raise ValueError("Signal timestamps must be minute aligned")
    step = Decimal(str(config.tick_size))
    slip = Decimal(str(schedule["slippage_bps"])) / 10000
    units = config.lot_size
    equity = Decimal(str(config.capital))
    trade_limit = Decimal(str(config.max_trade_loss))
    daily_limit = Decimal(str(config.max_daily_loss))
    opening, cutoff, flatten = (
        _clock(getattr(config, key), key) for key in ("entry_start", "entry_cutoff", "flatten_at")
    )
    trades, rejected, unresolved = [], [], []
    missing_entries = signals.index.difference(frame.index)
    for at in missing_entries:
        rejected.append({"signal_at": at.isoformat(), "reason": "missing_entry_minute"})
    active = None
    day = None
    day_net = Decimal(0)
    cooldown_until = None
    previous = None

    def reject(at, reason, details=None):
        rejected.append({"signal_at": at.isoformat(), "reason": reason, **(details or {})})

    for at, bar in frame.iterrows():
        if active is not None and (previous is None or at - previous != MINUTE):
            unresolved.append({**active["record"], "reason": "missing_exposure_minute"})
            break
        if at.date() != day:
            day = at.date()
            day_net = Decimal(0)
            cooldown_until = None
        if at in signals.index:
            if not opening <= at.time() < cutoff:
                reject(at, "entry_window")
            elif active is not None:
                reject(at, "position_open")
            elif cooldown_until is not None and at < cooldown_until:
                reject(at, "cooldown")
            else:
                stop = _tick(
                    decimal_value(signals.loc[at, "stop"], "signal stop", minimum="0.000001"), step
                )
                entry = _fill(bar["open"], step, slip, buy=True)
                if stop <= 0 or stop >= entry or Decimal(str(bar["open"])) <= stop:
                    reject(at, "invalid_stop")
                else:
                    entry_fee = order_cost(entry * units, "BUY", schedule)
                    planned_exit = _fill(stop, step, slip)
                    planned = (
                        (entry - planned_exit) * units
                        + entry_fee
                        + order_cost(planned_exit * units, "SELL", schedule)
                    )
                    target = entry + 3 * (entry - stop)
                    remaining = daily_limit + min(day_net, Decimal(0))
                    required = entry * units + entry_fee
                    diagnostics = {
                        "entry_price": float(entry),
                        "stop_price": float(stop),
                        "target_price": float(target),
                        "quantity": units,
                        "planned_loss": float(planned),
                        "max_trade_loss": float(trade_limit),
                        "remaining_daily_allowance": float(remaining),
                        "required_cash": float(required),
                        "available_cash": float(equity),
                    }
                    if planned > trade_limit:
                        reject(at, "trade_risk_cap", diagnostics)
                    elif planned > remaining:
                        reject(at, "daily_risk_cap", diagnostics)
                    elif required > equity:
                        reject(at, "capital", diagnostics)
                    else:
                        active = {
                            "entry": entry,
                            "stop": stop,
                            "target": target,
                            "entry_fee": entry_fee,
                            "planned": planned,
                            "record": {
                                "signal_at": at.isoformat(),
                                "entry_at": at.isoformat(),
                                "entry_price": float(entry),
                                "stop_price": float(stop),
                                "target_price": float(target),
                                "quantity": units,
                                "planned_loss": float(planned),
                            },
                        }
        if active is not None:
            stop, target = active["stop"], active["target"]
            price = reason = None
            exit_at = at + MINUTE
            ambiguous = False
            raw_open = Decimal(str(bar["open"]))
            if raw_open <= stop:
                price, reason, exit_at = _fill(raw_open, step, slip), "stop_gap", at
            elif raw_open >= target:
                price, reason, exit_at = _fill(target, step, slip), "target", at
            elif at.time() >= flatten:
                price, reason, exit_at = _fill(raw_open, step, slip), "session_flatten", at
            elif Decimal(str(bar["low"])) <= stop:
                price, reason = _fill(stop, step, slip), "stop_loss"
                ambiguous = Decimal(str(bar["high"])) >= target
            elif Decimal(str(bar["high"])) >= target:
                price, reason = _fill(target, step, slip), "target"
            if reason:
                fee = active["entry_fee"] + order_cost(price * units, "SELL", schedule)
                gross = (price - active["entry"]) * units
                net = gross - fee
                trades.append(
                    {
                        **active["record"],
                        "exit_at": exit_at.isoformat(),
                        "exit_price": float(price),
                        "reason": reason,
                        "gross_pnl": float(gross),
                        "fees": float(fee),
                        "net_pnl": float(net),
                        "ambiguous": bool(ambiguous),
                    }
                )
                equity += net
                day_net += net
                if net < 0:
                    cooldown_until = exit_at + pd.Timedelta(minutes=config.cooldown_minutes)
                active = None
        previous = at
    else:
        if active is not None:
            unresolved.append({**active["record"], "reason": "end_of_data_open_position"})
    complete = not unresolved
    rejected.sort(key=lambda r: r["signal_at"])
    return {
        "trades": trades,
        "rejected": rejected,
        "summary": _summary(trades, complete),
        "unresolved": unresolved,
        "complete": complete,
    }


def run_paper(frame, as_of, variant, config, costs):
    prepared = prepare_minutes(frame, as_of)
    if prepared.empty:
        raise ValueError("no usable closed minutes")
    signals = make_signals(prepared, variant)
    result = simulate(prepared, signals, config, costs)
    features = signals.attrs["features"]
    records = []
    for at, row in features.iterrows():
        records.append(
            {
                "timestamp": at.isoformat(),
                **{
                    key: (float(value) if np.isfinite(value) else None)
                    for key, value in row.items()
                    if key not in {"ready", "segment"}
                },
                "ready": bool(row["ready"]),
            }
        )
    coverage = []
    for day, rows in prepared.groupby(prepared.index.date):
        expected = pd.date_range(
            pd.Timestamp(day, tz=IST) + pd.Timedelta(hours=9, minutes=15), periods=385, freq="min"
        )
        coverage.append(
            {
                "date": day.isoformat(),
                "observed_minutes": len(rows),
                "full_session": rows.index.equals(expected),
            }
        )
    quality = prepared.attrs["quality"]
    return {
        **result,
        "variant": variant,
        "features": records,
        "quality": {
            **quality,
            "complete_3m_bars": len(features),
            "forming_or_future_minutes": quality["forming_minutes"],
            "outside_session_minutes": quality["non_regular_minutes"],
            "signal_count": len(signals),
            "first_observed": prepared.index[0].isoformat(),
            "last_observed": prepared.index[-1].isoformat(),
            "sessions": coverage,
        },
        "as_of": pd.Timestamp(as_of).tz_convert(IST).isoformat(),
    }
