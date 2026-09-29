"""Kotak-style basket topologies are static shapes, not entry signals."""

from services.strategy_module.basket_templates import all_templates, get_template


def _payoff(template, spot, *, atm=100, step=10):
    total = 0.0
    for leg in template.legs:
        strike = atm + leg.strike_offset * step
        intrinsic = max(spot - strike, 0) if leg.option_type == "CE" else max(strike - spot, 0)
        total += (1 if leg.side == "B" else -1) * leg.lots * intrinsic
    return total


def test_all_16_template_shapes():
    templates = all_templates()
    assert len(templates) == 16
    assert [x.lots for x in get_template("call-ratio-spread").legs] == [1, 2]
    assert [x.lots for x in get_template("long-call-butterfly").legs] == [1, 2, 1]
    assert len([x for x in templates if x.provenance == "conventional-inference"]) == 4
    assert {x.category for x in templates} == {"bullish", "bearish", "neutral", "volatile"}
    assert len({x.id for x in templates}) == 16


def test_template_payoff_tails():
    ratio = get_template("call-ratio-spread")
    assert _payoff(ratio, 1000) < _payoff(ratio, 100)
    butterfly = get_template("long-call-butterfly")
    assert _payoff(butterfly, 100) > _payoff(butterfly, 0)
    assert _payoff(butterfly, 100) > _payoff(butterfly, 200)
    buy_call = get_template("buy-call")
    assert _payoff(buy_call, 200) > 0
    short_straddle = get_template("short-straddle")
    assert _payoff(short_straddle, 1000) < 0
    assert _payoff(short_straddle, 0) < 0
