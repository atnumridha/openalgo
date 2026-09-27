"""Causal technical features and offline option-payoff learning helpers.

No broker, database or order access. Scikit-learn is needed only by the CLI.
Counterfactual single-lot labels are not shared-capital portfolio results.
"""

from bisect import bisect_right
from collections import defaultdict, deque
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from services.research.costs import order_cost
from services.research.replay import _filtered_contract, _slipped, _tick
from services.risk import BreachReason, PositionRisk, evaluate_position
from services.risk.budget import BudgetPolicy, evaluate_budget


def technical_features(frame, *, include_volume=False):
    """One output row per already-closed candle; no backward fill or future fit."""
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or frame.index.tz is None
        or not frame.index.is_monotonic_increasing
        or not frame.index.is_unique
    ):
        raise ValueError("Candle timestamps must be ordered, unique and timezone aware")
    f = frame.astype(float)
    if not np.isfinite(f[["open", "high", "low", "close"]]).all().all():
        raise ValueError("OHLC must be finite")
    if (
        (f.low <= 0)
        | (f.high < f[["open", "close"]].max(axis=1))
        | (f.low > f[["open", "close"]].min(axis=1))
    ).any():
        raise ValueError("OHLC is inconsistent")
    c, h, low, o = f.close, f.high, f.low, f.open
    out = pd.DataFrame(index=f.index)
    for n in (1, 3, 6, 12):
        out[f"return_{n}"] = c.pct_change(n, fill_method=None)
    emas = {n: c.ewm(span=n, adjust=False, min_periods=n).mean() for n in (8, 12, 21, 26, 50)}
    for n in (8, 21, 50):
        out[f"ema_{n}_distance"] = c / emas[n] - 1
    out["trend_spread"] = (emas[8] - emas[21]) / c
    out["trend_slope"] = emas[21].pct_change(5, fill_method=None)
    macd = emas[12] - emas[26]
    out["macd"] = macd / c
    out["macd_histogram"] = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()) / c
    change = c.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["rsi"] = (gain / (gain + loss).replace(0, np.nan)).where(gain + loss != 0, 0.5)
    tr = pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["atr_fraction"] = atr / c
    up, down = h.diff(), -low.diff()
    plus = (
        up.where((up > down) & (up > 0), 0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        / atr
    )
    minus = (
        down.where((down > up) & (down > 0), 0)
        .ewm(alpha=1 / 14, adjust=False, min_periods=14)
        .mean()
        / atr
    )
    out["directional_spread"] = plus - minus
    out["adx"] = (
        ((plus - minus).abs() / (plus + minus).replace(0, np.nan))
        .ewm(alpha=1 / 14, adjust=False, min_periods=14)
        .mean()
    )
    mean, std = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    out["bollinger_position"] = (c - mean) / std.replace(0, np.nan)
    out["bollinger_width"] = 4 * std / c
    lo, hi = low.rolling(14).min(), h.rolling(14).max()
    out["stochastic"] = (c - lo) / (hi - lo).replace(0, np.nan)
    span = (h - low).replace(0, np.nan)
    out["body"] = (c - o) / span
    out["upper_wick"] = (h - pd.concat([o, c], axis=1).max(axis=1)) / span
    out["lower_wick"] = (pd.concat([o, c], axis=1).min(axis=1) - low) / span
    out["close_location"] = (c - low) / span
    out["high_break_distance"] = c / h.shift().rolling(20).max() - 1
    out["low_break_distance"] = c / low.shift().rolling(20).min() - 1
    out["efficiency"] = (c - c.shift(20)).abs() / change.abs().rolling(20).sum().replace(0, np.nan)
    out["realized_volatility"] = c.pct_change(fill_method=None).rolling(20).std(ddof=0)
    days = f.index.strftime("%Y-%m-%d")
    daily = f.groupby(days).agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    previous = daily.shift(1).reindex(days).set_axis(f.index)
    out["prior_close_distance"] = c / previous.close - 1
    out["prior_high_distance"] = c / previous.high - 1
    out["prior_low_distance"] = c / previous.low - 1
    out["session_return"] = c / o.groupby(days).transform("first") - 1
    out["session_high_distance"] = c / h.groupby(days).cummax() - 1
    out["session_low_distance"] = c / low.groupby(days).cummin() - 1
    minutes = f.index.hour * 60 + f.index.minute - 555
    out["time_sin"] = np.sin(2 * np.pi * minutes / 375)
    out["time_cos"] = np.cos(2 * np.pi * minutes / 375)
    if include_volume:
        v = f.volume.where(f.volume >= 0)
        out["relative_volume"] = v / v.shift().rolling(20).mean().replace(0, np.nan)
        out["volume_log"] = np.log1p(v)
        typical = (h + low + c) / 3
        vwap = (typical * v).groupby(days).cumsum() / v.groupby(days).cumsum().replace(0, np.nan)
        out["vwap_distance"] = c / vwap - 1
    return out.replace([np.inf, -np.inf], np.nan)


def label_option_trade(rows, signal_at, contract, atr, costs, session_close="15:25"):
    """Net R for one eligible lot; unavailable future outcomes remain missing.

    Position stop/target decisions use the shared risk core. Portfolio admission,
    drawdown and multi-trade interaction are evaluated separately by run_replay.
    """
    timestamps = [r["timestamp"] for r in rows]
    start = bisect_right(timestamps, signal_at)
    expected = (datetime.fromisoformat(signal_at) + timedelta(minutes=1)).isoformat()
    if start == len(rows) or rows[start]["timestamp"] != expected:
        return None
    slip = costs["slippage_bps"] / 10000
    entry = _slipped(rows[start]["open"], slip, contract, buy=True)
    exact = Decimal(str(entry))
    stop = _tick(exact - max(exact * Decimal(".10"), Decimal(str(atr)) * Decimal("1.5")), contract)
    distance = exact - Decimal(str(stop))
    target = _tick(exact + distance * 2, contract, up=True)
    if not 20 <= entry <= 120 or distance > exact * Decimal(".25"):
        return None
    units = contract["lot_size"] * contract["multiplier"]
    entry_fee = order_cost(Decimal(str(entry * units)), "BUY", costs)
    if Decimal(str(entry * units)) + entry_fee > Decimal("8000"):
        return None
    stop_fill = _slipped(stop, slip, contract)
    planned = (
        Decimal(str((entry - stop_fill) * units))
        + entry_fee
        + order_cost(Decimal(str(stop_fill * units)), "SELL", costs)
    )
    if planned <= 0:
        return None
    admission = evaluate_budget(
        BudgetPolicy(), (), signal_at[:10], Decimal("10000"), Decimal("10000"), planned
    )
    if not admission.allowed:
        return None
    risk = PositionRisk(entry_price=entry, quantity=units, stop_price=stop, target_price=target)
    for bar in rows[start:]:
        at = bar["timestamp"]
        if at != expected or at[:10] != signal_at[:10] or at[11:16] > session_close:
            return None
        opening = evaluate_position(risk, bar["open"])
        price, reason, ambiguous = None, None, False
        if opening.reason in (BreachReason.STOP, BreachReason.TARGET):
            price, reason = bar["open"], str(opening.reason)
        else:
            stopped = evaluate_position(risk, bar["low"]).reason == BreachReason.STOP
            won = evaluate_position(risk, bar["high"]).reason == BreachReason.TARGET
            if stopped:
                price, reason, ambiguous = stop, "sl", won
            elif won:
                price, reason = target, "target"
            elif at[11:16] == session_close:
                price, reason = bar["close"], "session_close"
        if price is not None:
            fill = _slipped(price, slip, contract)
            net = (
                Decimal(str((fill - entry) * units))
                - entry_fee
                - order_cost(Decimal(str(fill * units)), "SELL", costs)
            ).quantize(Decimal(".01"))
            return {
                "net_r": float(net / planned),
                "net_pnl": float(net),
                "entry_at": rows[start]["timestamp"],
                "exit_at": at,
                "ambiguous": ambiguous,
                "exit_reason": reason,
            }
        expected = (datetime.fromisoformat(at) + timedelta(minutes=1)).isoformat()
    return None


def assert_chronology(training, later):
    if training.empty or later.empty:
        raise ValueError("Chronological splits require observations")
    end = max(training.timestamp.max(), training.label_exit_at.dropna().max())
    if end >= later.timestamp.min():
        raise ValueError("Training observations or labels overlap the later period")


def signal_schedule(opportunities, predictions, threshold):
    if len(opportunities) != len(predictions) or not np.isfinite(predictions).all():
        raise ValueError("Predictions must be finite and match opportunities")
    ordered = opportunities[["timestamp", "direction", "symbol"]].copy()
    ordered["score"] = predictions
    ordered = ordered[ordered.score > threshold].sort_values(
        ["timestamp", "score", "direction"], ascending=[True, False, True], kind="stable"
    )
    return {
        row.timestamp: {"direction": row.direction, "symbol": row.symbol}
        for row in ordered.drop_duplicates("timestamp").itertuples(index=False)
    }


def validation_qualifies(metrics):
    """Validation evidence must meet the registered minimum in both scenarios."""
    return all(
        metrics[scenario]["net_pnl"] is not None
        and metrics[scenario]["net_pnl"] > 0
        and metrics[scenario]["trade_count"] >= 20
        and metrics[scenario]["ambiguous_exit_count"] == 0
        for scenario in ("base", "stress")
    )


OPTION_FEATURES = (
    "return_1",
    "return_3",
    "return_6",
    "rsi",
    "atr_fraction",
    "body",
    "upper_wick",
    "lower_wick",
    "relative_volume",
    "volume_log",
    "vwap_distance",
)


def build_opportunities(data, underlying_features, costs, *, labels=False):
    """Opportunity eligibility uses only data observable at the signal timestamp."""
    meta = data["metadata"]
    by_time, by_contract_day = defaultdict(dict), defaultdict(list)
    for row in data["rows"]:
        by_time[row["timestamp"]][row["symbol"]] = row
        if row["symbol"] != meta["underlying_symbol"]:
            by_contract_day[(row["symbol"], row["timestamp"][:10])].append(row)
    option_features = {}
    for key, rows in by_contract_day.items():
        frame = pd.DataFrame(rows).set_index("timestamp")
        frame.index = pd.DatetimeIndex(frame.index)
        option_features[key] = technical_features(
            frame[["open", "high", "low", "close", "volume"]], include_volume=True
        )
    histories = defaultdict(lambda: deque(maxlen=11))
    output, rejected = [], defaultdict(int)
    previous_day = None
    for at, bars in sorted(by_time.items()):
        day = at[:10]
        if day != previous_day:
            histories.clear()
            previous_day = day
        for symbol, row in bars.items():
            if symbol == meta["underlying_symbol"]:
                continue
            history = histories[symbol]
            if history and datetime.fromisoformat(at) - datetime.fromisoformat(
                history[-1]["timestamp"]
            ) != timedelta(minutes=1):
                history.clear()
            history.append(row)
        underlying = bars.get(meta["underlying_symbol"])
        if (
            underlying is None
            or at[11:16] >= meta["session_close"]
            or pd.Timestamp(at) not in underlying_features.index
        ):
            continue
        u = underlying_features.loc[at]
        if u.isna().any():
            rejected["underlying_feature_warmup"] += 1
            continue
        for direction in ("CE", "PE"):
            contract, atr = _filtered_contract(
                meta["contracts"],
                bars,
                histories,
                underlying,
                direction,
                day,
                Decimal("10000"),
                BudgetPolicy(),
                costs,
                costs["slippage_bps"] / 10000,
                rejected,
            )
            if contract is None:
                continue
            o = option_features[(contract["symbol"], day)].loc[at, list(OPTION_FEATURES)]
            if o.isna().any():
                rejected["option_feature_warmup"] += 1
                continue
            features = {"u_" + k: float(v) for k, v in u.items()} | {
                "o_" + k: float(v) for k, v in o.items()
            }
            features.update(
                direction_ce=float(direction == "CE"),
                premium=bars[contract["symbol"]]["close"],
                moneyness=(underlying["close"] - contract["strike"]) / underlying["close"],
                days_to_expiry=(
                    datetime.fromisoformat(contract["expiry"]) - datetime.fromisoformat(day)
                ).days,
                lot_size=contract["lot_size"],
            )
            record = {
                "timestamp": at,
                "direction": direction,
                "symbol": contract["symbol"],
                **features,
            }
            if labels:
                label = label_option_trade(
                    by_contract_day[(contract["symbol"], day)],
                    at,
                    contract,
                    atr,
                    costs,
                    meta["session_close"],
                )
                record.update(
                    net_r=label["net_r"] if label else np.nan,
                    label_exit_at=label["exit_at"] if label else None,
                    label_ambiguous=label["ambiguous"] if label else None,
                )
                if label is None:
                    rejected["unavailable_label"] += 1
            output.append(record)
    return pd.DataFrame(output), dict(rejected)
