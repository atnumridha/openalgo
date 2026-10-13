"""Translate native filled quantity and persisted provider protection into shared risk."""

from dataclasses import fields
from decimal import Decimal as D

from services.risk.index_options import IndexOptionRisk, evaluate_index_option
from services.risk.option_costs import FeeSchedule, estimate_option_fees


def evaluate(protection, leg, index_price, option_bid, day_net, brokerage=D(0)):
    p = protection
    avg = D(str(leg["entry_avg"]))
    qty = int(leg["qty"])
    rates = FeeSchedule(brokerage=brokerage)

    def value(key, default=None):
        return D(str(p[key])) if p.get(key) is not None else default

    risk = IndexOptionRisk(
        direction=p["direction"],
        index_reference=value("index_reference"),
        initial_index_stop=value("initial_stop"),
        index_stop=value("index_stop"),
        index_target=value("target"),
        index_peak=value("index_peak"),
        entry_price=avg,
        quantity=qty,
        tick=value("tick_size"),
        controlled=bool(p.get("controlled")),
        index_trailing=bool(p.get("index_trailing")),
        option_stop=value("option_stop"),
        option_target=value("option_target"),
        entry_fees=estimate_option_fees("BUY", avg, qty, rates),
        net_peak=value("net_peak"),
        net_floor=value("net_floor"),
        cash_trail_enabled=bool(p.get("cash_trail_enabled")),
        cash_activation=value("cash_activation", D(1000)),
        cash_distance=value("cash_distance", D(250)),
        rates=rates,
    )
    decision = evaluate_index_option(risk, index_price, option_bid, D(day_net))
    updated = dict(p)
    for key, attr in [
        ("index_stop", "index_stop"),
        ("index_peak", "index_peak"),
        ("option_stop", "option_stop"),
        ("net_peak", "net_peak"),
        ("net_floor", "net_floor"),
    ]:
        v = getattr(decision.state, attr)
        updated[key] = str(v) if v is not None else None
    updated["index_trailing"] = decision.state.index_trailing
    updated["gross_open"] = str(decision.gross) if decision.gross is not None else None
    updated["net_open_estimate"] = str(decision.net) if decision.net is not None else None
    return updated, decision.reason
