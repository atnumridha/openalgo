"""Versioned long-option profit ratchet. Pure; costs are frozen at admission."""

from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from services.research.costs import decimal_value, execution_economics, order_cost
from services.risk.models import BreachReason, PositionRisk, is_price
from services.risk.position import evaluate_position

PROFIT_RECIPE = "one-lot-cash300-profit-trail-v2"
TECHNICAL_PROFIT_RECIPE = "one-lot-technical-profit-trail-v3"
PROFIT_LOCK_RECIPE = "one-lot-technical-profit-lock-v4"
TECHNICAL_PROFIT_RECIPES = (TECHNICAL_PROFIT_RECIPE, PROFIT_LOCK_RECIPE)
PROFIT_RECIPES = (PROFIT_RECIPE, *TECHNICAL_PROFIT_RECIPES)


def profit_config(contract, costs, *, recipe=PROFIT_RECIPE):
    if recipe not in PROFIT_RECIPES:
        raise ValueError("Unsupported profit protection recipe")
    tick = decimal_value(contract.get("tick_size"), "tick_size")
    if not tick.is_finite() or tick <= 0:
        raise ValueError("Profit protection requires a positive price tick")
    return {"version": recipe, "tick_size": str(tick), "costs": execution_economics(costs)}


def validate_profit_config(config):
    if not isinstance(config, dict) or config.get("version") not in PROFIT_RECIPES:
        raise ValueError("Unsupported profit protection recipe")
    validated = profit_config(config, config.get("costs"), recipe=config["version"])
    if set(config) != set(validated):
        raise ValueError("Unexpected profit protection settings")
    return validated


def _break_even(entry, quantity, peak, tick, costs):
    """Lowest tick whose modeled slipped sell covers entry and both order fees."""
    slip = Decimal(str(costs["slippage_bps"])) / 10000
    if not 0 <= slip < 1:
        raise ValueError("Profit protection slippage is invalid")
    fee = order_cost(entry * quantity, "BUY", costs)

    def net(ticks):
        fill = (ticks * tick * (1 - slip) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        return (fill - entry) * quantity - fee - order_cost(fill * quantity, "SELL", costs)

    low = int((entry / tick).to_integral_value(rounding=ROUND_CEILING))
    high = int((peak / tick).to_integral_value(rounding=ROUND_FLOOR))
    if high < low or net(high) < 0:
        return None
    while low < high:
        mid = (low + high) // 2
        if net(mid) >= 0:
            high = mid
        else:
            low = mid + 1
    return low * tick


def evaluate_profit(risk, last_price, config):
    """Versioned gross floors; v4 locks INR100 at INR300, then limits giveback to INR300."""
    config = validate_profit_config(config)
    if not risk.is_long or not is_price(risk.entry_price) or not is_price(risk.quantity):
        raise ValueError("Profit protection requires a filled long option position")
    if not is_price(last_price):
        return evaluate_position(replace(risk, target_price=None), last_price)
    entry, units = Decimal(str(risk.entry_price)), Decimal(str(risk.quantity))
    tick = Decimal(config["tick_size"])
    peak = max(entry, Decimal(str(last_price)), Decimal(str(risk.highest_price or entry)))
    gross_peak = (peak - entry) * units
    candidate = None
    if gross_peak >= 300:
        candidate = _break_even(entry, units, peak, tick, config["costs"])
        if candidate is not None and gross_peak >= 600:
            trail = ((peak - Decimal(300) / units) / tick).to_integral_value(
                rounding=ROUND_CEILING
            ) * tick
            candidate = max(candidate, min(peak, trail))
    if config["version"] == TECHNICAL_PROFIT_RECIPE and gross_peak >= 1000:
        gross_floor = max(entry + Decimal(900) / units, peak - Decimal(300) / units)
        milestone = (gross_floor / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        candidate = max(candidate or entry, min(peak, milestone))
    if config["version"] == PROFIT_LOCK_RECIPE and gross_peak >= 300:
        # Gross floors are independent of the entry's smaller all-in risk cap.
        # Rounding up protects at least the floor; the observed peak bounds it.
        gross_floor = max(Decimal(100), gross_peak - Decimal(300))
        floor_price = ((entry + gross_floor / units) / tick).to_integral_value(
            rounding=ROUND_CEILING
        ) * tick
        candidate = max(candidate or entry, min(peak, floor_price))
    old = risk.effective_stop
    stop = old if candidate is None else max(old or 0, float(candidate))
    decision = evaluate_position(
        replace(risk, stop_price=stop, target_price=None, trailing_enabled=False), last_price
    )
    return replace(
        decision,
        stop_moved=stop != old,
        trail_armed=candidate is not None or (old is not None and old > risk.entry_price),
    )


def _carry(risk, decision):
    return replace(
        risk,
        stop_price=decision.stop_price,
        target_price=None,
        highest_price=decision.highest_price,
    )


def profit_open(risk, price, config):
    decision = evaluate_profit(risk, price, config)
    return _carry(risk, decision), decision


def profit_bar(risk, bar, config):
    """OHLC approximation: ratchet at known open/close, never unordered high.

    A gap fills at open. The existing/open-earned stop is checked against low
    before the close can raise it. A close-earned level protects subsequent bars.
    Tick monitoring is more granular; candles cannot prove the intrabar path.
    """
    risk, opening = profit_open(risk, bar["open"], config)
    if opening.breached:
        return risk, bar["open"], profit_reason(risk)
    if bar["low"] <= risk.stop_price:
        return risk, risk.stop_price, profit_reason(risk)
    risk, closing = profit_open(risk, bar["close"], config)
    if closing.breached:
        return risk, bar["close"], profit_reason(risk)
    return risk, None, None


def profit_reason(risk):
    return "profit_stop" if risk.stop_price > risk.entry_price else "stop_loss"
