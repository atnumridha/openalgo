"""Read-only first-fill timing from complete entry-order evidence."""

from decimal import Decimal


def first_entry_fill_time(plan, payload, fills, complete, now):
    from .service import Rejected, fill_timestamp, number

    if not complete or not isinstance(fills, list) or not plan.get("entry_order_id"):
        return None
    selected = [f for f in fills if str(f.get("order_id")) == str(plan["entry_order_id"])]
    if not selected:
        return None
    try:
        total, stamps, ids = Decimal(0), [], set()
        for fill in selected:
            nested = fill.get("product") or {}
            if (
                str(fill.get("product_id", nested.get("id"))) != str(plan["pid"])
                or fill.get("fill_type") != "normal"
                or fill.get("side") != payload["side"]
                or not fill.get("id")
                or str(fill["id"]) in ids
            ):
                return None
            ids.add(str(fill["id"]))
            size = number(fill["size"], True)
            if size != size.to_integral_value():
                return None
            stamp = fill_timestamp(fill.get("created_at"))
            if stamp > Decimal(str(now)) + 5:
                return None
            total += size
            stamps.append(stamp)
        if total <= 0 or total > number(payload["size"], True):
            return None
        return float(min(stamps))
    except (Rejected, KeyError, TypeError, ValueError):
        return None
