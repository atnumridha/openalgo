"""Read-only admission preview for resetting the current sandbox test session.

The sandbox and strategy ledgers are separate databases. A run total alone is
not authority to change funds; this preview reconciles its actual sandbox
orders and trades before a destructive reset can be offered.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, or_, text

from database import sandbox_db, sandbox_reset_journal
from database import strategy_module_db as store
from services.strategy_module import portfolio_governor, session


@dataclass(frozen=True)
class ResetPreview:
    session_start_utc: datetime
    session_end_utc: datetime
    run_ids: tuple[int, ...]
    order_ids: tuple[str, ...]
    trade_ids: tuple[str, ...]
    realised_pnl: Decimal
    funds_before: Decimal | None
    funds_after: Decimal | None
    blockers: tuple[str, ...]
    version: str
    position_adjustments: tuple[tuple[int, Decimal], ...] = ()
    reservation_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ResetResult:
    audit_id: int | None
    run_count: int
    order_count: int
    trade_count: int
    realised_pnl: Decimal
    funds_after: Decimal | None
    already_done: bool
    version: str


class ResetBlocked(RuntimeError):
    """Preview is stale or a safety precondition is not met."""


class ResetRecoveryRequired(RuntimeError):
    """A reset journal needs reconciliation before further sandbox entries."""


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _replay_position_realised_pnl(
    trades: list[sandbox_db.SandboxTrades],
) -> dict[tuple[str, str, str], Decimal]:
    """Replay the sandbox's average-cost accounting from attributable fills.

    Strategy runs pair their own entry and exit, while the sandbox position
    book nets concurrent strategies into one position.  The position columns
    are ``NUMERIC(..., 2)``, so SQLAlchemy reads the running average and P&L
    back at cent precision between fills.  Replaying that boundary is the only
    safe way to distinguish expected average-cost rounding from ledger drift.
    """
    from database.token_db import get_symbol_info

    state: dict[tuple[str, str, str], tuple[int, Decimal, Decimal]] = {}
    contract_values: dict[tuple[str, str], Decimal] = {}
    ordered = sorted(trades, key=lambda row: (row.trade_timestamp, row.id))
    for trade in ordered:
        key = (trade.symbol, trade.exchange, trade.product)
        old_quantity, stored_average, stored_realised = state.get(
            key, (0, Decimal("0.00"), Decimal("0.00"))
        )
        # Each fill is committed by the execution engine.  The next fill sees
        # the scale-2 values materialised by SQLAlchemy rather than the raw
        # higher-precision SQLite representation.
        average = _money(stored_average)
        realised = _money(stored_realised)
        signed_quantity = int(trade.quantity) if trade.action == "BUY" else -int(trade.quantity)
        final_quantity = old_quantity + signed_quantity
        price = Decimal(str(trade.price))

        if old_quantity == 0:
            average = price
        elif (old_quantity > 0 and signed_quantity > 0) or (
            old_quantity < 0 and signed_quantity < 0
        ):
            total_quantity = abs(old_quantity) + abs(signed_quantity)
            average = (
                Decimal(abs(old_quantity)) * average
                + Decimal(abs(signed_quantity)) * price
            ) / Decimal(total_quantity)
        else:
            reduced_quantity = min(abs(old_quantity), abs(signed_quantity))
            instrument = (trade.symbol, trade.exchange)
            if instrument not in contract_values:
                try:
                    symbol = get_symbol_info(*instrument)
                    contract_values[instrument] = Decimal(
                        str(symbol.contract_value if symbol and symbol.contract_value else 1)
                    )
                except Exception:
                    contract_values[instrument] = Decimal("1")
            multiplier = contract_values[instrument]
            price_difference = price - average if old_quantity > 0 else average - price
            realised += price_difference * Decimal(reduced_quantity) * multiplier
            if abs(signed_quantity) > abs(old_quantity):
                average = price

        state[key] = (final_quantity, average, realised)

    return {key: _money(values[2]) for key, values in state.items()}


def preview(user_id: str, now: datetime | None = None) -> ResetPreview:
    """Select one owner's current-session sandbox runs without writing anything."""
    moment = now or datetime.now(session.IST)
    start_ist = session.session_started_at(moment)
    end_ist = start_ist + timedelta(days=1)
    start_utc = start_ist.astimezone(UTC).replace(tzinfo=None)
    end_utc = end_ist.astimezone(UTC).replace(tzinfo=None)
    start_sandbox = start_ist.replace(tzinfo=None)
    end_sandbox = end_ist.replace(tzinfo=None)
    blockers: list[str] = []

    runs = (
        store.db_session.query(store.SmStrategyRun)
        .join(store.SmStrategy, store.SmStrategy.id == store.SmStrategyRun.strategy_id)
        .filter(
            store.SmStrategy.user_id == str(user_id),
            store.SmStrategyRun.mode == "sandbox",
            store.SmStrategyRun.started_at >= start_utc,
            store.SmStrategyRun.started_at < end_utc,
        )
        .order_by(store.SmStrategyRun.id)
        .limit(1002)
        .all()
    )
    if len(runs) > 1000:
        blockers.append("Too many sandbox runs to reset safely")
    run_ids = tuple(row.id for row in runs)
    if any(row.stopped_at is None for row in runs):
        blockers.append("A sandbox strategy run is still open")
    reservations = (
        store.db_session.query(store.SmRiskReservation)
        .filter(
            store.SmRiskReservation.user_id == str(user_id),
            store.SmRiskReservation.scope == f"{user_id}|sandbox|sandbox",
        )
        .all()
    )
    selected_ids = {str(value) for value in run_ids}
    reservation_ids: list[int] = []
    for reservation in reservations:
        components = reservation.components or []
        component_runs = {
            str(component.get("run_id"))
            for component in components
            if isinstance(component, dict)
        }
        if component_runs & selected_ids:
            if len(component_runs) != len(components) or not component_runs <= selected_ids:
                blockers.append("A sandbox risk reservation shares an unselected run")
            else:
                reservation_ids.append(reservation.id)
    # Flow executions can be part-way through producing a strategy signal.
    # Flow has no per-owner key in this schema, so refuse the short reset
    # while *any* workflow execution is recorded as running.
    if inspect(store.db_session.bind).has_table("flow_workflow_executions"):
        running_flow = store.db_session.execute(
            text("SELECT 1 FROM flow_workflow_executions WHERE status='running' LIMIT 1")
        ).first()
        if running_flow:
            blockers.append("A Flow execution is still running")
    spanning = (
        store.db_session.query(store.SmStrategyRun.id)
        .join(store.SmStrategy, store.SmStrategy.id == store.SmStrategyRun.strategy_id)
        .filter(
            store.SmStrategy.user_id == str(user_id),
            store.SmStrategyRun.mode == "sandbox",
            store.SmStrategyRun.started_at < start_utc,
            or_(
                store.SmStrategyRun.stopped_at.is_(None),
                store.SmStrategyRun.stopped_at >= start_utc,
            ),
        )
        .first()
    )
    if spanning:
        blockers.append("A sandbox run spans the session boundary")

    orders = (
        store.db_session.query(store.SmStrategyOrder)
        .filter(store.SmStrategyOrder.run_id.in_(run_ids))
        .order_by(store.SmStrategyOrder.id)
        .limit(10002)
        .all()
        if run_ids
        else []
    )
    if len(orders) > 10000:
        blockers.append("Too many strategy orders to reset safely")
    sandbox_ids = tuple(str(row.broker_order_id) for row in orders if row.broker_order_id)
    if len(sandbox_ids) != len(set(sandbox_ids)):
        blockers.append("A sandbox order is referenced by more than one strategy order")
    if any(
        row.status in {"complete", "open", "pending", "trigger pending"} and not row.broker_order_id
        for row in orders
    ):
        blockers.append("A strategy fill has no attributable sandbox order")

    sandbox_orders = (
        sandbox_db.db_session.query(sandbox_db.SandboxOrders)
        .filter(
            sandbox_db.SandboxOrders.user_id == str(user_id),
            sandbox_db.SandboxOrders.orderid.in_(sandbox_ids),
        )
        .all()
        if sandbox_ids
        else []
    )
    sandbox_by_id = {row.orderid: row for row in sandbox_orders}
    trades = (
        sandbox_db.db_session.query(sandbox_db.SandboxTrades)
        .filter(
            sandbox_db.SandboxTrades.user_id == str(user_id),
            sandbox_db.SandboxTrades.orderid.in_(sandbox_ids),
        )
        .order_by(sandbox_db.SandboxTrades.id)
        .all()
        if sandbox_ids
        else []
    )
    trades_by_order: dict[str, list[sandbox_db.SandboxTrades]] = {}
    for trade in trades:
        trades_by_order.setdefault(trade.orderid, []).append(trade)

    for strategy_order in orders:
        oid = strategy_order.broker_order_id
        if not oid:
            continue
        sandbox_order = sandbox_by_id.get(oid)
        if sandbox_order is None:
            blockers.append(
                f"Sandbox order evidence is missing for strategy order {strategy_order.id}"
            )
            continue
        if (sandbox_order.symbol, sandbox_order.exchange, sandbox_order.action) != (
            strategy_order.symbol,
            strategy_order.exchange,
            strategy_order.action,
        ) or sandbox_order.quantity != strategy_order.qty:
            blockers.append(f"Sandbox order {oid} does not match its strategy order")
        if sandbox_order.order_status != "complete" or sandbox_order.pending_quantity != 0:
            blockers.append(f"Sandbox order {oid} is not fully complete")
        if not start_sandbox <= sandbox_order.order_timestamp < end_sandbox:
            blockers.append(f"Sandbox order {oid} is outside the current session")
        matched_trades = trades_by_order.get(oid, [])
        if any(
            (row.symbol, row.exchange, row.action, row.product)
            != (
                sandbox_order.symbol,
                sandbox_order.exchange,
                sandbox_order.action,
                sandbox_order.product,
            )
            for row in matched_trades
        ):
            blockers.append(f"Sandbox trades do not match order {oid}")
        actual_qty = sum(int(row.quantity) for row in matched_trades)
        expected_qty = int(strategy_order.filled_qty or 0)
        if strategy_order.status == "complete" and expected_qty == 0:
            expected_qty = int(strategy_order.qty)
        if actual_qty != expected_qty:
            blockers.append(
                f"Sandbox fill quantity does not match strategy order {strategy_order.id}"
            )
        if sandbox_order.filled_quantity != actual_qty:
            blockers.append(f"Sandbox order {oid} filled quantity does not match its trades")
        if any(not start_sandbox <= row.trade_timestamp < end_sandbox for row in matched_trades):
            blockers.append(f"Sandbox trade for order {oid} is outside the current session")
        if actual_qty:
            total = sum((_money(row.price) * row.quantity for row in matched_trades), Decimal(0))
            strategy_price = Decimal(str(strategy_order.avg_fill_price or 0))
            if abs(total - strategy_price * expected_qty) > Decimal("0.01"):
                blockers.append(
                    f"Sandbox fill price does not match strategy order {strategy_order.id}"
                )
            if abs(total - _money(sandbox_order.average_price) * actual_qty) > Decimal("0.01"):
                blockers.append(f"Sandbox order {oid} average price does not match its trades")

    pending = (
        sandbox_db.db_session.query(sandbox_db.SandboxOrders.id)
        .filter(
            sandbox_db.SandboxOrders.user_id == str(user_id),
            sandbox_db.SandboxOrders.order_status.in_(("open", "trigger pending")),
        )
        .first()
    )
    if pending:
        blockers.append("A sandbox order is still pending")
    instruments = {(row.symbol, row.exchange) for row in orders}
    positions: list[sandbox_db.SandboxPositions] = []
    holdings: list[sandbox_db.SandboxHoldings] = []
    position_adjustments: list[tuple[int, Decimal]] = []
    replayed_position_pnl: dict[tuple[str, str, str], Decimal] = {}
    position_pnl: dict[tuple[str, str, str], Decimal] = {}
    if instruments:
        positions = (
            sandbox_db.db_session.query(sandbox_db.SandboxPositions)
            .filter(sandbox_db.SandboxPositions.user_id == str(user_id))
            .all()
        )
        if any(row.quantity and (row.symbol, row.exchange) in instruments for row in positions):
            blockers.append("A selected sandbox instrument has an open position")
        trade_cashflow: dict[tuple[str, str, str], Decimal] = {}
        for trade in trades:
            key = (trade.symbol, trade.exchange, trade.product)
            direction = Decimal(1) if trade.action == "SELL" else Decimal(-1)
            trade_cashflow[key] = trade_cashflow.get(key, Decimal(0)) + (
                _money(trade.price) * trade.quantity * direction
            )
        replayed_position_pnl = _replay_position_realised_pnl(trades)
        for row in positions:
            key = (row.symbol, row.exchange, row.product)
            if key[:2] in instruments:
                position_pnl[key] = position_pnl.get(key, Decimal(0)) + _money(
                    row.today_realized_pnl
                )
                if key in replayed_position_pnl:
                    position_adjustments.append((row.id, _money(row.today_realized_pnl)))
        if any(
            abs(value - replayed_position_pnl.get(key, Decimal(0))) > Decimal("0.01")
            for key, value in position_pnl.items()
        ):
            blockers.append("Sandbox position P&L does not reconcile with strategy fills")
        holdings = (
            sandbox_db.db_session.query(sandbox_db.SandboxHoldings)
            .filter(sandbox_db.SandboxHoldings.user_id == str(user_id))
            .all()
        )
        if any(row.quantity and (row.symbol, row.exchange) in instruments for row in holdings):
            blockers.append("A selected sandbox instrument has an open holding")
        session_trades = (
            sandbox_db.db_session.query(sandbox_db.SandboxTrades)
            .filter(
                sandbox_db.SandboxTrades.user_id == str(user_id),
                sandbox_db.SandboxTrades.trade_timestamp >= start_sandbox,
                sandbox_db.SandboxTrades.trade_timestamp < end_sandbox,
            )
            .all()
        )
        if any(
            (row.symbol, row.exchange) in instruments and row.orderid not in sandbox_ids
            for row in session_trades
        ):
            blockers.append("Other sandbox trading shares an instrument with these runs")

    strategy_realised = sum((_money(row.pnl_realized) for row in runs), Decimal("0.00"))
    if run_ids and not store.filled_orders_have_usable_evidence(
        list(run_ids),
        completed_run_ids=list(run_ids),
        run_realized={row.id: _money(row.pnl_realized) for row in runs},
    ):
        blockers.append("Strategy fills do not reconcile with realised P&L")

    # Prefer the wallet's independently replayed position result when every
    # selected instrument has a position ledger row.  This reverses the cash
    # that the sandbox actually credited/debited, not the small theoretical
    # difference produced by per-strategy pairing.
    realised = strategy_realised
    if trades and set(replayed_position_pnl) <= set(position_pnl):
        realised = sum(position_pnl.values(), Decimal("0.00"))

    fund = (
        sandbox_db.db_session.query(sandbox_db.SandboxFunds)
        .filter_by(user_id=str(user_id))
        .one_or_none()
    )
    funds_before = _money(fund.available_balance) if fund else None
    funds_after = funds_before - realised if funds_before is not None else None
    if fund is None:
        blockers.append("Sandbox funds are unavailable")
    elif _money(fund.used_margin) != 0:
        blockers.append("Sandbox margin is still reserved")
    elif run_ids:
        all_session_trades = (
            sandbox_db.db_session.query(sandbox_db.SandboxTrades.orderid)
            .filter(
                sandbox_db.SandboxTrades.user_id == str(user_id),
                sandbox_db.SandboxTrades.trade_timestamp >= start_sandbox,
                sandbox_db.SandboxTrades.trade_timestamp < end_sandbox,
            )
            .all()
        )
        if all(oid in sandbox_ids for (oid,) in all_session_trades) and (
            _money(fund.today_realized_pnl) != realised
        ):
            blockers.append("Sandbox funds P&L does not reconcile with strategy runs")

    facts = {
        "user": str(user_id),
        "start": start_utc.isoformat(),
        "end": end_utc.isoformat(),
        "runs": [
            (
                row.id,
                row.stopped_at.isoformat() if row.stopped_at else None,
                str(_money(row.pnl_realized)),
            )
            for row in runs
        ],
        "reservations": [(row.id, row.order_key, row.components) for row in reservations],
        "orders": [
            (
                row.id,
                row.broker_order_id,
                row.status,
                row.symbol,
                row.exchange,
                row.action,
                row.qty,
                row.filled_qty,
                str(row.avg_fill_price),
                row.placed_at.isoformat() if row.placed_at else None,
            )
            for row in orders
        ],
        "sandbox_orders": [
            (
                row.orderid,
                row.order_status,
                row.symbol,
                row.exchange,
                row.action,
                row.product,
                row.quantity,
                row.filled_quantity,
                row.pending_quantity,
                str(row.average_price),
                row.order_timestamp.isoformat(),
            )
            for row in sorted(sandbox_orders, key=lambda item: item.orderid)
        ],
        "trades": [
            (
                row.tradeid,
                row.orderid,
                row.symbol,
                row.exchange,
                row.action,
                row.product,
                row.quantity,
                str(row.price),
                row.trade_timestamp.isoformat(),
            )
            for row in trades
        ],
        "positions": [
            (
                row.id,
                row.symbol,
                row.exchange,
                row.product,
                row.quantity,
                str(row.today_realized_pnl),
                str(row.accumulated_realized_pnl),
                str(row.pnl),
                row.created_at.isoformat(),
            )
            for row in positions
            if (row.symbol, row.exchange) in instruments
        ],
        "holdings": [
            (row.id, row.symbol, row.exchange, row.quantity)
            for row in holdings
            if (row.symbol, row.exchange) in instruments
        ],
        "funds": [
            str(fund.available_balance),
            str(fund.used_margin),
            str(fund.realized_pnl),
            str(fund.today_realized_pnl),
        ]
        if fund
        else None,
        "blockers": blockers,
    }
    version = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
    return ResetPreview(
        session_start_utc=start_utc,
        session_end_utc=end_utc,
        run_ids=run_ids,
        order_ids=sandbox_ids,
        trade_ids=tuple(row.tradeid for row in trades),
        realised_pnl=realised,
        funds_before=funds_before,
        funds_after=funds_after,
        blockers=tuple(blockers),
        version=version,
        position_adjustments=tuple(position_adjustments),
        reservation_ids=tuple(reservation_ids),
    )


def _sqlite_path(bind) -> Path:
    if bind.url.get_backend_name() != "sqlite" or not bind.url.database:
        raise ResetBlocked("Sandbox reset requires two file-backed SQLite databases")
    path = Path(bind.url.database).resolve()
    if not path.is_file():
        raise ResetBlocked("A sandbox database file is unavailable")
    return path


def _backup(source: Path, destination: Path) -> None:
    source_uri = source.as_uri() + "?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        integrity = dst.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise ResetBlocked("A sandbox reset backup failed integrity verification")


@contextmanager
def _admission_lock(user_id: str):
    """Share the governor's account lease so no strategy entry races deletion."""
    scope = portfolio_governor._scope_key(str(user_id), "sandbox", None)
    lock = portfolio_governor._admission_lock(scope)
    if not portfolio_governor._acquire_admission_lock(scope, lock):
        raise ResetBlocked("A sandbox entry is already being processed")
    try:
        yield
    finally:
        portfolio_governor._release_admission_lock(scope, lock)


def _delete_rows(connection: sqlite3.Connection, view: ResetPreview, user_id: str) -> None:
    run_marks = ",".join("?" for _ in view.run_ids)
    reservation_marks = ",".join("?" for _ in view.reservation_ids)
    order_marks = ",".join("?" for _ in view.order_ids)
    trade_marks = ",".join("?" for _ in view.trade_ids)
    if not run_marks:
        return

    # Fail closed if a row changed after the last preview or belongs to a
    # different account. The operation uses exact selected primary keys.
    owned = connection.execute(
        f"SELECT COUNT(*) FROM sm_strategy_run r JOIN sm_strategy s ON s.id=r.strategy_id "
        f"WHERE s.user_id=? AND r.mode='sandbox' AND r.stopped_at IS NOT NULL "
        f"AND r.id IN ({run_marks})",
        (str(user_id), *view.run_ids),
    ).fetchone()[0]
    if owned != len(view.run_ids):
        raise ResetBlocked("Sandbox runs changed during reset")

    session_start_ist = (
        view.session_start_utc.replace(tzinfo=UTC).astimezone(session.IST).replace(tzinfo=None)
    )
    for position_id, realised_for_position in view.position_adjustments:
        position = connection.execute(
            "SELECT quantity, accumulated_realized_pnl, today_realized_pnl, pnl, "
            "created_at, margin_blocked FROM sb.sandbox_positions WHERE id=? AND user_id=?",
            (position_id, str(user_id)),
        ).fetchone()
        if position is None or position[0] != 0 or _money(position[2]) != realised_for_position:
            raise ResetBlocked("Sandbox position P&L changed during reset")
        accumulated_after = _money(position[1]) - realised_for_position
        today_after = _money(position[2]) - realised_for_position
        pnl_after = _money(position[3]) - realised_for_position
        created_at = datetime.fromisoformat(str(position[4]))
        if (
            created_at >= session_start_ist
            and accumulated_after == 0
            and today_after == 0
            and pnl_after == 0
            and _money(position[5]) == 0
        ):
            connection.execute(
                "DELETE FROM sb.sandbox_positions WHERE id=? AND user_id=?",
                (position_id, str(user_id)),
            )
        else:
            connection.execute(
                "UPDATE sb.sandbox_positions SET accumulated_realized_pnl=?, "
                "today_realized_pnl=?, pnl=? WHERE id=? AND user_id=?",
                (
                    str(accumulated_after),
                    str(today_after),
                    str(pnl_after),
                    position_id,
                    str(user_id),
                ),
            )

    if view.trade_ids:
        connection.execute(
            f"DELETE FROM sb.sandbox_trades WHERE user_id=? AND tradeid IN ({trade_marks})",
            (str(user_id), *view.trade_ids),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != len(view.trade_ids):
            raise ResetBlocked("Sandbox trades changed during reset")
    if view.order_ids:
        connection.execute(
            f"DELETE FROM sb.sandbox_orders WHERE user_id=? AND orderid IN ({order_marks})",
            (str(user_id), *view.order_ids),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != len(view.order_ids):
            raise ResetBlocked("Sandbox orders changed during reset")
    if view.reservation_ids:
        connection.execute(
            f"DELETE FROM sm_risk_reservation WHERE user_id=? "
            f"AND scope=? AND id IN ({reservation_marks})",
            (str(user_id), f"{user_id}|sandbox|sandbox", *view.reservation_ids),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != len(view.reservation_ids):
            raise ResetBlocked("Sandbox risk reservations changed during reset")

    connection.execute(
        f"UPDATE sm_critical_alert SET run_id=NULL WHERE user_id=? AND run_id IN ({run_marks})",
        (str(user_id), *view.run_ids),
    )
    for table in (
        "sm_profit_comparison",
        "sm_strategy_checkpoint",
        "sm_strategy_event",
        "sm_strategy_order",
    ):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists:
            connection.execute(f"DELETE FROM {table} WHERE run_id IN ({run_marks})", view.run_ids)
    connection.execute(f"DELETE FROM sm_strategy_run WHERE id IN ({run_marks})", view.run_ids)
    if connection.execute("SELECT changes()").fetchone()[0] != len(view.run_ids):
        raise ResetBlocked("Sandbox run set changed during reset")

    before = view.funds_before
    after = view.funds_after
    if before is None or after is None:
        raise ResetBlocked("Sandbox funds are unavailable")
    old = connection.execute(
        "SELECT available_balance, realized_pnl, today_realized_pnl, total_pnl, used_margin "
        "FROM sb.sandbox_funds WHERE user_id=?",
        (str(user_id),),
    ).fetchone()
    if old is None or _money(old[0]) != before or _money(old[4]) != 0:
        raise ResetBlocked("Sandbox funds changed during reset")
    realised = view.realised_pnl
    connection.execute(
        "UPDATE sb.sandbox_funds SET available_balance=?, realized_pnl=?, "
        "today_realized_pnl=?, total_pnl=? WHERE user_id=? AND available_balance=?",
        (
            str(after),
            str(_money(old[1]) - realised),
            str(_money(old[2]) - realised),
            str(_money(old[3]) - realised),
            str(user_id),
            old[0],
        ),
    )
    if connection.execute("SELECT changes()").fetchone()[0] != 1:
        raise ResetBlocked("Sandbox funds changed during reset")


def _verify_committed(connection: sqlite3.Connection, view: ResetPreview, user_id: str) -> None:
    """Check both ledgers before changing the durable audit to complete."""
    for database, table, column, ids in (
        ("main", "sm_strategy_run", "id", view.run_ids),
        ("main", "sm_risk_reservation", "id", view.reservation_ids),
        ("sb", "sandbox_orders", "orderid", view.order_ids),
        ("sb", "sandbox_trades", "tradeid", view.trade_ids),
    ):
        if ids:
            marks = ",".join("?" for _ in ids)
            remaining = connection.execute(
                f"SELECT COUNT(*) FROM {database}.{table} WHERE {column} IN ({marks})",
                ids,
            ).fetchone()[0]
            if remaining:
                raise ResetRecoveryRequired("The reset ledgers did not commit together")
    fund = connection.execute(
        "SELECT available_balance FROM sb.sandbox_funds WHERE user_id=?", (str(user_id),)
    ).fetchone()
    if fund is None or _money(fund[0]) != view.funds_after:
        raise ResetRecoveryRequired("Sandbox funds did not reflect the reset")


def execute(user_id: str, expected_version: str, now: datetime | None = None) -> ResetResult:
    """Clear one verified sandbox session; never contact a live broker."""
    if not isinstance(expected_version, str) or len(expected_version) != 64:
        raise ResetBlocked("A current reset preview is required")
    with _admission_lock(user_id):
        try:
            sandbox_reset_journal.assert_recovered(user_id)
        except RuntimeError as exc:
            raise ResetRecoveryRequired(str(exc)) from exc
        view = preview(user_id, now=now)
        if expected_version != view.version:
            raise ResetBlocked("The sandbox state changed; review a fresh preview")
        if view.blockers:
            raise ResetBlocked("; ".join(view.blockers))
        if not view.run_ids:
            return ResetResult(
                audit_id=None,
                run_count=0,
                order_count=0,
                trade_count=0,
                realised_pnl=Decimal("0.00"),
                funds_after=view.funds_after,
                already_done=True,
                version=view.version,
            )

        strategy_path = _sqlite_path(store.db_session.bind)
        sandbox_path = _sqlite_path(sandbox_db.db_session.bind)
        if strategy_path == sandbox_path:
            raise ResetBlocked("Strategy and sandbox databases must be separate")
        backup_dir = strategy_path.parent / "backups"
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        nonce = uuid4().hex
        strategy_backup = backup_dir / f"sandbox-reset-{nonce}-strategy.db"
        sandbox_backup = backup_dir / f"sandbox-reset-{nonce}-sandbox.db"
        _backup(strategy_path, strategy_backup)
        _backup(sandbox_path, sandbox_backup)

        payload = {
            "version": view.version,
            "session_start_utc": view.session_start_utc.isoformat(),
            "run_ids": list(view.run_ids),
            "order_ids": list(view.order_ids),
            "trade_ids": list(view.trade_ids),
            "position_ids": [position_id for position_id, _ in view.position_adjustments],
            "reservation_ids": list(view.reservation_ids),
            "position_adjustments": [
                [position_id, str(amount)] for position_id, amount in view.position_adjustments
            ],
            "realised_pnl": str(view.realised_pnl),
            "funds_before": str(view.funds_before),
            "funds_after": str(view.funds_after),
            "strategy_backup": str(strategy_backup),
            "sandbox_backup": str(sandbox_backup),
        }
        audit_id = sandbox_reset_journal.begin(user_id, payload)
        store.db_session.remove()
        sandbox_db.db_session.remove()
        connection = sqlite3.connect(strategy_path, timeout=10, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("ATTACH DATABASE ? AS sb", (str(sandbox_path),))
            connection.execute("BEGIN IMMEDIATE")
            # A second preview reads the latest committed evidence while both
            # SQLite files are write-locked. Manual sandbox writes not using
            # the governor lease cannot change either file until this commits.
            locked_view = preview(user_id, now=now)
            store.db_session.remove()
            sandbox_db.db_session.remove()
            if locked_view.version != view.version or locked_view.blockers:
                raise ResetBlocked("Sandbox state changed while preparing the reset")
            _delete_rows(connection, view, user_id)
            connection.execute("COMMIT")
            # SQLite WAL cannot crash-atomically commit attached databases.
            # Leave the audit PREPARED through the cross-file commit so any
            # crash forces recovery. Mark COMPLETE only after both are visible.
            _verify_committed(connection, view, user_id)
            sandbox_reset_journal.set_state(audit_id, "complete", "Sandbox session reset completed")
            portfolio_governor.forget_reset_sandbox_reservations(user_id, view.run_ids)
        except BaseException as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            store.db_session.remove()
            sandbox_reset_journal.set_state(
                audit_id, "recovery_required", "Sandbox reset needs recovery"
            )
            raise ResetRecoveryRequired(
                "Sandbox reset did not complete; new sandbox entries are paused"
            ) from exc
        finally:
            connection.close()
            store.db_session.remove()
            sandbox_db.db_session.remove()

        return ResetResult(
            audit_id=audit_id,
            run_count=len(view.run_ids),
            order_count=len(view.order_ids),
            trade_count=len(view.trade_ids),
            realised_pnl=view.realised_pnl,
            funds_after=view.funds_after,
            already_done=False,
            version=view.version,
        )


def recover(user_id: str, now: datetime | None = None) -> int:
    """Restore only a failed reset's selected rows, never an entire live DB.

    This is an operator recovery path, not a retry of the funds reversal.
    The gate stays closed unless the original read-only preview is restored.
    """
    with _admission_lock(user_id):
        audit = sandbox_reset_journal.latest(user_id)
        if audit is None or (audit.payload or {}).get("state") not in {
            "prepared",
            "recovery_required",
        }:
            raise ResetBlocked("There is no sandbox reset requiring recovery")
        payload = dict(audit.payload or {})
        expected = str(payload.get("version") or "")
        if preview(user_id, now=now).version == expected:
            sandbox_reset_journal.set_state(
                audit.id, "rolled_back", "Sandbox reset rolled back without changing test data"
            )
            portfolio_governor.invalidate_sandbox_reservation_cache(user_id)
            return int(audit.id)

        strategy_path = _sqlite_path(store.db_session.bind)
        sandbox_path = _sqlite_path(sandbox_db.db_session.bind)
        backup_dir = (strategy_path.parent / "backups").resolve()
        strategy_backup = Path(str(payload.get("strategy_backup") or "")).resolve()
        sandbox_backup = Path(str(payload.get("sandbox_backup") or "")).resolve()
        if (
            strategy_backup.parent != backup_dir
            or sandbox_backup.parent != backup_dir
            or not strategy_backup.is_file()
            or not sandbox_backup.is_file()
        ):
            raise ResetRecoveryRequired("Verified sandbox reset backups are unavailable")
        run_ids = tuple(int(value) for value in payload.get("run_ids", []))
        order_ids = tuple(str(value) for value in payload.get("order_ids", []))
        trade_ids = tuple(str(value) for value in payload.get("trade_ids", []))
        position_ids = tuple(int(value) for value in payload.get("position_ids", []))
        reservation_ids = tuple(int(value) for value in payload.get("reservation_ids", []))
        position_adjustments = {
            int(position_id): Decimal(str(amount))
            for position_id, amount in payload.get("position_adjustments", [])
        }
        if set(position_adjustments) != set(position_ids):
            raise ResetRecoveryRequired("Position recovery evidence is incomplete")
        if not run_ids:
            raise ResetRecoveryRequired("The failed reset has no selected runs")
        store.db_session.remove()
        sandbox_db.db_session.remove()
        connection = sqlite3.connect(strategy_path, timeout=10, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("ATTACH DATABASE ? AS sb", (str(sandbox_path),))
            connection.execute("ATTACH DATABASE ? AS original", (str(strategy_backup),))
            connection.execute("ATTACH DATABASE ? AS original_sb", (str(sandbox_backup),))
            connection.execute("BEGIN IMMEDIATE")
            current_fund = connection.execute(
                "SELECT available_balance, realized_pnl, today_realized_pnl, total_pnl "
                "FROM sb.sandbox_funds WHERE user_id=?",
                (str(user_id),),
            ).fetchone()
            original_fund = connection.execute(
                "SELECT available_balance, realized_pnl, today_realized_pnl, total_pnl "
                "FROM original_sb.sandbox_funds WHERE user_id=?",
                (str(user_id),),
            ).fetchone()
            if original_fund is None or _money(original_fund[0]) != Decimal(
                str(payload["funds_before"])
            ):
                raise ResetRecoveryRequired("Original sandbox funds backup does not reconcile")
            realised = Decimal(str(payload["realised_pnl"]))
            expected_after = tuple(_money(value) - realised for value in original_fund)
            if current_fund is None or tuple(map(_money, current_fund)) not in {
                tuple(map(_money, original_fund)),
                expected_after,
            }:
                raise ResetRecoveryRequired("Sandbox funds changed after the failed reset")
            for table, key in (("sandbox_orders", "orderid"), ("sandbox_trades", "tradeid")):
                new_rows = connection.execute(
                    f"SELECT 1 FROM sb.{table} current WHERE current.user_id=? "
                    f"AND NOT EXISTS (SELECT 1 FROM original_sb.{table} previous "
                    f"WHERE previous.user_id=current.user_id "
                    f"AND previous.{key}=current.{key}) LIMIT 1",
                    (str(user_id),),
                ).fetchone()
                if new_rows:
                    raise ResetRecoveryRequired(
                        "New sandbox activity prevents automatic reset recovery"
                    )
            ids = ",".join("?" for _ in run_ids)
            order_marks = ",".join("?" for _ in order_ids)
            trade_marks = ",".join("?" for _ in trade_ids)
            position_marks = ",".join("?" for _ in position_ids)
            # Preserve all unrelated activity. A selected row that survived a
            # partial commit is left untouched; a missing one is copied back.
            connection.execute(
                f"INSERT OR IGNORE INTO sm_strategy_run SELECT * FROM original.sm_strategy_run "
                f"WHERE id IN ({ids})",
                run_ids,
            )
            if reservation_ids:
                reservation_marks = ",".join("?" for _ in reservation_ids)
                connection.execute(
                    f"INSERT OR IGNORE INTO sm_risk_reservation "
                    f"SELECT * FROM original.sm_risk_reservation "
                    f"WHERE user_id=? AND scope=? AND id IN ({reservation_marks})",
                    (str(user_id), f"{user_id}|sandbox|sandbox", *reservation_ids),
                )
            for table in (
                "sm_strategy_order",
                "sm_strategy_checkpoint",
                "sm_strategy_event",
                "sm_profit_comparison",
            ):
                exists = connection.execute(
                    "SELECT 1 FROM original.sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if exists:
                    connection.execute(
                        f"INSERT OR IGNORE INTO {table} SELECT * FROM original.{table} "
                        f"WHERE run_id IN ({ids})",
                        run_ids,
                    )
            if order_ids:
                connection.execute(
                    f"INSERT OR IGNORE INTO sb.sandbox_orders "
                    f"SELECT * FROM original_sb.sandbox_orders WHERE user_id=? "
                    f"AND orderid IN ({order_marks})",
                    (str(user_id), *order_ids),
                )
            if trade_ids:
                connection.execute(
                    f"INSERT OR IGNORE INTO sb.sandbox_trades "
                    f"SELECT * FROM original_sb.sandbox_trades WHERE user_id=? "
                    f"AND tradeid IN ({trade_marks})",
                    (str(user_id), *trade_ids),
                )
            if position_ids:
                columns = [
                    row[1]
                    for row in connection.execute(
                        "PRAGMA original_sb.table_info(sandbox_positions)"
                    ).fetchall()
                ]
                session_start_ist = (
                    datetime.fromisoformat(str(payload["session_start_utc"]))
                    .replace(tzinfo=UTC)
                    .astimezone(session.IST)
                    .replace(tzinfo=None)
                )
                for position_id in position_ids:
                    original_position = connection.execute(
                        "SELECT * FROM original_sb.sandbox_positions WHERE id=? AND user_id=?",
                        (position_id, str(user_id)),
                    ).fetchone()
                    current_position = connection.execute(
                        "SELECT * FROM sb.sandbox_positions WHERE id=? AND user_id=?",
                        (position_id, str(user_id)),
                    ).fetchone()
                    if original_position is None:
                        raise ResetRecoveryRequired("Position backup is incomplete")
                    original_fields = dict(zip(columns, original_position, strict=True))
                    expected_fields = dict(original_fields)
                    adjustment = position_adjustments[position_id]
                    for field in ("accumulated_realized_pnl", "today_realized_pnl", "pnl"):
                        expected_fields[field] = _money(original_fields[field]) - adjustment
                    expected_deleted = datetime.fromisoformat(
                        str(original_fields["created_at"])
                    ) >= session_start_ist and all(
                        _money(expected_fields[field]) == 0
                        for field in (
                            "accumulated_realized_pnl",
                            "today_realized_pnl",
                            "pnl",
                            "margin_blocked",
                        )
                    )

                    def matches(
                        fields: dict[str, object], current: tuple | None = current_position
                    ) -> bool:
                        if current is None:
                            return False
                        for field, value in zip(columns, current, strict=True):
                            expected_value = fields[field]
                            if field in (
                                "accumulated_realized_pnl",
                                "today_realized_pnl",
                                "pnl",
                            ):
                                if _money(value) != _money(expected_value):
                                    return False
                            elif value != expected_value:
                                return False
                        return True

                    if not (
                        matches(original_fields)
                        or (expected_deleted and current_position is None)
                        or (not expected_deleted and matches(expected_fields))
                    ):
                        raise ResetRecoveryRequired(
                            "A sandbox position changed after the reset backup"
                        )
                connection.execute(
                    f"DELETE FROM sb.sandbox_positions WHERE user_id=? "
                    f"AND id IN ({position_marks})",
                    (str(user_id), *position_ids),
                )
                connection.execute(
                    f"INSERT INTO sb.sandbox_positions SELECT * FROM original_sb.sandbox_positions "
                    f"WHERE user_id=? AND id IN ({position_marks})",
                    (str(user_id), *position_ids),
                )
            connection.execute(
                "UPDATE sm_critical_alert SET run_id=("
                "SELECT prior.run_id FROM original.sm_critical_alert prior "
                "WHERE prior.id=sm_critical_alert.id) "
                f"WHERE id IN (SELECT id FROM original.sm_critical_alert WHERE run_id IN ({ids}))",
                run_ids,
            )
            connection.execute(
                "UPDATE sb.sandbox_funds SET available_balance=?, realized_pnl=?, "
                "today_realized_pnl=?, total_pnl=? WHERE user_id=?",
                (*original_fund, str(user_id)),
            )
            connection.execute("COMMIT")
        except BaseException as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise ResetRecoveryRequired(
                "Sandbox reset recovery could not restore the snapshot"
            ) from exc
        finally:
            connection.close()
            store.db_session.remove()
            sandbox_db.db_session.remove()
        if preview(user_id, now=now).version != expected:
            raise ResetRecoveryRequired(
                "Sandbox reset recovery did not reconcile the original state"
            )
        sandbox_reset_journal.set_state(
            int(audit.id), "rolled_back", "Sandbox reset restored from verified backup"
        )
        portfolio_governor.invalidate_sandbox_reservation_cache(user_id)
        return int(audit.id)
