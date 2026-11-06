"""Translate assistant settings and verified option charges into pure risk inputs."""

import math
from decimal import ROUND_CEILING, Decimal

from services.risk.cash_budget import cash_budget

from .analysis import FEE_SOURCES, fees, number, plan, snap, validate_settings


def validated_cash_policy(ticket):
    """Reject malformed/unknown policies while leaving legacy tickets unchanged."""
    if (
        ticket.get("strategy") == "trend"
        and ticket.get("risk_policy", {}).get("kind") == "structural_premium"
    ):
        policy = ticket["risk_policy"]
        if ticket.get("strategy_version") != "1.0" or not 0 < number(
            policy.get("planned_sl", 0)
        ) < number(policy.get("planned_target", 0)):
            raise ValueError("A valid structural premium policy is required")
        return None
    if "risk_policy" not in ticket and ticket.get("strategy") != "opening_reversal":
        return None
    policy = ticket.get("risk_policy")
    if (
        not isinstance(policy, dict)
        or policy.get("kind") != "cash_budget"
        or ticket.get("strategy") != "opening_reversal"
        or ticket.get("strategy_version") != "1.0"
    ):
        raise ValueError("A valid opening reversal cash budget policy is required")
    for key in ("loss_budget", "target_multiple"):
        if isinstance(policy.get(key), bool):
            raise ValueError("Cash budget policy values must be positive finite numbers")
        try:
            value = number(policy[key])
        except (ValueError, TypeError, KeyError):
            raise ValueError("Cash budget policy values must be positive finite numbers") from None
        if value <= 0:
            raise ValueError("Cash budget policy values must be positive finite numbers")
    return {
        "kind": "cash_budget",
        "loss_budget": number(policy["loss_budget"]),
        "target_multiple": number(policy["target_multiple"]),
    }


def _cost_estimator(
    entry,
    quantity,
    exchange,
    settings,
    day,
    entry_quantity=None,
    closed_value=0,
    filled_order_count=1,
    future_order_count=1,
):
    def estimate(exit_price):
        # fees() reports nearest paise; one extra paise conservatively covers
        # its hidden fraction instead of understating risk at a tick boundary.
        charge = fees(
            entry * (entry_quantity or quantity),
            closed_value + exit_price * quantity,
            exchange,
            0,
            day,
        )
        brokerage = (
            Decimal(str(settings["brokerage"]))
            * Decimal("1.18")
            * (filled_order_count + future_order_count)
        )
        return float(
            (Decimal(str(charge["total"])) + brokerage + Decimal("0.01")).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
        )

    return estimate


def _cash_plan(
    entry,
    quantity,
    tick,
    exchange,
    settings,
    loss_budget,
    target_multiple,
    day,
    stop_floor=0,
    *,
    entry_quantity=None,
    closed_quantity=0,
    closed_value=0,
    filled_order_count=1,
    future_order_count=1,
):
    day = day or "2026-10-14"
    settings = validate_settings(settings, day)
    estimator = _cost_estimator(
        entry,
        quantity,
        exchange,
        settings,
        day,
        entry_quantity,
        closed_value,
        filled_order_count,
        future_order_count,
    )
    result = cash_budget(
        entry,
        quantity,
        tick,
        estimator,
        loss_budget=loss_budget,
        target_multiple=target_multiple,
        slippage=settings["slippage"],
        stop_floor=stop_floor,
        realized_gross=closed_value - entry * closed_quantity,
    )
    result["risk_policy"] = {
        "kind": "cash_budget",
        "loss_budget": result["loss_budget"],
        "target_multiple": result["target_multiple"],
        "net_target": result["net_target"],
    }
    result["cost_basis"] = {
        "entry": entry,
        "quantity": quantity,
        "exchange": exchange,
        "day": day,
        "brokerage_per_order": settings["brokerage"],
        "slippage_per_unit": settings["slippage"],
        "fee_rounding": "conservative_paise",
        "basis": "confirmed_fills" if stop_floor else "entry_preview",
        "entry_quantity": entry_quantity or quantity,
        "closed_quantity": closed_quantity,
        "closed_value": closed_value,
        "realized_gross": result["realized_gross"],
        "filled_order_count": filled_order_count,
        "expected_exit_orders": future_order_count,
    }
    result.update(fee_verified="2026-10-14", fee_source=FEE_SOURCES.get(exchange))
    if result["fits"]:
        target_exit = max(0, result["target"] - settings["slippage"])
        stop_exit = max(0, result["sl"] - settings["slippage"])
        fee_breakdown = fees(
            entry * (entry_quantity or quantity),
            closed_value + target_exit * quantity,
            exchange,
            0,
            day,
        )
        charged_brokerage = settings["brokerage"] * (filled_order_count + future_order_count)
        fee_breakdown.update(
            brokerage=round(charged_brokerage, 2),
            gst=round(fee_breakdown["gst"] + charged_brokerage * 0.18, 2),
            total=estimator(target_exit),
        )
        result.update(
            costs=estimator(target_exit),
            stop_costs=estimator(stop_exit),
            fee_breakdown=fee_breakdown,
        )
    return result


def plan_cash(
    entry,
    quantity,
    tick,
    exchange,
    settings,
    loss_budget=500,
    target_multiple=3,
    day=None,
    *,
    lot=1,
):
    """Plan an opening-reversal entry using a total loss budget and net target."""
    entry = number(entry)
    if (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity <= 0
        or not isinstance(lot, int)
        or isinstance(lot, bool)
        or lot <= 0
        or quantity % lot
    ):
        raise ValueError("Quantity must be positive whole lots")
    if abs(entry - snap(entry, tick)) > 1e-7:
        raise ValueError("Prices must align with contract tick size")
    result = _cash_plan(
        entry, quantity, tick, exchange, settings, loss_budget, target_multiple, day
    )
    if result["fits"]:
        checked = plan(
            entry,
            result["sl"],
            result["target"],
            quantity,
            exchange,
            settings,
            tick,
            lot,
            day or "2026-10-14",
        )
        result["max_lots"] = checked["max_lots"]
        result["fits"] = checked["fits"] and (
            validate_settings(settings)["risk"] is None
            or result["risk"] <= validate_settings(settings)["risk"]
        )
        result["reason"] = (
            "" if result["fits"] else "Quantity exceeds configured risk or premium budget"
        )
    return result


def reconcile_cash(ticket, day):
    """Translate confirmed fills into a plan, preserving every tighter stop."""
    policy = validated_cash_policy(ticket)
    if policy is None or not ticket.get("remaining"):
        return None
    floor = max(ticket["sl"], ticket.get("current_sl", 0), ticket.get("desired_sl", 0))
    ops = ticket["ops"]
    filled_orders = sum(o.get("filled", 0) > 0 for o in ops)
    closed_value = sum(
        o.get("value", 0) - o.get("baseline_value", 0) for o in ops if o["role"] != "entry"
    )
    pending_sells = [
        o
        for o in ops
        if o["role"] != "entry"
        and o.get("state") == "accepted"
        and o.get("broker_status")
        not in ("complete", "completed", "cancelled", "canceled", "rejected")
        and o["quantity"] > o.get("filled", 0)
    ]
    covered = sum(o["quantity"] - o.get("filled", 0) for o in pending_sells)
    # An already partially filled SELL has already paid its per-order charge.
    # Pending unfilled sells and uncovered residual each may incur another.
    future_orders = sum(not o.get("filled", 0) for o in pending_sells) + math.ceil(
        max(0, ticket["remaining"] - covered) / ticket["freeze"]
    )
    result = _cash_plan(
        ticket["average_entry"],
        ticket["remaining"],
        ticket["tick"],
        ticket["exchange"],
        ticket["risk_settings"],
        policy["loss_budget"],
        policy["target_multiple"],
        day,
        floor,
        entry_quantity=ticket["entry_quantity"],
        closed_quantity=ticket["closed_quantity"],
        closed_value=closed_value,
        filled_order_count=filled_orders,
        future_order_count=future_orders,
    )
    result["cost_basis"]["basis"] = "confirmed_fills"
    return result
