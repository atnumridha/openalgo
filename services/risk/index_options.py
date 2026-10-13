"""Pure index-driven long-option protection, in explicit index/premium/cash units."""

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR
from decimal import Decimal as D

from .option_costs import FeeSchedule, estimate_option_fees


@dataclass(frozen=True)
class IndexOptionRisk:
    direction: str
    index_reference: D
    initial_index_stop: D
    index_stop: D
    index_target: D
    index_peak: D
    entry_price: D
    quantity: int
    tick: D
    controlled: bool = False
    index_trailing: bool = False
    option_stop: D | None = None
    option_target: D | None = None
    entry_fees: D = D(0)
    net_peak: D | None = None
    net_floor: D | None = None
    cash_trail_enabled: bool = False
    cash_activation: D = D(1000)
    cash_distance: D = D(250)
    friction: D = D(".50")
    trade_loss: D = D(500)
    daily_loss: D = D(1000)
    rates: FeeSchedule = FeeSchedule()


@dataclass(frozen=True)
class IndexOptionDecision:
    state: IndexOptionRisk
    reason: str | None = None
    gross: D | None = None
    net: D | None = None


def evaluate_index_option(p, index_price, option_bid, day_net):
    if p.direction not in ("CE", "PE") or p.quantity <= 0 or p.tick <= 0 or p.entry_price <= 0:
        raise ValueError("Invalid long-option protection identity or units.")
    if any(
        not D(v).is_finite()
        for v in (
            p.index_reference,
            p.initial_index_stop,
            p.index_stop,
            p.index_target,
            p.index_peak,
            p.entry_price,
            p.tick,
            day_net,
        )
    ):
        raise ValueError("Protection values must be finite.")
    bid = (
        D(option_bid)
        if option_bid is not None and D(option_bid).is_finite() and option_bid > 0
        else None
    )
    price = (
        D(index_price)
        if index_price is not None and D(index_price).is_finite() and index_price > 0
        else None
    )
    gross = (bid - p.entry_price) * p.quantity if bid is not None else None
    net = (
        gross - p.entry_fees - estimate_option_fees("SELL", bid, p.quantity, p.rates)
        if gross is not None
        else None
    )

    def result(reason=None):
        return IndexOptionDecision(p, reason, gross, net)

    if net is not None and day_net + net <= -p.daily_loss:
        return result("Daily loss limit")
    if net is not None and net <= -p.trade_loss:
        return result("Option loss limit")
    bull = p.direction == "CE"
    if price is not None:
        if price <= p.index_stop if bull else price >= p.index_stop:
            return result("Index trailing stop" if p.index_trailing else "Index ATR stop")
        if price >= p.index_target if bull else price <= p.index_target:
            return result("Index 6R target")
    if bid is not None:
        if p.option_stop is not None and bid <= p.option_stop:
            return result(
                "Option net-profit trailing stop"
                if p.net_floor is not None
                else "Option premium stop"
            )
        if p.option_target is not None and bid >= p.option_target:
            return result("Manual option premium target")
        executable = max(p.tick, bid - p.friction)
        trail_net = (
            (executable - p.entry_price) * p.quantity
            - p.entry_fees
            - estimate_option_fees("SELL", executable, p.quantity, p.rates)
        )
        if p.net_floor is not None and trail_net <= p.net_floor:
            return result("Option net-profit trailing stop")
        if p.cash_trail_enabled:
            peak = max(p.net_peak if p.net_peak is not None else trail_net, trail_net)
            p = replace(p, net_peak=peak)
            if peak >= p.cash_activation:
                floor = max(p.net_floor or D(0), peak - p.cash_distance)
                low, high = 1, int((executable / p.tick).to_integral_value(rounding=ROUND_CEILING))
                while low < high:
                    middle = (low + high) // 2
                    candidate = middle * p.tick
                    proceeds = (
                        (candidate - p.entry_price) * p.quantity
                        - p.entry_fees
                        - estimate_option_fees("SELL", candidate, p.quantity, p.rates)
                    )
                    if proceeds >= floor:
                        high = middle
                    else:
                        low = middle + 1
                candidate = ((low * p.tick + p.friction) / p.tick).to_integral_value(
                    rounding=ROUND_CEILING
                ) * p.tick
                p = replace(p, net_floor=floor, option_stop=max(p.option_stop or p.tick, candidate))
    if price is not None:
        risk = abs(p.index_reference - p.initial_index_stop)
        if risk > 0:
            peak = max(p.index_peak, price) if bull else min(p.index_peak, price)
            profit = (peak - p.index_reference) * (1 if bull else -1)
            active = p.index_trailing or profit >= risk * (2 if p.controlled else 1)
            gap = risk * (D(".5") if p.controlled else 1)
            candidate = peak - gap if bull else peak + gap
            if p.controlled:
                candidate = (candidate / D(".05")).to_integral_value(
                    rounding=ROUND_CEILING if bull else ROUND_FLOOR
                ) * D(".05")
            stop = (
                (max(p.index_stop, candidate) if bull else min(p.index_stop, candidate))
                if active
                else p.index_stop
            )
            p = replace(p, index_peak=peak, index_stop=stop, index_trailing=active)
    return result()
