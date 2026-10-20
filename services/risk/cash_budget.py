"""Pure tick-aligned planning for a long option's total cash risk and net goal."""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation


def _decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Prices and limits must be finite numbers") from None
    if isinstance(value, bool) or not result.is_finite():
        raise ValueError("Prices and limits must be finite numbers")
    return result


def _money(value, rounding):
    return float(value.quantize(Decimal("0.01"), rounding=rounding))


def cash_budget(
    entry,
    quantity,
    tick,
    estimated_cost,
    *,
    loss_budget=500,
    target_multiple=3,
    slippage=0,
    stop_floor=0,
    realized_gross=0,
):
    """Find the widest safe stop and smallest target reaching the net cash goal.

    ``estimated_cost(exit_price)`` supplies a nonnegative, monotone round-trip
    charge estimate; it must not perform I/O. Stop prices round towards lower
    risk and targets towards the net goal. The fill average need not be a tick.
    ``stop_floor`` preserves protection already requested or broker-confirmed.
    ``quantity`` is the remaining exposure and ``realized_gross`` is confirmed
    closed-leg P&L; the supplied costs cover the entire entry/exit lifecycle.
    """
    entry, tick, budget, multiple, slip, floor, realized = map(
        _decimal, (entry, tick, loss_budget, target_multiple, slippage, stop_floor, realized_gross)
    )
    if (
        min(entry, tick, budget, multiple) <= 0
        or min(slip, floor) < 0
        or not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity <= 0
    ):
        raise ValueError("Cash budget, prices and quantity must be positive")
    qty = Decimal(quantity)
    goal = budget * multiple

    def cost(exit_price):
        value = _decimal(estimated_cost(float(exit_price)))
        if value < 0:
            raise ValueError("Estimated costs must be nonnegative")
        return value

    def risk_at(index):
        exit_price = max(Decimal(0), tick * index - slip)
        return (entry - exit_price) * qty - realized + cost(exit_price)

    def reward_at(index):
        exit_price = max(Decimal(0), tick * index - slip)
        return realized + (exit_price - entry) * qty - cost(exit_price)

    result = {
        "entry": float(entry),
        "quantity": quantity,
        "loss_budget": float(budget),
        "target_multiple": float(multiple),
        "net_target": float(goal),
        "realized_gross": float(realized),
        "sl": None,
        "target": None,
        "risk": None,
        "reward": None,
        "net_rr": None,
        "fits": False,
        "reason": "The loss budget cannot cover fees, slippage and one protective stop tick",
    }
    highest_stop = int((entry / tick).to_integral_value(rounding=ROUND_CEILING)) - 1
    if highest_stop < 1 or risk_at(highest_stop) > budget:
        return result
    lo, hi = 1, highest_stop
    while lo < hi:
        middle = (lo + hi) // 2
        if risk_at(middle) <= budget:
            hi = middle
        else:
            lo = middle + 1
    stop_index = max(lo, int((floor / tick).to_integral_value(rounding=ROUND_CEILING)))
    target_lo = (
        1 if realized > 0 else int((entry / tick).to_integral_value(rounding=ROUND_FLOOR)) + 1
    )
    target_hi = target_lo
    for _ in range(64):
        if reward_at(target_hi) >= goal:
            break
        target_hi *= 2
    else:
        result["reason"] = "The net target cannot be reached with the supplied cost estimate"
        return result
    while target_lo < target_hi:
        middle = (target_lo + target_hi) // 2
        if reward_at(middle) >= goal:
            target_hi = middle
        else:
            target_lo = middle + 1
    risk = max(Decimal(0), risk_at(stop_index))
    reward = reward_at(target_lo)
    result.update(
        sl=float(tick * stop_index),
        target=float(tick * target_lo),
        risk=_money(risk, ROUND_CEILING),
        reward=_money(reward, ROUND_FLOOR),
        net_rr=round(float(reward / risk), 4) if risk else None,
        fits=True,
        reason="",
    )
    return result


def trend_premium_stop(entry, option_atr, confirmed_option_low, tick):
    """Use the lower ATR/confirmed-swing stop, rounded towards less risk."""
    entry, atr, tick = map(_decimal, (entry, option_atr, tick))
    swing = None if confirmed_option_low is None else _decimal(confirmed_option_low)
    if min(entry, atr, tick) <= 0 or (swing is not None and swing <= 0):
        raise ValueError("A positive option ATR and valid confirmed low are required")
    stop = entry - Decimal("1.5") * atr
    if swing is not None:
        stop = min(stop, swing - tick)
    stop = (stop / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    if not 0 < stop < entry:
        raise ValueError("The option's structural stop is unavailable")
    return float(stop)
