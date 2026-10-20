"""Constrained 30-minute stop/target/entry/filter search with walk-forward scoring."""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from ml_signals.account import (
    AccountConfig,
    contracts_for_trade,
    monte_carlo_ruin,
    simulate_account,
)
from ml_signals.features import build_features
from ml_signals.labels import FEE_PLANS, simulate_trade
from ml_signals.sentiment import build_sentiment_features

STOP_GRID = (0.10, 0.15, 0.20)
TARGET_GRID = (0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0)
TIMEFRAMES = ("1m", "3m", "5m", "15m")
ENTRY_FAMILIES = ("v2_balanced", "v2_early", "breakout", "pullback")
SENTIMENT_FILTERS = (
    "none",
    "taker_agrees",
    "oi_price_agrees",
    "premium_agrees",
    "bybit_position_agrees",
)
ENTRY_ORDERS = ("market", "limit")
FEE_PLANS_USED = ("scalper", "scalper+diwali")


def resample_bars(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Fold sorted 1m OHLCV candles into fixed minute buckets."""
    frame = bars.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)
    if minutes == 1:
        frame["source_end_index"] = np.arange(len(frame), dtype=int)
        return frame
    bucket = (frame["time"].astype("int64") // (minutes * 60)).to_numpy()
    grouped = frame.groupby(bucket, sort=True)
    out = grouped.agg(
        time=("time", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index(drop=True)
    out["source_end_index"] = [int(np.asarray(indices)[-1]) for indices in grouped.indices.values()]
    return out


def _signal_columns(
    bars: pd.DataFrame, interval: str, sentiment: pd.DataFrame | None
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    from openalgo import ta

    features = build_features(bars, interval=interval, sentiment=sentiment, include_sentiment=False)
    high, low, close = (bars[k].to_numpy(float) for k in ("high", "low", "close"))
    st_value, st_direction = ta.supertrend(
        high, low, close, period=_v2_profile(interval)[0], multiplier=_v2_profile(interval)[1]
    )
    ema_period = _v2_profile(interval)[2]
    ema = np.asarray(ta.ema(close, ema_period), float)
    beyond = (close - st_value) / close * 100
    valid = np.isfinite(st_value) & np.isfinite(ema) & np.isfinite(beyond)
    long_balanced = (
        valid
        & np.r_[False, st_direction[:-1] > st_direction[1:]]
        & (st_direction < 0)
        & (close > ema)
        & (beyond >= max(0.118, _v2_profile(interval)[3]))
    )
    short_balanced = (
        valid
        & np.r_[False, st_direction[:-1] < st_direction[1:]]
        & (st_direction > 0)
        & (close < ema)
        & (-beyond >= max(0.118, _v2_profile(interval)[3]))
    )
    long_early = valid & np.r_[False, st_direction[:-1] > st_direction[1:]] & (st_direction < 0)
    short_early = valid & np.r_[False, st_direction[:-1] < st_direction[1:]] & (st_direction > 0)
    return features, long_balanced | long_early, short_balanced | short_early


def _v2_profile(interval: str) -> tuple[int, float, int, float]:
    return {
        "1m": (7, 1.5, 20, 0.15),
        "3m": (6, 1.4, 13, 0.18),
        "5m": (6, 1.4, 13, 0.18),
        "15m": (5, 1.3, 8, 0.20),
    }[interval]


def _sentiment_mask(features: pd.DataFrame, side: int, filter_name: str) -> np.ndarray:
    n = len(features)
    if filter_name == "none":
        return np.ones(n, dtype=bool)

    def col(*names):
        for name in names:
            key = f"sent_{name}"
            if key in features:
                return pd.to_numeric(features[key], errors="coerce").to_numpy(float)
        return np.full(n, np.nan)

    if filter_name == "taker_agrees":
        x = col("binance_taker_buy_ratio")
        return np.isfinite(x) & (side * (x - 0.5) > 0)
    if filter_name == "oi_price_agrees":
        x = col("delta_oi_price_disagreement")
        return np.isfinite(x) & (x > 0)
    if filter_name == "premium_agrees":
        x = col("delta_mark_premium_z", "binance_premium_z")
        return np.isfinite(x) & (side * x > 0)
    if filter_name == "bybit_position_agrees":
        x = col("bybit_long_account_ratio")
        return np.isfinite(x) & (side * (x - 0.5) > 0)
    return np.zeros(n, dtype=bool)


def _trade_indices(
    bars: pd.DataFrame,
    long_signal: np.ndarray,
    short_signal: np.ndarray,
    *,
    sentiment_features: pd.DataFrame | None,
    filter_name: str,
    sideways_hold: bool,
) -> list[tuple[int, int]]:
    from ml_signals.features import _efficiency

    close = bars["close"].to_numpy(float)
    er = _efficiency(close, 20)
    out = []
    for i in range(len(bars) - 1):
        side = 1 if long_signal[i] else -1 if short_signal[i] else 0
        if not side:
            continue
        if sideways_hold and (not np.isfinite(er[i]) or er[i] < 0.3):
            continue
        if filter_name != "none":
            if (
                sentiment_features is None
                or not _sentiment_mask(sentiment_features, side, filter_name)[i]
            ):
                continue
        out.append((i, side))
    return out


def _simulate_entries(
    minute_bars: pd.DataFrame,
    signal_bars: pd.DataFrame,
    entries: list[tuple[int, int]],
    *,
    stop_pct: float,
    target_pct: float,
    fee_plan: str,
    entry_order: str,
    break_even: bool,
    max_hold_minutes: int = 28,
) -> list[dict[str, Any]]:
    trades = []
    last_exit_minute = 0
    last_available_signal_minute = -(10**12)
    for signal_index, side in entries:
        source_index = int(
            signal_bars.get("source_end_index", pd.Series(np.arange(len(signal_bars)))).iloc[
                signal_index
            ]
        )
        entry_index = source_index + 1
        if entry_index >= len(minute_bars):
            continue
        signal_minute = int(minute_bars.iloc[entry_index]["time"] // 60)
        # One open position at a time: do not enter a later model signal while
        # a prior 28-minute trade is unresolved in the 1m fill path.
        if signal_minute <= last_exit_minute or signal_minute <= last_available_signal_minute:
            continue
        last_available_signal_minute = signal_minute
        result = simulate_trade(
            minute_bars,
            entry_index=entry_index - 1,
            side=side,
            stop_pct=stop_pct,
            target_pct=target_pct,
            max_hold_minutes=max_hold_minutes,
            fee_plan=fee_plan,
            entry_order=entry_order,
        )
        if result is None:
            continue
        # Optional break-even: conservatively cap adverse excursion after +1R
        # only when the 1m path says +1R happened before the stop.
        if break_even:
            en = result["entry_index"]
            exit_i = result["exit_index"]
            entry = result["entry_price"]
            risk = stop_pct
            armed = False
            for j in range(en, exit_i + 1):
                b = minute_bars.iloc[j]
                fav = (
                    side
                    * ((float(b["high"]) if side > 0 else float(b["low"])) - entry)
                    / entry
                    * 100
                )
                adv = (
                    side
                    * ((float(b["low"]) if side > 0 else float(b["high"])) - entry)
                    / entry
                    * 100
                )
                if fav >= risk:
                    armed = True
                if armed and adv <= 0:
                    result["exit_kind"] = "break_even"
                    result["exit_price"] = entry
                    result["gross_pct"] = 0.0
                    result["net_pct"] = (
                        -result["entry_fee_pct"]
                        - result["exit_fee_pct"]
                        - result["slippage_pct"]
                        + result["voucher_pct"]
                    )
                    result["exit_index"] = j
                    result["held_minutes"] = j - en + 1
                    break
        result.update(
            {
                "signal_index": signal_index,
                "side": side,
                "signal_time": int(signal_bars.iloc[signal_index]["time"]),
            }
        )
        trades.append(result)
        last_exit_minute = int(minute_bars.iloc[int(result["exit_index"])]["time"] // 60)
    return trades


def _account_summary(
    trades: list[dict[str, Any]], *, leverage: float, start_usd: float = 100.0
) -> dict[str, Any]:
    """Compound trades using a position sized to the 0.2%-of-account loss cap.

    Contracts are re-sized at each equity level, with notional capped by the
    requested leverage and liquidation distance. The rule's trade return is
    first translated to account return using actual notional; losses cannot be
    hidden by multiplying capped risk back up by leverage.
    """
    requested = min(float(leverage), 25.0)
    equity = float(start_usd)
    curve = [equity]
    peak = equity
    max_dd = 0.0
    wins = 0
    liquidations = 0
    notionals = []
    margins = []
    risk_dollars = []
    for trade in trades:
        entry = float(trade.get("entry_price") or 0)
        stop_pct = float(trade.get("stop_pct") or 0.2)
        size = contracts_for_trade(
            equity=equity,
            price=entry,
            stop_pct=stop_pct,
            leverage=requested,
            config=AccountConfig(
                start_usd=start_usd,
                max_leverage=25,
                risk_fraction=0.002,
                max_loss_fraction=0.002,
                max_notional_fraction=25,
            ),
            risk_fraction=0.002,
        )
        notional = float(size["notional_usd"])
        margin = float(size["margin_usd"])
        if notional <= 0 or margin > equity:
            account_return = -0.95 if margin > equity else 0.0
        else:
            account_return = float(trade["net_pct"]) * notional / equity
            if account_return <= -0.95:
                account_return = -0.95
                liquidations += 1
        equity *= max(0.01, 1 + account_return / 100)
        wins += account_return > 0
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity / peak - 1) * 100)
        curve.append(equity)
        notionals.append(notional)
        margins.append(margin)
        risk_dollars.append(float(size.get("risk_usd", 0)))
    acct_returns = [
        ((curve[i + 1] / curve[i]) - 1) * 100 for i in range(len(curve) - 1) if curve[i] > 0
    ]
    return {
        "start_usd": start_usd,
        "end_usd": equity,
        "return_pct": (equity / start_usd - 1) * 100,
        "max_drawdown_pct": max_dd,
        "trades": len(trades),
        "win_rate_pct": wins / max(1, len(trades)) * 100,
        "liquidations": liquidations,
        "requested_leverage": requested,
        "max_risk_usd_per_trade": start_usd * 0.002,
        "median_notional_usd": float(np.median(notionals)) if notionals else 0.0,
        "median_margin_usd": float(np.median(margins)) if margins else 0.0,
        "median_risk_usd": float(np.median(risk_dollars)) if risk_dollars else 0.0,
        "probability_lose_50pct": monte_carlo_ruin(
            acct_returns,
            start_usd=start_usd,
            leverage=1,
            risk_fraction=1,
            threshold_loss_pct=50,
            simulations=500,
        ),
        "equity_curve": curve,
    }


def run_search(
    minute_bars: pd.DataFrame,
    *,
    sentiment_frames: dict[str, pd.DataFrame] | None = None,
    settings: dict[str, Any] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Grid-search entries/exits/filters, score on chronological walk-forward folds."""
    minute_bars = (
        minute_bars.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)
    )
    if len(minute_bars) < 60 * 24 * 30:
        raise ValueError("Phase 1 search needs at least 30 days of 1m BTC candles")
    cfg = settings or {}
    stops = tuple(float(x) for x in cfg.get("stops", (0.10, 0.15, 0.20)))
    targets = tuple(float(x) for x in cfg.get("targets", (0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0)))
    max_hold = min(28, int(cfg.get("max_hold_minutes", 28)))
    levers = tuple(float(x) for x in cfg.get("leverage", (5, 10, 15, 20, 25)))
    entry_orders = tuple(cfg.get("entry_orders", ("market", "limit")))
    fees = tuple(cfg.get("fee_plans", ("standard", "scalper", "scalper+diwali")))
    entry_filters = tuple(cfg.get("sentiment_filters", SENTIMENT_FILTERS))
    break_even_values = (False, True)
    timeframes = tuple(cfg.get("timeframes", TIMEFRAMES))
    if any(tf not in TIMEFRAMES for tf in timeframes):
        raise ValueError(f"unsupported timeframe; choose from {TIMEFRAMES}")
    split = int(len(minute_bars) * 0.7)
    results: list[dict[str, Any]] = []
    total = sum(
        len(STOP_GRID)
        * len(TARGET_GRID)
        * len(ENTRY_FAMILIES)
        * len(entry_filters)
        * len(entry_orders)
        * len(fees)
        * len(break_even_values)
        for _ in timeframes
    )
    done = 0
    sentiment_1m = (
        build_sentiment_features(minute_bars, frames=sentiment_frames, interval="1m")
        if sentiment_frames
        else None
    )

    # Random baseline: match the base V2 Balanced+sideways signal count per TF.
    rng = np.random.default_rng(20261002)
    random_cache: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for tf in timeframes:
        tf_minutes = int(tf[:-1])
        b = resample_bars(minute_bars, tf_minutes)
        sf = None
        if sentiment_1m is not None:
            sf = sentiment_1m.iloc[b["source_end_index"].to_numpy()].reset_index(drop=True)
        feat = build_features(b, interval=tf, sentiment=sf, include_sentiment=False)
        longs, shorts = _signals_for_family(b, feat, tf)
        base_entries = _trade_indices(
            b, longs, shorts, sentiment_features=sf, filter_name="none", sideways_hold=True
        )
        eligible = [i for i in range(50, len(b) - 1) if np.isfinite(b.iloc[i]["close"])]
        random_count = max(1, len(base_entries))
        picked = (
            rng.choice(eligible, size=min(random_count, len(eligible)), replace=False)
            if eligible
            else []
        )
        random_cache[(tf, 0)] = [(int(i), 1 if rng.random() < 0.5 else -1) for i in sorted(picked)]

        for family in ENTRY_FAMILIES:
            feature_frame = build_features(b, interval=tf, sentiment=sf, include_sentiment=True)
            longs, shorts = _signals_for_family(b, feature_frame, tf, family=family)
            for filter_name, stop_pct, target_pct, entry_order, fee_plan, be in itertools.product(
                entry_filters, stops, targets, entry_orders, fees, break_even_values
            ):
                entries = _trade_indices(
                    b,
                    longs,
                    shorts,
                    sentiment_features=sf,
                    filter_name=filter_name,
                    sideways_hold=True,
                )
                all_trades = _simulate_entries(
                    minute_bars,
                    b,
                    entries,
                    stop_pct=stop_pct,
                    target_pct=target_pct,
                    fee_plan=fee_plan,
                    entry_order=entry_order,
                    break_even=be,
                    max_hold_minutes=max_hold,
                )
                train_trades = [
                    t for t in all_trades if t["signal_time"] < int(bars_time(minute_bars, split))
                ]
                test_trades = [
                    t for t in all_trades if t["signal_time"] >= int(bars_time(minute_bars, split))
                ]
                train_r = [t["net_pct"] for t in train_trades]
                test_r = [t["net_pct"] for t in test_trades]
                account = _account_summary(test_trades, leverage=max(levers))
                rand_entries = random_cache[(tf, 0)]
                rand_trades = _simulate_entries(
                    minute_bars,
                    b,
                    rand_entries,
                    stop_pct=stop_pct,
                    target_pct=target_pct,
                    fee_plan=fee_plan,
                    entry_order=entry_order,
                    break_even=be,
                    max_hold_minutes=max_hold,
                )
                rand_test = [
                    t["net_pct"]
                    for t in rand_trades
                    if t["signal_time"] >= int(bars_time(minute_bars, split))
                ]
                _account_summary(test_trades, leverage=max(levers))["equity_curve"]
                results.append(
                    {
                        "timeframe": tf,
                        "family": family,
                        "filter": filter_name,
                        "stop_pct": stop_pct,
                        "target_pct": target_pct,
                        "entry_order": entry_order,
                        "fee_plan": fee_plan,
                        "break_even": be,
                        "hold_minutes": max_hold,
                        "train": _summarize(train_r),
                        "test": _summarize(test_r),
                        "random_test": _summarize(rand_test),
                        "account": account,
                        "train_beats_random": _sum(train_r)
                        > _sum(
                            [
                                t["net_pct"]
                                for t in rand_trades
                                if t["signal_time"] < int(bars_time(minute_bars, split))
                            ]
                        ),
                        "test_beats_random": _sum(test_r) > _sum(rand_test),
                    }
                )
                done += 1
                if progress and done % 50 == 0:
                    progress(done, total, f"{tf} {family} {filter_name}")
    results.sort(
        key=lambda r: (r["test_beats_random"], r["test"]["net_pct"], r["account"]["end_usd"]),
        reverse=True,
    )
    candidates = [
        r
        for r in results
        if r["test_beats_random"] and r["train_beats_random"] and r["test"]["trades"] >= 20
    ]
    return {
        "settings": len(results),
        "candidate_count": len(candidates),
        "best": results[0] if results else None,
        "ranked": results[:100],
        "candidates": candidates[:100],
        "promotable": bool(candidates),
        "note": "No edge is guaranteed; candidates must beat a matched random-entry baseline on both chronological train and test windows.",
    }


def bars_time(frame: pd.DataFrame, index: int) -> int:
    return int(frame.iloc[min(max(index, 0), len(frame) - 1)]["time"])


def _sum(values: list[float]) -> float:
    return float(np.sum(values)) if values else 0.0


def _summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "trades": 0,
            "net_pct": 0.0,
            "win_pct": 0.0,
            "avg_net_pct": 0.0,
            "max_drawdown_pct": 0.0,
        }
    a = np.asarray(values, dtype=float)
    equity = np.cumsum(a)
    peak = np.maximum.accumulate(np.r_[0.0, equity])[1:]
    dd = equity - peak
    return {
        "trades": int(len(a)),
        "net_pct": round(float(a.sum()), 4),
        "win_pct": round(float((a > 0).mean() * 100), 2),
        "avg_net_pct": round(float(a.mean()), 5),
        "max_drawdown_pct": round(float(dd.min()), 4),
    }


def _signals_for_family(
    bars: pd.DataFrame, features: pd.DataFrame, interval: str, family: str = "v2_balanced"
) -> tuple[np.ndarray, np.ndarray]:
    from openalgo import ta

    high, low, close = (bars[k].to_numpy(float) for k in ("high", "low", "close"))
    period, mult, ema_period, min_move = _v2_profile(interval)
    st, direction = ta.supertrend(high, low, close, period, mult)
    st, direction = np.asarray(st, float), np.asarray(direction, float)
    ma = np.asarray(ta.ema(close, ema_period), float)
    valid = np.isfinite(st) & np.isfinite(ma) & np.isfinite(direction)
    flips_up = np.r_[False, direction[:-1] > direction[1:]] & (direction < 0)
    flips_down = np.r_[False, direction[:-1] < direction[1:]] & (direction > 0)
    long_bal = (
        valid & flips_up & (close > ma) & ((close - st) / close * 100 >= max(0.118, min_move))
    )
    short_bal = (
        valid & flips_down & (close < ma) & ((st - close) / close * 100 >= max(0.118, min_move))
    )
    if family == "v2_balanced":
        return long_bal, short_bal
    if family == "v2_early":
        return valid & flips_up, valid & flips_down
    if family == "breakout":
        window = max(2, 20 // max(1, int(interval[:-1])))
        rolling_high = pd.Series(high).rolling(window).max().shift(1).to_numpy()
        rolling_low = pd.Series(low).rolling(window).min().shift(1).to_numpy()
        return (close > rolling_high) & valid, (close < rolling_low) & valid
    if family == "pullback":
        e9 = np.asarray(ta.ema(close, 9), float)
        return valid & (direction < 0) & (close > ma) & (low <= e9) & (close >= e9), valid & (
            direction > 0
        ) & (close < ma) & (high >= e9) & (close <= e9)
    raise ValueError(f"unknown entry family: {family}")
