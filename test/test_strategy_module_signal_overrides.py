"""Signal entries that carry their own size and risk levels, on a crypto leg.

An ML trade opens through a signal-mode strategy, but its quantity and its
stop, target and trail are decided per trade, not configured on the leg. They
travel as overrides on the entry and land in the run's leg state, which is
what the risk engine evaluates and what a checkpoint restores.

Every exit on a crypto leg is sent reduce-only, so two exits racing on one
leg can only shrink the position, never open one the other way.
"""

from unittest.mock import patch

import pytest

import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import engine, order_dispatch, risk_adapter, signals, state
from services.strategy_module.order_dispatch import DispatchResult

USER = "signal_crypto_test_user"


@pytest.fixture(scope="module", autouse=True)
def seed_master_contract():
    from database.symbol import SymToken, db_session, init_db

    init_db()
    inserted = False
    if SymToken.query.filter_by(symbol="BTCUSDFUT", exchange="CRYPTO").first() is None:
        db_session.add(
            SymToken(
                symbol="BTCUSDFUT",
                brsymbol="BTCUSD",
                name="BTC",
                exchange="CRYPTO",
                brexchange="DELTAIN",
                token="27",
                expiry="",
                strike=-1.0,
                lotsize=1,
                instrumenttype="PERPFUT",
                tick_size=0.5,
            )
        )
        inserted = True
    db_session.commit()
    yield
    if inserted:
        SymToken.query.filter_by(symbol="BTCUSDFUT", exchange="CRYPTO").delete()
        db_session.commit()
    db_session.remove()


@pytest.fixture(autouse=True)
def clean_slate():
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            if row["current_run_id"]:
                state.clear_run_state(row["current_run_id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def placed():
    seen = []

    def record(**kwargs):
        seen.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id=f"SB-{len(seen)}", response={})

    with (
        patch.object(signals.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(signals, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        yield seen


def _make():
    created, error = store.create_strategy(
        USER,
        {
            "name": "ML crypto test",
            "underlying": "MULTI",
            "underlying_exchange": "CRYPTO",
            "universe_tab": "stocks_fno",
            "strategy_kind": "signal",
            "direction": "both",
            "strategy_type": "positional",
            "product": "NRML",
            "legs": [
                {
                    "id": 1,
                    "symbol": "BTCUSDFUT",
                    "exchange": "CRYPTO",
                    "side": "both",
                    "qty": 1,
                    "segment": "futures",
                    "trail": {"x": 0, "y": 0},
                }
            ],
        },
    )
    assert error is None, error
    return store.get_strategy(created["id"], USER)


def test_crypto_orders_carry_the_carry_product():
    assert order_dispatch.product_for_exchange("NRML", "CRYPTO") == "NRML"
    assert order_dispatch.product_for_exchange("MIS", "CRYPTO") == "MIS"


def test_reduce_only_is_sent_only_where_the_venue_honours_it():
    crypto = order_dispatch.build_order(
        symbol="BTCUSDFUT", exchange="CRYPTO", action="BUY", quantity=1,
        product="NRML", strategy_name="t", reduce_only=True,
    )
    cash = order_dispatch.build_order(
        symbol="SBIN", exchange="NSE", action="BUY", quantity=1,
        product="MIS", strategy_name="t", reduce_only=True,
    )
    assert crypto["reduce_only"] is True
    assert "reduce_only" not in cash


def test_an_entry_carries_its_own_size_stop_target_and_trail(placed):
    strategy = _make()
    result = signals.handle_signal(
        strategy,
        "short_entry",
        leg_id=1,
        overrides={
            "quantity": 7,
            "sl_pts": 0.2,
            "target_pts": 0.6,
            "risk_unit": "percent",
            "trail": {"x": 0.15, "y": 0},
        },
    )
    assert result.ok, result.error
    assert placed[0]["quantity"] == "7"
    assert placed[0]["action"] == "SELL"
    assert placed[0]["product"] == "NRML"
    assert "reduce_only" not in placed[0]

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.apply_fill(run_id, 1, 85_000.0, is_entry=True)
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["qty"] == 7
    assert leg["risk_unit"] == "percent"
    assert leg["trail_x"] == 0.15
    risk = risk_adapter.leg_to_position_risk(leg)
    # A short: the stop 0.2% above the fill, the target 0.6% below.
    assert risk.stop_price == pytest.approx(85_170.0)
    assert risk.target_price == pytest.approx(84_490.0)
    assert risk.trailing_enabled


def test_the_configured_leg_is_left_as_it_was(placed):
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1, overrides={"quantity": 9})
    legs = store.get_strategy(strategy.id, USER).legs
    assert legs[0]["qty"] == 1


def test_every_crypto_exit_is_reduce_only(placed):
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1, overrides={"quantity": 2})
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.apply_fill(run_id, 1, 85_000.0, is_entry=True)

    result = signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert result.ok, result.error
    assert placed[-1]["action"] == "SELL"
    assert placed[-1]["quantity"] == "2"
    assert placed[-1]["reduce_only"] is True


def test_an_entry_can_carry_an_exchange_held_stop(placed):
    strategy = _make()
    signals.handle_signal(
        strategy,
        "long_entry",
        leg_id=1,
        overrides={"quantity": 1},
        bracket={"bracket_stop_loss_price": 84_830.0, "bracket_stop_trigger_method": "mark_price"},
    )
    assert placed[0]["bracket_stop_loss_price"] == "84830.0"
    assert placed[0]["bracket_stop_trigger_method"] == "mark_price"


def test_a_restart_keeps_a_percent_stop_in_percent():
    # A per-trade stop of 0.2% read back as 0.2 points would sit $0.20 from a
    # $85,000 entry and close the trade on the next tick.
    from services.strategy_module import recovery

    leg = recovery._rebuild_legacy_leg(
        "1",
        entries=[],
        exits=[],
        cp_leg={
            "position": "S",
            "symbol": "BTCUSDFUT",
            "exchange": "CRYPTO",
            "qty": 7,
            "status": "open",
            "entry_avg": 85_000.0,
            "entry_status": "complete",
            "risk_unit": "percent",
            "sl_pts": 0.2,
            "target_pts": 0.6,
        },
        config_leg={},
    )
    assert leg["risk_unit"] == "percent"
    risk = risk_adapter.leg_to_position_risk({**leg, "entry_avg": 85_000.0})
    assert risk.stop_price == pytest.approx(85_170.0)



def test_an_entrys_own_levels_survive_a_restart_before_any_checkpoint(placed):
    # The order row carries the levels, so a crash between the entry and the
    # first checkpoint does not bring the trade back with no stop at all.
    from services.strategy_module import recovery

    strategy = _make()
    result = signals.handle_signal(
        strategy,
        "short_entry",
        leg_id=1,
        overrides={
            "quantity": 7,
            "sl_pts": 0.2,
            "target_pts": 0.6,
            "risk_unit": "percent",
            "trail": {"x": 0.15, "y": 0},
        },
    )
    run_id = result.run_id
    entry = [o for o in store.list_orders(run_id) if o["kind"] == "entry"][0]
    assert entry["risk"]["risk_unit"] == "percent"
    store.update_order(entry["id"], status="complete", avg_fill_price=85_000.0, filled_qty=7)
    state.clear_run_state(run_id)

    recovered = recovery.recover_run(run_id)
    assert recovered is not None
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["risk_unit"] == "percent"
    assert leg["sl_pts"] == pytest.approx(0.2)
    assert leg["trail_x"] == pytest.approx(0.15)
    risk = risk_adapter.leg_to_position_risk(leg)
    assert risk.stop_price == pytest.approx(85_170.0)
