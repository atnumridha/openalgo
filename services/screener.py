"""Bounded analytical snapshots. No orders, subscriptions or execution workers."""

import copy
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from threading import RLock

from database import screener_db as db

FRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "1d"}
FIELDS = {
    "close",
    "open",
    "high",
    "low",
    "volume",
    "bar_change_pct",
    "session_change_pct",
    "ema",
    "sma",
    "rsi",
    "macd",
    "signal",
    "histogram",
    "atr",
    "bb_upper",
    "bb_lower",
    "relative_volume",
    "highest_high",
    "lowest_low",
    "prior_day_high",
    "prior_day_low",
    "support",
    "resistance",
    "candle_pattern",
}
OPS = {"gt", "gte", "lt", "lte", "eq", "cross_above", "cross_below", "within_pct"}
PATTERNS = {
    "all",
    "engulfing",
    "rejection",
    "inside-break",
    "star",
    "marubozu",
    "three-candles",
    "piercing",
}
MAX_PAYLOAD = 256_000
_lock = RLock()
_pool = None
_jobs = {}
_pending = {}
_cache = {}
JOB_TTL = 900
CACHE_TTL = 3600


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def validate_items(items, limit=500):
    if not isinstance(items, list) or len(items) > limit:
        raise ValueError(f"items must contain at most {limit} instruments")
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid instrument")
        for field, maximum in [("symbol", 100), ("exchange", 20)]:
            v = item.get(field)
            if (
                not isinstance(v, str)
                or not v.strip()
                or len(v) > maximum
                or any(ord(c) < 32 for c in v)
            ):
                raise ValueError("Invalid instrument identity")
        clean = {
            "symbol": item["symbol"].strip().upper(),
            "exchange": item["exchange"].strip().upper(),
        }
        if "name" in item:
            if not isinstance(item["name"], str) or len(item["name"]) > 200:
                raise ValueError("Invalid instrument name")
            clean["name"] = item["name"]
        result.append(clean)
    return result


def validate_definition(value):
    if not isinstance(value, dict):
        raise ValueError("definition must be an object")
    d = copy.deepcopy(value)
    if type(d.get("version")) is not int or d["version"] != 1:
        raise ValueError("Unsupported schema version")
    if (
        not isinstance(d.get("name"), str)
        or not 1 <= len(d["name"].strip()) <= 64
        or len(d["name"]) > 64
    ):
        raise ValueError("Name must have 1 to 64 characters")
    d["name"] = d["name"].strip()
    if d.get("interval") not in FRAMES or d.get("intent") not in {"observe", "bullish", "bearish"}:
        raise ValueError("Invalid timeframe or intent")
    u = d.get("universe")
    if not isinstance(u, dict) or u.get("kind") not in {"stored", "watchlist", "nifty50", "custom"}:
        raise ValueError("Invalid universe")
    if u["kind"] == "watchlist" and (type(u.get("id")) is not int or u["id"] < 1):
        raise ValueError("Invalid watchlist id")
    if "items" in u:
        u["items"] = validate_items(u["items"])
    leaves = 0

    def operand(v):
        if finite(v) and abs(v) <= 1e15:
            return
        if not isinstance(v, dict) or v.get("field") not in FIELDS:
            raise ValueError("Unsupported operand")
        if "offset" in v and (type(v["offset"]) is not int or v["offset"] not in (0, 1)):
            raise ValueError("Offset must be 0 or 1")
        if "period" in v and (type(v["period"]) is not int or not 1 <= v["period"] <= 500):
            raise ValueError("Period must be 1 to 500")
        if "pattern" in v and v["pattern"] not in PATTERNS:
            raise ValueError("Unsupported pattern")

    def node(n, depth):
        nonlocal leaves
        if (
            not isinstance(n, dict)
            or depth > 3
            or not isinstance(n.get("id"), str)
            or not 1 <= len(n["id"]) <= 80
        ):
            raise ValueError("Invalid rule or depth exceeds 3")
        if "enabled" in n and type(n["enabled"]) is not bool:
            raise ValueError("Invalid enabled state")
        if n.get("type") == "group":
            children = n.get("children")
            if (
                n.get("op") not in {"all", "any"}
                or not isinstance(children, list)
                or len(children) > 24
            ):
                raise ValueError("Invalid group")
            for c in children:
                node(c, depth + 1)
        elif n.get("type") == "condition":
            leaves += 1
            if leaves > 24 or n.get("op") not in OPS:
                raise ValueError("Unsupported condition or more than 24 leaves")
            operand(n.get("left"))
            operand(n.get("right"))
            if n["op"] == "within_pct" and (
                not finite(n.get("tolerance")) or not 0 <= n["tolerance"] <= 100
            ):
                raise ValueError("Invalid tolerance")
        else:
            raise ValueError("Unsupported node")

    if not isinstance(d.get("rule"), dict) or d["rule"].get("type") != "group":
        raise ValueError("Root must be a group")
    node(d["rule"], 0)
    return d


def validate_events(events, mode):
    if mode not in {"live", "analyzer"} or not isinstance(events, list) or len(events) > 100:
        raise ValueError("Invalid mode or events (maximum 100)")
    now = time.time()
    result = []
    directions = {
        "MATCH",
        "BULLISH setup",
        "BEARISH setup",
        "LONG setup",
        "SHORT setup",
        "BUY CE",
        "BUY PE",
        "AVOID CE",
        "AVOID PE",
    }
    for event in events:
        item = validate_items([event])[0]
        t = event.get("time")
        observed = event.get("observedAt")
        if (
            not finite(t)
            or type(t) is not int
            or not 0 < t <= now + 2
            or not finite(observed)
            or not t <= observed <= now + 2
        ):
            raise ValueError("Invalid event timestamps")
        if now - observed > 90:
            raise ValueError("Stale observations cannot create alert events")
        if event.get("direction") not in directions:
            raise ValueError("Invalid event direction")
        source = event.get("source")
        if not isinstance(source, str) or not 1 <= len(source) <= 80:
            raise ValueError("Invalid source")
        result.append(
            {
                **item,
                "time": t,
                "observedAt": observed,
                "direction": event["direction"],
                "source": source,
            }
        )
    return result


def read_catalog():
    from database.historify_db import get_data_catalog

    return get_data_catalog()


def read_watchlists(owner):
    from database.watchlist_db import get_watchlists

    return get_watchlists(owner)


def read_bars(symbol, exchange, interval, **kwargs):
    from database.historify_db import get_ohlcv

    return get_ohlcv(symbol, exchange, interval, **kwargs)


def universes(owner):
    result = []
    errors = []
    try:
        unique = {}
        for row in read_catalog():
            item = validate_items([{"symbol": row["symbol"], "exchange": row["exchange"]}])[0]
            unique[(item["symbol"], item["exchange"])] = item
        result.append(
            {
                "id": "stored",
                "label": "Downloaded data",
                "items": list(unique.values())[:500],
                "coverage": {"available": len(unique), "limit": 500},
            }
        )
    except Exception:
        result.append({"id": "stored", "label": "Downloaded data", "items": []})
        errors.append({"source": "stored", "message": "Downloaded catalog unavailable"})
    try:
        for row in read_watchlists(owner):
            result.append(
                {
                    "id": f"watchlist:{row['id']}",
                    "label": row["name"],
                    "items": validate_items(row["items"]),
                }
            )
    except Exception:
        errors.append({"source": "watchlists", "message": "Watchlists unavailable"})
    # No bundled list claims current official index membership.
    errors.append(
        {"source": "nifty50", "message": "Official current NIFTY50 membership is not connected"}
    )
    result.append(
        {
            "id": "crypto",
            "label": "Crypto presets",
            "items": [
                {"symbol": "BTCUSD", "exchange": "DELTA"},
                {"symbol": "ETHUSD", "exchange": "DELTA"},
            ],
        }
    )
    return {"universes": result, "errors": errors}


def normalize_bars(rows):
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")
    if not isinstance(rows, list):
        raise ValueError("Invalid candle source")
    result = {}
    for row in rows:
        stamp = row.get("time", row.get("timestamp"))
        if not finite(stamp) or stamp <= 0 or int(stamp) != stamp:
            raise ValueError("Invalid UTC candle timestamp")
        values = [row.get(k) for k in ("open", "high", "low", "close")]
        if any(not finite(v) or v <= 0 for v in values):
            raise ValueError("Invalid source candle")
        opening, high, low, close = values
        if low > min(opening, close) or high < max(opening, close):
            raise ValueError("Invalid source candle geometry")
        volume = row.get("volume")
        if volume is not None and (not finite(volume) or volume < 0):
            raise ValueError("Invalid source volume")
        candle = {
            "time": int(stamp),
            "open": float(opening),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": volume,
        }
        if stamp in result and result[stamp] != candle:
            raise ValueError("Conflicting source candles")
        result[stamp] = candle
    return sorted(result.values(), key=lambda x: x["time"])[-600:]


def observation(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.timestamp()
    elif isinstance(value, str):
        try:
            return observation(datetime.fromisoformat(value))
        except ValueError:
            return 0
    return float(value) if finite(value) and 0 < value <= time.time() + 2 else 0


def metadata(symbol, exchange):
    from database.market_calendar_db import get_market_timing
    from services.symbol_service import get_symbol_info

    result = {"session": None}
    try:
        ok, response, _ = get_symbol_info(symbol, exchange)
        tick = response.get("data", {}).get("tick_size") if ok else None
        if tick is not None and finite(float(tick)) and float(tick) > 0:
            result["tickSize"] = float(tick)
    except Exception:
        pass
    if exchange == "DELTA":
        return result
    try:
        timing = get_market_timing({"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange, exchange))
        if timing:
            result["session"] = {
                "start": timing["start_offset"] / 60000,
                "end": timing["end_offset"] / 60000,
                "offset": 19800,
            }
    except Exception:
        pass
    return result


def _missing(item, interval, message):
    return {
        **item,
        "interval": interval,
        "source": "unavailable",
        "observedAt": 0,
        "session": None,
        "candles": [],
        "daily": [],
        "error": message,
    }


def stored_dataset(owner, mode, item, interval, broker=None, catalog=None):
    cache_key = (owner, mode, broker, item["exchange"], item["symbol"], interval)
    with _lock:
        cached = _cache.get(cache_key)
        cached_data = (
            copy.deepcopy(cached[1])
            if cached and time.monotonic() - cached[0] < CACHE_TTL
            else None
        )
    try:
        source_interval = "D" if interval == "1d" else "1m"
        catalog = [
            r
            for r in (read_catalog() if catalog is None else catalog)
            if r["symbol"] == item["symbol"] and r["exchange"] == item["exchange"]
        ]
        matching = [r for r in catalog if r["interval"] == source_interval]
        observed = observation(matching[0].get("last_download_at")) if matching else 0
        if observed:
            # Bound DB materialisation to a recent window; aggregation remains
            # Historify's exchange-aligned UTC implementation.
            seconds = {
                "1m": 60,
                "3m": 180,
                "5m": 300,
                "15m": 900,
                "30m": 1800,
                "1h": 3600,
                "1d": 86400,
            }[interval]
            rows = read_bars(
                item["symbol"],
                item["exchange"],
                "D" if interval == "1d" else interval,
                start_timestamp=max(1, int(observed) - max(600 * seconds * 4, 86400 * 7)),
                end_timestamp=int(observed),
            )
            candles = normalize_bars(rows)
            if candles:
                daily = []
                daily_catalog = [r for r in catalog if r["interval"] == "D"]
                daily_observed = (
                    observation(daily_catalog[0].get("last_download_at")) if daily_catalog else 0
                )
                if daily_observed and daily_observed <= observed:
                    daily = normalize_bars(
                        read_bars(
                            item["symbol"],
                            item["exchange"],
                            "D",
                            start_timestamp=int(observed) - 86400 * 900,
                            end_timestamp=int(daily_observed),
                        )
                    )
                result = {
                    **item,
                    "interval": interval,
                    "source": "historify",
                    "observedAt": observed,
                    "candles": candles,
                    "daily": daily,
                    **metadata(item["symbol"], item["exchange"]),
                }
                if item["exchange"] != "DELTA" and not result.get("session"):
                    result["error"] = "Verified instrument session unavailable"
                if cached_data and (
                    result.get("error") or cached_data.get("observedAt", 0) > result["observedAt"]
                ):
                    return cached_data
                return result
    except Exception:
        # A prior verified snapshot retains its original source observation.
        if cached_data:
            return cached_data
        return _missing(item, interval, "Stored source contains invalid or unreadable data")
    if cached_data:
        return cached_data
    return _missing(item, interval, "No verified stored history; load data explicitly")


def refresh_dataset(owner, mode, item, interval, credentials):
    if item["exchange"] == "DELTA":
        return _missing(item, interval, "Use the public Delta history adapter for this instrument")
    if not credentials.get("auth_token") or not credentials.get("broker"):
        return _missing(item, interval, "Active broker connection required")
    from services.history_service import get_history
    from utils.db_sessions import remove_all_scoped_sessions

    try:
        observed = time.time()  # Capture BEFORE either request, including rate-limit wait.
        today = datetime.now(UTC).date()
        kwargs = {**credentials, "background": True}
        ok, response, _ = get_history(
            item["symbol"],
            item["exchange"],
            interval,
            (today - timedelta(days=900 if interval == "1d" else 30)).isoformat(),
            today.isoformat(),
            **kwargs,
        )
        if not ok:
            return _missing(item, interval, "Broker history unavailable")
        candles = normalize_bars(response.get("data", []))
        daily = []
        if interval == "1d":
            daily = candles
        else:
            ok_daily, response_daily, _ = get_history(
                item["symbol"],
                item["exchange"],
                "1d",
                (today - timedelta(days=900)).isoformat(),
                today.isoformat(),
                **kwargs,
            )
            if ok_daily:
                daily = normalize_bars(response_daily.get("data", []))
        result = {
            **item,
            "interval": interval,
            "source": f"broker:{credentials['broker']}",
            "observedAt": observed,
            "candles": candles,
            "daily": daily,
            **metadata(item["symbol"], item["exchange"]),
        }
        if not candles:
            result["error"] = "Broker returned no candles"
        if not result.get("session"):
            result["error"] = "Verified instrument session unavailable"
        if not result.get("error"):
            with _lock:
                _cache[
                    (owner, mode, credentials["broker"], item["exchange"], item["symbol"], interval)
                ] = (time.monotonic(), copy.deepcopy(result))
                while len(_cache) > 1000:
                    _cache.pop(next(iter(_cache)))
        return result
    except Exception:
        return _missing(item, interval, "Broker source contains invalid or unreadable data")
    finally:
        remove_all_scoped_sessions()


def _prune():
    now = time.monotonic()
    for identity, job in list(_jobs.items()):
        if now - job["created"] > JOB_TTL:
            _jobs.pop(identity)
    for key, (future, created) in list(_pending.items()):
        if future.done() and now - created > 2:
            _pending.pop(key)
    for key, (created, _) in list(_cache.items()):
        if now - created > CACHE_TTL:
            _cache.pop(key)


def start_job(owner, mode, items, interval, credentials):
    global _pool
    items = validate_items(items, 25)
    if mode not in {"live", "analyzer"} or interval not in FRAMES:
        raise ValueError("Invalid mode or timeframe")
    with _lock:
        _prune()
        active = sum(
            1
            for j in _jobs.values()
            if j["owner"] == owner
            and not j["cancelled"]
            and any(not f.done() for _, f in j["work"])
        )
        if (
            active >= 4
            or len(_jobs) >= 128
            or sum(not f.done() for f, _ in _pending.values()) + len(items) > 128
        ):
            raise db.Conflict("Screener refresh capacity reached; wait or cancel")
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="screener-data")
        work = []
        for item in items:
            key = (
                owner,
                mode,
                credentials.get("broker"),
                item["exchange"],
                item["symbol"],
                interval,
            )
            existing = _pending.get(key)
            if existing and not existing[0].cancelled():
                future = existing[0]
            else:
                future = _pool.submit(
                    refresh_dataset, owner, mode, item, interval, dict(credentials)
                )
                _pending[key] = (future, time.monotonic())
            work.append((item, future))
        identity = uuid.uuid4().hex
        _jobs[identity] = {
            "owner": owner,
            "mode": mode,
            "interval": interval,
            "created": time.monotonic(),
            "work": work,
            "cancelled": False,
        }
        return job_result(owner, identity)


def job_result(owner, identity):
    with _lock:
        _prune()
        job = _jobs.get(identity)
        if not job or job["owner"] != owner:
            raise db.NotFound("Refresh job not found or expired")
        datasets = []
        running = False
        for item, future in job["work"]:
            if future.done() and not future.cancelled():
                try:
                    datasets.append(copy.deepcopy(future.result()))
                except Exception:
                    datasets.append(_missing(item, job["interval"], "Refresh failed"))
            running = running or future.running()
        total = len(job["work"])
        done = len(datasets)
        status = (
            "complete" if done == total or job["cancelled"] else "running" if running else "queued"
        )
        return {
            "job_id": identity,
            "status": status,
            "datasets": datasets,
            "cancelled": job["cancelled"],
            "progress": {
                "completed": done,
                "total": total,
                "failed": sum("error" in d for d in datasets),
            },
        }


def cancel_job(owner, identity):
    with _lock:
        job_result(owner, identity)
        job = _jobs[identity]
        job["cancelled"] = True
        for _, future in job["work"]:
            # A coalesced task can still belong to another active browser job.
            shared = any(
                other is not job
                and not other["cancelled"]
                and any(f is future for _, f in other["work"])
                for other in _jobs.values()
            )
            if not shared:
                future.cancel()
        return job_result(owner, identity)


def reset_runtime():
    global _pool
    with _lock:
        pool = _pool
        _pool = None
        _jobs.clear()
        _pending.clear()
        _cache.clear()
    if pool:
        pool.shutdown(wait=True, cancel_futures=True)
