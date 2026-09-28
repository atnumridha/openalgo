"""Versioned whole-lot price-stop geometry shared by research and managed entries."""

from decimal import ROUND_CEILING, Decimal, InvalidOperation

from services.risk.budget import current_policy
from services.risk.profit_exit import PROFIT_RECIPE

FIXED_CASH_RECIPE = "one-lot-cash300-3r-v1"
CASH_RISK_RECIPE = PROFIT_RECIPE
CASH_RECIPES = (FIXED_CASH_RECIPE, CASH_RISK_RECIPE)


def cash_exit(entry, technical_distance, contract, *, runner=False):
    """Cap monetary loss, rounding the absolute stop toward the entry tick."""
    try:
        exact, distance = Decimal(str(entry)), Decimal(str(technical_distance))
        tick = Decimal(str(contract.get("tick_size", 0)))
        lot = Decimal(str(contract.get("lot_size", 0)))
        multiplier = Decimal(str(contract.get("multiplier", 1)))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Cash stop requires numeric price, distance, tick and whole lot") from exc
    if any(not x.is_finite() or x <= 0 for x in (exact, distance, tick, lot, multiplier)):
        raise ValueError("Cash stop requires positive finite price, distance, tick and whole lot")
    units = lot * multiplier
    if lot != lot.to_integral_value() or units != units.to_integral_value() or exact % tick:
        raise ValueError("Cash stop requires tick-aligned entry and whole lot units")
    distance = min(distance, current_policy().per_trade_limit / units)
    stop = ((exact - distance) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    actual = exact - stop
    if actual < tick or stop <= 0:
        raise ValueError("Cash stop cannot be represented by at least one price tick")
    target = exact + 3 * actual
    if runner:
        target = ((exact + Decimal(900) / units) / tick).to_integral_value(
            rounding=ROUND_CEILING
        ) * tick
    return stop, target, actual * units


def pacing_config(cooldown_minutes=5):
    if type(cooldown_minutes) is not int or cooldown_minutes not in (0, 5, 15):
        raise ValueError("Cooldown must be 0, 5 or 15 whole minutes")
    return {"cooldown_minutes": cooldown_minutes, "daily_trade_cap": None}


def current_configuration(config):
    """Reject partial/mixed version bindings; absent bindings retain legacy math."""
    if config.get("risk_policy_version") not in (None, "two-bucket-v1", current_policy().version):
        raise ValueError("Unsupported risk policy version")
    current = config.get("risk_recipe") in CASH_RECIPES
    if current or config.get("risk_policy_version") == current_policy().version:
        if not current or config.get("risk_policy_version") != current_policy().version:
            raise ValueError("Current cash recipe and risk policy must be bound together")
        if type(config.get("max_hold_minutes")) is not int or config["max_hold_minutes"] not in (
            5,
            10,
            15,
        ):
            raise ValueError("Current cash recipe requires a 5, 10 or 15-minute holding deadline")
        pace = config.get("pacing")
        if not isinstance(pace, dict) or pace != pacing_config(pace.get("cooldown_minutes")):
            raise ValueError("Current cash recipe requires its bound pacing")
        params = config.get("parameters", {})
        if Decimal(str(params.get("target_pct", 0))) != Decimal(str(params.get("stop_pct", 0))) * 3:
            raise ValueError("Current cash recipe requires exactly 3R before charges")
    return current
