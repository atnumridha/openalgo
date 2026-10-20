"""Closed-bar BTC market-sentiment features and transparent composite score.

Input frames use UTC seconds in `time`. Every alignment is backward/as-of and
feature shifts are applied before use. A source timestamp is never treated as
known before its bar/observation has closed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ml_signals.data import align_asof, load_frame

SENTIMENT_SOURCES = (
    "delta_mark",
    "delta_spot_index",
    "delta_open_interest",
    "delta_funding",
    "binance_futures",
    "binance_premium",
    "bybit_oi",
    "bybit_account_ratio",
    "deribit_dvol",
    "coinbase_spot",
    "fear_greed",
)


def _num(frame: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce")
    return pd.Series(np.nan, index=frame.index, dtype=float)


def _safe_z(value: pd.Series, window: int = 96, min_periods: int = 20) -> pd.Series:
    mean = value.rolling(window, min_periods=min_periods).mean()
    std = value.rolling(window, min_periods=min_periods).std(ddof=0).replace(0, np.nan)
    return ((value - mean) / std).clip(-8, 8)


def _returns(value: pd.Series, periods: int) -> pd.Series:
    return value.pct_change(periods, fill_method=None).replace([np.inf, -np.inf], np.nan)


def _as_known_at_bar(frame: pd.DataFrame, interval_seconds: int) -> pd.DataFrame:
    """A source bar's close becomes known at its open time + its duration."""
    if frame.empty or "time" not in frame:
        return frame
    out = frame.copy()
    out["time"] = pd.to_numeric(out["time"], errors="coerce") + int(interval_seconds)
    return out.dropna(subset=["time"]).sort_values("time")


def build_sentiment_features(
    bars: pd.DataFrame,
    *,
    frames: dict[str, pd.DataFrame] | None = None,
    interval: str = "1m",
    publish_lag_seconds: int = 0,
    as_of: int | None = None,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Backward-asof sentiment features per closed candle, plus a composite [-1, 1].

    `frames` is injectable for deterministic tests. Otherwise frames are read
    from Parquet using the source names in `ml_signals.data.SOURCES`, for
    `symbol` (BTCUSD when omitted).

    `as_of` is the live clock. A bar still forming at that moment has not
    closed, so it is aligned to `as_of` instead of to a close in the future.
    """
    if bars.empty:
        return pd.DataFrame(index=bars.index)
    seconds = _interval_seconds(interval)
    base = bars[["time", "close"]].copy().reset_index(drop=True)
    base["time"] = pd.to_numeric(base["time"], errors="coerce") + seconds + int(publish_lag_seconds)
    if as_of is not None:
        base["time"] = base["time"].clip(upper=int(as_of))
    base = base.rename(columns={"close": "bar_close"})
    result = base.copy()

    sources = (
        frames
        if frames is not None
        else {name: load_frame(name, symbol=symbol) for name in SENTIMENT_SOURCES}
    )
    aligned: dict[str, pd.DataFrame] = {}
    for name in SENTIMENT_SOURCES:
        src = sources.get(name, pd.DataFrame())
        if src.empty:
            aligned[name] = base.copy()
            continue
        src = _as_known_at_bar(src, _source_seconds(name))
        rename = {
            col: f"{name}__{col}" for col in src.columns if col != "time" and col in base.columns
        }
        if rename:
            src = src.rename(columns=rename)
        aligned[name] = align_asof(base, src, max_age_seconds=_max_age(name))

    close = pd.to_numeric(result["bar_close"], errors="coerce")
    delta_mark = aligned["delta_mark"]
    delta_spot = aligned["delta_spot_index"]
    mark = _num(delta_mark, "close")
    spot = _num(delta_spot, "close")
    premium = (mark / spot - 1).replace([np.inf, -np.inf], np.nan) * 100
    result["delta_mark_premium_pct"] = premium
    result["delta_mark_premium_z"] = _safe_z(premium)
    result["delta_mark_premium_chg_5"] = premium.diff(5)

    oi = _num(aligned["delta_open_interest"], "close")
    oi_change = _returns(oi, 5) * 100
    price_change_5 = _returns(close, 5) * 100
    result["delta_oi_change_5_pct"] = oi_change
    result["delta_oi_price_disagreement"] = oi_change * price_change_5
    result["delta_oi_z"] = _safe_z(oi)

    funding = _num(aligned["delta_funding"], "close")
    funding = funding.ffill()
    result["funding_rate"] = funding
    result["funding_z"] = _safe_z(funding, window=max(20, 7 * 24 * 60 // max(1, seconds // 60)))

    bn_fut = aligned["binance_futures"]
    taker_buy = _num(bn_fut, "taker_buy_volume")
    total_volume = _num(bn_fut, "volume")
    taker_ratio = (taker_buy / total_volume).replace([np.inf, -np.inf], np.nan)
    result["binance_taker_buy_ratio"] = taker_ratio
    result["binance_taker_delta_z"] = _safe_z((2 * taker_ratio - 1).fillna(0))
    result["binance_volume_z"] = _safe_z(_num(bn_fut, "volume"))

    premium_frame = aligned["binance_premium"]
    premium_close = _num(premium_frame, "close")
    result["binance_premium"] = premium_close
    result["binance_premium_z"] = _safe_z(premium_close)

    bybit_oi = _num(
        aligned["bybit_oi"],
        "bybit_oi__openInterest",
        "bybit_oi__singleOpenInterest",
        "openInterest",
        "singleOpenInterest",
    )
    result["bybit_open_interest"] = bybit_oi
    result["bybit_oi_change_3_pct"] = _returns(bybit_oi, 3) * 100
    account_ratio = _num(
        aligned["bybit_account_ratio"], "bybit_account_ratio__buyRatio", "buyRatio"
    )
    result["bybit_long_account_ratio"] = account_ratio
    result["bybit_long_ratio_chg_3"] = account_ratio.diff(3)

    dvol = _num(aligned["deribit_dvol"], "close")
    result["deribit_dvol"] = dvol
    result["deribit_dvol_z"] = _safe_z(dvol)

    cb_spot = _num(aligned["coinbase_spot"], "close")
    # Binance futures close is not spot. Compare Coinbase BTC-USD spot to Delta's
    # BTC spot index so the cross-venue basis is on like instruments.
    result["coinbase_premium_pct"] = (cb_spot / spot - 1).replace([np.inf, -np.inf], np.nan) * 100
    result["coinbase_premium_z"] = _safe_z(result["coinbase_premium_pct"])

    fng = _num(aligned["fear_greed"], "value")
    result["fear_greed"] = fng
    result["fear_greed_centered"] = (fng - 50) / 50

    # A small, transparent composite: each source contributes at most one vote.
    # Positive values imply pro-long conditions; negative implies pro-short.
    # NaN sources are skipped, then the remaining votes are averaged.
    votes = pd.DataFrame(index=result.index)
    votes["taker_flow"] = (taker_ratio - 0.5) * 2
    votes["delta_oi"] = (
        np.sign(oi_change) * np.sign(price_change_5) * np.minimum(1, oi_change.abs() / 2)
    )
    votes["delta_basis"] = np.tanh(premium / 0.05)
    votes["binance_basis"] = np.tanh(premium_close / 0.05)
    votes["bybit_accounts"] = (account_ratio - 0.5) * 4
    votes["coinbase_basis"] = np.tanh(result["coinbase_premium_pct"] / 0.1)
    votes["fear_greed"] = result["fear_greed_centered"]
    votes["funding_contrarian"] = -np.tanh(funding / 0.03)
    result["sentiment_composite"] = votes.mean(axis=1, skipna=True).clip(-1, 1)
    result["sentiment_sources_count"] = votes.notna().sum(axis=1)
    result["sentiment_top_long"] = _top_driver(votes, bullish=True)
    result["sentiment_top_short"] = _top_driver(votes, bullish=False)

    # Return only features, keeping the input bar index stable.
    return result.drop(columns=["time", "close"], errors="ignore").set_axis(bars.index)


def _top_driver(votes: pd.DataFrame, *, bullish: bool) -> pd.Series:
    arr = votes.to_numpy(dtype=float)
    names = np.asarray(votes.columns, dtype=object)
    if arr.size == 0:
        return pd.Series(np.full(len(votes), "unavailable", dtype=object), index=votes.index)
    valid = np.isfinite(arr)
    score = np.where(valid, arr if bullish else -arr, -np.inf)
    best = names[np.argmax(score, axis=1)]
    out = np.where(valid.any(axis=1), best, "unavailable").astype(object)
    return pd.Series(out, index=votes.index)


def _interval_seconds(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1]) * 60
    if interval.endswith("h"):
        return int(interval[:-1]) * 3600
    if interval.endswith("d"):
        return int(interval[:-1]) * 86400
    return 60


def _source_seconds(name: str) -> int:
    if name == "delta_funding":
        return 3600
    if name == "fear_greed":
        return 86400
    if name == "bybit_oi":
        # Bybit OI timestamps refer to the 5-minute bucket; use it only after
        # that bucket closes.
        return 300
    if name == "bybit_account_ratio":
        # Account ratio is a point observation at its server timestamp.
        return 0
    if name == "deribit_dvol":
        # Hourly DVOL bars are stamped at the hour open and close live.
        return 3600
    return 60


def _max_age(name: str) -> int:
    if name == "bybit_oi":
        return 2 * 300
    if name == "bybit_account_ratio":
        return 2 * 300
    return 2 * _source_seconds(name)
