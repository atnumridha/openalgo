"""Sandbox crypto positions report Delta's fees, worked out from their own fills."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from test_gthread_sandbox_support import prepare_databases, release_sessions, reset_user

USER = "sandbox_crypto_fees"


@pytest.fixture(autouse=True)
def account(monkeypatch):
    prepare_databases()
    reset_user(USER)
    release_sessions()
    from services import crypto_fee_service
    from services.crypto_fees import ContractFees

    # No network: BTCUSD's published rates.
    monkeypatch.setattr(
        crypto_fee_service,
        "contract_fees",
        lambda symbol, exchange="CRYPTO": (ContractFees(symbol="BTCUSD"), 0.001),
    )
    monkeypatch.setattr(
        crypto_fee_service,
        "fee_profile",
        lambda settings=None: crypto_fee_service.FeeProfile(),
    )
    yield
    release_sessions()


def _seed(fills, quantity):
    from database.sandbox_db import SandboxPositions, SandboxTrades, db_session

    now = datetime.now()
    for index, (minutes_ago, action, qty, price) in enumerate(fills):
        db_session.add(
            SandboxTrades(
                tradeid=f"{USER}-{index}",
                orderid=f"{USER}-o{index}",
                user_id=USER,
                symbol="BTCUSDFUT",
                exchange="CRYPTO",
                action=action,
                quantity=qty,
                price=Decimal(str(price)),
                product="NRML",
                trade_timestamp=now - timedelta(minutes=minutes_ago),
            )
        )
    db_session.add(
        SandboxPositions(
            user_id=USER,
            symbol="BTCUSDFUT",
            exchange="CRYPTO",
            product="NRML",
            quantity=quantity,
            average_price=Decimal("85000"),
            ltp=Decimal("84500"),
            pnl=Decimal("0"),
        )
    )
    db_session.commit()
    position = SandboxPositions.query.filter_by(user_id=USER, symbol="BTCUSDFUT").first()
    db_session.expunge(position)
    db_session.remove()
    return position


def test_open_position_carries_its_opening_fee():
    from sandbox.position_manager import PositionManager

    position = _seed([(5, "SELL", 2, 85000)], quantity=-2)
    fields = PositionManager(USER)._crypto_fee_fields(position, 0.001)
    assert fields["fees_paid"] == pytest.approx(170 * 0.0005 * 1.18)
    assert fields["funding"] == 0.0
    assert fields["opened_at"]


def test_closed_inside_the_scalper_window_pays_only_to_open():
    from sandbox.position_manager import PositionManager

    position = _seed([(20, "SELL", 1, 85000), (10, "BUY", 1, 84500)], quantity=0)
    fields = PositionManager(USER)._crypto_fee_fields(position, 0.001)
    assert fields["fees_paid"] == pytest.approx(85 * 0.0005 * 1.18)
    assert fields["opened_at"] == ""


def test_cash_positions_are_untouched():
    from sandbox.position_manager import PositionManager

    class Cash:
        exchange = "NSE"

    assert PositionManager(USER)._crypto_fee_fields(Cash(), 1.0) == {}
