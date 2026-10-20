"""Day-local entry counting and advisory cash milestones. No order operations."""

from datetime import datetime

from .analysis import IST, fees, fill_time, number

PROFIT_TARGET = 2000
LOSS_LIMIT = 1000
MAX_ENTRIES = 3
MAX_TRACKED_ENTRY_IDS = 20000


def merge_fills(*groups):
    """Merge durable observations without masking a changed broker fill."""
    merged = {}
    for group in groups:
        for fill in group:
            key = (str(fill.get("orderid", "")), str(fill.get("tradeid", "")))
            if not all(key):
                raise ValueError("Missing stable fill IDs")
            previous = merged.get(key)
            if previous:
                fields = ("symbol", "exchange", "product", "action")
                numbers = ("quantity", "average_price")
                if (
                    any(previous.get(k) != fill.get(k) for k in fields)
                    or any(number(previous[k]) != number(fill[k]) for k in numbers)
                    or fill_time(previous["timestamp"]) != fill_time(fill["timestamp"])
                ):
                    raise ValueError("Broker fill changed; waiting for account reconciliation")
            else:
                merged[key] = fill
    return list(merged.values())


def merge_checkpoints(previous, other, day):
    """Share latched milestones between the execution and read-only monitors."""
    a = previous if previous.get("date") == day else {}
    b = other if other.get("date") == day else {}
    result = {
        **a,
        "date": day,
        "entry_ids": sorted(set(a.get("entry_ids", [])) | set(b.get("entry_ids", []))),
        "entries": max(a.get("entries", 0), b.get("entries", 0)),
        "legacy_unverified": bool(a.get("legacy_unverified") or b.get("legacy_unverified")),
    }
    for label in ("profit", "loss"):
        reached = [x for x in (a, b) if x.get(f"{label}_reached")]
        if reached:
            first = min(reached, key=lambda x: x.get(f"{label}_reached_at", float("inf")))
            for suffix in ("reached", "reached_at", "reached_net"):
                key = f"{label}_{suffix}"
                if key in first:
                    result[key] = first[key]
    times = [x["entry_limit_reached_at"] for x in (a, b) if x.get("entry_limit_reached_at")]
    if times:
        result["entry_limit_reached_at"] = min(times)
    return result


def order_evidence(orders, fills, day, historical=()):
    """A filled order with missing trade rows cannot be mistaken for no trading."""
    quantities, dates = {}, {}
    for f in [*historical, *fills]:
        key = (f["exchange"], str(f["orderid"]))
        dates[key] = datetime.fromtimestamp(fill_time(f["timestamp"]), IST).date().isoformat()
    for f in fills:
        if datetime.fromtimestamp(fill_time(f["timestamp"]), IST).date().isoformat() == day:
            key = (f["exchange"], str(f["orderid"]))
            quantities[key] = quantities.get(key, 0) + int(f["quantity"])
    ids, missing = set(), False
    for o in orders:
        key = (o.get("exchange"), str(o.get("orderid", "")))
        qty = number(o.get("filled_quantity") or 0)
        if str(o.get("order_status", "")).lower() in ("complete", "completed"):
            qty = max(qty, number(o.get("quantity") or 0))
        if qty <= 0:
            continue
        actual_day = dates.get(key)
        if actual_day is not None:
            if actual_day != day:
                continue
        elif (
            o.get("timestamp")
            and datetime.fromtimestamp(fill_time(o["timestamp"]), IST).date().isoformat() != day
        ):
            # Creation date is not a fill date (e.g. an overnight AMO).
            # Without fill evidence neither its trade day nor P&L is known.
            missing = True
            continue
        if not key[0] or not key[1]:
            raise ValueError("Filled order identity unavailable")
        if o.get("action") == "BUY":
            ids.add(f"{key[0]}:{key[1]}")
        missing = missing or qty > quantities.get(key, 0)
    return {
        "entry_ids": ids,
        "complete": not missing,
        "reason": "Completed broker orders are missing fills; waiting for full trade data"
        if missing
        else "",
    }


def advance(previous, day, fills, now, net=None, *, minimum_entries=0, known_ids=()):
    """Remember filled BUY orders and milestones across polls/restarts for one IST day."""
    old = previous if previous.get("date") == day else {}
    seen = set(old.get("entry_ids", []))
    observed = set(known_ids)
    for fill in fills:
        if fill.get("action") != "BUY" or number(fill.get("quantity", 0)) <= 0:
            continue
        if datetime.fromtimestamp(fill_time(fill["timestamp"]), IST).date().isoformat() != day:
            continue
        if not fill.get("orderid") or not fill.get("exchange"):
            raise ValueError("Filled entry identity unavailable")
        observed.add(f"{fill['exchange']}:{fill['orderid']}")
    seen.update(observed)
    entries = max(minimum_entries, old.get("entries", 0), len(seen))
    if len(seen) > MAX_TRACKED_ENTRY_IDS:
        raise ValueError("Daily entry ledger capacity reached; review trading activity")
    result = {
        **old,
        "date": day,
        "entries": entries,
        "entry_ids": sorted(seen),
        # Unknown legacy identities cannot be resolved by later app entries.
        # Fail closed for this session; the next IST day starts a clean ledger.
        "legacy_unverified": bool(old.get("legacy_unverified") or entries > len(seen)),
        "count_verified": not bool(old.get("legacy_unverified") or entries > len(seen)),
        "max_entries": MAX_ENTRIES,
        "remaining_entries": max(0, MAX_ENTRIES - entries),
        "excess_entries": max(0, entries - MAX_ENTRIES),
        "profit_target": PROFIT_TARGET,
        "loss_limit": LOSS_LIMIT,
        "profit_reached": bool(old.get("profit_reached")),
        "loss_reached": bool(old.get("loss_reached")),
        "net": net,
        "updated_at": now,
    }
    for label, reached in (
        ("profit", net is not None and net >= PROFIT_TARGET),
        ("loss", net is not None and net <= -LOSS_LIMIT),
    ):
        if reached and not result[f"{label}_reached"]:
            result.update(
                {f"{label}_reached": True, f"{label}_reached_at": now, f"{label}_reached_net": net}
            )
    if entries >= MAX_ENTRIES and not result.get("entry_limit_reached_at"):
        result["entry_limit_reached_at"] = now
    return result


def liquidation(journal, quotes, brokerage, day, now):
    """Use the same verified long-option liquidation estimate for both monitors."""
    if not journal["complete"]:
        raise ValueError(journal["reason"])
    gross, costs = 0, 0
    for position in journal["open_positions"]:
        quantity = int(position["quantity"])
        if quantity <= 0 or position["exchange"] not in ("NFO", "BFO"):
            raise ValueError(
                "Account contains unsupported exposure; risk reconciliation unavailable"
            )
        q = quotes[(position["symbol"], position["exchange"])]
        bid = number(q.get("bid", 0))
        if bid <= 0 or not 0 <= now - q.get("time", 0) <= 5:
            raise ValueError("Open position liquidation quote unavailable")
        gross += (bid - number(position["average_price"])) * quantity
        costs += fees(0, bid * quantity, position["exchange"], 0, day)["total"] + brokerage * 1.18
    return {
        "net": journal["net_realised"] + gross - costs,
        "open_gross": gross,
        "estimated_liquidation_costs": costs,
    }
