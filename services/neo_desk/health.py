"""Operational feedback preserves last known values when refreshes fail."""

from datetime import datetime

from database import neo_desk_db as desk
from utils.thread_safe_cache import LockedTTLCache

from .types import IST

cache = LockedTTLCache(maxsize=8, ttl=15)
last = LockedTTLCache(maxsize=8, ttl=86400)


def account_refresh(previous, ok, data, now, error=None):
    result = (
        {"value": dict(data), "observed_at": now.isoformat(), "error": None}
        if ok
        else {
            **(previous or {"value": None, "observed_at": None}),
            "error": error or "Broker funds refresh unavailable.",
        }
    )
    when = datetime.fromisoformat(result["observed_at"]) if result["observed_at"] else None
    result["age_seconds"] = max(0, int((now - when).total_seconds())) if when else None
    result["stale"] = not ok or (result["age_seconds"] or 0) > 15
    return result


def execution_feedback(owner):
    existing = cache.get(owner)
    if existing:
        return existing
    from database.auth_db import get_auth_token
    from services.funds_service import get_funds
    from websocket_proxy.app_integration import proxy_status

    now = datetime.now(IST)
    auth = get_auth_token(owner)
    ok = False
    data = {}
    if auth:
        ok, response, _ = get_funds(auth_token=auth, broker="kotak")
        data = response.get("data", {}) if ok else {}
    account = account_refresh(last.get(owner), ok, data, datetime.now(IST))
    last[owner] = account
    config = desk.view(owner)
    local = now.astimezone(IST)
    minute = local.hour * 60 + local.minute
    blockers = []
    if not auth:
        blockers.append("Kotak session expired or disconnected; reconnect with TOTP.")
    if not ok or data.get("availabletradinglimit") is None:
        blockers.append("Fresh broker trading allowance unavailable.")
    if local.weekday() > 4 or not 585 <= minute <= 915:
        blockers.append("Outside the 09:45–15:15 IST entry window.")
    if config["pending"]:
        blockers.append("Native entry outcome uncertain; reconcile before new entries.")
    if config["run_id"]:
        blockers.append("Owned exposure is managed; no replacement entry.")
    result = {
        "activation": config["activation"],
        "mode": config["mode"],
        "waiting_reason": config["status"],
        "account": account,
        "proxy": proxy_status(),
        "blockers": blockers,
        "observed_at": now.isoformat(),
        "note": "A connected transport does not prove fresh broker ticks; see the chart feed timestamps. Stopping entries keeps owned exits managed.",
    }
    cache[owner] = result
    return result
