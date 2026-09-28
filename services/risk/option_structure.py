"""Causal option-price structure for managed forward scalping, version v5.

The objective describes a plan, not an executable take-profit or a forecast.
Loss affordability is independently enforced with fees, slippage and whole lots.
"""

from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from services.risk.budget import EQUITY_POLICY_VERSION, FIXED_POLICY_VERSION

STRUCTURE_RECIPE = "one-lot-option-structure-runner-v5"
IST = ZoneInfo("Asia/Kolkata")


def positive(value):
    try:
        result = Decimal(str(value)) if not isinstance(value, bool) else Decimal("NaN")
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Option structure requires positive finite values") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("Option structure requires positive finite values")
    return result


def stamp(value):
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Option structure requires dated completed candles") from exc
    if result.tzinfo is None or result.second or result.microsecond:
        raise ValueError("Option structure requires aligned timezone-aware candles")
    return result.astimezone(IST)


def structure_plan(contract, candles, signal_at, entry, bid):
    signal = stamp(signal_at)
    entry, bid = positive(entry), positive(bid)
    tick, lot, quantity = (positive(contract.get(k)) for k in ("tick_size", "lot_size", "quantity"))
    if quantity != lot or lot != lot.to_integral_value() or entry % tick:
        raise ValueError("Option structure requires one whole lot and a tick-aligned entry")
    if contract.get("position") != "B" or contract.get("exchange") != "NFO":
        raise ValueError("Option structure requires a long NFO option")
    if not str(contract.get("symbol", "")).endswith(("CE", "PE")):
        raise ValueError("Option structure requires an option contract")
    if not isinstance(candles, list) or len(candles) != 3:
        raise ValueError("Option structure needs three completed one-minute candles")
    validated = []
    for i, row in enumerate(candles):
        at = stamp(row.get("closed_at"))
        if at != signal - timedelta(minutes=2-i) or at.date() != signal.date():
            raise ValueError("Option structure candles are stale, missing or not contiguous")
        op, hi, lo, cl = (positive(row.get(k)) for k in ("open", "high", "low", "close"))
        if lo > min(op, cl) or hi < max(op, cl) or lo > hi:
            raise ValueError("Option structure candle prices are inconsistent")
        validated.append({"closed_at": at.isoformat(), "open": str(op), "high": str(hi),
                          "low": str(lo), "close": str(cl)})
    low = min(Decimal(row["low"]) for row in validated)
    stop = (low / tick).to_integral_value(rounding=ROUND_FLOOR) * tick - tick
    if stop <= 0 or stop >= bid or bid >= entry:
        raise ValueError("Option structure stop is already crossed or quote is invalid")
    return {
        "version": STRUCTURE_RECIPE, "symbol": contract["symbol"], "exchange": contract["exchange"],
        "signal_at": signal.isoformat(), "candles": validated, "entry_price": str(entry),
        "quote_bid": str(bid), "stop_price": str(stop), "planned_gross_loss": str((entry-stop)*quantity),
        "objective_r": 3, "hard_target": False, "profit_milestone_inr": 900,
    }


def validate_structure(contract, plan):
    if not isinstance(plan, dict):
        raise ValueError("Persisted option structure is required")
    try:
        rebuilt = structure_plan(contract, plan["candles"], plan["signal_at"], plan["entry_price"], plan["quote_bid"])
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Persisted option structure is incomplete") from exc
    if plan != rebuilt or positive(contract.get("initial_stop_price")) != Decimal(rebuilt["stop_price"]):
        raise ValueError("Persisted option structure or stop changed")
    return rebuilt


def objective_ratio(leg, price):
    context = leg.get("scalp_context") or {}
    if context.get("risk_recipe") != STRUCTURE_RECIPE or context.get("exit_basis") != "option_premium":
        raise ValueError("Option runner recipe and exit basis disagree")
    if context.get("risk_policy_version") not in {EQUITY_POLICY_VERSION, FIXED_POLICY_VERSION} or leg.get("target_pts") is not None:
        raise ValueError("Option runner policy or hard target is incompatible")
    plan = validate_structure(leg, context.get("structure"))
    # Rebase the planning objective on the same adverse entry price used to
    # reserve loss. The absolute stop never moves with that price.
    distance = positive(price) - Decimal(plan["stop_price"])
    if distance <= 0:
        raise ValueError("Option entry has crossed its structure stop")
    objective = positive(price) + Decimal(plan["objective_r"]) * distance
    return (objective - positive(price)) / distance
