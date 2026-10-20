"""Crypto fee core against the shared vectors, plus the edges they cannot show."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.crypto_fees import (
    ContractFees,
    FeeProfile,
    fees_from_fills,
    fill_fee,
    net_pnl,
    open_position_fees,
    opening_voucher,
    reported_commission,
)

VECTORS = json.loads(Path(__file__).with_name("vectors.json").read_text())


def _contract(raw: dict) -> ContractFees:
    return ContractFees(**raw)


def _profile(raw: dict) -> FeeProfile:
    return FeeProfile(**{k: tuple(v) if isinstance(v, list) else v for k, v in raw.items()})


@pytest.mark.parametrize("case", VECTORS["fill_fee"], ids=lambda c: c["name"])
def test_fill_fee_vectors(case):
    result = fill_fee(_contract(case["contract"]), _profile(case["profile"]), **case["args"])
    expect = case["expect"]
    for key in ("fee", "gst", "total"):
        assert getattr(result, key) == pytest.approx(expect[key], abs=1e-9), key
    assert result.waived is expect["waived"]
    assert result.capped is expect["capped"]


@pytest.mark.parametrize("case", VECTORS["open_position_fees"], ids=lambda c: c["name"])
def test_open_position_vectors(case):
    result = open_position_fees(
        _contract(case["contract"]), _profile(case["profile"]), **case["args"]
    )
    for key, value in case["expect"].items():
        actual = getattr(result, key)
        if value is None:
            assert actual is None, key
        else:
            assert actual == pytest.approx(value, abs=1e-9), key


@pytest.mark.parametrize("case", VECTORS["net_pnl"], ids=lambda c: c["name"])
def test_net_pnl_vectors(case):
    assert net_pnl(**case["args"]) == pytest.approx(case["expect"], abs=1e-9)


@pytest.mark.parametrize("case", VECTORS["opening_voucher"], ids=lambda c: c["name"])
def test_opening_voucher_vectors(case):
    result = opening_voucher(_contract(case["contract"]), _profile(case["profile"]), **case["args"])
    assert result == pytest.approx(case["expect"], abs=1e-9)


@pytest.mark.parametrize("case", VECTORS["diwali_examples"], ids=lambda c: c["name"])
def test_delta_published_diwali_examples(case):
    btc = ContractFees(symbol="BTCUSD")
    profile = _profile(case["profile"])
    held = case["held_minutes"]
    opening = fill_fee(btc, profile, **case["open"])
    standard = FeeProfile(gst_pct=profile.gst_pct, scalper_offer=False)
    scalper = FeeProfile(gst_pct=profile.gst_pct)

    def net(p: FeeProfile) -> float:
        close = fill_fee(btc, p, **case["close"], closing=True, held_minutes=held)
        return net_pnl(gross=case["gross"], fees_paid=opening.total, exit_fee_due=close.total)

    expect = case["expect"]
    assert net(standard) == pytest.approx(expect["no_offer_net"], abs=1e-9)
    assert net(scalper) == pytest.approx(expect["scalper_net"], abs=1e-9)
    assert net(profile) == pytest.approx(expect["diwali_net"], abs=1e-9)
    voucher = opening_voucher(btc, profile, opening_fee=opening.fee, held_minutes=held)
    assert voucher == pytest.approx(expect["voucher"], abs=1e-9)


def test_reported_commission_adds_gst_only_when_the_figure_excludes_it():
    # $85 at 0.05%: 0.0425 before GST, 0.05015 with it.
    assert reported_commission(0.0425, notional=85, effective_rate=0.0005) == pytest.approx(0.05015)
    assert reported_commission(0.05015, notional=85, effective_rate=0.0005) == pytest.approx(
        0.05015
    )
    assert reported_commission(0.0, notional=85, effective_rate=0.0005) == 0.0
    assert reported_commission(0.031) == 0.031


BTC = ContractFees(symbol="BTCUSD")
DIWALI = FeeProfile(diwali_offer=True)


def test_fills_closed_inside_the_window_pay_only_the_opening_fee():
    fills = [(0.0, -1, 85_000.0), (600.0, 1, 84_500.0)]
    fees, voucher, opened = fees_from_fills(BTC, FeeProfile(), fills, contract_value=0.001)
    assert fees == pytest.approx(85 * 0.0005 * 1.18)
    assert voucher == 0.0
    assert opened is None


def test_fills_closed_after_the_window_pay_both_sides():
    fills = [(0.0, 2, 85_000.0), (3_600.0, -2, 86_000.0)]
    fees, _, _ = fees_from_fills(BTC, FeeProfile(), fills, contract_value=0.001)
    assert fees == pytest.approx((170 + 172) * 0.0005 * 1.18)


def test_a_flip_closes_the_old_side_and_opens_the_new_one():
    # Long 1, then sell 3 ten minutes later: closes 1 free, opens 2 short.
    fills = [(0.0, 1, 100.0), (600.0, -3, 100.0)]
    fees, _, opened = fees_from_fills(BTC, FeeProfile(), fills, contract_value=1.0)
    assert fees == pytest.approx((100 + 200) * 0.0005 * 1.18)
    assert opened == 600.0


def test_an_open_position_has_earned_no_voucher_yet():
    fills = [(0.0, 1, 100.0)]
    _, voucher, opened = fees_from_fills(BTC, DIWALI, fills, contract_value=1.0)
    assert voucher == 0.0
    assert opened == 0.0


def test_a_btc_close_inside_30_minutes_earns_the_opening_fee_before_gst():
    fills = [(0.0, 1000, 60_000.0), (1_200.0, -1000, 60_100.0)]
    fees, voucher, _ = fees_from_fills(BTC, DIWALI, fills, contract_value=0.001)
    assert fees == pytest.approx(30.0 * 1.18)
    assert voucher == pytest.approx(30.0)


def test_a_partial_close_earns_its_share_of_the_opening_fee():
    fills = [(0.0, 1000, 60_000.0), (600.0, -400, 60_100.0), (3_000.0, -600, 60_050.0)]
    _, voucher, opened = fees_from_fills(BTC, DIWALI, fills, contract_value=0.001)
    # 40% closed at 10 minutes earns 40% of $30; the rest closes at 50 minutes.
    assert voucher == pytest.approx(12.0)
    assert opened is None


def test_eth_gets_the_free_close_but_no_voucher():
    eth = ContractFees(symbol="ETHUSD")
    fills = [(0.0, 10, 2_000.0), (600.0, -10, 2_010.0)]
    fees, voucher, _ = fees_from_fills(eth, DIWALI, fills, contract_value=0.01)
    assert fees == pytest.approx(200 * 0.0005 * 1.18)
    assert voucher == 0.0


def test_the_monthly_cap_counts_what_was_already_earned():
    fills = [(0.0, 1000, 60_000.0), (600.0, -1000, 60_000.0)]
    _, voucher, _ = fees_from_fills(
        BTC, DIWALI, fills, contract_value=0.001, voucher_earned_before=90.0
    )
    assert voucher == pytest.approx(10.0)


def test_a_voucher_is_never_part_of_net_cash():
    view = open_position_fees(
        BTC, DIWALI, entry_notional=60_000, exit_notional=60_100, held_minutes=5
    )
    assert view.voucher_now > 0
    assert net_pnl(gross=100.0, fees_paid=view.entry_fee, exit_fee_due=view.exit_fee_now) == (
        pytest.approx(100.0 - 35.4)
    )
