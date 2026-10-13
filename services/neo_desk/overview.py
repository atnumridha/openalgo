"""Contextual market overview with explicit partial coverage and timestamp uncertainty."""

import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal as D

from utils.httpx_client import get_httpx_client
from utils.thread_safe_cache import LockedTTLCache

from .types import IST

MEMBERS_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"
cache = LockedTTLCache(maxsize=8, ttl=30)
members_cache = LockedTTLCache(maxsize=1, ttl=86400)


def positive(value):
    try:
        v = D(str(value))
        return v if v.is_finite() and v > 0 else None
    except Exception:
        return None


def stamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def fresh(q, now):
    t = stamp(q.get("timestamp"))
    return bool(t and 0 <= (now - t).total_seconds() <= 30)


def stale(q, now):
    t = stamp(q.get("timestamp"))
    return bool(t and not 0 <= (now - t).total_seconds() <= 30)


def market_overview(index_quote, confirmed_bars, constituent_quotes, now):
    quote = index_quote or {}
    price = positive(quote.get("ltp"))
    previous = positive(quote.get("prev_close"))
    change = price - previous if price and previous else None
    up = down = flat = 0
    for q in constituent_quotes[:50]:
        last = positive(q.get("ltp"))
        prev = positive(q.get("prev_close"))
        if not last or not prev or stale(q, now):
            continue
        if last > prev:
            up += 1
        elif last < prev:
            down += 1
        else:
            flat += 1
    rsi = None
    if len(confirmed_bars) >= 15 and all(
        b.confirmed and not b.repaired for b in confirmed_bars[-15:]
    ):
        differences = [
            b.close - a.close for a, b in zip(confirmed_bars, confirmed_bars[1:], strict=False)
        ]
        gain = sum(max(v, D(0)) for v in differences[:14]) / 14
        loss = sum(max(-v, D(0)) for v in differences[:14]) / 14
        for value in differences[14:]:
            gain = (gain * 13 + max(value, D(0))) / 14
            loss = (loss * 13 + max(-value, D(0))) / 14
        rsi = (
            D(100)
            if loss == 0 and gain > 0
            else D(50)
            if loss == gain == 0
            else 100 - 100 / (1 + gain / loss)
        )
    local = now.astimezone(IST)
    is_open = local.weekday() < 5 and 555 <= local.hour * 60 + local.minute < 930
    return {
        "price": str(price) if price else None,
        "previous_close": str(previous) if previous else None,
        "change": str(change) if change is not None else None,
        "change_pct": str(change / previous * 100) if change is not None else None,
        "rsi14": str(rsi.quantize(D(".01"))) if rsi is not None else None,
        "advances": up,
        "declines": down,
        "unchanged": flat,
        "covered": up + down + flat,
        "missing": 50 - up - down - flat,
        "total": 50,
        "fresh": fresh(quote, now),
        "exchange_time": quote.get("timestamp"),
        "observed_at": now.isoformat(),
        "market_session": "cash session" if is_open else "closed",
        "source": "Kotak broker snapshots; RSI from confirmed NIFTY 15m bars",
        "timestamp_note": "Exchange quote timestamp unavailable"
        if not stamp(quote.get("timestamp"))
        else None,
    }


def constituents():
    existing = members_cache.get("nifty50")
    if existing:
        return existing
    response = get_httpx_client().get(
        MEMBERS_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,*/*;q=0.8",
            "Referer": "https://www.niftyindices.com/",
        },
        timeout=5,
    )
    response.raise_for_status()
    symbols = [row["Symbol"].strip() for row in csv.DictReader(io.StringIO(response.text))]
    if len(set(symbols)) != 50 or any(
        not s or len(s) > 30 or not all(c.isalnum() or c in "-&" for c in s) for s in symbols
    ):
        raise ValueError("Official NIFTY 50 membership could not be verified.")
    members_cache["nifty50"] = symbols
    return symbols


def live_overview(owner):
    existing = cache.get(owner)
    if existing:
        return existing
    from database.auth_db import get_auth_token
    from services.history_service import get_history
    from services.quotes_service import get_multiquotes, get_quotes

    from .runner import closed_bars

    auth = get_auth_token(owner)
    now = datetime.now(IST)
    errors = []
    index = {}
    bars = []
    quotes = []
    if auth:
        ok, response, _ = get_quotes("NIFTY", "NSE_INDEX", auth_token=auth, broker="kotak")
        index = response.get("data", {}) if ok else {}
        if not ok:
            errors.append("NIFTY broker quote unavailable.")
        ok, response, _ = get_history(
            "NIFTY",
            "NSE_INDEX",
            "15m",
            (now.date() - timedelta(days=35)).isoformat(),
            now.date().isoformat(),
            auth_token=auth,
            broker="kotak",
        )
        bars = closed_bars(response.get("data", []), now) if ok else []
        if not ok:
            errors.append("Confirmed NIFTY history unavailable; RSI is unresolved.")
        try:
            from database.token_db import get_symbol_info

            members = constituents()
            symbols = []
            for symbol in members:
                native = symbol if get_symbol_info(symbol, "NSE") else symbol + "-EQ"
                symbols.append({"symbol": native, "exchange": "NSE"})
            ok, response, _ = get_multiquotes(symbols, auth_token=auth, broker="kotak")
            records = response.get("results", []) if ok else []
            quotes = [row.get("data", {}) for row in records if isinstance(row, dict)]
            if not ok:
                errors.append("Constituent quotes unavailable; breadth is partial.")
        except Exception:
            errors.append(
                "Official membership or constituent quotes unavailable; breadth is partial."
            )
    else:
        errors.append("Connect Kotak to refresh market context.")
    result = market_overview(index, bars, quotes, datetime.now(IST))
    result["errors"] = errors
    result["members_source"] = MEMBERS_URL
    cache[owner] = result
    return result
