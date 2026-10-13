from decimal import Decimal as D

from services.risk.option_costs import FeeSchedule, estimate_option_fees, money


def estimate(side, price, quantity, brokerage=D(10)):
    return estimate_option_fees(side, price, quantity, FeeSchedule(brokerage=brokerage))


from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PromotionWindow:
    start: date
    end: date
    verified: bool = False


@dataclass(frozen=True)
class FeePlan:
    brokerage: D = D("10")
    source: str = "Kotak Trade Free estimate; actual charges require broker reports"


def estimate_charges(fills, promotion=None, plan=FeePlan()):
    totals = {k: D(0) for k in ("brokerage", "exchange", "sebi", "ipft", "gst", "stamp", "stt")}
    seen = set()
    per_fill = {}
    orders = defaultdict(list)
    dates = set()
    executed_fills = 0
    for f in fills:
        qty = int(f["quantity"])
        if qty <= 0:
            continue
        if f.get("exchange") not in ("NFO", "nse_fo"):
            return {
                "total": None,
                "breakdown": {},
                "promotion_verified": False,
                "source": "Estimate unavailable for non-NSE options",
            }
        day = date.fromisoformat(f["trade_date"])
        price = D(str(f["price"]))
        side = {"B": "BUY", "S": "SELL"}.get(f["side"], f["side"])
        order = (day, f.get("exchange"), f["order_id"])
        dates.add(day.isoformat())
        executed_fills += 1
        orders[order].append(f)
        free = bool(promotion and promotion.verified and promotion.start <= day <= promotion.end)
        brokerage = D(0) if free or order in seen else plan.brokerage
        seen.add(order)
        rates = FeeSchedule(
            brokerage=brokerage, stt=D(".0015") if day >= date(2026, 4, 1) else D(".001")
        )
        turnover = price * qty
        values = {
            "brokerage": brokerage,
            "exchange": turnover * rates.exchange,
            "sebi": turnover * rates.sebi,
            "ipft": turnover * rates.ipft,
            "stamp": turnover * rates.stamp if side == "BUY" else D(0),
            "stt": turnover * rates.stt if side == "SELL" else D(0),
        }
        values["gst"] = (
            values["brokerage"] + values["exchange"] + values["sebi"] + values["ipft"]
        ) * rates.gst
        values = {k: money(v) for k, v in values.items()}
        per_fill[fill_key(f)] = str(sum(values.values()))
        for k, v in values.items():
            totals[k] += v
    # An order's charges belong to every executed part, not only the first fill.
    for parts in orders.values():
        total = sum(D(per_fill[fill_key(f)]) for f in parts)
        quantity = sum(f["quantity"] for f in parts)
        remaining = total
        for i, f in enumerate(parts):
            charge = remaining if i == len(parts) - 1 else money(total * f["quantity"] / quantity)
            per_fill[fill_key(f)] = str(charge)
            remaining -= charge
    return {
        "total": str(sum(totals.values())),
        "breakdown": {k: str(v) for k, v in totals.items()},
        "per_fill": per_fill,
        "promotion_verified": bool(promotion and promotion.verified),
        "source": plan.source,
        "assumption": (
            "Assumes your free-brokerage offer covers the selected dates; offer dates are not broker-verified. Statutory charges still apply."
            if plan.brokerage == 0 else
            f"₹{plan.brokerage} per executed order unless a dated promotion is verified"
        ),
        "fill_count": executed_fills,
        "executed_order_count": len(orders),
        "recorded_dates": sorted(dates),
    }


def fill_key(fill):
    return "|".join(str(fill[k]) for k in ("trade_date", "exchange", "fill_id"))
