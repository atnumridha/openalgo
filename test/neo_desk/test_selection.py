from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest
from conftest import contract, quote, when

from services.neo_desk.presets import get_preset
from services.neo_desk.selection import select_contract


def choose(c=None, q=None, cash=D(10000)):
    c = c or contract()
    q = q or quote(c)
    return select_contract(
        [c], {c.symbol: q}, get_preset("orb_trail"), cash, when(), direction="CE"
    )


def test_selects_exact_lot_with_allowance_and_costs():
    s = choose()
    assert s.ok and s.quantity == 65 and s.limit_price == D("50.70")
    assert s.entry_cost > s.limit_price * 65
    assert not choose(cash=D(3000)).ok


@pytest.mark.parametrize(
    "change",
    [
        {"received_at": when() - timedelta(seconds=6)},
        {"exchange_time": when() - timedelta(seconds=10)},
        {"ask_qty": 64},
        {"bid_qty": 0},
        {"bid": D(48)},
        {"ask": D(56)},
    ],
)
def test_stale_thin_or_wide_quotes_refuse(change):
    assert not choose(q=replace(quote(), **change)).ok


@pytest.mark.parametrize(
    "change",
    [
        {"lot_size": 75},
        {"tick_size": D(0)},
        {"expiry": when().date() - timedelta(days=1)},
        {"option_type": "PE"},
    ],
)
def test_wrong_or_expired_contract_refuses(change):
    assert not choose(c=replace(contract(), **change)).ok


def test_controlled_profile_requires_five_recent_option_minutes():
    c = contract()
    q = quote(c)
    assert not select_contract(
        [c], {c.symbol: q}, get_preset("orb_controls"), D(10000), when(), direction="CE"
    ).ok


def test_equal_premiums_choose_strike_nearest_the_current_index():
    a = contract(symbol="A-far", strike=D(23000))
    b = contract(symbol="Z-near", strike=D(22500))
    selected = select_contract(
        [a, b],
        {a.symbol: quote(a), b.symbol: quote(b)},
        get_preset("orb_trail"),
        D(10000),
        when(),
        direction="CE",
        index_reference=D(22500),
    )
    assert selected.contract == b
