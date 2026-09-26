"""Durable audit and recovery gate for the sandbox-only test reset.

Uses the existing automation-event table so a failed reset remains visible
across restarts without a schema migration or an unrelated live-order change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from database import sandbox_db
from database import strategy_module_db as store

KIND = "sandbox_session_reset"
UNSAFE_STATES = frozenset({"prepared", "recovery_required"})
_verified_audits: set[tuple[str, int, str]] = set()


def latest(user_id: str) -> store.SmAutomationEvent | None:
    return (
        store.db_session.query(store.SmAutomationEvent)
        .filter_by(user_id=str(user_id), kind=KIND)
        .order_by(store.SmAutomationEvent.id.desc())
        .first()
    )


def assert_recovered(user_id: str) -> None:
    row = latest(user_id)
    if row and (row.payload or {}).get("state") in UNSAFE_STATES:
        raise RuntimeError("A sandbox reset needs recovery; new sandbox entries are paused")
    if row and (row.payload or {}).get("state") == "complete":
        marker = (str(store.db_session.bind.url), int(row.id), row.ts.isoformat())
        if marker not in _verified_audits:
            payload = row.payload or {}
            run_ids = tuple(int(item) for item in payload.get("run_ids", []))
            reservation_ids = tuple(int(item) for item in payload.get("reservation_ids", []))
            order_ids = tuple(str(item) for item in payload.get("order_ids", []))
            trade_ids = tuple(str(item) for item in payload.get("trade_ids", []))
            divergent = False
            if (
                run_ids
                and store.db_session.query(store.SmStrategyRun.id)
                .filter(store.SmStrategyRun.id.in_(run_ids))
                .first()
            ):
                divergent = True
            if (
                reservation_ids
                and store.db_session.query(store.SmRiskReservation.id)
                .filter(store.SmRiskReservation.id.in_(reservation_ids))
                .first()
            ):
                divergent = True
            if (
                order_ids
                and sandbox_db.db_session.query(sandbox_db.SandboxOrders.id)
                .filter(
                    sandbox_db.SandboxOrders.user_id == str(user_id),
                    sandbox_db.SandboxOrders.orderid.in_(order_ids),
                )
                .first()
            ):
                divergent = True
            if (
                trade_ids
                and sandbox_db.db_session.query(sandbox_db.SandboxTrades.id)
                .filter(
                    sandbox_db.SandboxTrades.user_id == str(user_id),
                    sandbox_db.SandboxTrades.tradeid.in_(trade_ids),
                )
                .first()
            ):
                divergent = True
            completed_ist = (
                row.ts.replace(tzinfo=UTC).astimezone(sandbox_db.IST).replace(tzinfo=None)
            )
            later_trade = (
                sandbox_db.db_session.query(sandbox_db.SandboxTrades.id)
                .filter(
                    sandbox_db.SandboxTrades.user_id == str(user_id),
                    sandbox_db.SandboxTrades.trade_timestamp > completed_ist,
                )
                .first()
            )
            if not later_trade:
                fund = (
                    sandbox_db.db_session.query(sandbox_db.SandboxFunds)
                    .filter_by(user_id=str(user_id))
                    .one_or_none()
                )
                if fund is None or Decimal(str(fund.available_balance)).quantize(
                    Decimal("0.01")
                ) != Decimal(str(payload["funds_after"])):
                    divergent = True
            if divergent:
                set_state(int(row.id), "recovery_required", "Sandbox reset ledgers diverged")
                raise RuntimeError("A sandbox reset needs recovery; ledgers diverged")
            _verified_audits.add(marker)


def begin(user_id: str, payload: dict[str, Any]) -> int:
    assert_recovered(user_id)
    row = store.SmAutomationEvent(
        user_id=str(user_id),
        ts=datetime.now(UTC).replace(tzinfo=None),
        kind=KIND,
        severity="warn",
        message="Sandbox session reset prepared",
        payload={**payload, "state": "prepared"},
    )
    store.db_session.add(row)
    store.db_session.commit()
    return int(row.id)


def set_state(audit_id: int, state: str, message: str) -> None:
    row = store.db_session.get(store.SmAutomationEvent, int(audit_id))
    if row is None or row.kind != KIND:
        raise RuntimeError("Sandbox reset audit record is missing")
    row.payload = {**(row.payload or {}), "state": state}
    row.message = message
    row.severity = "info" if state == "complete" else "critical"
    store.db_session.commit()
    if state != "complete":
        _verified_audits.clear()
