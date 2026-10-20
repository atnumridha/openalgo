"""Resumable public market-data download for crypto scalp research.

All stored timestamps are UTC seconds. Downloads are incremental, overlap one
bar at page boundaries, and replace duplicate timestamps deterministically.
Unavailable feeds are recorded in a coverage manifest rather than silently
inventing values.

Every source is per traded symbol: the Delta contract with its mark price,
spot index, open interest and funding, the matching Binance and Bybit USDT
pair, the Coinbase pair, Deribit's DVOL where Deribit publishes one, and the
market-wide Fear & Greed index. ``SOURCES`` is BTCUSD's set, and its data lives
directly in ``db/ml_signals/`` where it always has; another symbol's lives in
``db/ml_signals/<SYMBOL>/``. The source names are the same for every symbol,
so features and models are written once.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("OPENALGO_ML_DATA_DIR", ROOT / "db" / "ml_signals"))
MANIFEST = DATA_DIR / "coverage.json"
YEAR_SECONDS = 365 * 24 * 60 * 60


@dataclass(frozen=True)
class SourceSpec:
    name: str
    interval: str
    kind: str
    url: str
    params: dict[str, Any]
    page_seconds: int
    page_limit: int
    timestamp_unit: str = "s"
    timestamp_key: str = "time"
    static_params: tuple[tuple[str, Any], ...] = ()


SOURCES: dict[str, SourceSpec] = {
    "delta_btcusd": SourceSpec(
        "delta_btcusd",
        "1m",
        "delta_candles",
        "https://api.india.delta.exchange/v2/history/candles",
        {"resolution": "1m", "symbol": "BTCUSD"},
        4000 * 60,
        4000,
    ),
    "delta_mark": SourceSpec(
        "delta_mark",
        "1m",
        "delta_candles",
        "https://api.india.delta.exchange/v2/history/candles",
        {"resolution": "1m", "symbol": "MARK:BTCUSD"},
        4000 * 60,
        4000,
    ),
    "delta_spot_index": SourceSpec(
        "delta_spot_index",
        "1m",
        "delta_candles",
        "https://api.india.delta.exchange/v2/history/candles",
        {"resolution": "1m", "symbol": ".DEXBTUSD"},
        4000 * 60,
        4000,
    ),
    "delta_open_interest": SourceSpec(
        "delta_open_interest",
        "1m",
        "delta_candles",
        "https://api.india.delta.exchange/v2/history/candles",
        {"resolution": "1m", "symbol": "OI:BTCUSD"},
        4000 * 60,
        4000,
    ),
    "delta_funding": SourceSpec(
        "delta_funding",
        "1h",
        "delta_candles",
        "https://api.india.delta.exchange/v2/history/candles",
        {"resolution": "1h", "symbol": "FUNDING:BTCUSD"},
        24 * 60 * 60,
        4000,
    ),
    "binance_futures": SourceSpec(
        "binance_futures",
        "1m",
        "binance_klines",
        "https://fapi.binance.com/fapi/v1/klines",
        {"symbol": "BTCUSDT", "interval": "1m", "limit": 1000},
        1000 * 60,
        1000,
        "ms",
    ),
    "binance_premium": SourceSpec(
        "binance_premium",
        "1m",
        "binance_klines",
        "https://fapi.binance.com/fapi/v1/premiumIndexKlines",
        {"symbol": "BTCUSDT", "interval": "1m", "limit": 1000},
        1000 * 60,
        1000,
        "ms",
    ),
    "bybit_oi": SourceSpec(
        "bybit_oi",
        "5m",
        "bybit_oi",
        "https://api.bybit.com/v5/market/open-interest",
        {"category": "linear", "symbol": "BTCUSDT", "intervalTime": "5min", "limit": 200},
        200 * 5 * 60,
        200,
        "ms",
        "timestamp",
    ),
    "bybit_account_ratio": SourceSpec(
        "bybit_account_ratio",
        "5m",
        "bybit_account_ratio",
        "https://api.bybit.com/v5/market/account-ratio",
        {"category": "linear", "symbol": "BTCUSDT", "period": "5min", "limit": 500},
        500 * 5 * 60,
        500,
        "ms",
        "timestamp",
    ),
    "deribit_dvol": SourceSpec(
        "deribit_dvol",
        "1h",
        "deribit_dvol",
        "https://www.deribit.com/api/v2/public/get_volatility_index_data",
        {"currency": "BTC", "resolution": 3600},
        1000 * 60 * 60,
        1000,
        "ms",
    ),
    "coinbase_spot": SourceSpec(
        "coinbase_spot",
        "1m",
        "coinbase_candles",
        "https://api.exchange.coinbase.com/products/BTC-USD/candles",
        {"granularity": 60},
        300 * 60,
        300,
        "s",
    ),
    "fear_greed": SourceSpec(
        "fear_greed",
        "1d",
        "fear_greed",
        "https://api.alternative.me/fng/",
        {"limit": 0, "format": "json"},
        365 * 24 * 60 * 60,
        5000,
        "s",
        "timestamp",
    ),
}

DEFAULT_SYMBOL = "BTCUSD"
PRICE_SOURCE = "delta_btcusd"

#: Assets Deribit publishes a DVOL index for.
DVOL_ASSETS = frozenset({"BTC", "ETH"})


def normalize_symbol(symbol: str | None) -> str:
    """A Delta perpetual's symbol from any spelling: BTCUSD, btcusd, BTCUSDFUT."""
    text = (symbol or DEFAULT_SYMBOL).strip().upper()
    if text.endswith("FUT"):
        text = text[:-3]
    if not text.isalnum() or not text.endswith("USD") or len(text) <= 3:
        raise ValueError(f"unsupported ML symbol {symbol!r}")
    return text


def base_asset(symbol: str) -> str:
    return normalize_symbol(symbol)[:-3]


def _swap(spec: SourceSpec, url: str | None = None, **params: Any) -> SourceSpec:
    merged = {**spec.params, **params}
    return SourceSpec(
        spec.name,
        spec.interval,
        spec.kind,
        url or spec.url,
        merged,
        spec.page_seconds,
        spec.page_limit,
        spec.timestamp_unit,
        spec.timestamp_key,
        spec.static_params,
    )


_SOURCE_CACHE: dict[str, dict[str, SourceSpec]] = {}


def sources_for(symbol: str | None = None) -> dict[str, SourceSpec]:
    """Every source for one traded symbol, under the names BTCUSD's use."""
    symbol = normalize_symbol(symbol)
    cached = _SOURCE_CACHE.get(symbol)
    if cached is not None:
        return cached
    if symbol == DEFAULT_SYMBOL:
        _SOURCE_CACHE[symbol] = SOURCES
        return SOURCES
    base = base_asset(symbol)
    built = {
        "delta_btcusd": _swap(SOURCES["delta_btcusd"], symbol=symbol),
        "delta_mark": _swap(SOURCES["delta_mark"], symbol=f"MARK:{symbol}"),
        "delta_spot_index": _swap(SOURCES["delta_spot_index"], symbol=_spot_index(symbol)),
        "delta_open_interest": _swap(SOURCES["delta_open_interest"], symbol=f"OI:{symbol}"),
        "delta_funding": _swap(SOURCES["delta_funding"], symbol=f"FUNDING:{symbol}"),
        "binance_futures": _swap(SOURCES["binance_futures"], symbol=f"{base}USDT"),
        "binance_premium": _swap(SOURCES["binance_premium"], symbol=f"{base}USDT"),
        "bybit_oi": _swap(SOURCES["bybit_oi"], symbol=f"{base}USDT"),
        "bybit_account_ratio": _swap(SOURCES["bybit_account_ratio"], symbol=f"{base}USDT"),
        "coinbase_spot": _swap(
            SOURCES["coinbase_spot"],
            url=f"https://api.exchange.coinbase.com/products/{base}-USD/candles",
        ),
        "fear_greed": SOURCES["fear_greed"],
    }
    if base in DVOL_ASSETS:
        built["deribit_dvol"] = _swap(SOURCES["deribit_dvol"], currency=base)
    ordered = {name: built[name] for name in SOURCES if name in built}
    _SOURCE_CACHE[symbol] = ordered
    return ordered


def _spot_index(symbol: str) -> str:
    """Delta's spot index for a perpetual, from its product, else the usual spelling."""
    try:
        response = httpx.get(
            f"https://api.india.delta.exchange/v2/products/{symbol}",
            timeout=10,
            headers={"User-Agent": "OpenAlgo-MLResearch/1.0"},
        )
        index = ((response.json().get("result") or {}).get("spot_index") or {}).get("symbol")
        if index:
            return str(index)
    except Exception as exc:
        logger.warning("Could not read Delta's spot index for %s: %s", symbol, exc)
    return f".DE{base_asset(symbol)}USD"


def data_dir(symbol: str | None = None) -> Path:
    """Where a symbol's Parquet files live. BTCUSD keeps the original location."""
    symbol = normalize_symbol(symbol)
    return DATA_DIR if symbol == DEFAULT_SYMBOL else DATA_DIR / symbol


def manifest_path(symbol: str | None = None) -> Path:
    return data_dir(symbol) / "coverage.json"


# Independent feeds are deliberately rate-limited; this downloader can resume
# the next day without restarting a full-year scrape.
_SOURCE_DELAY = {
    "delta_candles": 0.15,
    "binance_klines": 0.15,
    "bybit_oi": 0.25,
    "bybit_account_ratio": 0.25,
    "deribit_dvol": 0.25,
    "coinbase_candles": 0.35,
    "fear_greed": 0.5,
}


class DownloadError(RuntimeError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _manifest(symbol: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(manifest_path(symbol).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_source(name: str, symbol: str | None = None) -> pd.DataFrame:
    path = data_dir(symbol) / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _write_source(name: str, frame: pd.DataFrame, symbol: str | None = None) -> None:
    folder = data_dir(symbol)
    folder.mkdir(parents=True, exist_ok=True)
    frame = frame.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".parquet", dir=folder)
    os.close(fd)
    try:
        frame.to_parquet(tmp_name, index=False, compression="zstd")
        os.replace(tmp_name, folder / f"{name}.parquet")
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _timestamp(value: Any, unit: str) -> int | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if unit == "ms":
        v /= 1000
    elif unit == "us":
        v /= 1_000_000
    return int(v)


def normalize_records(name: str, records: Any, spec: SourceSpec | None = None) -> pd.DataFrame:
    """Normalize a public provider page to timestamped numeric columns."""
    spec = spec or SOURCES[name]
    if isinstance(records, dict):
        records = records.get("data", records.get("list", []))
    if not isinstance(records, list) or not records:
        return pd.DataFrame(columns=["time"])

    rows: list[dict[str, Any]] = []
    for rec in records:
        if isinstance(rec, dict):
            time_value = rec.get(spec.timestamp_key)
            if time_value is None:
                time_value = rec.get("time") or rec.get("timestamp")
            timestamp = _timestamp(time_value, spec.timestamp_unit)
            if timestamp is None:
                continue
            row: dict[str, Any] = {"time": timestamp}
            for key, value in rec.items():
                if key in {"time", "timestamp", "symbol", "pair", "contract"}:
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(number):
                    row[key] = number
            if spec.kind == "delta_candles":
                for field in ("open", "high", "low", "close", "volume"):
                    if field in rec and rec[field] is not None:
                        row[field] = float(rec[field])
            if spec.kind == "binance_klines":
                # Binance kline schema: open time, OHLC, base volume, close time,
                # quote volume, count, taker-buy base, taker-buy quote, ignore.
                row.update(
                    {
                        "open": float(rec[1]),
                        "high": float(rec[2]),
                        "low": float(rec[3]),
                        "close": float(rec[4]),
                        "volume": float(rec[5]),
                        "quote_volume": float(rec[7]),
                        "trade_count": float(rec[8]),
                        "taker_buy_volume": float(rec[9]),
                        "taker_buy_quote_volume": float(rec[10]),
                    }
                )
            elif spec.kind == "coinbase_candles":
                # Coinbase schema is [time, low, high, open, close, volume].
                row.update(
                    {
                        "low": float(rec[1]),
                        "high": float(rec[2]),
                        "open": float(rec[3]),
                        "close": float(rec[4]),
                        "volume": float(rec[5]),
                    }
                )
            rows.append(row)
        elif isinstance(rec, (list, tuple)) and spec.kind == "binance_klines" and len(rec) >= 11:
            timestamp = _timestamp(rec[0], "ms")
            if timestamp is not None:
                rows.append(
                    {
                        "time": timestamp,
                        "open": float(rec[1]),
                        "high": float(rec[2]),
                        "low": float(rec[3]),
                        "close": float(rec[4]),
                        "volume": float(rec[5]),
                        "quote_volume": float(rec[7]),
                        "trade_count": float(rec[8]),
                        "taker_buy_volume": float(rec[9]),
                        "taker_buy_quote_volume": float(rec[10]),
                    }
                )
        elif isinstance(rec, (list, tuple)) and spec.kind == "coinbase_candles" and len(rec) >= 6:
            timestamp = _timestamp(rec[0], "s")
            if timestamp is not None:
                rows.append(
                    {
                        "time": timestamp,
                        "low": float(rec[1]),
                        "high": float(rec[2]),
                        "open": float(rec[3]),
                        "close": float(rec[4]),
                        "volume": float(rec[5]),
                    }
                )
        elif isinstance(rec, (list, tuple)) and spec.kind == "deribit_dvol" and len(rec) >= 5:
            timestamp = _timestamp(rec[0], "ms")
            if timestamp is not None:
                rows.append(
                    {
                        "time": timestamp,
                        "open": float(rec[1]),
                        "high": float(rec[2]),
                        "low": float(rec[3]),
                        "close": float(rec[4]),
                    }
                )
    return (
        pd.DataFrame(rows)
        .drop_duplicates("time", keep="last")
        .sort_values("time")
        .reset_index(drop=True)
    )


def _parse_page(spec: SourceSpec, body: dict[str, Any]) -> list[Any]:
    if spec.kind == "delta_candles":
        return body.get("result") or []
    if spec.kind == "binance_klines":
        return body if isinstance(body, list) else []
    if spec.kind in {"bybit_oi", "bybit_account_ratio"}:
        return (body.get("result") or {}).get("list") or []
    if spec.kind == "deribit_dvol":
        # Deribit returns [timestamp_ms, open, high, low, close] rows.
        return ((body.get("result") or {}).get("data")) or []
    if spec.kind == "coinbase_candles":
        return body if isinstance(body, list) else []
    if spec.kind == "fear_greed":
        return body.get("data") or []
    return []


def _request_body(
    client: httpx.Client,
    spec: SourceSpec,
    params: dict[str, Any],
    *,
    retries: int = 5,
) -> dict[str, Any] | list[Any]:
    """One rate-limited HTTP request with bounded retry/backoff."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = client.get(spec.url, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(min(30.0, (2**attempt) + random.random()))
                continue
            response.raise_for_status()
            body = response.json()
            if isinstance(body, dict) and (
                body.get("success") is False or body.get("retCode", 0) not in (0, None)
            ):
                raise DownloadError(
                    f"{spec.name}: provider error {body.get('error') or body.get('retMsg')}"
                )
            return body
        except (httpx.HTTPError, ValueError, DownloadError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(30.0, (2**attempt) + random.random()))
    raise DownloadError(f"{spec.name}: request failed: {last_error}")


def _paginate_source(
    client: httpx.Client,
    spec: SourceSpec,
    start: int,
    end: int,
    *,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[pd.DataFrame, int, str | None]:
    """Fetch one bounded range using each provider's native pagination."""
    additions: list[pd.DataFrame] = []
    pages = 0
    error = None

    def append_records(records: list[Any]) -> pd.DataFrame:
        frame = normalize_records(spec.name, records, spec)
        if not frame.empty:
            frame = frame[(frame["time"] >= start) & (frame["time"] < end)]
            if not frame.empty:
                additions.append(frame)
        return frame

    if spec.kind == "fear_greed":
        try:
            body = _request_body(client, spec, dict(spec.params))
            append_records(_parse_page(spec, body))
            pages = 1
        except DownloadError as exc:
            error = str(exc)

    elif spec.kind == "binance_klines":
        cursor = start
        max_pages = max(1, math.ceil((end - start) / spec.page_seconds) + 2)
        for _ in range(max_pages):
            if cursor >= end:
                break
            params = dict(spec.params)
            params.update(startTime=cursor * 1000, endTime=end * 1000, limit=spec.page_limit)
            try:
                body = _request_body(client, spec, params)
            except DownloadError as exc:
                error = str(exc)
                break
            records = _parse_page(spec, body)
            frame = append_records(records)
            pages += 1
            if progress:
                progress(spec.name, pages, max_pages)
            time.sleep(_SOURCE_DELAY[spec.kind])
            if frame.empty:
                break
            # Providers may return a cached/newest window ignoring one query
            # bound. Never let out-of-range rows enter the cache or next cursor.
            frame = frame[(frame["time"] >= start) & (frame["time"] < end)]
            if frame.empty:
                break
            if len(records) < spec.page_limit and int(frame["time"].max()) + 60 >= end:
                break
            last = int(frame["time"].max())
            next_cursor = last + 60
            if next_cursor <= cursor:
                error = f"{spec.name}: Binance pagination made no progress at {cursor}"
                break
            cursor = next_cursor
        else:
            if cursor < end and error is None:
                error = f"{spec.name}: pagination safety limit reached before requested end"

    elif spec.kind == "delta_candles":
        cursor = start
        page_span = spec.page_seconds
        max_pages = max(1, math.ceil((end - start) / page_span) + 3)
        for _ in range(max_pages):
            if cursor >= end:
                break
            page_end = min(end, cursor + page_span)
            try:
                body = _request_body(client, spec, _params(spec, cursor, page_end))
            except DownloadError as exc:
                error = str(exc)
                break
            records = _parse_page(spec, body)
            frame = append_records(records)
            pages += 1
            if progress:
                progress(spec.name, pages, max_pages)
            time.sleep(_SOURCE_DELAY[spec.kind])
            if not records or frame.empty:
                break
            if len(records) >= spec.page_limit:
                next_cursor = int(frame["time"].max()) + _interval_seconds(spec.interval)
                if next_cursor <= cursor:
                    error = f"{spec.name}: Delta pagination made no progress at {cursor}"
                    break
                cursor = next_cursor
            else:
                cursor = page_end
        else:
            if cursor < end and error is None:
                error = f"{spec.name}: pagination safety limit reached before requested end"

    elif spec.kind == "deribit_dvol":
        # Deribit returns the newest rows of the window (ascending) and a
        # continuation that is the end_timestamp of the next, older page.
        page_end_ms = end * 1000
        max_pages = max(1, math.ceil((end - start) / spec.page_seconds) + 3)
        for _ in range(max_pages):
            params = dict(spec.params)
            params.update(start_timestamp=start * 1000, end_timestamp=page_end_ms)
            try:
                body = _request_body(client, spec, params)
            except DownloadError as exc:
                error = str(exc)
                break
            records = _parse_page(spec, body)
            append_records(records)
            pages += 1
            if progress:
                progress(spec.name, pages, max_pages)
            time.sleep(_SOURCE_DELAY[spec.kind])
            continuation = (body.get("result") or {}).get("continuation")
            if not records or not continuation:
                break
            if int(continuation) >= page_end_ms:
                error = f"{spec.name}: Deribit pagination made no progress at {page_end_ms}"
                break
            page_end_ms = int(continuation)
        else:
            if error is None:
                error = f"{spec.name}: pagination safety limit reached before requested start"

    elif spec.kind == "coinbase_candles":
        # Coinbase bounds each response by its 300-candle maximum. Its REST
        # response is newest-first, so advance the cursor from returned times.
        cursor = start
        max_pages = max(1, math.ceil((end - start) / spec.page_seconds) + 2)
        for _ in range(max_pages):
            if cursor >= end:
                break
            page_end = min(end, cursor + spec.page_seconds)
            try:
                body = _request_body(client, spec, _params(spec, cursor, page_end))
            except DownloadError as exc:
                error = str(exc)
                break
            records = _parse_page(spec, body)
            frame = append_records(records)
            pages += 1
            if progress:
                progress(spec.name, pages, max_pages)
            time.sleep(_SOURCE_DELAY[spec.kind])
            if not records or frame.empty:
                cursor = page_end
            else:
                cursor = int(frame["time"].max()) + 60
        else:
            if cursor < end and error is None:
                error = f"{spec.name}: pagination safety limit reached before requested end"

    elif spec.kind in {"bybit_oi", "bybit_account_ratio"}:
        # The v5 OI endpoint is cursor-paginated, newest page first, and some
        # endpoints clamp older start/end requests to their most recent window.
        cursor_start = start
        cursor_end = end
        cursor_token: str | None = None
        previous_oldest: int | None = None
        empty_run = 0
        max_pages = min(5000, max(1, math.ceil((end - start) / spec.page_seconds) + 4))
        for _ in range(max_pages):
            params = _params(spec, cursor_start, cursor_end)
            if cursor_token:
                params["cursor"] = cursor_token
            try:
                body = _request_body(client, spec, params)
            except DownloadError as exc:
                error = str(exc)
                break
            records = _parse_page(spec, body)
            frame = append_records(records)
            pages += 1
            if progress:
                progress(spec.name, pages, max_pages)
            time.sleep(_SOURCE_DELAY[spec.kind])
            if frame.empty:
                empty_run += 1
                if empty_run >= 2:
                    break
                cursor_end = max(start, cursor_start - spec.page_seconds)
                cursor_start = max(start, cursor_end - spec.page_seconds)
                cursor_token = None
                continue
            empty_run = 0
            oldest = int(frame["time"].min())
            result = body.get("result") or {}
            next_token = result.get("nextPageCursor") if spec.kind == "bybit_oi" else None
            if next_token and next_token != cursor_token:
                cursor_token = next_token
                cursor_end = oldest
                cursor_start = max(start, oldest - spec.page_seconds)
                continue
            cursor_token = None
            if previous_oldest is not None and oldest >= previous_oldest:
                break
            previous_oldest = oldest
            if oldest <= start:
                break
            cursor_end = oldest - 1
            cursor_start = max(start, cursor_end - spec.page_seconds)
        else:
            if cursor_start > start and error is None:
                error = f"{spec.name}: pagination safety limit reached before requested start"

    if additions:
        frame = pd.concat(additions, ignore_index=True, sort=False)
        frame = (
            frame.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
        )
    else:
        frame = pd.DataFrame(columns=["time"])
    return frame, pages, error


def _params(spec: SourceSpec, start: int, end: int) -> dict[str, Any]:
    params = dict(spec.params)
    if spec.kind in {"delta_candles", "binance_klines"}:
        params.update(
            start=start if spec.timestamp_unit == "s" else start * 1000,
            end=end if spec.timestamp_unit == "s" else end * 1000,
        )
        if spec.kind == "binance_klines":
            params.setdefault("limit", spec.page_limit)
    elif spec.kind in {"bybit_oi", "bybit_account_ratio"}:
        params.update(startTime=start * 1000, endTime=end * 1000)
    elif spec.kind == "deribit_dvol":
        params.update(start_timestamp=start * 1000, end_timestamp=end * 1000)
    elif spec.kind == "coinbase_candles":
        params.update(
            start=datetime.fromtimestamp(start, UTC).isoformat(),
            end=datetime.fromtimestamp(end, UTC).isoformat(),
        )
    return params


def _get_page(
    client: httpx.Client, spec: SourceSpec, start: int, end: int, retries: int = 5
) -> list[Any]:
    params = _params(spec, start, end)
    for attempt in range(retries):
        try:
            response = client.get(spec.url, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(min(30.0, (2**attempt) + random.random()))
                continue
            response.raise_for_status()
            body = response.json()
            if isinstance(body, dict):
                if body.get("success") is False or body.get("retCode", 0) not in (0, None):
                    raise DownloadError(
                        f"{spec.name}: provider error {body.get('error') or body.get('retMsg')}"
                    )
            return _parse_page(spec, body)
        except (httpx.HTTPError, ValueError) as exc:
            if attempt + 1 == retries:
                raise DownloadError(
                    f"{spec.name}: request failed for {start}-{end}: {exc}"
                ) from exc
            time.sleep(min(30.0, (2**attempt) + random.random()))
    raise DownloadError(f"{spec.name}: retries exhausted for {start}-{end}")


def _existing_bounds(frame: pd.DataFrame) -> tuple[int | None, int | None]:
    if frame.empty or "time" not in frame:
        return None, None
    return int(frame["time"].min()), int(frame["time"].max())


def _ranges_to_fetch(name: str, frame: pd.DataFrame, start: int, end: int) -> list[tuple[int, int]]:
    spec = SOURCES[name]
    first, last = _existing_bounds(frame)
    if first is None:
        # First load scans back from the present, stopping at the provider's
        # actual retention edge instead of assuming a full-year archive.
        return [(start, end)]
    # Refresh from the last stored bar with one-bar overlap; fill old leading
    # history only when the cached dataset begins after the requested floor.
    ranges: list[tuple[int, int]] = []
    if first > start + spec.page_seconds:
        ranges.append((start, first))
    refresh_from = max(start, last - spec.page_seconds)
    if refresh_from < end:
        ranges.append((refresh_from, end))
    return ranges


def download_source(
    name: str,
    *,
    days: int = 365,
    client: httpx.Client | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    now: int | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Incrementally download one source and atomically write its Parquet cache."""
    specs = sources_for(symbol)
    if name not in specs:
        raise KeyError(f"unknown sentiment/data source: {name}")
    spec = specs[name]
    now = int(time.time()) if now is None else int(now)
    start, end = now - int(days * 86400), now
    owns_client = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": "OpenAlgo-MLResearch/1.0"})
    try:
        existing = _read_source(name, symbol)
        additions: list[pd.DataFrame] = []
        page_count = 0
        unavailable = None
        for rstart, rend in _ranges_to_fetch(name, existing, start, end):
            try:
                frame, page_count, page_error = _paginate_source(
                    client, spec, rstart, rend, progress=progress
                )
                if not frame.empty:
                    additions.append(frame)
                if page_error:
                    unavailable = page_error
                    logger.warning("ML source %s fetch stopped: %s", name, page_error)
            except DownloadError as exc:
                unavailable = str(exc)
                logger.warning("ML source %s fetch stopped: %s", name, exc)
                break
        pieces = [part for part in (existing, *additions) if not part.empty]
        if pieces:
            result = pd.concat(pieces, ignore_index=True, sort=False)
            result = (
                result.drop_duplicates("time", keep="last")
                .sort_values("time")
                .reset_index(drop=True)
            )
            _write_source(name, result, symbol)
        else:
            result = existing
        first, last = _existing_bounds(result)
        status = {
            "name": name,
            "interval": spec.interval,
            "rows": int(len(result)),
            "first_time": first,
            "last_time": last,
            "first_utc": datetime.fromtimestamp(first, UTC).isoformat() if first else None,
            "last_utc": datetime.fromtimestamp(last, UTC).isoformat() if last else None,
            "span_days": round((last - first) / 86400, 2) if first and last else 0,
            "last_refresh": datetime.now(UTC).isoformat(),
            "pages_requested": page_count,
            "error": unavailable,
        }
        manifest = _manifest(symbol)
        manifest[name] = status
        _atomic_json(manifest_path(symbol), manifest)
        return status
    finally:
        if owns_client:
            client.close()


def coverage_report(symbol: str | None = None) -> dict[str, Any]:
    """Return coverage and missing-window estimates from cached Parquet data.

    Recomputed only when the manifest or a source file changes on disk, since
    scanning a year of minute rows per source takes seconds.
    """
    folder = data_dir(symbol)
    specs = sources_for(symbol)
    signature = tuple(
        (path.name, path.stat().st_mtime_ns) if path.exists() else (path.name, None)
        for path in (manifest_path(symbol), *(folder / f"{name}.parquet" for name in specs))
    )
    key = normalize_symbol(symbol)
    cached = _coverage_cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    report = _coverage_report(symbol)
    _coverage_cache[key] = (signature, report)
    return report


_coverage_cache: dict[str, tuple[tuple, dict[str, Any]]] = {}


def _coverage_report(symbol: str | None = None) -> dict[str, Any]:
    manifest = _manifest(symbol)
    report = {}
    for name, spec in sources_for(symbol).items():
        frame = _read_source(name, symbol)
        info = manifest.get(name, {})
        first, last = _existing_bounds(frame)
        if first is not None and len(frame) > 1:
            diffs = frame["time"].diff().dropna().to_numpy(dtype="int64")
            typical = (
                spec.page_seconds
                if spec.kind in {"bybit_oi", "bybit_account_ratio"}
                else _interval_seconds(spec.interval)
            )
            gap_rows = int((diffs > typical * 1.5).sum())
            gap_seconds = int(
                sum(max(0, int(gap) - typical) for gap in diffs if gap > typical * 1.5)
            )
        else:
            gap_rows, gap_seconds = 0, 0
        report[name] = {
            **info,
            "name": name,
            "interval": spec.interval,
            "rows": int(len(frame)),
            "first_time": first,
            "last_time": last,
            "first_utc": datetime.fromtimestamp(first, UTC).isoformat() if first else None,
            "last_utc": datetime.fromtimestamp(last, UTC).isoformat() if last else None,
            "span_days": round((last - first) / 86400, 2) if first and last else 0,
            "gap_count": gap_rows,
            "gap_seconds": gap_seconds,
            "error": info.get("error"),
        }
    return report


def _interval_seconds(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1]) * 60
    if interval.endswith("h"):
        return int(interval[:-1]) * 3600
    if interval.endswith("d"):
        return int(interval[:-1]) * 86400
    return 60


def download_all(
    *,
    days: int = 365,
    progress: Callable[[str, int, int], None] | None = None,
    now: int | None = None,
    client_factory: Callable[[], httpx.Client] | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Refresh all known public feeds independently; unavailable providers are reported, not fatal."""
    client_factory = client_factory or (
        lambda: httpx.Client(timeout=30, headers={"User-Agent": "OpenAlgo-MLResearch/1.0"})
    )
    specs = sources_for(symbol)
    results = {}
    for name in specs:
        client = client_factory()
        try:
            results[name] = download_source(
                name, days=days, client=client, progress=progress, now=now, symbol=symbol
            )
        except Exception as exc:
            results[name] = {
                "name": name,
                "interval": specs[name].interval,
                "rows": 0,
                "error": str(exc),
            }
            logger.exception("ML source %s download failed", name)
        finally:
            client.close()
    return results


def load_frame(
    name: str,
    *,
    start: int | None = None,
    end: int | None = None,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Load a cached source and optionally bound it to UTC-second limits.

    A source the symbol does not have (DVOL for SOL) loads as an empty frame,
    which features treat as missing rather than as zero.
    """
    if name not in SOURCES:
        raise KeyError(f"unknown sentiment/data source: {name}")
    if name not in sources_for(symbol):
        return pd.DataFrame()
    frame = _read_source(name, symbol)
    if frame.empty:
        return frame
    if start is not None:
        frame = frame[frame["time"] >= int(start)]
    if end is not None:
        frame = frame[frame["time"] <= int(end)]
    return frame.reset_index(drop=True)


def align_asof(
    bars: pd.DataFrame,
    source: pd.DataFrame,
    *,
    max_age_seconds: int | None = None,
) -> pd.DataFrame:
    """Backward-asof align source readings to bars. Never forward-fill from the future."""
    if bars.empty:
        return bars.copy()
    left = bars.sort_values("time").copy()
    if source.empty or "time" not in source:
        for col in source.columns:
            if col != "time" and col not in left:
                left[col] = float("nan")
        return left
    right = source.sort_values("time").drop_duplicates("time", keep="last")
    tolerance = max_age_seconds
    return pd.merge_asof(left, right, on="time", direction="backward", tolerance=tolerance)


def probe_source_coverage(
    client: httpx.Client | None = None,
    *,
    now: int | None = None,
    probes: int = 8,
    spacing_seconds: int = 45 * 86400,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Cheap coverage probe: request a few one-page windows from recent to ~1y ago."""
    now = int(time.time()) if now is None else int(now)
    owns_client = client is None
    client = client or httpx.Client(timeout=20, headers={"User-Agent": "OpenAlgo-MLResearch/1.0"})
    result = {}
    try:
        for name, spec in SOURCES.items():
            if sources and name not in sources:
                continue
            samples = []
            error = None
            for age in range(probes):
                end = now - age * spacing_seconds
                start = end - spec.page_seconds
                try:
                    rows = _get_page(client, spec, start, end, retries=2)
                    frame = normalize_records(name, rows, spec)
                    samples.append(
                        {
                            "requested_start": datetime.fromtimestamp(start, UTC).isoformat(),
                            "rows": int(len(frame)),
                            "first_time": int(frame["time"].min()) if not frame.empty else None,
                            "last_time": int(frame["time"].max()) if not frame.empty else None,
                        }
                    )
                except Exception as exc:
                    error = str(exc)
                    samples.append(
                        {
                            "requested_start": datetime.fromtimestamp(start, UTC).isoformat(),
                            "rows": 0,
                            "error": error,
                        }
                    )
                time.sleep(_SOURCE_DELAY[spec.kind])
            good = [s for s in samples if s.get("rows", 0) > 0]
            result[name] = {
                "interval": spec.interval,
                "probes": samples,
                "oldest_nonempty_utc": min((s["first_time"] for s in good), default=None),
                "oldest_nonempty": datetime.fromtimestamp(
                    min(s["first_time"] for s in good), UTC
                ).isoformat()
                if good
                else None,
                "error": error,
            }
            if progress:
                progress(name, result[name])
    finally:
        if owns_client:
            client.close()
    return result
