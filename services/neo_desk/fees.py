"""Estimated option charges; reported paid fees remain separate accounting facts."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

from services.risk.option_costs import FeeSchedule, estimate_option_fees, money

FEE_ESTIMATE_VERSION = "options-nse-bse-account-20261023-v1"


def estimate(side, price, quantity, brokerage=D(10)):
    return estimate_option_fees(side, price, quantity, FeeSchedule(brokerage=brokerage))


@dataclass(frozen=True)
class PromotionWindow:
    start: date
    end: date
    verified: bool = False


@dataclass(frozen=True)
class FeePlan:
    brokerage: D | None = D("10")
    source: str = "Kotak option charge estimate; actual charges require broker reports"


def estimate_charges(fills, promotion=None, plan=FeePlan()):
    totals = {k: D(0) for k in ("brokerage", "exchange", "sebi", "ipft", "gst", "stamp", "stt")}
    seen, dates = set(), set()
    per_fill_values, orders = {}, defaultdict(list)
    executed_fills = unsupported = 0
    for f in fills:
        qty = int(f["quantity"])
        if qty <= 0:
            continue
        executed_fills += 1
        day = date.fromisoformat(f["trade_date"])
        dates.add(day.isoformat())
        exchange = {"nse_fo": "NFO", "bse_fo": "BFO"}.get(f.get("exchange"), f.get("exchange"))
        if exchange not in ("NFO", "BFO") or (
            f.get("symbol") and not f["symbol"].endswith(("CE", "PE"))
        ):
            unsupported += 1
            continue
        price = D(str(f["price"]))
        side = {"B": "BUY", "S": "SELL"}.get(f["side"], f["side"])
        if side not in ("BUY", "SELL") or not price.is_finite() or price <= 0:
            raise ValueError("Fee estimates require valid executed prices and sides.")
        order = (day, exchange, f["order_id"])
        orders[order].append(f)
        free = bool(promotion and promotion.verified and promotion.start <= day <= promotion.end)
        if plan.brokerage is None:
            from services.kotak_assistant.analysis import account_brokerage

            order_rate = D(str(account_brokerage(day.isoformat())))
        else:
            order_rate = plan.brokerage
        brokerage = D(0) if free or order in seen else order_rate
        seen.add(order)
        rates = FeeSchedule(
            brokerage=brokerage,
            exchange=D(".000325") if exchange == "BFO" else FeeSchedule.exchange,
            ipft=D(0) if exchange == "BFO" else FeeSchedule.ipft,
            stt=D(".0015") if day >= date(2026, 4, 1) else D(".001"),
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
        per_fill_values[fill_key(f)] = values
        for k, v in values.items():
            totals[k] += v
    # Allocate the once-per-order brokerage across its actual filled quantity.
    # Turnover taxes stay with each fill's own price, including differently priced splits.
    for parts in orders.values():
        brokerage = sum(per_fill_values[fill_key(f)]["brokerage"] for f in parts)
        broker_gst = money(brokerage * FeeSchedule.gst)
        quantity = sum(f["quantity"] for f in parts)
        remaining, remaining_gst = brokerage, broker_gst
        for i, f in enumerate(parts):
            values = per_fill_values[fill_key(f)]
            allocated = (
                remaining if i == len(parts) - 1 else money(brokerage * f["quantity"] / quantity)
            )
            allocated_gst = (
                remaining_gst
                if i == len(parts) - 1
                else money(broker_gst * f["quantity"] / quantity)
            )
            values["gst"] += allocated_gst - money(values["brokerage"] * FeeSchedule.gst)
            values["brokerage"] = allocated
            remaining -= allocated
            remaining_gst -= allocated_gst
    return {
        "total": str(sum(totals.values())) if per_fill_values else None,
        "breakdown": {k: str(v) for k, v in totals.items()},
        "per_fill": {k: str(sum(v.values())) for k, v in per_fill_values.items()},
        "per_fill_breakdown": {
            k: {name: str(value) for name, value in v.items()} for k, v in per_fill_values.items()
        },
        "promotion_verified": bool(promotion and promotion.verified),
        "source": plan.source,
        "assumption": (
            "Account notice: ₹0 brokerage before 22 Oct 2026; ₹10 per executed order from 22 Oct, plus GST and statutory charges."
            if plan.brokerage is None
            else "Assumes your free-brokerage offer covers the selected dates; offer dates are not broker-verified. Statutory charges still apply."
            if plan.brokerage == 0
            else f"₹{plan.brokerage} per executed order unless a dated promotion is verified"
        ),
        "fill_count": executed_fills,
        "estimated_fill_count": len(per_fill_values),
        "unsupported_fill_count": unsupported,
        "complete": unsupported == 0,
        "executed_order_count": len(orders),
        "recorded_dates": sorted(dates),
        "version": FEE_ESTIMATE_VERSION,
    }


def fill_key(fill):
    return "|".join(str(fill[k]) for k in ("trade_date", "exchange", "fill_id"))
