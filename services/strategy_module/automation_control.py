"""Owner-scoped automation admission and explicit Flow linkage."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import flow_db
from database import strategy_module_db as store
from database.flow_db import get_workflows_for_strategy
from services.strategy_module.workflow_link import (
    STRATEGY_EXECUTION_NODE_TYPES,
    WorkflowLink,
    validate_workflow_link,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def require_automation_entry(strategy_id: int, user_id: str) -> tuple[bool, str | None]:
    """Admit only a durably armed owner; never trust a cached strategy snapshot.

    A separate connection and scalar select avoid both the scoped ORM identity
    map and a caller's old transaction. The connection closes before audit
    writes, so a refused entry does not hold a read transaction during commit.
    """
    if type(strategy_id) is not int or strategy_id <= 0 or not isinstance(user_id, str) or not user_id:
        return False, "Strategy automation is unavailable; new entries are blocked"
    try:
        with store.engine.connect() as connection:
            row = connection.execute(
                select(store.SmStrategy.automation_state).where(
                    store.SmStrategy.id == strategy_id,
                    store.SmStrategy.user_id == user_id,
                )
            ).first()
    except Exception:
        logger.exception("Could not read automation admission for strategy %s", strategy_id)
        return False, "Strategy automation is unavailable; new entries are blocked"
    if row is None:
        # Do not attach an audit event to another owner's strategy.
        return False, "Strategy automation is unavailable; new entries are blocked"
    automation_state = row[0]
    if automation_state == "armed":
        return True, None
    reason = f"Strategy automation is {automation_state or 'unknown'}; new entries are blocked"
    store.record_event(
        strategy_id, user_id, "automation_entry_blocked", reason,
        severity="warn", payload={"state": automation_state, "reason": reason},
    )
    return False, reason


def resolve_workflow_link(
    strategy, *, require_sandbox: bool = True
) -> tuple[WorkflowLink | None, str | None]:
    """Resolve explicit links using the shared, database-independent validator."""
    return validate_workflow_link(
        strategy, get_workflows_for_strategy(getattr(strategy, "id", None)),
        require_sandbox=require_sandbox,
    )


@dataclass(frozen=True, slots=True)
class ControlResult:
    ok: bool
    state: str
    workflow_id: int | None = None
    run_id: int | None = None
    close_pending: bool = False
    error: str | None = None


@contextmanager
def _control_lease(user_id: str):
    """Serialize controls with sandbox entries, including across workers."""
    from services.strategy_module import portfolio_governor

    scope = portfolio_governor._scope_key(user_id, "sandbox", None)
    lock = portfolio_governor._admission_lock(scope)
    if not portfolio_governor._acquire_admission_lock(scope, lock):
        raise RuntimeError("A sandbox entry or control is already being processed")
    try:
        yield
    finally:
        portfolio_governor._release_admission_lock(scope, lock)


def _read_strategy(strategy_id: int, user_id: str):
    if (
        type(strategy_id) is not int
        or strategy_id <= 0
        or not isinstance(user_id, str)
        or not user_id
    ):
        return None
    # Read independently of the request's identity map and old transaction.
    with Session(store.engine) as session:
        return session.scalar(
            select(store.SmStrategy).where(
                store.SmStrategy.id == strategy_id,
                store.SmStrategy.user_id == user_id,
            )
        )


def _transition(
    strategy_id: int, user_id: str, state: str, reason: str | None = None, *, notify: bool = True
) -> None:
    from services.strategy_module.lifecycle_events import record_and_notify

    before = _read_strategy(strategy_id, user_id)
    if before is None:
        raise RuntimeError("Strategy not found")
    if (before.automation_state, before.automation_state_reason) == (state, reason):
        return
    try:
        ok, error = store.set_automation_state(strategy_id, user_id, state, reason=reason)
        if not ok:
            raise RuntimeError(error or "Could not persist automation state")
    except Exception:
        store.db_session.rollback()
        raise
    if not notify:
        return
    record_and_notify(
        strategy_id,
        user_id,
        "run_stop_failed" if state == "close_failed" else "automation_state_changed",
        reason or f"Strategy automation is {state}",
        severity="critical" if state == "close_failed" else "info",
        payload={"state": state, "previous_state": before.automation_state, "reason": reason},
    )


def _critical(strategy_id: int, user_id: str, error: str) -> None:
    from services.strategy_module.lifecycle_events import record_and_notify

    logger.critical("Automation control for strategy %s: %s", strategy_id, error)
    record_and_notify(strategy_id, user_id, "run_stop_failed", error, severity="critical")


def _positive(value) -> bool:
    try:
        number = Decimal(str(value))
        return number.is_finite() and number > 0
    except (TypeError, ValueError, InvalidOperation):
        return False


def _enable_refusal(strategy, error: str, workflow_id: int | None = None) -> ControlResult:
    current_state = strategy.automation_state
    if current_state == "armed":
        # An already armed strategy whose prerequisites changed must not keep
        # admitting entries. Never claim disabled while exposure may exist.
        _transition(strategy.id, strategy.user_id, "close_failed", error)
        current_state = "close_failed"
    return ControlResult(
        False,
        current_state,
        workflow_id,
        strategy.current_run_id,
        current_state in {"closing", "close_failed"},
        error,
    )


def _shared_workflow_error(workflow, strategy_id: int) -> str | None:
    if any(not isinstance(node, dict) or type(node.get("type")) is not str
           for node in workflow.nodes):
        return "Linked Flow workflow has malformed nodes; individual control is unsafe"
    if any(
        node.get("type") in STRATEGY_EXECUTION_NODE_TYPES
        and node.get("data", {}).get("strategyId") != strategy_id
        for node in workflow.nodes
    ):
        return "Shared Flow workflow controls more than one strategy; individual control is unsafe"
    return None


def _exclusive_link_under_lease(strategy, workflow_id: int):
    """Re-read linkage while the caller holds this workflow's mutation lease."""
    flow_db.db_session.expire_all()
    link, error = resolve_workflow_link(strategy)
    if error or link is None:
        return None, error or "Flow workflow is unavailable"
    if link.workflow_id != workflow_id:
        return None, "Linked Flow workflow changed during control; reconciliation is required"
    workflow = flow_db.get_workflow(workflow_id)
    if workflow is None:
        return None, "Flow workflow is unavailable"
    return link, _shared_workflow_error(workflow, strategy.id)


def enable_sandbox(strategy_id: int, user_id: str, api_key: str) -> ControlResult:
    """Arm a saved sandbox strategy; activation cannot start a run or an order."""
    from services import flow_lifecycle_service as flow

    try:
        with _control_lease(user_id):
            strategy = _read_strategy(strategy_id, user_id)
            if strategy is None:
                return ControlResult(False, "disabled", error="Strategy not found")
            if strategy.automation_state not in {"disabled", "armed"}:
                return _enable_refusal(strategy, "Close/reconciliation must finish before enabling")
            if strategy.live_enabled:
                return _enable_refusal(
                    strategy, "Live-enabled strategies cannot use sandbox automation"
                )
            if not isinstance(api_key, str) or not api_key.strip():
                return _enable_refusal(strategy, "API key not configured")
            legs = strategy.legs
            if (
                not isinstance(legs, list)
                or not legs
                or any(
                    not isinstance(leg, dict) or not _positive(leg.get("sl_pts")) for leg in legs
                )
            ):
                return _enable_refusal(
                    strategy, "Every signal leg requires a configured positive stop loss"
                )
            if store.has_unresolved_order_outcomes(user_id, "sandbox"):
                return _enable_refusal(
                    strategy, "An order outcome is unresolved; reconcile before enabling"
                )
            with Session(store.engine) as session:
                unsafe_run = session.scalar(
                    select(store.SmStrategyRun.id).where(
                        store.SmStrategyRun.strategy_id == strategy_id,
                        store.SmStrategyRun.stopped_at.is_(None),
                        (store.SmStrategyRun.mode != "sandbox")
                        | store.SmStrategyRun.stop_requested_reason.is_not(None),
                    )
                )
                open_run = session.scalar(
                    select(store.SmStrategyRun.id).where(
                        store.SmStrategyRun.strategy_id == strategy_id,
                        store.SmStrategyRun.stopped_at.is_(None),
                    )
                )
            if unsafe_run is not None:
                return _enable_refusal(strategy, "A live or stopping run requires reconciliation")
            if open_run is None:
                from services.strategy_module.recovery import verify_automation_flatness

                flat, error = verify_automation_flatness(strategy_id, user_id)
                if not flat:
                    return _enable_refusal(
                        strategy, error or "Existing exposure requires reconciliation"
                    )
            flow_db.db_session.expire_all()
            link, error = resolve_workflow_link(strategy)
            if error or link is None:
                return _enable_refusal(strategy, error or "Flow workflow is unavailable")
            workflow_id = link.workflow_id
            with flow_db.workflow_mutation_lease(workflow_id):
                link, error = _exclusive_link_under_lease(strategy, workflow_id)
                if error:
                    return _enable_refusal(strategy, error, workflow_id)
                workflow = flow_db.get_workflow(workflow_id)
                blocked = flow.execution_blocked(workflow)
                if blocked:
                    return _enable_refusal(
                        strategy, blocked.get("message") or blocked["error"], workflow_id
                    )
                if strategy.automation_state == "armed" and link.active:
                    return ControlResult(True, "armed", workflow_id, strategy.current_run_id)
                if strategy.automation_state == "armed":
                    # A restored trigger may fire immediately. Hold admission
                    # closed until registration and verification both succeed.
                    _transition(strategy_id, user_id, "closing", notify=False)
                payload, status = flow.activate_workflow(workflow_id, api_key)
                if status != 200:
                    error = payload.get("error") or "Flow activation failed"
                    if "inconsistent" in error.lower():
                        _critical(strategy_id, user_id, error)
                    return _enable_refusal(strategy, error, workflow_id)
                try:
                    verified, error = _exclusive_link_under_lease(strategy, workflow_id)
                    if error or verified is None or not verified.active:
                        raise RuntimeError(error or "Flow activation could not be verified")
                    _transition(strategy_id, user_id, "armed")
                except Exception as exc:
                    payload, status = flow.deactivate_workflow(workflow_id)
                    error = str(exc)
                    if status != 200:
                        error += "; inconsistent Flow state: " + (
                            payload.get("error") or "deactivation failed"
                        )
                        _critical(strategy_id, user_id, error)
                    return _enable_refusal(strategy, error, workflow_id)
                return ControlResult(True, "armed", workflow_id, strategy.current_run_id)
    except Exception as exc:
        logger.exception("Could not enable strategy %s", strategy_id)
        try:
            current = _read_strategy(strategy_id, user_id)
            if current is not None:
                if current.automation_state == "armed":
                    _critical(strategy_id, user_id, f"Enable could not block entries: {exc}")
                return ControlResult(
                    False,
                    current.automation_state,
                    run_id=current.current_run_id,
                    close_pending=current.automation_state in {"closing", "close_failed"},
                    error=str(exc),
                )
        except Exception:
            logger.exception("Could not read failed enable state for strategy %s", strategy_id)
        return ControlResult(False, "close_failed", close_pending=True, error=str(exc))


def disable_and_close(
    strategy_id: int,
    user_id: str,
    *,
    expected_control_state: tuple[str, datetime | None] | None = None,
) -> ControlResult:
    """Block entries and close; a recovery snapshot never owns a newer epoch.

    Operator requests omit the precondition. Recovery supplies the state and
    its durable change time, checked only after the admission lease is held.
    """
    from services import flow_lifecycle_service as flow
    from services.strategy_module import engine, recovery, state

    before = None
    workflow_id = run_id = None

    def failed(error: str) -> ControlResult:
        repeated = before is not None and (
            before.automation_state,
            before.automation_state_reason,
        ) == ("close_failed", error)
        _transition(strategy_id, user_id, "close_failed", error, notify=not repeated)
        return ControlResult(False, "close_failed", workflow_id, run_id, True, error)

    try:
        with _control_lease(user_id):
            before = _read_strategy(strategy_id, user_id)
            if before is None:
                return ControlResult(False, "disabled", error="Strategy not found")
            if (
                expected_control_state is not None
                and (
                    before.automation_state,
                    before.automation_state_updated_at,
                )
                != expected_control_state
            ):
                return ControlResult(
                    True,
                    before.automation_state,
                    run_id=before.current_run_id,
                    close_pending=before.automation_state in {"closing", "close_failed"},
                )
            _transition(
                strategy_id, user_id, "closing", notify=before.automation_state != "close_failed"
            )
            if before.live_enabled:
                return failed("Live-enabled strategies cannot use sandbox automation controls")
            flow_db.db_session.expire_all()
            link, link_error = resolve_workflow_link(before)
            if link is not None:
                workflow_id = link.workflow_id
                link_error = _shared_workflow_error(flow_db.get_workflow(workflow_id), strategy_id)
            # Refresh after the closing commit. Do not trust current_run_id:
            # late-fill recovery can also leave an older detached run open.
            with Session(store.engine) as session:
                open_runs = session.execute(
                    select(store.SmStrategyRun.id, store.SmStrategyRun.mode)
                    .where(
                        store.SmStrategyRun.strategy_id == strategy_id,
                        store.SmStrategyRun.stopped_at.is_(None),
                    )
                    .order_by(store.SmStrategyRun.id)
                ).all()
            if any(mode != "sandbox" for _, mode in open_runs):
                return failed("A non-sandbox run requires separate reconciliation")
            pending = False
            errors = []
            for current_id, _ in open_runs:
                run_id = current_id
                if state.get_run_state(current_id) is None:
                    recovery.recover_run(current_id)
                store.db_session.expire_all()
                current = store.get_run(current_id)
                if current is None:
                    errors.append(f"Run {current_id} could not be refreshed")
                    continue
                if current.stopped_at is not None:
                    continue
                outcome = engine.stop_run(current_id, user_id, reason="manual")
                if not isinstance(outcome, dict):
                    errors.append(f"Run {current_id} returned an unknown stop outcome")
                    continue
                pending = pending or bool(outcome.get("stop_pending"))
                refused = [
                    exit.get("error") or "exit refused"
                    for exit in outcome.get("exits", [])
                    if not exit.get("ok")
                ]
                if not outcome.get("ok") or refused:
                    errors.append(
                        outcome.get("error") or "; ".join(refused) or "Stop request failed"
                    )
            flat, flat_error = recovery.verify_automation_flatness(strategy_id, user_id)
            if link_error or link is None:
                return failed(
                    "; ".join([*errors, link_error or "Linked Flow workflow is unavailable"])
                )
            # Broker work above deliberately holds no Flow lease. Re-read
            # exclusivity now and keep graph edits outside the entire final
            # check/trigger teardown/state-write unit, not just the DB write.
            with flow_db.workflow_mutation_lease(workflow_id):
                link, link_error = _exclusive_link_under_lease(
                    _read_strategy(strategy_id, user_id), workflow_id
                )
                if link_error:
                    return failed("; ".join([*errors, link_error]))
                if not flat and open_runs and not link.active:
                    # Closing blocks new signals throughout activation.
                    payload, status = flow.activate_workflow(
                        workflow_id, engine._api_key_for(user_id)
                    )
                    if status != 200:
                        errors.append(
                            "Protective Flow could not be restored: "
                            + (payload.get("error") or "activation failed")
                        )
                if errors:
                    return failed("; ".join(errors))
                if pending:
                    return ControlResult(True, "closing", workflow_id, run_id, True)
                if not flat:
                    return failed(flat_error or "Strategy closure is not yet confirmed")
                payload, status = flow.deactivate_workflow(workflow_id)
                if status != 200:
                    return failed(payload.get("error") or "Flow deactivation failed")
                verified, error = _exclusive_link_under_lease(
                    _read_strategy(strategy_id, user_id), workflow_id
                )
                if error or verified is None or verified.active:
                    return failed(error or "Flow deactivation could not be verified")
                _transition(strategy_id, user_id, "disabled")
                return ControlResult(True, "disabled", workflow_id, run_id)
    except Exception as exc:
        logger.exception("Could not disable strategy %s", strategy_id)
        error = str(exc)
        try:
            current = _read_strategy(strategy_id, user_id)
            if current is not None and expected_control_state is not None:
                # This handler runs after lease exit (or failed acquisition).
                # Recovery has no authority to mutate a possibly newer epoch
                # here. The last in-lease state remains the durable gate.
                return ControlResult(
                    False,
                    current.automation_state,
                    workflow_id,
                    current.current_run_id,
                    current.automation_state in {"closing", "close_failed"},
                    error,
                )
            if current is not None and current.automation_state in {"closing", "close_failed"}:
                return failed(error)
            if current is not None:
                _critical(strategy_id, user_id, f"Disable could not block entries: {error}")
                return ControlResult(
                    False,
                    current.automation_state,
                    workflow_id,
                    current.current_run_id,
                    True,
                    error,
                )
        except Exception:
            logger.exception(
                "Could not record failed automation close for strategy %s", strategy_id
            )
        return ControlResult(False, "closing", workflow_id, run_id, True, error)
