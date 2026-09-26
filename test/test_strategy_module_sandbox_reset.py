"""Current-session sandbox reset must never infer cash from unverified run totals."""

import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
import pytz
from sqlalchemy import create_engine, text

from database import sandbox_db
from database import strategy_module_db as store

IST = pytz.timezone("Asia/Kolkata")


@pytest.fixture
def seeded_reset_db(tmp_path):
    strategy_engine = create_engine(f"sqlite:///{tmp_path / 'strategy.db'}")
    sandbox_engine = create_engine(f"sqlite:///{tmp_path / 'sandbox.db'}")
    old_strategy_bind = store.db_session.bind
    old_sandbox_bind = sandbox_db.db_session.bind
    store.db_session.remove()
    sandbox_db.db_session.remove()
    store.db_session.configure(bind=strategy_engine)
    sandbox_db.db_session.configure(bind=sandbox_engine)
    store.Base.metadata.create_all(strategy_engine)
    sandbox_db.Base.metadata.create_all(sandbox_engine)

    def strategy(user, name):
        row = store.SmStrategy(
            user_id=user,
            name=name,
            universe_tab="weekly_monthly",
            underlying="NIFTY",
            underlying_exchange="NSE_INDEX",
            webhook_token_hash=sha256(f"{user}:{name}".encode()).hexdigest(),
        )
        store.db_session.add(row)
        store.db_session.flush()
        return row

    owned = strategy("owner", "owned")
    foreign = strategy("foreign", "foreign")
    current_time = datetime(2026, 9, 25, 4, tzinfo=UTC).replace(tzinfo=None)
    older_time = datetime(2026, 9, 24, 4, tzinfo=UTC).replace(tzinfo=None)
    run = store.SmStrategyRun(
        strategy_id=owned.id,
        mode="sandbox",
        broker="sandbox",
        started_at=current_time,
        stopped_at=current_time,
        pnl_realized=Decimal("-100.00"),
    )
    older = store.SmStrategyRun(
        strategy_id=owned.id,
        mode="sandbox",
        broker="sandbox",
        started_at=older_time,
        stopped_at=older_time,
    )
    live = store.SmStrategyRun(
        strategy_id=owned.id,
        mode="live",
        broker="kotak",
        started_at=current_time,
        stopped_at=current_time,
    )
    other = store.SmStrategyRun(
        strategy_id=foreign.id,
        mode="sandbox",
        broker="sandbox",
        started_at=current_time,
        stopped_at=current_time,
    )
    store.db_session.add_all([run, older, live, other])
    store.db_session.flush()
    for kind, action, price, order_id in [
        ("entry", "BUY", "100.00", "SBX-ENTRY"),
        ("exit", "SELL", "80.00", "SBX-EXIT"),
    ]:
        store.db_session.add(
            store.SmStrategyOrder(
                run_id=run.id,
                leg_id=1,
                kind=kind,
                broker_order_id=order_id,
                symbol="TEST",
                exchange="NFO",
                action=action,
                qty=5,
                status="complete",
                filled_qty=5,
                avg_fill_price=Decimal(price),
                placed_at=current_time,
            )
        )
        sandbox_db.db_session.add(
            sandbox_db.SandboxOrders(
                orderid=order_id,
                user_id="owner",
                symbol="TEST",
                exchange="NFO",
                action=action,
                quantity=5,
                price_type="MARKET",
                product="NRML",
                order_status="complete",
                average_price=Decimal(price),
                filled_quantity=5,
                pending_quantity=0,
                order_timestamp=datetime(2026, 9, 25, 10),
            )
        )
        sandbox_db.db_session.add(
            sandbox_db.SandboxTrades(
                tradeid=f"TRADE-{order_id}",
                orderid=order_id,
                user_id="owner",
                symbol="TEST",
                exchange="NFO",
                action=action,
                quantity=5,
                price=Decimal(price),
                product="NRML",
                trade_timestamp=datetime(2026, 9, 25, 10),
            )
        )
    sandbox_db.db_session.add(
        sandbox_db.SandboxFunds(
            user_id="owner",
            total_capital=Decimal("100000.00"),
            available_balance=Decimal("99900.00"),
            used_margin=Decimal("0.00"),
            realized_pnl=Decimal("-100.00"),
            today_realized_pnl=Decimal("-100.00"),
            unrealized_pnl=Decimal("0.00"),
            total_pnl=Decimal("-100.00"),
        )
    )
    store.db_session.commit()
    sandbox_db.db_session.commit()

    class Seeded:
        now = IST.localize(datetime(2026, 9, 25, 12))
        owned_sandbox_run_id = run.id
        other_user_run_id = other.id
        live_run_id = live.id
        older_run_id = older.id

    yield Seeded()

    store.db_session.remove()
    sandbox_db.db_session.remove()
    store.db_session.configure(bind=old_strategy_bind)
    sandbox_db.db_session.configure(bind=old_sandbox_bind)
    strategy_engine.dispose()
    sandbox_engine.dispose()


def test_preview_only_selects_owned_sandbox_runs_from_current_session(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert view.run_ids == (seeded_reset_db.owned_sandbox_run_id,)
    assert seeded_reset_db.other_user_run_id not in view.run_ids
    assert seeded_reset_db.live_run_id not in view.run_ids
    assert seeded_reset_db.older_run_id not in view.run_ids


def test_preview_reverses_verified_loss_exactly(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert view.realised_pnl == Decimal("-100.00")
    assert view.funds_before == Decimal("99900.00")
    assert view.funds_after == Decimal("100000.00")
    assert not view.blockers


def test_preview_blocks_price_difference_that_changes_cash_by_five_paise(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    trade = (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades).filter_by(orderid="SBX-ENTRY").one()
    )
    trade.price = Decimal("100.01")
    sandbox_db.db_session.commit()

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert any("fill price" in reason.lower() for reason in view.blockers)


def test_preview_blocks_position_ledger_pnl_that_disagrees_with_selected_runs(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    sandbox_db.db_session.add(
        sandbox_db.SandboxPositions(
            user_id="owner",
            symbol="TEST",
            exchange="NFO",
            product="NRML",
            quantity=0,
            average_price=Decimal("100.00"),
            today_realized_pnl=Decimal("-99.95"),
            accumulated_realized_pnl=Decimal("-99.95"),
        )
    )
    sandbox_db.db_session.commit()

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert any("position" in reason.lower() and "p&l" in reason.lower() for reason in view.blockers)


def test_preview_accepts_replayed_average_cost_rounding_and_restores_actual_wallet_pnl(
    seeded_reset_db,
):
    """Concurrent fills may differ from per-run P&L by the sandbox's cent-rounded average."""
    from services.strategy_module import sandbox_reset

    original_exit_trade = (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades)
        .filter_by(orderid="SBX-EXIT")
        .one()
    )
    original_exit_trade.trade_timestamp = datetime(2026, 9, 25, 10, 3)
    original_exit_order = (
        sandbox_db.db_session.query(sandbox_db.SandboxOrders)
        .filter_by(orderid="SBX-EXIT")
        .one()
    )
    original_exit_order.order_timestamp = datetime(2026, 9, 25, 10, 3)

    strategy = store.db_session.query(store.SmStrategy).filter_by(
        user_id="owner", name="owned"
    ).one()
    run = store.SmStrategyRun(
        strategy_id=strategy.id,
        mode="sandbox",
        broker="sandbox",
        started_at=datetime(2026, 9, 25, 4),
        stopped_at=datetime(2026, 9, 25, 4, 5),
        pnl_realized=Decimal("-100.05"),
    )
    store.db_session.add(run)
    store.db_session.flush()
    for kind, action, price, order_id, placed_at in [
        ("entry", "BUY", "100.01", "SBX-ENTRY-2", datetime(2026, 9, 25, 10, 1)),
        ("exit", "SELL", "80.00", "SBX-EXIT-2", datetime(2026, 9, 25, 10, 2)),
    ]:
        store.db_session.add(
            store.SmStrategyOrder(
                run_id=run.id,
                leg_id=1,
                kind=kind,
                broker_order_id=order_id,
                symbol="TEST",
                exchange="NFO",
                action=action,
                qty=5,
                status="complete",
                filled_qty=5,
                avg_fill_price=Decimal(price),
                placed_at=placed_at,
            )
        )
        sandbox_db.db_session.add(
            sandbox_db.SandboxOrders(
                orderid=order_id,
                user_id="owner",
                symbol="TEST",
                exchange="NFO",
                action=action,
                quantity=5,
                price_type="MARKET",
                product="NRML",
                order_status="complete",
                average_price=Decimal(price),
                filled_quantity=5,
                pending_quantity=0,
                order_timestamp=placed_at,
            )
        )
        sandbox_db.db_session.add(
            sandbox_db.SandboxTrades(
                tradeid=f"TRADE-{order_id}",
                orderid=order_id,
                user_id="owner",
                symbol="TEST",
                exchange="NFO",
                action=action,
                quantity=5,
                price=Decimal(price),
                product="NRML",
                trade_timestamp=placed_at,
            )
        )
    sandbox_db.db_session.add(
        sandbox_db.SandboxPositions(
            user_id="owner",
            symbol="TEST",
            exchange="NFO",
            product="NRML",
            quantity=0,
            average_price=Decimal("100.005"),
            today_realized_pnl=Decimal("-200.00"),
            accumulated_realized_pnl=Decimal("-200.00"),
            pnl=Decimal("-200.00"),
            created_at=datetime(2026, 9, 25, 10),
        )
    )
    fund = sandbox_db.db_session.query(sandbox_db.SandboxFunds).filter_by(user_id="owner").one()
    fund.available_balance = Decimal("99800.00")
    fund.realized_pnl = Decimal("-200.00")
    fund.today_realized_pnl = Decimal("-200.00")
    fund.total_pnl = Decimal("-200.00")
    store.db_session.commit()
    sandbox_db.db_session.commit()

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)

    assert not view.blockers
    assert view.realised_pnl == Decimal("-200.00")
    assert view.funds_after == Decimal("100000.00")


def test_preview_does_not_select_unrelated_flat_product_position(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    position = sandbox_db.SandboxPositions(
        user_id="owner",
        symbol="TEST",
        exchange="NFO",
        product="MIS",
        quantity=0,
        average_price=Decimal("100.00"),
        today_realized_pnl=Decimal("0.00"),
        accumulated_realized_pnl=Decimal("0.00"),
        pnl=Decimal("0.00"),
        created_at=datetime(2026, 9, 25, 10),
    )
    sandbox_db.db_session.add(position)
    sandbox_db.db_session.commit()
    position_id = position.id

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert not view.blockers
    assert position_id not in dict(view.position_adjustments)
    sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)
    assert sandbox_db.db_session.get(sandbox_db.SandboxPositions, position_id)


def test_preview_blocks_prior_session_run_still_open(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    older = store.db_session.get(store.SmStrategyRun, seeded_reset_db.older_run_id)
    older.stopped_at = None
    store.db_session.commit()

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert any("session boundary" in reason.lower() for reason in view.blockers)


def test_preview_blocks_running_flow_execution(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    with store.db_session.bind.begin() as connection:
        connection.execute(
            text("CREATE TABLE flow_workflow_executions (id INTEGER PRIMARY KEY, status TEXT)")
        )
        connection.execute(
            text("INSERT INTO flow_workflow_executions (id, status) VALUES (1, 'running')")
        )

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert any("flow execution" in reason.lower() for reason in view.blockers)


def test_reset_removes_only_selected_flat_run_risk_reservation(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    reservation = store.SmRiskReservation(
        user_id="owner", scope="owner|sandbox|sandbox", order_key="hold",
        components=[{"run_id": seeded_reset_db.owned_sandbox_run_id}],
    )
    store.db_session.add(reservation)
    store.db_session.commit()
    reservation_id = reservation.id

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert not view.blockers
    assert view.reservation_ids == (reservation_id,)
    sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)
    assert store.db_session.get(store.SmRiskReservation, reservation_id) is None


def test_preview_blocks_reservation_shared_with_unselected_run(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    store.db_session.add(store.SmRiskReservation(
        user_id="owner", scope="owner|sandbox|sandbox", order_key="mixed",
        components=[
            {"run_id": seeded_reset_db.owned_sandbox_run_id},
            {"run_id": seeded_reset_db.older_run_id},
        ],
    ))
    store.db_session.commit()
    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert any("risk reservation" in reason.lower() for reason in view.blockers)


def test_sandbox_reset_admission_lock_is_held_across_processes(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    lock_directory = store.db_session.bind.url.database
    lock_path = (
        Path(lock_directory).resolve().parent
        / ".sandbox-admission-locks"
        / sha256(b"owner|sandbox|sandbox").hexdigest()
    )
    contender = (
        "import fcntl, os, sys; "
        "fd=os.open(sys.argv[1], os.O_RDWR); "
        "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)"
    )
    with sandbox_reset._admission_lock("owner"):
        result = subprocess.run(
            [sys.executable, "-c", contender, str(lock_path)],
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
    result = subprocess.run(
        [sys.executable, "-c", contender, str(lock_path)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0


def test_preview_version_changes_when_a_trade_changes(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    original = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    trade = (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades).filter_by(orderid="SBX-ENTRY").one()
    )
    trade.price = Decimal("100.01")
    sandbox_db.db_session.commit()

    changed = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert changed.version != original.version


@pytest.mark.parametrize(
    "fault", ["status", "filled", "pending", "price", "order_time", "trade_time", "symbol"]
)
def test_preview_blocks_inconsistent_sandbox_execution_evidence(seeded_reset_db, fault):
    from services.strategy_module import sandbox_reset

    order = (
        sandbox_db.db_session.query(sandbox_db.SandboxOrders).filter_by(orderid="SBX-ENTRY").one()
    )
    trade = (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades).filter_by(orderid="SBX-ENTRY").one()
    )
    if fault == "status":
        order.order_status = "cancelled"
    elif fault == "filled":
        order.filled_quantity = 4
    elif fault == "pending":
        order.pending_quantity = 1
    elif fault == "price":
        order.average_price = Decimal("101.00")
    elif fault == "order_time":
        order.order_timestamp = datetime(2026, 9, 24, 10)
    elif fault == "symbol":
        trade.symbol = "UNRELATED"
    else:
        trade.trade_timestamp = datetime(2026, 9, 24, 10)
    sandbox_db.db_session.commit()

    assert sandbox_reset.preview("owner", now=seeded_reset_db.now).blockers


def test_preview_version_includes_sandbox_fill_quantity(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    before = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    order = (
        sandbox_db.db_session.query(sandbox_db.SandboxOrders).filter_by(orderid="SBX-ENTRY").one()
    )
    order.filled_quantity = 4
    sandbox_db.db_session.commit()

    assert sandbox_reset.preview("owner", now=seeded_reset_db.now).version != before.version


@pytest.mark.parametrize(
    "fault",
    ["open_run", "pending_order", "open_position", "mixed_trade", "bad_fill", "cross_session_run"],
)
def test_preview_blocks_unsafe_session_state(seeded_reset_db, fault):
    from services.strategy_module import sandbox_reset

    if fault == "open_run":
        run = store.db_session.get(store.SmStrategyRun, seeded_reset_db.owned_sandbox_run_id)
        run.stopped_at = None
        store.db_session.commit()
    elif fault == "pending_order":
        order = (
            sandbox_db.db_session.query(sandbox_db.SandboxOrders)
            .filter_by(orderid="SBX-ENTRY")
            .one()
        )
        order.order_status = "open"
        sandbox_db.db_session.commit()
    elif fault == "open_position":
        sandbox_db.db_session.add(
            sandbox_db.SandboxPositions(
                user_id="owner",
                symbol="TEST",
                exchange="NFO",
                product="NRML",
                quantity=5,
                average_price=Decimal("100.00"),
            )
        )
        sandbox_db.db_session.commit()
    elif fault == "mixed_trade":
        sandbox_db.db_session.add(
            sandbox_db.SandboxTrades(
                tradeid="MANUAL-TRADE",
                orderid="MANUAL-ORDER",
                user_id="owner",
                symbol="TEST",
                exchange="NFO",
                action="BUY",
                quantity=1,
                price=Decimal("100.00"),
                product="NRML",
                trade_timestamp=datetime(2026, 9, 25, 10),
            )
        )
        sandbox_db.db_session.commit()
    elif fault == "bad_fill":
        trade = (
            sandbox_db.db_session.query(sandbox_db.SandboxTrades)
            .filter_by(orderid="SBX-ENTRY")
            .one()
        )
        trade.quantity = 4
        sandbox_db.db_session.commit()
    else:
        older = store.db_session.get(store.SmStrategyRun, seeded_reset_db.older_run_id)
        older.stopped_at = datetime(2026, 9, 25, 4, tzinfo=UTC).replace(tzinfo=None)
        store.db_session.commit()

    assert sandbox_reset.preview("owner", now=seeded_reset_db.now).blockers


def test_execute_clears_only_owned_session_and_reverses_verified_loss(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    result = sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)

    assert result.funds_after == Decimal("100000.00")
    assert store.db_session.get(store.SmStrategyRun, seeded_reset_db.owned_sandbox_run_id) is None
    assert store.db_session.get(store.SmStrategyRun, seeded_reset_db.older_run_id) is not None
    assert store.db_session.get(store.SmStrategyRun, seeded_reset_db.live_run_id) is not None
    assert store.db_session.get(store.SmStrategyRun, seeded_reset_db.other_user_run_id) is not None
    assert (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades).filter_by(user_id="owner").count()
        == 0
    )
    fund = sandbox_db.db_session.query(sandbox_db.SandboxFunds).filter_by(user_id="owner").one()
    assert fund.available_balance == Decimal("100000.00")
    assert fund.today_realized_pnl == Decimal("0.00")


def test_execute_clears_flat_position_pnl_from_selected_sandbox_fills(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    sandbox_db.db_session.add(
        sandbox_db.SandboxPositions(
            user_id="owner",
            symbol="TEST",
            exchange="NFO",
            product="NRML",
            quantity=0,
            average_price=Decimal("100.00"),
            today_realized_pnl=Decimal("-100.00"),
            accumulated_realized_pnl=Decimal("-100.00"),
            pnl=Decimal("-100.00"),
            created_at=datetime(2026, 9, 25, 10),
        )
    )
    sandbox_db.db_session.commit()
    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert not view.blockers

    sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)

    position = (
        sandbox_db.db_session.query(sandbox_db.SandboxPositions)
        .filter_by(user_id="owner", symbol="TEST", exchange="NFO", product="NRML")
        .one_or_none()
    )
    assert position is None or position.today_realized_pnl == Decimal("0.00")


def test_execute_rejects_stale_preview_without_changing_funds(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    trade = (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades).filter_by(orderid="SBX-ENTRY").one()
    )
    trade.price = Decimal("100.01")
    sandbox_db.db_session.commit()

    with pytest.raises(sandbox_reset.ResetBlocked):
        sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)
    assert sandbox_db.db_session.query(sandbox_db.SandboxFunds).filter_by(
        user_id="owner"
    ).one().available_balance == Decimal("99900.00")


def test_second_reset_is_noop_and_does_not_credit_funds_twice(seeded_reset_db):
    from services.strategy_module import sandbox_reset

    first = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    sandbox_reset.execute("owner", first.version, now=seeded_reset_db.now)
    second = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    result = sandbox_reset.execute("owner", second.version, now=seeded_reset_db.now)

    assert result.already_done
    assert result.funds_after == Decimal("100000.00")


def test_mutation_failure_rolls_back_both_databases_and_blocks_new_entries(
    seeded_reset_db,
    monkeypatch,
):
    from database import sandbox_reset_journal
    from services.strategy_module import sandbox_reset

    original_delete = sandbox_reset._delete_rows

    def crash_after_deletes(connection, view, user_id):
        original_delete(connection, view, user_id)
        raise RuntimeError("injected failure after both deletes")

    monkeypatch.setattr(sandbox_reset, "_delete_rows", crash_after_deletes)
    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)

    with pytest.raises(sandbox_reset.ResetRecoveryRequired):
        sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)

    assert store.db_session.get(store.SmStrategyRun, seeded_reset_db.owned_sandbox_run_id)
    assert (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades).filter_by(user_id="owner").count()
        == 2
    )
    assert sandbox_db.db_session.query(sandbox_db.SandboxFunds).filter_by(
        user_id="owner"
    ).one().available_balance == Decimal("99900.00")
    with pytest.raises(RuntimeError, match="recovery"):
        sandbox_reset_journal.assert_recovered("owner")


def test_recovery_after_rolled_back_reset_reopens_sandbox_admission(
    seeded_reset_db,
    monkeypatch,
):
    from database import sandbox_reset_journal
    from services.strategy_module import sandbox_reset

    original_delete = sandbox_reset._delete_rows

    def crash_after_deletes(connection, view, user_id):
        original_delete(connection, view, user_id)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(sandbox_reset, "_delete_rows", crash_after_deletes)
    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    with pytest.raises(sandbox_reset.ResetRecoveryRequired):
        sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)

    sandbox_reset.recover("owner", now=seeded_reset_db.now)
    sandbox_reset_journal.assert_recovered("owner")
    assert store.db_session.get(store.SmStrategyRun, seeded_reset_db.owned_sandbox_run_id)


def test_post_commit_failure_leaves_recovery_gate_until_rows_are_restored(
    seeded_reset_db,
    monkeypatch,
):
    from database import sandbox_reset_journal
    from services.strategy_module import sandbox_reset

    def crash_before_complete(audit_id, state, message):
        if state == "complete":
            assert sandbox_reset_journal.latest("owner").payload["state"] == "prepared"
            raise RuntimeError("simulated crash after attached commit")
        return original_set_state(audit_id, state, message)

    original_set_state = sandbox_reset_journal.set_state
    monkeypatch.setattr(sandbox_reset_journal, "set_state", crash_before_complete)
    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    with pytest.raises(sandbox_reset.ResetRecoveryRequired):
        sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)

    assert sandbox_reset_journal.latest("owner").payload["state"] == "recovery_required"
    assert store.db_session.get(store.SmStrategyRun, seeded_reset_db.owned_sandbox_run_id) is None
    assert (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades).filter_by(user_id="owner").count()
        == 0
    )
    sandbox_reset.recover("owner", now=seeded_reset_db.now)
    assert sandbox_reset.preview("owner", now=seeded_reset_db.now).version == view.version


def test_recovery_refuses_to_overwrite_changed_position_mark(seeded_reset_db, monkeypatch):
    from database import sandbox_reset_journal
    from services.strategy_module import sandbox_reset

    position = sandbox_db.SandboxPositions(
        user_id="owner",
        symbol="TEST",
        exchange="NFO",
        product="NRML",
        quantity=0,
        average_price=Decimal("100.00"),
        ltp=Decimal("80.00"),
        today_realized_pnl=Decimal("-100.00"),
        accumulated_realized_pnl=Decimal("-100.00"),
        pnl=Decimal("-100.00"),
        created_at=datetime(2026, 9, 24, 10),
    )
    sandbox_db.db_session.add(position)
    sandbox_db.db_session.commit()
    position_id = position.id
    original_set_state = sandbox_reset_journal.set_state

    def crash_before_complete(audit_id, state, message):
        if state == "complete":
            raise RuntimeError("simulated crash")
        return original_set_state(audit_id, state, message)

    monkeypatch.setattr(sandbox_reset_journal, "set_state", crash_before_complete)
    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    with pytest.raises(sandbox_reset.ResetRecoveryRequired):
        sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)

    later = sandbox_db.db_session.get(sandbox_db.SandboxPositions, position_id)
    later.ltp = Decimal("81.00")
    sandbox_db.db_session.commit()
    with pytest.raises(sandbox_reset.ResetRecoveryRequired):
        sandbox_reset.recover("owner", now=seeded_reset_db.now)
    assert sandbox_db.db_session.get(sandbox_db.SandboxPositions, position_id).ltp == Decimal(
        "81.00"
    )


def test_recovery_pending_blocks_governor_sandbox_entry_before_market_data(
    seeded_reset_db,
    monkeypatch,
):
    from database import sandbox_reset_journal
    from services.strategy_module import portfolio_governor

    sandbox_reset_journal.begin("owner", {"version": "pending"})

    def should_not_read_market_data(*args, **kwargs):
        raise AssertionError("entry facts must not be read during reset recovery")

    monkeypatch.setattr(portfolio_governor, "build_entry_facts", should_not_read_market_data)
    decision, admission = portfolio_governor.acquire_entry_admission(
        "owner",
        {},
        [],
        "unused",
        "sandbox",
        portfolio_governor.GovernorPolicy(),
        datetime.now(UTC),
        broker="sandbox",
    )
    assert not decision.allowed
    assert decision.code == "sandbox_reset_recovery_required"
    assert admission is None


def test_completed_reset_rechecks_both_ledgers_after_process_restart(seeded_reset_db):
    from database import sandbox_reset_journal
    from services.strategy_module import sandbox_reset

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)
    sandbox_db.db_session.add(
        sandbox_db.SandboxTrades(
            tradeid="TRADE-SBX-ENTRY",
            orderid="SBX-ENTRY",
            user_id="owner",
            symbol="TEST",
            exchange="NFO",
            action="BUY",
            quantity=5,
            price=Decimal("100.00"),
            product="NRML",
            trade_timestamp=datetime(2026, 9, 25, 10),
        )
    )
    sandbox_db.db_session.commit()

    sandbox_reset_journal._verified_audits.clear()  # Simulate a new process.
    with pytest.raises(RuntimeError, match="recovery"):
        sandbox_reset_journal.assert_recovered("owner")


def test_completed_reset_detects_unreversed_funds_after_restart(seeded_reset_db):
    from database import sandbox_reset_journal
    from services.strategy_module import sandbox_reset

    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)
    fund = sandbox_db.db_session.query(sandbox_db.SandboxFunds).filter_by(user_id="owner").one()
    fund.available_balance = Decimal("99900.00")
    sandbox_db.db_session.commit()

    sandbox_reset_journal._verified_audits.clear()
    with pytest.raises(RuntimeError, match="recovery"):
        sandbox_reset_journal.assert_recovered("owner")


def test_recovery_restores_selected_rows_after_partial_database_commit(
    seeded_reset_db,
    monkeypatch,
):
    from database import sandbox_reset_journal
    from services.strategy_module import sandbox_reset

    sandbox_db.db_session.add(
        sandbox_db.SandboxPositions(
            user_id="owner",
            symbol="TEST",
            exchange="NFO",
            product="NRML",
            quantity=0,
            average_price=Decimal("100.00"),
            today_realized_pnl=Decimal("-100.00"),
            accumulated_realized_pnl=Decimal("-100.00"),
            pnl=Decimal("-100.00"),
            created_at=datetime(2026, 9, 25, 10),
        )
    )
    sandbox_db.db_session.commit()
    reservation = store.SmRiskReservation(
        user_id="owner", scope="owner|sandbox|sandbox", order_key="recovery",
        components=[{"run_id": seeded_reset_db.owned_sandbox_run_id}],
    )
    store.db_session.add(reservation)
    store.db_session.commit()
    reservation_id = reservation.id

    original_delete = sandbox_reset._delete_rows

    def fail_after_delete(connection, view, user_id):
        original_delete(connection, view, user_id)
        raise RuntimeError("simulate interrupted reset")

    monkeypatch.setattr(sandbox_reset, "_delete_rows", fail_after_delete)
    before = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    with pytest.raises(sandbox_reset.ResetRecoveryRequired):
        sandbox_reset.execute("owner", before.version, now=seeded_reset_db.now)

    # Emulate a crash that committed only one side of the cross-file mutation.
    store.db_session.query(store.SmStrategyOrder).filter_by(
        run_id=seeded_reset_db.owned_sandbox_run_id
    ).delete()
    store.db_session.query(store.SmStrategyRun).filter_by(
        id=seeded_reset_db.owned_sandbox_run_id
    ).delete()
    store.db_session.query(store.SmRiskReservation).filter_by(id=reservation_id).delete()
    store.db_session.commit()
    sandbox_db.db_session.query(sandbox_db.SandboxTrades).filter_by(user_id="owner").delete()
    sandbox_db.db_session.query(sandbox_db.SandboxOrders).filter_by(user_id="owner").delete()
    sandbox_db.db_session.query(sandbox_db.SandboxPositions).filter_by(user_id="owner").delete()
    fund = sandbox_db.db_session.query(sandbox_db.SandboxFunds).filter_by(user_id="owner").one()
    fund.available_balance = Decimal("100000.00")
    fund.realized_pnl = Decimal("0.00")
    fund.today_realized_pnl = Decimal("0.00")
    fund.total_pnl = Decimal("0.00")
    sandbox_db.db_session.commit()

    sandbox_reset.recover("owner", now=seeded_reset_db.now)
    sandbox_reset_journal.assert_recovered("owner")
    assert sandbox_reset.preview("owner", now=seeded_reset_db.now).version == before.version
    assert store.db_session.get(store.SmRiskReservation, reservation_id)


@pytest.fixture
def reset_api_client(seeded_reset_db, monkeypatch):
    from flask import Flask
    from flask_wtf.csrf import CSRFProtect, generate_csrf

    from blueprints.strategy_module import strategy_module_bp
    from limiter import limiter
    from services.strategy_module import sandbox_reset

    original_preview = sandbox_reset.preview
    original_execute = sandbox_reset.execute
    monkeypatch.setattr(
        sandbox_reset, "preview",
        lambda user_id, now=None: original_preview(user_id, now=now or seeded_reset_db.now),
    )
    monkeypatch.setattr(
        sandbox_reset, "execute",
        lambda user_id, version, now=None: original_execute(
            user_id, version, now=now or seeded_reset_db.now
        ),
    )

    monkeypatch.setattr(limiter, "enabled", False)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret", WTF_CSRF_ENABLED=True)
    CSRFProtect(app)
    app.register_blueprint(strategy_module_bp)

    @app.get("/test/csrf")
    def csrf_token():
        return {"token": generate_csrf()}

    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session["logged_in"] = True
        user_session["user"] = "owner"
        user_session["login_time"] = datetime.now(IST).isoformat()
    return client


def test_reset_api_preview_is_owner_scoped_and_has_no_credentials(reset_api_client):
    response = reset_api_client.get("/strategy/api/sandbox-reset/preview")

    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["run_count"] == 1
    assert body["data"]["funds_after"] == 100000.0
    assert "api_key" not in str(body).lower()


def test_reset_api_post_requires_csrf_and_current_preview(reset_api_client):
    assert (
        reset_api_client.post("/strategy/api/sandbox-reset", json={"version": "x" * 64}).status_code
        == 400
    )
    token = reset_api_client.get("/test/csrf").get_json()["token"]
    response = reset_api_client.post(
        "/strategy/api/sandbox-reset",
        json={"version": "a" * 64},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 409


def test_reset_api_execute_returns_audit_and_new_funds(reset_api_client, seeded_reset_db):
    preview_body = reset_api_client.get("/strategy/api/sandbox-reset/preview").get_json()["data"]
    token = reset_api_client.get("/test/csrf").get_json()["token"]
    response = reset_api_client.post(
        "/strategy/api/sandbox-reset",
        json={"version": preview_body["version"]},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["funds_after"] == 100000.0
    assert response.get_json()["data"]["audit_id"] is not None
