"""Fresh executable quotes for managed technical-stop option recipes.

LTP is not evidence that the entire option lot can be sold at that price.
A one-second cache bounds REST demand; every use revalidates native age/depth.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic

from services.strategy_module.portfolio_governor import GovernorPolicy, _quote_timestamp


@dataclass(frozen=True)
class ExecutableQuote:
    bid: Decimal
    ask: Decimal
    timestamp: datetime


_cache = {}
_lock = Lock()


def clear_cache():
    with _lock:
        _cache.clear()


def _positive(value):
    try:
        result = Decimal(str(value)) if not isinstance(value, bool) else Decimal("NaN")
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Executable quote has invalid numeric evidence") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("Executable quote requires positive finite price and depth")
    return result


def executable_quote(leg, response, *, now=None):
    now = now or datetime.now(UTC)
    if not isinstance(response, dict) or response.get("status") != "success":
        raise ValueError("Executable option quote unavailable")
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError("Executable option quote unavailable")
    policy = GovernorPolicy()
    stamp = _quote_timestamp(data.get("timestamp", data.get("lstup_time")))
    if (
        stamp is None
        or not -policy.max_quote_future_seconds
        <= (now - stamp).total_seconds()
        <= policy.max_quote_age_seconds
    ):
        raise ValueError("Fresh native quote timestamp required")
    bid, ask = _positive(data.get("bid")), _positive(data.get("ask"))
    bid_qty = _positive(data.get("bid_qty", data.get("bid_quantity")))
    ask_qty = _positive(data.get("ask_qty", data.get("ask_quantity")))
    qty = _positive(leg.get("quantity") or leg.get("qty"))
    limit = (
        policy.high_volatility_option_max_spread_pct
        if str(leg.get("exchange")).upper() == "MCX"
        else policy.option_max_spread_pct
    )
    if ask <= bid or (ask - bid) / bid > limit or min(bid_qty, ask_qty) < qty:
        raise ValueError("Executable quote requires a usable spread and full-lot depth")
    return ExecutableQuote(bid, ask, stamp)


def fetch_executable_quote(client, leg, *, scope, now=None, monotonic_now=None):
    """Scope is run/account identity, never an API key. Network calls stay outside locks."""
    moment = monotonic() if monotonic_now is None else monotonic_now
    key = (scope, str(leg.get("symbol")), str(leg.get("exchange")))
    with _lock:
        cached = _cache.get(key)
    if cached is None or not 0 <= moment - cached[0] < 1:
        try:
            response = client.get_quotes(leg["symbol"], leg["exchange"])
        except Exception as exc:
            raise ValueError("Executable option quote unavailable") from exc
        with _lock:
            if len(_cache) >= 256:
                _cache.clear()
            _cache[key] = (moment, response)
    else:
        response = cached[1]
    return executable_quote(leg, response, now=now)
