"""Closed positions release reserved risk only from attributable durable fills."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from database import strategy_module_db as store
from services.strategy_module import portfolio_governor as governor
from services.strategy_module import state


@pytest.fixture
def closed_trade():
    store.init_db()
    owner = f"closed-reservation-{uuid4().hex}"
    strategy = store.SmStrategy(
        user_id=owner,
        name=owner,
        universe_tab="nifty",
        underlying="NIFTY",
        underlying_exchange="NSE",
        webhook_token_hash=uuid4().hex,
    )
    store.db_session.add(strategy)
    store.db_session.flush()
    start = datetime(2026, 9, 28, 7, 0)
    run = store.SmStrategyRun(
        strategy_id=strategy.id,
        mode="sandbox",
        broker="kotak",
        started_at=start,
        stopped_at=start + timedelta(minutes=1),
        stop_reason="manual",
    )
    store.db_session.add(run)
    store.db_session.flush()
    reference = uuid4().hex
    common = {
        "run_id": run.id,
        "leg_id": 1,
        "position_ref": reference,
        "symbol": "NIFTY29SEP2626000CE",
        "exchange": "NFO",
        "product": "MIS",
        "qty": 25,
        "status": "complete",
        "filled_qty": 25,
        "avg_fill_price": Decimal("100"),
    }
    entry = store.SmStrategyOrder(
        **common,
        kind="entry",
        action="BUY",
        broker_order_id=uuid4().hex,
        placed_at=start,
        filled_at=start,
    )
    exit_order = store.SmStrategyOrder(
        **common,
        kind="exit_leg_manual",
        action="SELL",
        broker_order_id=uuid4().hex,
        placed_at=start + timedelta(seconds=30),
        filled_at=start + timedelta(seconds=31),
    )
    store.db_session.add_all([entry, exit_order])
    store.db_session.commit()
    scope = f"{owner}|sandbox|sandbox"
    component = governor.ReservationComponent(
        leg_id=1,
        cash_positions=0,
        nifty_option_positions=1,
        derivative_positions=1,
        configured_risk=Decimal("250"),
        estimated_debit=Decimal("2500"),
        exchange="NFO",
        symbol=entry.symbol,
        quantity_delta=Decimal("25"),
        baseline_quantity=Decimal("0"),
        run_id=run.id,
        position_ref=reference,
        entry_order_id=entry.id,
    )
    reservation = governor._EntryReservation(owner, scope, [component], Decimal("25000"), True)
    governor._persist_reservation(reservation)
    governor._entry_reservations[scope] = [reservation]
    governor._reservation_cash_baselines[scope] = Decimal("25000")
    state.clear_run_state(run.id)
    trade = SimpleNamespace(
        owner=owner,
        scope=scope,
        strategy=strategy,
        run=run,
        entry=entry,
        exit=exit_order,
        component=component,
        reservation=reservation,
    )
    run_id, strategy_id = run.id, strategy.id
    yield trade
    state.clear_run_state(run_id)
    governor._entry_reservations.pop(trade.scope, None)
    governor._reservation_cash_baselines.pop(trade.scope, None)
    store.db_session.rollback()
    store.db_session.query(store.SmRiskReservation).filter_by(user_id=owner).delete()
    store.db_session.query(store.SmStrategyOrder).filter_by(run_id=run_id).delete()
    store.db_session.query(store.SmStrategyRun).filter_by(id=run_id).delete()
    store.db_session.query(store.SmStrategy).filter_by(id=strategy_id).delete()
    store.db_session.commit()
    store.db_session.remove()


def reconcile(trade):
    return governor._reconcile_reservations(
        trade.owner,
        governor.EntryFacts(mode="sandbox", available_cash=Decimal("25000"), scope=trade.scope),
    )


@pytest.mark.parametrize("restart", [False, True])
def test_closed_trade_releases_durable_and_memory_reservation(closed_trade, restart):
    trade = closed_trade
    if restart:
        governor._entry_reservations.pop(trade.scope)
        governor._reservation_cash_baselines.pop(trade.scope)
        governor._restore_reservations(trade.scope, trade.owner)

    assert reconcile(trade) == []
    assert trade.scope not in governor._entry_reservations
    assert trade.scope not in governor._reservation_cash_baselines
    assert store.list_risk_reservations(trade.owner, scope=trade.scope) == []
    governor._restore_reservations(trade.scope, trade.owner)
    assert reconcile(trade) == []


@pytest.mark.parametrize(
    "target,updates",
    [
        ("exit", {"status": "open", "filled_qty": 10}),
        ("exit", {"status": "unknown", "filled_qty": 25}),
        ("exit", {"filled_qty": 10}),
        ("exit", {"filled_qty": None}),
        ("exit", {"filled_qty": 26}),
        ("exit", {"status": "cancelled", "filled_qty": 25}),
        ("exit", {"position_ref": "another-position"}),
        ("exit", {"action": "BUY"}),
        ("exit", {"symbol": "OTHER"}),
        ("exit", {"product": "NRML"}),
        ("exit", {"avg_fill_price": None}),
        ("entry", {"position_ref": "reused-order-id"}),
        ("entry", {"position_ref": "reused-order-id", "status": "cancelled", "filled_qty": 0}),
        ("entry", {"status": "cancelled", "filled_qty": 10}),
        ("run", {"mode": "live"}),
        ("run", {"stopped_at": None}),
        ("strategy", {"user_id": "another-owner"}),
    ],
)
def test_incomplete_or_unmatched_fill_evidence_keeps_reservation(closed_trade, target, updates):
    trade = closed_trade
    for name, value in updates.items():
        setattr(getattr(trade, target), name, value)
    store.db_session.commit()

    assert reconcile(trade)
    assert store.list_risk_reservations(trade.owner, scope=trade.scope)


def test_closed_runtime_state_cannot_override_partial_durable_exit(closed_trade):
    trade = closed_trade
    trade.exit.filled_qty = 10
    trade.exit.status = "open"
    store.db_session.commit()
    state.hydrate_run_state(
        trade.run.id,
        {
            "legs": {"1": {"position_ref": trade.component.position_ref, "status": "closed"}},
        },
    )

    assert reconcile(trade)
    assert store.list_risk_reservations(trade.owner, scope=trade.scope)


def test_only_closed_component_is_removed_from_durable_multi_leg_reservation(closed_trade):
    trade = closed_trade
    unresolved = replace(trade.component, leg_id=2, position_ref=uuid4().hex, entry_order_id=None)
    store.delete_risk_reservations(trade.owner, [trade.entry.id], scope=trade.scope)
    trade.reservation.components.append(unresolved)
    governor._persist_reservation(trade.reservation)

    assert reconcile(trade) == [unresolved]
    durable = store.list_risk_reservations(trade.owner, scope=trade.scope)
    assert len(durable) == 1
    assert [component["leg_id"] for component in durable[0]["components"]] == [2]
    governor._entry_reservations.pop(trade.scope)
    governor._restore_reservations(trade.scope, trade.owner)
    assert reconcile(trade) == [unresolved]


@pytest.mark.parametrize("broker", ["kotak", "other"])
def test_live_closed_trade_requires_matching_broker(closed_trade, broker):
    trade = closed_trade
    trade.run.mode = "live"
    trade.run.broker = broker
    row = store.db_session.query(store.SmRiskReservation).filter_by(user_id=trade.owner).one()
    row.scope = f"{trade.owner}|live|kotak"
    store.db_session.commit()
    governor._entry_reservations.pop(trade.scope)
    governor._reservation_cash_baselines.pop(trade.scope)
    trade.scope = row.scope
    trade.reservation.scope = row.scope
    governor._entry_reservations[trade.scope] = [trade.reservation]

    assert bool(reconcile(trade)) is (broker != "kotak")
    assert bool(store.list_risk_reservations(trade.owner, scope=trade.scope)) is (broker != "kotak")


def test_unresolved_late_exit_keeps_reservation_even_when_fills_balance(closed_trade):
    trade = closed_trade
    store.db_session.add(
        store.SmStrategyOrder(
            run_id=trade.run.id,
            leg_id=1,
            position_ref=trade.component.position_ref,
            kind="exit_recovery",
            symbol=trade.entry.symbol,
            exchange="NFO",
            product="MIS",
            qty=25,
            filled_qty=0,
            action="SELL",
            status="unknown",
        )
    )
    store.db_session.commit()

    assert reconcile(trade)
    assert store.list_risk_reservations(trade.owner, scope=trade.scope)


def test_truncated_order_history_keeps_reservation(closed_trade):
    trade = closed_trade
    store.db_session.add_all(
        [
            store.SmStrategyOrder(
                run_id=trade.run.id,
                leg_id=1,
                position_ref=trade.component.position_ref,
                kind="exit_recovery",
                symbol=trade.entry.symbol,
                exchange="NFO",
                product="MIS",
                qty=25,
                filled_qty=0,
                action="SELL",
                status="rejected",
            )
            for _ in range(100)
        ]
    )
    store.db_session.commit()

    assert reconcile(trade)
    assert store.list_risk_reservations(trade.owner, scope=trade.scope)


@pytest.mark.parametrize("quantity_visible", [False, True])
def test_failed_durable_release_keeps_memory_risk(closed_trade, monkeypatch, quantity_visible):
    from sqlalchemy.orm import Session

    trade = closed_trade
    if quantity_visible:
        trade.reservation.components = [
            replace(
                trade.component,
                quantity_delta=Decimal("0"),
                configured_risk=Decimal("0"),
                nifty_option_positions=0,
                derivative_positions=0,
            )
        ]

    def failed_commit(_session):
        raise RuntimeError("database unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", failed_commit)
        active = governor._reconcile_reservations(
            trade.owner,
            governor.EntryFacts(mode="sandbox", available_cash=Decimal("22500"), scope=trade.scope),
        )

    assert active
    assert trade.scope in governor._entry_reservations
    assert store.list_risk_reservations(trade.owner, scope=trade.scope)
    assert reconcile(trade) == []


def test_repeated_closed_reconciliation_releases_database_connections(closed_trade):
    from sqlalchemy import event

    trade = closed_trade
    trade.exit.status = "unknown"
    store.db_session.commit()
    # Expire fixture reads before measuring the independent reconciliation sessions.
    _ = trade.run.id
    store.db_session.remove()
    checked_out = set()

    def checkout(connection, _record, _proxy):
        checked_out.add(id(connection))

    def checkin(connection, _record):
        checked_out.discard(id(connection))

    event.listen(store.engine, "checkout", checkout)
    event.listen(store.engine, "checkin", checkin)
    try:
        for _ in range(100):
            assert not governor._durably_closed_component(trade.reservation, trade.component)
            assert checked_out == set()
    finally:
        event.remove(store.engine, "checkout", checkout)
        event.remove(store.engine, "checkin", checkin)
