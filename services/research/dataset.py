"""Bounded, immutable market data normalization; absent evidence stays absent."""

import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime, time, timezone
from zoneinfo import ZoneInfo

from services.research.costs import decimal_value

MAX_ROWS = 100000
MAX_BODY_BYTES = 20 * 1024 * 1024
IST = ZoneInfo("Asia/Kolkata")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _text(value, name, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be nonempty text of at most {maximum} characters")
    return value.strip()


def _integer(value, name, minimum=1, maximum=100000):
    number = decimal_value(value, name, minimum=minimum, maximum=maximum)
    if number != number.to_integral_value():
        raise ValueError(f"{name} must be a whole number")
    return int(number)


def validate_dataset(payload, now=None):
    if not isinstance(payload, dict):
        raise ValueError("Dataset must be an object")
    name = _text(payload.get("name"), "name")
    provider = _text(payload.get("provider"), "provider")
    raw = payload.get("metadata")
    if not isinstance(raw, dict):
        raise ValueError("Dataset metadata is required")
    if raw.get("timezone") != "Asia/Kolkata" or raw.get("timestamp_convention") != "bar_close":
        raise ValueError("Use Asia/Kolkata and explicit bar_close timestamps")
    underlying = _text(raw.get("underlying_symbol"), "underlying_symbol")
    minutes = _integer(raw.get("bar_minutes"), "bar_minutes", maximum=60)
    try:
        close = time.fromisoformat(raw["session_close"])
        if close.second or close.tzinfo or len(raw["session_close"]) != 5:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError("session_close must use HH:MM") from None
    if close < time(3, 0):
        raise ValueError("Midnight-crossing overnight sessions are not supported")
    opening = None
    if "session_open" in raw:
        try:
            opening = time.fromisoformat(raw["session_open"])
            if opening.second or opening.tzinfo or len(raw["session_open"]) != 5:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError("session_open must use HH:MM") from None
        if opening < time(3, 0) or opening >= close:
            raise ValueError("session_open must be at or after 03:00 and before session_close")
    source = _text(raw.get("source_reference"), "source_reference", 1000)
    contracts = []
    symbols = {underlying}
    if not isinstance(raw.get("contracts"), list) or not 1 <= len(raw["contracts"]) <= 2000:
        raise ValueError("Supply between 1 and 2000 point-in-time contracts")
    for item in raw["contracts"]:
        if not isinstance(item, dict):
            raise ValueError("Each contract must be an object")
        symbol = _text(item.get("symbol"), "contract symbol")
        if symbol in symbols:
            raise ValueError("Contract symbols must be unique and distinct from the underlying")
        symbols.add(symbol)
        if (
            item.get("underlying") != underlying
            or item.get("option_type") not in ("CE", "PE")
            or item.get("segment") not in ("index", "mcx")
        ):
            raise ValueError("Contract underlying, option_type and segment are required")
        try:
            expiry = date.fromisoformat(item["expiry"]).isoformat()
        except (KeyError, TypeError, ValueError):
            raise ValueError("Each contract requires an ISO expiry date") from None
        contracts.append(
            {
                "symbol": symbol,
                "underlying": underlying,
                "exchange": _text(item.get("exchange"), "exchange", 40),
                "option_type": item["option_type"],
                "segment": item["segment"],
                "strike": float(
                    decimal_value(item.get("strike"), "strike", minimum="0.000001", maximum=1e9)
                ),
                "expiry": expiry,
                "lot_size": _integer(item.get("lot_size"), "lot_size", maximum=1000000),
                "multiplier": float(
                    decimal_value(
                        item.get("multiplier"), "multiplier", minimum="0.000001", maximum=1e6
                    )
                ),
            }
        )
    if "rows" in payload and "csv" in payload:
        raise ValueError("Supply either rows or csv")
    rows = payload.get("rows")
    if "csv" in payload:
        if not isinstance(payload["csv"], str) or len(payload["csv"].encode()) > MAX_BODY_BYTES:
            raise ValueError("CSV exceeds the import limit")
        with io.StringIO(payload["csv"]) as stream:
            reader = csv.DictReader(stream)
            rows = []
            for row in reader:
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise ValueError("Too many bars")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError(f"Supply between 1 and {MAX_ROWS} bars")
    now = now or datetime.now(UTC)
    normalized, seen, sessions = [], set(), set()
    contracts_by_symbol = {c["symbol"]: c for c in contracts}
    for row in rows:
        if not isinstance(row, dict) or row.get("symbol") not in symbols:
            raise ValueError("Every bar must name the underlying or a declared contract")
        try:
            at = datetime.fromisoformat(row["timestamp"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Every bar requires an ISO timestamp") from None
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Bar timestamps must include a timezone")
        at = at.astimezone(IST)
        if at.time() < time(3, 0):
            raise ValueError("Midnight-crossing overnight sessions are not supported")
        if at > now or at.second or at.microsecond:
            raise ValueError("Bar timestamps must be closed, minute-aligned, and not in the future")
        symbol = row["symbol"]
        if (
            symbol in contracts_by_symbol
            and at.date().isoformat() > contracts_by_symbol[symbol]["expiry"]
        ):
            raise ValueError("Option bar occurs after its declared contract expiry")
        key = (symbol, at.isoformat())
        if key in seen:
            raise ValueError("Dataset contains duplicate symbol timestamps")
        seen.add(key)
        prices = {
            key: float(decimal_value(row.get(key), key, minimum="0.000001", maximum=1e9))
            for key in ("open", "high", "low", "close")
        }
        if (
            prices["low"] > min(prices["open"], prices["close"])
            or prices["high"] < max(prices["open"], prices["close"])
            or prices["low"] > prices["high"]
        ):
            raise ValueError("OHLC prices are inconsistent")
        volume = row.get("volume")
        volume = (
            None if volume in (None, "") else float(decimal_value(volume, "volume", maximum=1e15))
        )
        normalized.append(
            {"symbol": symbol, "timestamp": at.isoformat(), **prices, "volume": volume}
        )
        if symbol == underlying:
            sessions.add(at.date().isoformat())
    if not sessions:
        raise ValueError("Dataset must include underlying bars")
    normalized.sort(key=lambda row: (row["timestamp"], row["symbol"]))
    metadata = {
        "underlying_symbol": underlying,
        "timezone": "Asia/Kolkata",
        "bar_minutes": minutes,
        "timestamp_convention": "bar_close",
        "session_close": close.strftime("%H:%M"),
        "source_reference": source,
        "contracts": sorted(contracts, key=lambda c: c["symbol"]),
    }
    if opening is not None:
        metadata["session_open"] = opening.strftime("%H:%M")
    content = {"metadata": metadata, "rows": normalized}
    return {
        "name": name,
        "provider": provider,
        **content,
        "content_hash": digest(content),
        "row_count": len(normalized),
        "session_count": len(sessions),
        "sessions": sorted(sessions),
        "start": normalized[0]["timestamp"],
        "end": normalized[-1]["timestamp"],
        "quality": "candle_screening",
    }
