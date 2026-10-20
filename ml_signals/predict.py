"""Orchestration helpers for the ML API and chart indicator."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml_signals import data
from ml_signals.features import build_features
from ml_signals.search import run_search
from ml_signals.train import TrainConfig, current_version, load_version, symbol_dir, train_model

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "db" / "ml_signals" / "search_results.json"
INTERVALS = ("1m", "3m", "5m", "15m")
# funding_z looks back seven days of bars; the spare two cover EMA warmup, so a
# window's first bar matches a computation over the full saved year.
WARMUP_SECONDS = 9 * 86400

_active_model: dict[str, dict[str, Any]] = {}


def _load_frame(
    name: str,
    *,
    symbol: str | None = None,
    start: int | None = None,
    end: int | None = None,
) -> pd.DataFrame:
    """Load one source frame, tolerating older call signatures in tests."""
    try:
        return data.load_frame(name, symbol=symbol, start=start, end=end)
    except TypeError:
        return data.load_frame(name, start=start, end=end)


def _load_price(symbol: str | None = None) -> pd.DataFrame:
    frame = _load_frame(data.PRICE_SOURCE, symbol=symbol)
    if frame.empty:
        name = data.normalize_symbol(symbol)
        raise FileNotFoundError(f"No Delta {name} candle cache; refresh ML data first")
    return frame


def _frames(symbol: str | None = None) -> dict[str, pd.DataFrame]:
    sources = data.sources_for(symbol)
    return {name: _load_frame(name, symbol=symbol) for name in sources if name != data.PRICE_SOURCE}


def _frames_with_live(start: int | None, symbol: str | None = None) -> dict[str, pd.DataFrame]:
    """Saved history from ``start`` with the live engine's newer readings on top."""
    from ml_signals.live import merge_frames, recent_frames

    try:
        live = recent_frames(symbol)
    except TypeError:
        live = recent_frames()
    floor = 0 if start is None else int(start)
    out = {}
    for name in data.sources_for(symbol):
        saved = _load_frame(name, symbol=symbol, start=start)
        recent = live.get(name)
        out[name] = saved if recent is None or recent.empty else merge_frames(saved, recent, floor)
    return out


def load_active_model(symbol: str | None = None) -> dict[str, Any]:
    """The active version for a symbol, reloaded only when current.json changes.

    Returns ``{"stamp", "version", "metrics", "models": {interval: entry}}``.
    """
    key = data.normalize_symbol(symbol)
    version = current_version(key)
    if version is None:
        raise FileNotFoundError("No active model. Train and activate one first.")
    current = symbol_dir(key) / "current.json"
    stamp = current.stat().st_mtime_ns
    cached = _active_model.get(key)
    if cached is not None and cached["stamp"] == stamp:
        return cached
    loaded = load_version(key, version)
    entry = {"stamp": stamp, "version": version, **loaded}
    _active_model[key] = entry
    return entry


def interval_entry(active: dict[str, Any] | None, interval: str) -> dict[str, Any] | None:
    """One interval's model from an active version, or the entry itself if it is one."""
    if active is None:
        return None
    if "model" in active:
        return active
    entry = (active.get("models") or {}).get(interval)
    if entry is None:
        return None
    return {**entry, "version": active.get("version"), "metrics": active.get("metrics") or {}}


def class_probabilities(entry: dict[str, Any], features: pd.DataFrame) -> np.ndarray:
    """Probabilities as columns WAIT, LONG, SHORT for each feature row."""
    numeric = features.select_dtypes(include=[np.number])
    if entry["columns"] is not None:
        numeric = numeric.reindex(columns=entry["columns"])
    numeric = numeric.fillna(entry["medians"]).fillna(0)
    model = entry["model"]
    raw = model.predict_proba(numeric.to_numpy())
    out = np.zeros((len(numeric), 3), dtype=float)
    for source_index, class_value in enumerate(model.classes_):
        if int(class_value) in (0, 1, 2):
            out[:, int(class_value)] = raw[:, source_index]
    return out


def _save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, default=_json_default))
    temp.replace(path)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def run_rule_search(symbol: str | None = None) -> dict[str, Any]:
    symbol_name = data.normalize_symbol(symbol)
    result = run_search(_load_price(symbol_name), sentiment_frames=_frames(symbol_name))
    _save_json(RESULTS.with_name(f"search_results_{symbol_name.lower()}.json"), result)
    return result


def label_preview(
    stop_pct: float,
    target_pct: float,
    hold_minutes: int,
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    from ml_signals.labels import plan_from_settings, preview_counts

    symbol_name = data.normalize_symbol(symbol)
    price = _load_price(symbol_name)
    output = {}
    for interval, minutes in (("1m", 1), ("3m", 3), ("5m", 5), ("15m", 15)):
        frame = price if minutes == 1 else _resample(price, minutes)
        output[interval] = preview_counts(
            frame,
            stop_pct=stop_pct,
            target_pct=target_pct,
            max_hold_minutes=hold_minutes,
            fee_plan=plan_from_settings(symbol_name),
        )
    return output


def run_training(
    config: TrainConfig,
    update: Callable[..., None] | None = None,
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    symbol_name = data.normalize_symbol(symbol)
    price = _load_price(symbol_name)
    frames = _frames(symbol_name) if config.sentiment_enabled else None
    bars = {
        interval: price if interval == "1m" else _resample(price, int(interval[:-1]))
        for interval in config.intervals
    }
    return train_model(
        bars,
        sentiment_frames=frames,
        config=config,
        symbol=symbol_name,
        progress=(
            lambda message, progress: update(progress=progress, message=message) if update else None
        ),
    )


def predict(
    interval: str,
    from_time: int | None = None,
    to_time: int | None = None,
    *,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Per-bar probabilities for a chart window, saved history plus live readings."""
    if interval not in INTERVALS:
        return []
    symbol_name = data.normalize_symbol(symbol)
    try:
        active = load_active_model(symbol_name)
    except TypeError:
        # Test doubles may still expose the old no-arg shape.
        active = load_active_model()
    entry = interval_entry(active, interval)
    if entry is None:
        return []
    minutes = int(interval[:-1])
    seconds = minutes * 60
    start = None if from_time is None else int(from_time) - WARMUP_SECONDS
    frames = _frames_with_live(start, symbol_name)
    price = frames.pop(data.PRICE_SOURCE)
    if price.empty:
        raise FileNotFoundError(f"No Delta {symbol_name} candle cache; refresh ML data first")
    bars = price if minutes == 1 else _resample(price, minutes)
    features = build_features(
        bars, interval=interval, sentiment_frames=frames, as_of=int(time.time())
    )
    bar_times = bars["time"].to_numpy(dtype="int64") // seconds * seconds
    keep = np.ones(len(bars), dtype=bool)
    if from_time is not None:
        keep &= bar_times >= int(from_time) // seconds * seconds
    if to_time is not None:
        keep &= bar_times <= int(to_time)
    rows = np.flatnonzero(keep)
    if not len(rows):
        return []
    selected = features.iloc[rows]
    probabilities = class_probabilities(entry, selected)
    sentiment = selected.get("sent_sentiment_composite")
    decisions = decide_rows(entry, probabilities, selected)
    output = []
    for position, index in enumerate(rows):
        score = None if sentiment is None else sentiment.iloc[position]
        output.append(
            {
                "time": int(bar_times[index]),
                "p_wait": float(probabilities[position, 0]),
                "p_long": float(probabilities[position, 1]),
                "p_short": float(probabilities[position, 2]),
                "sentiment": float(score) if score is not None and pd.notna(score) else None,
                "version": entry["version"],
                "symbol": symbol_name,
                **decisions[position],
            }
        )
    return output


def decide_rows(
    entry: dict[str, Any], probabilities: np.ndarray, features: pd.DataFrame
) -> list[dict[str, Any]]:
    """Each row's action, expected values and stop/target distances.

    A model from the first trainer has no decision parameters; its rows say
    WAIT with a reason rather than inventing levels it was never judged on.
    """
    from ml_signals.decision import decide

    params = entry.get("decision")
    if params is None:
        return [
            {"action": "WAIT", "reason": "This model predates after-fee scoring. Retrain it."}
            for _ in range(len(probabilities))
        ]
    atr = features["atr_14_pct"].to_numpy(dtype=float)
    return [
        decide(float(row[1]), float(row[2]), float(atr[i]), params)
        for i, row in enumerate(probabilities)
    ]


def current_sentiment(interval: str = "15m", *, symbol: str | None = None) -> dict[str, Any]:
    minutes = int(interval[:-1])
    symbol_name = data.normalize_symbol(symbol)
    frames = _frames_with_live(int(time.time()) - WARMUP_SECONDS, symbol_name)
    price = frames.pop(data.PRICE_SOURCE)
    if price.empty:
        raise FileNotFoundError(f"No Delta {symbol_name} candle cache; refresh ML data first")
    frame = price if minutes == 1 else _resample(price, minutes)
    sentiment = build_features(
        frame, interval=interval, sentiment_frames=frames, as_of=int(time.time())
    )
    row = sentiment.iloc[-1]
    return {
        "interval": interval,
        "symbol": symbol_name,
        "score": float(row.get("sent_sentiment_composite", np.nan))
        if pd.notna(row.get("sent_sentiment_composite"))
        else None,
        "drivers": {
            key.removeprefix("sent_"): float(value)
            for key, value in row.items()
            if key.startswith("sent_")
            and isinstance(value, (int, float, np.floating))
            and pd.notna(value)
        },
    }


def _resample(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    bucket = (frame.time.astype("int64") // (minutes * 60)).to_numpy()
    grouped = frame.groupby(bucket, sort=True)
    return grouped.agg(
        time=("time", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index(drop=True)
