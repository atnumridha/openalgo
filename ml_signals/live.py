"""Live signal engine for ML symbols.

The research cache on disk changes only when someone presses Refresh data, so a
signal computed from it stops at that moment. This engine holds the recent
window of each source in memory, catches up from saved history, polls each
provider at a cadence that matches how often it can change, and recomputes the
signal once a second for intervals someone viewed recently.

Requests never compute. They read the latest published snapshot.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml_signals import data, predict
from ml_signals.features import build_features
from utils.lazy import LazyInit
from utils.logging import get_logger
from utils.shared_executors import get_executor
from utils.shutdown import register_shutdown_hook

logger = get_logger(__name__)

WINDOW_SECONDS = predict.WARMUP_SECONDS
IDLE_STOP_SECONDS = 60
ACTIVE_INTERVAL_SECONDS = 15
TICK_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 5.0
MAX_FETCHES_PER_TICK = 3
FAILED_RESTART_DELAY_SECONDS = 10
USER_AGENT = "OpenAlgo-MLResearch/1.0"

INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}

POLL_SECONDS = {
    "delta_btcusd": 1,
    "binance_futures": 2,
    "delta_mark": 5,
    "delta_spot_index": 5,
    "delta_open_interest": 5,
    "binance_premium": 5,
    "coinbase_spot": 10,
    "bybit_oi": 30,
    "bybit_account_ratio": 30,
    "delta_funding": 60,
    "deribit_dvol": 60,
    "fear_greed": 600,
}

SOURCE_LABELS = {
    "delta_btcusd": "Delta traded price",
    "delta_mark": "Delta mark price",
    "delta_spot_index": "Delta spot index",
    "delta_open_interest": "Delta open interest",
    "delta_funding": "Delta funding",
    "binance_futures": "Binance futures",
    "binance_premium": "Binance premium",
    "bybit_oi": "Bybit open interest",
    "bybit_account_ratio": "Bybit long/short accounts",
    "deribit_dvol": "Deribit DVOL",
    "coinbase_spot": "Coinbase spot",
    "fear_greed": "Fear & Greed",
}

_PROVIDERS = (
    ("delta_", "Delta Exchange"),
    ("binance_", "Binance"),
    ("bybit_", "Bybit"),
    ("deribit_", "Deribit"),
    ("coinbase_", "Coinbase"),
    ("fear_greed", "alternative.me"),
)


def provider_name(source: str) -> str:
    for prefix, provider in _PROVIDERS:
        if source.startswith(prefix):
            return provider
    return "The data provider"


def live_params(spec: data.SourceSpec, now: int) -> dict[str, Any]:
    """Request parameters for the newest few readings of a source."""
    step = data._interval_seconds(spec.interval)
    if spec.kind in {"delta_candles", "deribit_dvol", "coinbase_candles"}:
        return data._params(spec, now - 5 * step, now)
    params = dict(spec.params)
    if spec.kind == "binance_klines":
        params["limit"] = 5
    elif spec.kind in {"bybit_oi", "bybit_account_ratio"}:
        params["limit"] = 3
    elif spec.kind == "fear_greed":
        params["limit"] = 2
    return params


def fetch_latest(client: httpx.Client, name: str, spec: data.SourceSpec, now: int) -> pd.DataFrame:
    """One request for the newest readings of a source."""
    response = client.get(spec.url, params=live_params(spec, now), timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    if isinstance(body, dict) and (
        body.get("success") is False or body.get("retCode", 0) not in (0, None)
    ):
        raise data.DownloadError(
            f"{name}: provider error {body.get('error') or body.get('retMsg')}"
        )
    frame = data.normalize_records(name, data._parse_page(spec, body), spec)
    return frame[frame["time"] <= now] if not frame.empty else frame


def merge_frames(
    existing: pd.DataFrame | None, update: pd.DataFrame | None, floor: int
) -> pd.DataFrame:
    """Upsert readings by time (newer reading wins) and drop rows below floor."""
    parts = [part for part in (existing, update) if part is not None and not part.empty]
    if not parts:
        return pd.DataFrame(columns=["time"])
    if len(parts) == 1:
        merged = parts[0]
    else:
        merged = pd.concat(parts, ignore_index=True, sort=False)
        merged = merged.drop_duplicates("time", keep="last").sort_values("time")
    merged = merged[merged["time"] >= floor]
    return merged.reset_index(drop=True)


def _signal(
    bar_time: int,
    probabilities: np.ndarray,
    decision: dict[str, Any],
    sentiment: Any,
    close: float,
) -> dict[str, Any]:
    p_wait, p_long, p_short = (float(value) for value in probabilities)
    out = {
        "time": int(bar_time),
        "p_long": p_long,
        "p_short": p_short,
        "p_wait": p_wait,
        "sentiment": float(sentiment) if sentiment is not None and pd.notna(sentiment) else None,
        **decision,
    }
    stop_pct, target_pct = decision.get("stop_pct"), decision.get("target_pct")
    side = 1 if out["action"] == "LONG" else -1 if out["action"] == "SHORT" else 0
    if side and stop_pct and target_pct and close > 0:
        out["reference_price"] = float(close)
        out["stop_price"] = float(close * (1 - side * stop_pct / 100))
        out["target_price"] = float(close * (1 + side * target_pct / 100))
    return out


_NOT_DRIVERS = {"sent_bar_close", "sent_sentiment_composite", "sent_sentiment_sources_count"}


def _sentiment(features: pd.DataFrame, index: int, interval: str) -> dict[str, Any]:
    row = features.iloc[index]
    score = row.get("sent_sentiment_composite")
    drivers = {
        key.removeprefix("sent_"): float(value)
        for key, value in row.items()
        if key.startswith("sent_")
        and key not in _NOT_DRIVERS
        and isinstance(value, (int, float, np.number))
        and not isinstance(value, bool)
        and pd.notna(value)
    }
    count = row.get("sent_sentiment_sources_count")
    return {
        "interval": interval,
        "score": float(score) if score is not None and pd.notna(score) else None,
        "sources_used": int(count) if count is not None and pd.notna(count) else 0,
        "drivers": drivers,
    }


def build_snapshot(
    interval: str,
    frames: dict[str, pd.DataFrame],
    now: float,
    model_entry: dict[str, Any] | None,
    *,
    symbol: str | None = None,
) -> dict[str, Any] | None:
    """The live signal for one interval.

    ``model_entry`` is the active version (all intervals) or one interval's
    entry; either way only this interval's model is used.
    """
    symbol_name = data.normalize_symbol(symbol)
    price = frames.get(data.PRICE_SOURCE)
    if price is None or price.empty:
        return None
    seconds = INTERVAL_MINUTES[interval] * 60
    bars = price if seconds == 60 else predict._resample(price, seconds // 60)
    sources = {name: frame for name, frame in frames.items() if name != data.PRICE_SOURCE}
    features = build_features(bars, interval=interval, sentiment_frames=sources, as_of=int(now))

    bucket_times = bars["time"].to_numpy(dtype="int64") // seconds * seconds
    last = len(bars) - 1
    forming_index = last if int(bucket_times[last]) == int(now) // seconds * seconds else None
    closed_index = last - 1 if forming_index is not None else last
    rows = [index for index in (closed_index, forming_index) if index is not None and index >= 0]

    entry = predict.interval_entry(model_entry, interval)
    signals: dict[int, dict[str, Any]] = {}
    message = None
    if model_entry is None:
        message = "No model is active, so there is no signal yet. Train one below."
    elif entry is None:
        skipped = ((model_entry or {}).get("metrics") or {}).get("skipped_intervals") or {}
        message = skipped.get(interval) or f"The active model has no {interval} model."
    elif rows:
        with threadpool_limits(limits=1, user_api="openmp"):
            probabilities = predict.class_probabilities(entry, features.iloc[rows])
        decisions = predict.decide_rows(entry, probabilities, features.iloc[rows])
        composite = features.get("sent_sentiment_composite")
        close = bars["close"].to_numpy(dtype=float)
        for position, index in enumerate(rows):
            signals[index] = _signal(
                int(bucket_times[index]),
                probabilities[position],
                decisions[position],
                None if composite is None else composite.iloc[index],
                float(close[index]),
            )
        if entry.get("legacy"):
            message = "This model was trained before trades were judged after fees. Retrain it."
        elif not entry.get("promoted"):
            message = entry.get("promotion_reason")

    forming = None
    if forming_index is not None:
        start = int(bucket_times[forming_index])
        forming = {**(signals.get(forming_index) or {"time": start}), "closes_at": start + seconds}
    closed = None
    if closed_index >= 0:
        closed = signals.get(closed_index) or {"time": int(bucket_times[closed_index])}

    entry_view = entry or {}
    return {
        "symbol": symbol_name,
        "interval": interval,
        "computed_at": float(now),
        "price": float(price["close"].iloc[-1]),
        "price_time": int(price["time"].iloc[-1]),
        "model_version": (model_entry or {}).get("version"),
        "model_promoted": bool(entry_view.get("promoted", False)),
        "promotion_reason": entry_view.get("promotion_reason"),
        "forming": forming,
        "closed": closed,
        "sentiment": _sentiment(
            features,
            forming_index if forming_index is not None else closed_index,
            interval,
        ),
        "message": message,
    }


def _source_view(
    name: str, state: dict[str, Any], now: float, spec: data.SourceSpec
) -> dict[str, Any]:
    cadence = POLL_SECONDS.get(name, max(1, data._interval_seconds(spec.interval)))
    last_ok = state.get("last_ok")
    age = None if last_ok is None else max(0.0, now - last_ok)
    if state.get("catching_up"):
        status = "catching_up"
    elif state.get("error"):
        status = "error"
    elif age is None or age > max(10.0, 3.0 * cadence):
        status = "stale"
    else:
        status = "ok"
    return {
        "label": SOURCE_LABELS.get(name, name),
        "status": status,
        "age_seconds": age,
        "newest_time": state.get("newest"),
        "message": state.get("error"),
    }


@dataclass
class _Run:
    """Everything one poller run owns."""

    generation: int
    client: httpx.Client
    next_poll: dict[str, float] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)
    catch_up: tuple[str, Future] | None = None
    computed: dict[str, tuple[int, str | None, int]] = field(default_factory=dict)
    compute_errors: dict[str, str] = field(default_factory=dict)


class LiveEngine:
    """One poller thread that owns in-memory frames and published snapshots."""

    def __init__(self, symbol: str) -> None:
        self.symbol = data.normalize_symbol(symbol)
        self.sources = data.sources_for(self.symbol)
        self.catch_up_order = [
            name
            for name in (
                "delta_mark",
                "delta_spot_index",
                "delta_open_interest",
                "binance_futures",
                "binance_premium",
                "bybit_oi",
                "bybit_account_ratio",
                "delta_funding",
                "deribit_dvol",
                "fear_greed",
                "coinbase_spot",
            )
            if name in self.sources
        ]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._closed = False
        self._running = False
        self._generation = 0
        self._failed_at = 0.0
        self._touched: dict[str, float] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._sources: dict[str, dict[str, Any]] = {name: {} for name in self.sources}
        self._feed_message = "Starting the live feed."
        self._frames: dict[str, pd.DataFrame] = {}
        self._frames_version = 0

    def frames(self) -> dict[str, pd.DataFrame]:
        return self._frames

    def snapshot(self, interval: str) -> dict[str, Any]:
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"unsupported live interval {interval!r}")
        now = time.time()
        self._touch(interval, now)
        with self._lock:
            snapshot = self._snapshots.get(interval)
            states = {name: dict(state) for name, state in self._sources.items()}
            feed = self._feed_message
        sources = {
            name: _source_view(name, state, now, self.sources[name])
            for name, state in states.items()
        }
        base = {"symbol": self.symbol, "feed": feed, "server_time": now, "sources": sources}
        if snapshot is None:
            return {"state": "starting", "interval": interval, **base}
        return {**snapshot, "state": "live", **base}

    def stop(self) -> None:
        with self._lock:
            self._closed = True
            self._running = False
            self._generation += 1
        self._stop.set()

    def _touch(self, interval: str, now: float) -> None:
        with self._lock:
            self._touched[interval] = now
            if self._running or self._closed:
                return
            if now - self._failed_at < FAILED_RESTART_DELAY_SECONDS:
                return
            self._running = True
            self._generation += 1
            generation = self._generation
            self._stop.clear()
            self._snapshots.clear()
            self._feed_message = "Starting the live feed."
        thread = threading.Thread(
            target=self._run,
            args=(generation,),
            name=f"ml-live-signals-{self.symbol}",
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            logger.exception("Could not start ML live signal thread for %s", self.symbol)
            with self._lock:
                if self._generation == generation:
                    self._running = False

    def _keep_running(self, run: _Run) -> bool:
        with self._lock:
            if self._generation != run.generation or self._stop.is_set():
                return False
            latest = max(self._touched.values(), default=0.0)
            if time.time() - latest <= IDLE_STOP_SECONDS:
                return True
            self._running = False
            self._generation += 1
            self._snapshots.clear()
            return False

    def _set_feed(self, message: str) -> None:
        with self._lock:
            self._feed_message = message

    def _update_source(self, name: str, **values: Any) -> None:
        with self._lock:
            self._sources[name] = {**self._sources.get(name, {}), **values}

    def _publish(self, name: str, frame: pd.DataFrame) -> None:
        self._frames = {**self._frames, name: frame}
        self._frames_version += 1

    def _run(self, generation: int) -> None:
        run = _Run(
            generation=generation,
            client=httpx.Client(
                timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
            ),
        )
        try:
            self._set_feed(
                f"Catching up on {SOURCE_LABELS.get(data.PRICE_SOURCE, data.PRICE_SOURCE)}."
            )
            self._update_source(data.PRICE_SOURCE, catching_up=True)
            self._finish_catch_up(
                run,
                data.PRICE_SOURCE,
                self._fetch_gap(run.client, data.PRICE_SOURCE),
            )
            run.pending = list(self.catch_up_order)
            for name in run.pending:
                self._update_source(name, catching_up=True)
            while self._keep_running(run):
                started = time.monotonic()
                self._tick(run)
                self._stop.wait(max(0.05, TICK_SECONDS - (time.monotonic() - started)))
        except Exception:
            logger.exception("ML live signal engine stopped unexpectedly for %s", self.symbol)
            with self._lock:
                self._failed_at = time.time()
                self._feed_message = (
                    "The live feed stopped unexpectedly and restarts in a few seconds. "
                    "Details are in the error log."
                )
        finally:
            if run.catch_up is not None:
                run.catch_up[1].cancel()
            run.client.close()
            with self._lock:
                if self._generation == generation:
                    self._running = False
                    self._generation += 1

    def _fetch_gap(
        self,
        client: httpx.Client,
        name: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame, str | None]:
        """In-memory or saved history, plus whatever is missing up to now."""
        spec = self.sources[name]
        now = int(time.time())
        floor = now - WINDOW_SECONDS
        step = data._interval_seconds(spec.interval)
        base = self._frames.get(name)
        if base is None or base.empty:
            base = data.load_frame(name, symbol=self.symbol, start=floor)
        last = int(base["time"].max()) if not base.empty else floor
        start = max(floor, last - step)
        try:
            update, _, error = data._paginate_source(client, spec, start, now + 1)
        except Exception as exc:
            return base, pd.DataFrame(columns=["time"]), str(exc)
        return base, update, error

    def _finish_catch_up(
        self,
        run: _Run,
        name: str,
        result: tuple[pd.DataFrame, pd.DataFrame, str | None],
    ) -> None:
        base, update, error = result
        now = time.time()
        frame = merge_frames(base, update, int(now) - WINDOW_SECONDS)
        self._publish(name, frame)
        if error:
            logger.warning("ML live catch-up for %s %s stopped early: %s", self.symbol, name, error)
        self._update_source(
            name,
            catching_up=False,
            newest=int(frame["time"].max()) if not frame.empty else None,
            last_ok=None if error else now,
            error=(
                f"{provider_name(name)} did not send the missing history. Live readings continue."
            )
            if error
            else None,
        )
        run.next_poll[name] = now

    def _tick(self, run: _Run) -> None:
        executor = get_executor(f"ml-live-{self.symbol}", 4)
        if run.catch_up is not None and run.catch_up[1].done():
            name, future = run.catch_up
            run.catch_up = None
            try:
                self._finish_catch_up(run, name, future.result())
            except Exception as exc:
                logger.warning("ML live catch-up for %s %s failed: %s", self.symbol, name, exc)
                self._update_source(name, catching_up=False)
                run.next_poll[name] = time.time()
        if run.catch_up is None and run.pending:
            name = run.pending.pop(0)
            self._set_feed(f"Catching up on {SOURCE_LABELS.get(name, name)}.")
            run.catch_up = (name, executor.submit(self._fetch_gap, run.client, name))
        elif run.catch_up is None:
            self._set_feed("Live.")

        now = time.time()
        due = sorted(
            (name for name, at in run.next_poll.items() if at <= now),
            key=lambda name: (name != data.PRICE_SOURCE, run.next_poll[name]),
        )[:MAX_FETCHES_PER_TICK]
        futures: dict[str, Future] = {}
        try:
            futures = {
                name: executor.submit(fetch_latest, run.client, name, self.sources[name], int(now))
                for name in due
            }
        except RuntimeError as exc:
            if "shutdown" in str(exc).lower():
                self._set_feed("Stopping the live feed.")
                self._stop.set()
                return
            raise
        if futures:
            wait_futures(list(futures.values()), timeout=REQUEST_TIMEOUT_SECONDS + 1)
        for name, future in futures.items():
            self._apply_poll(run, name, future, now)
        self._recompute(run, time.time())

    def _apply_poll(self, run: _Run, name: str, future: Future, polled_at: float) -> None:
        spec = self.sources[name]
        cadence = POLL_SECONDS.get(name, max(1, data._interval_seconds(spec.interval)))
        try:
            if not future.done():
                raise TimeoutError("no answer within the request timeout")
            update = future.result()
        except Exception as exc:
            failures = run.failures.get(name, 0) + 1
            run.failures[name] = failures
            run.next_poll[name] = polled_at + min(60.0, cadence * 2 ** min(failures, 6))
            if failures == 1:
                logger.warning("ML live poll for %s %s failed: %s", self.symbol, name, exc)
            self._update_source(name, error=f"{provider_name(name)} did not answer. Retrying.")
            return
        run.failures[name] = 0
        run.next_poll[name] = polled_at + cadence
        existing = self._frames.get(name)
        frame = merge_frames(existing, update, int(polled_at) - WINDOW_SECONDS)
        if existing is None or not frame.equals(existing):
            self._publish(name, frame)
        self._update_source(
            name,
            last_ok=time.time(),
            newest=int(frame["time"].max()) if not frame.empty else None,
            error=None,
        )

    def _recompute(self, run: _Run, now: float) -> None:
        with self._lock:
            active = [i for i, at in self._touched.items() if now - at <= ACTIVE_INTERVAL_SECONDS]
            for interval in [i for i in self._snapshots if i not in active]:
                del self._snapshots[interval]
                run.computed.pop(interval, None)
        if not active:
            return
        try:
            entry = predict.load_active_model(self.symbol)
        except FileNotFoundError:
            entry = None
        except Exception:
            logger.exception("Could not load active ML model for %s", self.symbol)
            entry = None
        frames = self._frames
        key = (self._frames_version, entry["version"] if entry else None, int(now) // 60)
        for interval in active:
            if run.computed.get(interval) == key:
                continue
            try:
                snapshot = build_snapshot(interval, frames, now, entry, symbol=self.symbol)
            except Exception as exc:
                if run.compute_errors.get(interval) != str(exc):
                    run.compute_errors[interval] = str(exc)
                    logger.exception(
                        "ML live signal for %s %s could not be computed", self.symbol, interval
                    )
                continue
            run.compute_errors.pop(interval, None)
            if snapshot is not None:
                with self._lock:
                    self._snapshots[interval] = snapshot
                run.computed[interval] = key
            time.sleep(0)


class _EnginePool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engines: dict[str, LazyInit] = {}

    def get(self, symbol: str | None = None) -> LiveEngine:
        key = data.normalize_symbol(symbol)
        with self._lock:
            lazy = self._engines.get(key)
            if lazy is None:
                lazy = LazyInit(lambda: LiveEngine(key), name=f"ml-live-engine-{key}")
                self._engines[key] = lazy
        return lazy.get()

    def peek(self, symbol: str | None = None) -> LiveEngine | None:
        key = data.normalize_symbol(symbol)
        with self._lock:
            lazy = self._engines.get(key)
        return None if lazy is None else lazy.peek()

    def stop_all(self) -> None:
        with self._lock:
            lazies = list(self._engines.values())
        for lazy in lazies:
            engine = lazy.peek()
            if engine is not None:
                engine.stop()


_ENGINES = _EnginePool()


def get_engine(symbol: str | None = None) -> LiveEngine:
    return _ENGINES.get(symbol)


def recent_frames(symbol: str | None = None) -> dict[str, pd.DataFrame]:
    """Live source frames for one symbol, or empty when never started."""
    engine = _ENGINES.peek(symbol)
    return engine.frames() if engine is not None else {}


def _stop_engines() -> None:
    _ENGINES.stop_all()


register_shutdown_hook(_stop_engines, name="ml-live-signals", budget_s=3.0)
