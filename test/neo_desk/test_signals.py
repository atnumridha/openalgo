from dataclasses import replace
from decimal import Decimal as D

import pytest
from conftest import bars, when

from services.neo_desk.presets import get_preset
from services.neo_desk.signals import evaluate_setup


@pytest.mark.parametrize(
    "profile", ["orb_trail", "orb_controls", "donchian_controls", "price_retest"]
)
@pytest.mark.parametrize("side", ["CE", "PE"])
def test_both_directions_have_six_r(profile, side):
    s = evaluate_setup(bars(profile, side), get_preset(profile))
    assert s is not None and s.direction == side
    assert abs(s.target - s.index_reference) == 6 * abs(s.index_reference - s.initial_stop)
    assert s.execute_at > s.candle_open


def test_final_confirmed_close():
    assert evaluate_setup(bars(last="15:00"), get_preset("orb_trail")).execute_at == when("15:15")
    assert evaluate_setup(bars(last="15:15"), get_preset("orb_trail")) is None


@pytest.mark.parametrize("change", [{"confirmed": False}, {"repaired": True}])
def test_forming_or_uncertain_bar_never_signals(change):
    rows = bars()
    rows[-1] = replace(rows[-1], **change)
    assert evaluate_setup(rows, get_preset("orb_trail")) is None


def test_missing_opening_range_or_warmup_does_not_trade():
    rows = bars()
    assert evaluate_setup(rows[-2:], get_preset("orb_trail")) is None
    assert (
        evaluate_setup([b for b in rows if b.time != when("09:15")], get_preset("orb_trail"))
        is None
    )


def test_retest_waits_for_later_confirmation():
    assert evaluate_setup(bars("price_retest")[:-1], get_preset("price_retest")) is None


def test_donchian_repaired_trend_rejects():
    rows = bars("donchian_controls")
    rows[-3] = replace(rows[-3], repaired=True)
    assert evaluate_setup(rows, get_preset("donchian_controls")) is None
