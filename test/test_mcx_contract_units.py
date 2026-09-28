"""MCX orders keep physical quantities; money uses the quote unit."""

import pytest

from services.risk.contract_units import mcx_contract_multiplier, price_multiplier
from services.strategy_module import risk_adapter


@pytest.mark.parametrize(
    "root,lot,factor",
    [
        ("GOLDM", 100, 0.1),
        ("CRUDEOILM", 10, 1),
        ("SILVERM", 5, 1),
        ("NATGASMINI", 250, 1),
    ],
)
def test_verified_contract_units(root, lot, factor):
    assert mcx_contract_multiplier(root, lot) == factor
    leg = {
        "symbol": f"{root}05OCT261000CE",
        "exchange": "MCX",
        "lot_size": lot,
        "price_multiplier": factor,
    }
    assert price_multiplier(leg) == factor


@pytest.mark.parametrize(
    "root,lot",
    [
        ("GOLD", 100),
        ("GOLDM", 10),
        ("GOLDM", 100.1),
        ("SILVERM", 0),
        ("CRUDEOILM", True),
        ("GOLDM", float("nan")),
    ],
)
def test_unknown_or_inconsistent_units_are_refused(root, lot):
    with pytest.raises(ValueError):
        mcx_contract_multiplier(root, lot)


@pytest.mark.parametrize("factor", [1, 0, -1, True, float("nan"), float("inf")])
def test_snapshot_cannot_override_verified_quote_units(factor):
    with pytest.raises(ValueError):
        price_multiplier(
            {"symbol": "GOLDM05OCT261000CE", "exchange": "MCX", "price_multiplier": factor}
        )


def test_legacy_known_symbol_recovers_units_but_unknown_fails_closed():
    assert price_multiplier({"symbol": "GOLDM05OCT261000CE", "exchange": "MCX"}) == 0.1
    with pytest.raises(ValueError):
        price_multiplier({"symbol": "GOLDM_FAKE", "exchange": "MCX"})
    assert price_multiplier({"symbol": "NIFTY29SEP2622750CE", "exchange": "NFO"}) == 1


def test_goldm_adapter_uses_money_units_without_changing_order_quantity():
    leg = {
        "leg_id": 1,
        "position": "B",
        "symbol": "GOLDM05OCT261000CE",
        "exchange": "MCX",
        "qty": 100,
        "lot_size": 100,
        "price_multiplier": 0.1,
        "entry_avg": 100,
        "entry_status": "complete",
        "status": "open",
        "sl_pts": 30,
        "ltp": 160,
    }
    risk = risk_adapter.leg_to_position_risk(leg)
    assert risk.quantity == 10
    assert risk.initial_stop_price == 70
    assert risk_adapter.run_pnl({"legs": {1: leg}}) == (0, 600)
    assert leg["qty"] == 100


def test_goldm_profit_stop_protects_100_then_300_then_600():
    from services.risk.profit_exit import FIXED_PROFIT_LOCK_RECIPE, profit_config

    COSTS = {
        k: 0
        for k in (
            "brokerage_per_order",
            "exchange_rate",
            "sebi_rate",
            "gst_rate",
            "stamp_buy_rate",
            "stt_sell_rate",
            "slippage_bps",
        )
    }
    leg = {
        "leg_id": 1,
        "position": "B",
        "symbol": "GOLDM05OCT261000CE",
        "exchange": "MCX",
        "qty": 100,
        "lot_size": 100,
        "price_multiplier": 0.1,
        "entry_avg": 100,
        "entry_status": "complete",
        "status": "open",
        "sl_pts": 30,
    }
    leg["profit_protection"] = profit_config(
        {"tick_size": 0.5}, COSTS, recipe=FIXED_PROFIT_LOCK_RECIPE
    )
    for price, floor in [(130, 100), (160, 300), (190, 600), (250, 1200)]:
        result = risk_adapter.evaluate_leg(leg, price)
        assert (result.stop_price - 100) * 10 == pytest.approx(floor)
        assert not result.breached
    assert risk_adapter.evaluate_leg(leg, 219).breached
    assert leg["qty"] == 100


def test_durable_goldm_partial_exit_pnl_matches_recovery():
    from datetime import datetime
    from types import SimpleNamespace

    from database.strategy_module_db import _fold_owner_pnl, _pnl_fill_fact
    from services.strategy_module.recovery import _rebuild_legacy_leg

    orders = [
        dict(
            id=1,
            leg_id=1,
            symbol="GOLDM05OCT261000CE",
            exchange="MCX",
            status="complete",
            kind="entry",
            action="BUY",
            qty=100,
            filled_qty=100,
            avg_fill_price=100,
            placed_at=datetime(2026, 9, 28),
        ),
        dict(
            id=2,
            leg_id=1,
            symbol="GOLDM05OCT261000CE",
            exchange="MCX",
            status="complete",
            kind="exit_sl",
            action="SELL",
            qty=40,
            filled_qty=40,
            avg_fill_price=130,
            placed_at=datetime(2026, 9, 28),
        ),
    ]
    result = _fold_owner_pnl(
        [_pnl_fill_fact(SimpleNamespace(**o)) for o in orders], referenced=True
    )
    assert result[0] == pytest.approx(120)
    rebuilt = _rebuild_legacy_leg("1", orders[:1], orders[1:], {}, {"sl_pts": 30, "position": "B"})
    assert rebuilt["realized_pnl"] == pytest.approx(120)
    assert rebuilt["qty"] == 60
    assert rebuilt["price_multiplier"] == 0.1


def test_goldm_resolver_requires_consistent_master_metadata():
    from services.strategy_module.symbol_resolver import _finish

    contract = {"lotsize": 100, "tick_size": 0.5, "contract_value": 0.1}
    args = ("GOLDM05OCT261000CE", "MCX", {"underlying": "GOLDM", "lots": 1})
    resolved = _finish(contract, *args)
    assert resolved.ok and resolved.quantity == 100 and resolved.price_multiplier == 0.1
    for change in ({"lotsize": 10}, {"contract_value": None}, {"contract_value": 1}):
        assert not _finish(contract | change, *args).ok
