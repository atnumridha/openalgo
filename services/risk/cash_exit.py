"""Versioned whole-lot price-stop geometry shared by research and managed entries."""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation

from services.risk.admission import ML_RISK_RECIPE
from services.risk.budget import FIXED_POLICY_VERSION, SHARED_POLICY_VERSIONS, policy_for_version
from services.risk.profit_exit import (
    FIXED_PROFIT_LOCK_RECIPE,
    PROFIT_LOCK_RECIPE,
    PROFIT_RECIPE,
    PROFIT_RECIPES,
    TECHNICAL_PROFIT_RECIPE,
    TECHNICAL_PROFIT_RECIPES,
)

FIXED_CASH_RECIPE = "one-lot-cash300-3r-v1"
CASH_RISK_RECIPE = FIXED_PROFIT_LOCK_RECIPE
# v5 needs broker option-candle structure. Generic historical/ML recipes do not
# reproduce that entry plan and must not silently relabel their old geometry.
CASH_RECIPES = (FIXED_CASH_RECIPE, PROFIT_RECIPE, TECHNICAL_PROFIT_RECIPE, PROFIT_LOCK_RECIPE, FIXED_PROFIT_LOCK_RECIPE)
_RECIPE_POLICIES = {
    FIXED_CASH_RECIPE: "shared-300-3r-v1",
    PROFIT_RECIPE: "shared-300-3r-v1",
    TECHNICAL_PROFIT_RECIPE: "equity-1pct-v2",
    PROFIT_LOCK_RECIPE: "equity-1pct-v2",
    FIXED_PROFIT_LOCK_RECIPE: FIXED_POLICY_VERSION,
}


def recipe_policy(recipe, capital=Decimal("25000")):
    """An exit recipe retains its original risk contract for reproducible replay."""
    if recipe not in _RECIPE_POLICIES:
        raise ValueError("Unsupported risk recipe")
    return policy_for_version(_RECIPE_POLICIES[recipe], Decimal(str(capital)))


def _geometry(entry, technical_distance, contract, *, technical=False, runner=False):
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
    if not technical:
        distance = min(distance, Decimal("300") / units)
    rounding = ROUND_FLOOR if technical else ROUND_CEILING
    stop = ((exact - distance) / tick).to_integral_value(rounding=rounding) * tick
    actual = exact - stop
    if actual < tick or stop <= 0:
        raise ValueError("Cash stop cannot be represented by at least one price tick")
    target = exact + 3 * actual
    if runner:
        # This is a reporting milestone only; profit recipes have no hard target.
        target = ((exact + Decimal(900) / units) / tick).to_integral_value(
            rounding=ROUND_CEILING
        ) * tick
    return stop, target, actual * units


def cash_exit(entry, technical_distance, contract, *, runner=False):
    """Immutable legacy INR300 cap, rounded toward the entry tick."""
    return _geometry(entry, technical_distance, contract, runner=runner)


def recipe_exit(entry, technical_distance, contract, recipe):
    if recipe not in CASH_RECIPES:
        raise ValueError("Unsupported risk recipe")
    return _geometry(
        entry,
        technical_distance,
        contract,
        technical=recipe in TECHNICAL_PROFIT_RECIPES,
        runner=recipe in PROFIT_RECIPES,
    )


def pacing_config(cooldown_minutes=5):
    if type(cooldown_minutes) is not int or cooldown_minutes not in (0, 5, 15):
        raise ValueError("Cooldown must be 0, 5 or 15 whole minutes")
    return {"cooldown_minutes": cooldown_minutes, "daily_trade_cap": None}


def current_configuration(config):
    """Validate an explicit recipe/policy pair, including frozen legacy recipes.

    The boolean identifies whole-lot recipe configurations, not live eligibility.
    Qualification separately requires the current recipe and policy versions.
    """
    version, recipe = config.get("risk_policy_version"), config.get("risk_recipe")
    if version not in (None, "two-bucket-v1", *SHARED_POLICY_VERSIONS):
        raise ValueError("Unsupported risk policy version")
    current = recipe in CASH_RECIPES
    if current or version in SHARED_POLICY_VERSIONS:
        if not current or version != _RECIPE_POLICIES[recipe]:
            raise ValueError("Risk recipe and risk policy must be bound together")
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
    elif recipe not in (None, ML_RISK_RECIPE):
        raise ValueError("Unsupported risk recipe and policy binding")
    return current
