"""Leakage-safe feature generation for 30-minute BTC scalp signals."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml_signals.sentiment import build_sentiment_features
from openalgo import ta

TIMEFRAME_CODES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}


def _rsi(close: np.ndarray, period: int) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain = pd.Series(np.clip(delta, 0, None)).ewm(alpha=1 / period, adjust=False).mean()
    loss = pd.Series(np.clip(-delta, 0, None)).ewm(alpha=1 / period, adjust=False).mean()
    total = gain + loss
    return (100 * gain / total.where(total > 0)).fillna(50).to_numpy()


def _efficiency(close: np.ndarray, period: int = 20) -> np.ndarray:
    out = np.full(len(close), np.nan)
    if len(close) <= period:
        return out
    steps = np.abs(np.diff(close))
    # A sliding sum rather than a cumulative one, so a NaN poisons only the
    # windows that contain it.
    path = np.convolve(steps, np.ones(period), mode="valid")
    net = np.abs(close[period:] - close[:-period])
    out[period:] = np.divide(net, path, out=np.zeros_like(net), where=path > 0)
    return out


def _bars_to_frame(bars: pd.DataFrame | list[dict]) -> pd.DataFrame:
    frame = bars.copy() if isinstance(bars, pd.DataFrame) else pd.DataFrame(bars)
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"bars missing required columns: {sorted(missing)}")
    return frame.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)


def build_features(
    bars: pd.DataFrame | list[dict],
    *,
    interval: str,
    sentiment: pd.DataFrame | None = None,
    sentiment_frames: dict[str, pd.DataFrame] | None = None,
    include_sentiment: bool = True,
    as_of: int | None = None,
) -> pd.DataFrame:
    """Past-only price, trend and optional sentiment features for closed bars.

    Values are aligned to each bar close. No rolling operation is centred and
    no higher-timeframe/sentiment value is forward-aligned from the future.
    `as_of` aligns a bar still forming at that moment to the live clock.
    """
    if interval not in TIMEFRAME_CODES:
        raise ValueError(
            f"unsupported scalp timeframe {interval!r}; expected {sorted(TIMEFRAME_CODES)}"
        )
    b = _bars_to_frame(bars)
    close = b["close"].to_numpy(dtype=float)
    high = b["high"].to_numpy(dtype=float)
    low = b["low"].to_numpy(dtype=float)
    volume = b["volume"].fillna(0).to_numpy(dtype=float)
    len(b)
    x = pd.DataFrame(index=b.index)
    x["timeframe_code"] = float(TIMEFRAME_CODES[interval])

    for lag in (1, 2, 3, 5, 10, 15, 30, 50):
        x[f"return_{lag}"] = pd.Series(close).pct_change(lag, fill_method=None).to_numpy() * 100

    for period in (7, 14):
        x[f"rsi_{period}"] = _rsi(close, period)

    for period in (9, 21, 50):
        values = np.asarray(ta.ema(close, period), dtype=float)
        x[f"ema_{period}_dist_pct"] = (close / values - 1) * 100
        x[f"ema_{period}_slope_3"] = (
            pd.Series(values).pct_change(3, fill_method=None).to_numpy() * 100
        )

    macd = np.asarray(ta.ema(close, 12), dtype=float) - np.asarray(ta.ema(close, 26), dtype=float)
    macd_signal = np.asarray(ta.ema(macd, 9), dtype=float)
    x["macd_hist_pct"] = (macd - macd_signal) / close * 100

    atr14 = np.asarray(ta.atr(high, low, close, 14), dtype=float)
    x["atr_14_pct"] = atr14 / close * 100
    x["atr_14_change_5"] = pd.Series(atr14).pct_change(5, fill_method=None).to_numpy()

    for period in (20, 50):
        mean = pd.Series(close).rolling(period, min_periods=period).mean()
        std = pd.Series(close).rolling(period, min_periods=period).std(ddof=0)
        width = 4 * std
        x[f"bb_{period}_width_pct"] = width.to_numpy() / close * 100
        x[f"bb_{period}_pctb"] = (close - (mean.to_numpy() - 2 * std.to_numpy())) / width.to_numpy()

    for period in (10, 20, 50):
        x[f"efficiency_{period}"] = _efficiency(close, period)

    st, direction = ta.supertrend(high, low, close, 7, 1.5)
    st = np.asarray(st, dtype=float)
    direction = np.asarray(direction, dtype=float)
    x["supertrend_direction"] = direction
    x["supertrend_distance_pct"] = (close - st) / close * 100
    x["supertrend_flip"] = np.r_[np.nan, np.diff(direction)]

    vol_sma = pd.Series(volume).rolling(20, min_periods=10).mean()
    vol_std = pd.Series(volume).rolling(20, min_periods=10).std(ddof=0).replace(0, np.nan)
    x["volume_z_20"] = (pd.Series(volume) - vol_sma) / vol_std
    x["volume_change_3"] = (
        pd.Series(volume).pct_change(3, fill_method=None).replace([np.inf, -np.inf], np.nan)
    )

    dt = pd.to_datetime(b["time"], unit="s", utc=True)
    x["hour_utc_sin"] = np.sin(2 * np.pi * dt.dt.hour / 24)
    x["hour_utc_cos"] = np.cos(2 * np.pi * dt.dt.hour / 24)
    x["weekday_sin"] = np.sin(2 * np.pi * dt.dt.dayofweek / 7)
    x["weekday_cos"] = np.cos(2 * np.pi * dt.dt.dayofweek / 7)

    if include_sentiment:
        sent = sentiment
        if sent is None:
            sent = build_sentiment_features(
                b, frames=sentiment_frames, interval=interval, as_of=as_of
            )
        sent = sent.reindex(b.index)
        for col in sent.columns:
            if col.startswith("sentiment_top_"):
                continue
            if pd.api.types.is_numeric_dtype(sent[col]):
                x[f"sent_{col}"] = sent[col].to_numpy()

    # Features at row i use only bars with index <= i. First rows with warmup
    # NaNs are retained for auditing, then excluded by make_training_matrix.
    return x.replace([np.inf, -np.inf], np.nan)


def make_training_matrix(
    features: pd.DataFrame,
    labels: np.ndarray | pd.Series,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Drop warmup/unlabelled rows, preserve source indices, and add NaN mask."""
    y = np.asarray(labels)
    if len(features) != len(y):
        raise ValueError("feature and label lengths differ")
    valid_label = pd.notna(y)
    valid_features = features.notna().any(axis=1).to_numpy()
    mask = valid_label & valid_features
    return features.loc[mask].reset_index(drop=True), y[mask], np.flatnonzero(mask)
