"""Sizing a suggested trade from the balance, the stop and the fees."""

from __future__ import annotations

import math

import pytest

from ml_signals.sizing import size_trade
from services.crypto_fees import ContractFees, FeeProfile

BTC = ContractFees(symbol="BTCUSD")
TAKER_GST = 0.0005 * 1.18


def _size(**overrides):
    args = {
        "side": 1,
        "entry": 60_000.0,
        "stop_pct": 0.2,
        "target_pct": 0.5,
        "balance": 1_000.0,
        "risk_pct": 1.0,
        "max_leverage": 10.0,
        "contract_value": 0.001,
        "contract": BTC,
        "profile": FeeProfile(),
        "hold_minutes": 28,
    }
    args.update(overrides)
    return size_trade(**args)


def test_contracts_follow_the_risk_budget_with_fees_in_the_stop():
    sized = _size()
    per = 60.0
    stop_price = 60_000 * 0.998
    loss_one = per * 0.002 + per * TAKER_GST + 0.001 * stop_price * TAKER_GST
    assert sized.ok
    assert sized.contracts == math.floor(10.0 / loss_one)
    assert sized.risk_amount <= sized.risk_budget + 1e-9
    assert sized.risk_budget == pytest.approx(10.0)


def test_leverage_caps_the_size():
    sized = _size(stop_pct=0.02, risk_pct=5.0, max_leverage=2.0)
    assert sized.ok and sized.capped_by_leverage
    assert sized.notional <= 1_000.0 * 2.0 + 1e-6
    assert sized.margin == pytest.approx(sized.notional / 2.0)


def test_one_contract_over_budget_is_refused_with_the_amount():
    sized = _size(balance=20.0, risk_pct=0.5, contract_value=1.0, entry=150.0, stop_pct=0.2)
    assert not sized.ok
    assert "$0.10 risk budget" in sized.reason
    assert sized.contracts == 0


def test_wait_is_not_sized():
    assert not _size(side=0).ok


def test_no_balance_is_refused_in_plain_words():
    sized = _size(balance=0.0)
    assert not sized.ok and "USD balance" in sized.reason


def test_inside_the_scalper_window_the_target_closes_free():
    sized = _size(hold_minutes=28)
    assert sized.exit_fee_in_window == 0.0
    gross = sized.notional * 0.005
    assert sized.profit_at_target == pytest.approx(gross - sized.entry_fee)


def test_a_btc_diwali_trade_shows_its_voucher_beside_the_cash_figures():
    sized = _size(profile=FeeProfile(diwali_offer=True))
    assert sized.voucher_if_in_window == pytest.approx(sized.entry_fee / 1.18)
    plain = _size()
    assert sized.profit_at_target == pytest.approx(plain.profit_at_target)


def test_eth_gets_no_voucher():
    sized = _size(contract=ContractFees(symbol="ETHUSD"), profile=FeeProfile(diwali_offer=True))
    assert sized.voucher_if_in_window == 0.0
