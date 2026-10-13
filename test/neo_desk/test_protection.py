from dataclasses import replace
from decimal import Decimal as D

import pytest

from services.risk.index_options import IndexOptionRisk, evaluate_index_option


def risk(**kw):
    return replace(
        IndexOptionRisk(
            direction="CE",
            index_reference=D(100),
            initial_index_stop=D(90),
            index_stop=D(90),
            index_target=D(160),
            index_peak=D(100),
            entry_price=D(50),
            quantity=65,
            tick=D(".05"),
        ),
        **kw,
    )


@pytest.mark.parametrize("side,peak,expected", [("CE", D(110), D(100)), ("PE", D(90), D(100))])
def test_original_index_trail_arms_at_one_r(side, peak, expected):
    p = risk(
        direction=side,
        initial_index_stop=D(110) if side == "PE" else D(90),
        index_stop=D(110) if side == "PE" else D(90),
        index_target=D(40) if side == "PE" else D(160),
    )
    result = evaluate_index_option(p, peak, None, D(0))
    assert result.state.index_stop == expected and result.state.index_trailing
    later = evaluate_index_option(
        result.state, peak + (D(1) if side == "CE" else D(-1)), None, D(0)
    )
    assert later.state.index_stop == (D(101) if side == "CE" else D(99))


def test_controlled_index_runner_arms_at_two_r_protects_one_point_five_r():
    p = risk(controlled=True)
    assert evaluate_index_option(p, D(119), None, D(0)).state.index_stop == 90
    result = evaluate_index_option(p, D(120), None, D(0))
    assert result.state.index_stop == 115
    assert evaluate_index_option(result.state, D(114), None, D(0)).reason == "Index trailing stop"


def test_hard_target_remains_six_r_for_each_profile():
    for controlled in (False, True):
        assert (
            evaluate_index_option(risk(controlled=controlled), D(160), None, D(0)).reason
            == "Index 6R target"
        )


def test_cash_trail_uses_option_net_profit_not_index_points():
    p = risk(
        controlled=True,
        cash_trail_enabled=True,
        option_stop=D(45),
        rates=__import__("services.risk.option_costs", fromlist=["FeeSchedule"]).FeeSchedule(
            exchange=D(0), sebi=D(0), ipft=D(0), gst=D(0), stamp=D(0), stt=D(0)
        ),
    )
    result = evaluate_index_option(p, None, D("70.5"), D(0))
    assert result.state.net_peak == D(1300) and result.state.net_floor == 1050
    assert result.state.option_stop == D("66.7")
    assert (
        evaluate_index_option(result.state, None, D(65), D(0)).reason
        == "Option net-profit trailing stop"
    )


def test_option_guard_and_fees_can_exit_even_without_index_data():
    p = risk()
    assert evaluate_index_option(p, None, D(42), D(0)).reason == "Option loss limit"
    assert evaluate_index_option(p, None, D(49), D(-950)).reason == "Daily loss limit"
    assert evaluate_index_option(p, None, None, D(0)).net is None


def test_manual_premium_stop_and_target_are_option_prices():
    p = risk(option_stop=D(48), option_target=D(55))
    assert evaluate_index_option(p, D(105), D(47), D(0)).reason == "Option premium stop"
    assert evaluate_index_option(p, D(105), D(55), D(0)).reason == "Manual option premium target"
