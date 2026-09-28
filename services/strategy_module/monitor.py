"""Owner-scoped automation evidence and controls. Reading never starts a job."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import flow_db
from database import strategy_module_db as store
from services.strategy_module.workflow_link import validate_workflow_link
from utils.logging import get_logger, redact_text

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
SECRET_KEYS = re.compile(
    r"api.?key|token|password|secret|authorization|cookie|credential|mpin|totp", re.I
)


def clean(value):
    if isinstance(value, dict):
        return {
            str(k): "[redacted]" if SECRET_KEYS.search(str(k)) else clean(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return redact_text(value) if isinstance(value, str) else value


def utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value):
    return utc(value).isoformat() if value is not None else None


def owned_strategy(owner, sid):
    with Session(store.engine) as db:
        row = db.scalar(
            select(store.SmStrategy).where(
                store.SmStrategy.id == sid, store.SmStrategy.user_id == owner
            )
        )
    if row is None:
        raise LookupError("Strategy not found")
    return row


def linked_workflows(row):
    workflows = flow_db.get_workflows_for_strategy(row.id, strict=True)
    link, error = validate_workflow_link(row, workflows, require_sandbox=False)
    return (workflows[0] if link else None), link, error


def scheduler_state():
    from services.flow_scheduler_service import get_flow_scheduler

    try:
        scheduler = get_flow_scheduler()
        running = scheduler.scheduler.running and scheduler.scheduler.state == 1
        return scheduler, {"status": "running" if running else "paused", "error": None}
    except Exception:
        return None, {"status": "unavailable", "error": "Scheduler evidence is unavailable"}


def _interval(workflow):
    start = next((n.get("data", {}) for n in workflow.nodes if n.get("type") == "start"), {})
    if start.get("scheduleType") != "interval":
        return None
    try:
        return (
            max(1, float(start.get("intervalValue", 1)))
            * {"seconds": 1, "minutes": 60, "hours": 3600}[start.get("intervalUnit", "minutes")]
        )
    except (ValueError, TypeError, KeyError):
        return None


def _status(row, data, now, scheduler):
    if row.automation_state in ("closing", "close_failed"):
        return (
            row.automation_state,
            row.automation_state_reason
            or "Closure is not yet confirmed. Inspect orders and events.",
        )
    if row.automation_state != "armed":
        if data["open_run_count"]:
            return (
                "unmanaged_run",
                "Automation is not armed, but an open managed run remains. Inspect fills and request closure if needed.",
            )
        if row.automation_state == "disabled":
            return "disabled", "Automation is disabled."
        return "unknown", "Automation state is unknown; entry eligibility is not confirmed."
    if data["link_error"]:
        return "link_error", data["link_error"]
    if not data["workflow_active"]:
        return "flow_inactive", "Automation is armed but its Flow is inactive."
    if scheduler["status"] != "running":
        return (
            "scheduler_unavailable",
            "The scheduler is paused or unavailable; checks are not confirmed.",
        )
    if data["schedule_status"] != "scheduled":
        return "schedule_missing", "No upcoming scheduler check was found. Inspect the linked Flow."
    local = now.astimezone(IST)
    entry, exit_ = row.entry_time, row.exit_time
    from database.market_calendar_db import get_effective_session_window

    if (
        get_effective_session_window(local.date(), (row.underlying_exchange or "NSE").split("_")[0])
        is None
    ):
        return "outside_session", "Waiting for a trading session; no new entry is expected now."
    if row.strategy_type == "intraday" and entry and local.time().replace(tzinfo=None) < entry:
        return (
            "waiting_window",
            f"Waiting until {entry.strftime('%H:%M')} IST for this strategy’s entry window.",
        )
    if row.strategy_type == "intraday" and exit_ and local.time().replace(tzinfo=None) >= exit_:
        return (
            "outside_session",
            f"Entry window ended at {exit_.strftime('%H:%M')} IST. Inspect open runs for pending exits.",
        )
    age = data["check_age_seconds"]
    if age is None:
        return (
            "waiting_check",
            "No execution has been recorded; waiting for the first scheduled check.",
        )
    if data["interval_seconds"] is None:
        return (
            "scheduled",
            "Scheduled Flow. Inspect the last execution and next check; continuous signal monitoring is not confirmed.",
        )
    if (
        data["next_check_at"]
        and (now - datetime.fromisoformat(data["next_check_at"])).total_seconds() > 30
    ):
        return "stale", "The scheduled check is overdue; inspect scheduler health."
    if data["interval_seconds"] is not None and (
        age is None or age > max(95, data["interval_seconds"] * 2 + 15)
    ):
        return "stale", "No recent execution evidence. Automation may not be checking signals."
    if data["last_check_status"] in ("failed", "error"):
        reason = data["last_check_error"] or "The last execution failed; open its complete log."
        if "This intraday strategy can start only between" in reason:
            return (
                "waiting_check",
                "The last check was outside the entry window. Waiting for a new check.",
            )
        return "error", reason
    if data["last_check_status"] in ("collecting_history", "data_unavailable", "risk_blocked"):
        return data["last_check_status"], data["last_check_error"] or data["last_message"] or data[
            "last_check_status"
        ].replace("_", " ").capitalize()
    message = data.get("last_message") or ""
    if message.startswith(
        (
            "Market history unavailable",
            "Collecting history",
            "Daily regime needs",
            "MACD needs",
            "EMA 50/200 needs",
            "Research rules need",
        )
    ):
        return "data_unavailable", message
    evaluation = data.get("evaluation") or {}
    if (
        evaluation.get("technical", {}).get("data_ready") is False
        and data.get("last_check_at")
        and evaluation.get("recorded_at", "") >= data["last_check_at"]
    ):
        return (
            "data_unavailable",
            "The expected completed candle is missing. Inspect history timestamps below.",
        )
    if data["open_run_count"]:
        return "in_trade", "A managed trading run is active. Inspect orders for actual fill status."
    if data["last_check_status"] in ("pending", "running"):
        return "checking", "A strategy check is in progress."
    return "watching", data[
        "last_message"
    ] or "Checks are arriving. Waiting for an eligible trading signal."


def overview(owner, *, now=None):
    now = utc(now or datetime.now(UTC))
    scheduler, health = scheduler_state()
    with Session(store.engine) as db:
        rows = db.scalars(
            select(store.SmStrategy)
            .where(store.SmStrategy.user_id == owner)
            .order_by(store.SmStrategy.id)
        ).all()
        runs = db.scalars(
            select(store.SmStrategyRun)
            .join(store.SmStrategy)
            .where(store.SmStrategy.user_id == owner, store.SmStrategyRun.stopped_at.is_(None))
        ).all()
    result = []
    for row in rows:
        workflow, link, error = linked_workflows(row)
        last = None
        failure = None
        next_at = None
        schedule = "unavailable"
        if workflow:
            with Session(flow_db.engine) as db:
                last = db.scalar(
                    select(flow_db.FlowWorkflowExecution)
                    .where(flow_db.FlowWorkflowExecution.workflow_id == workflow.id)
                    .order_by(flow_db.FlowWorkflowExecution.id.desc())
                    .limit(1)
                )
                failure = db.scalar(
                    select(flow_db.FlowWorkflowExecution)
                    .where(
                        flow_db.FlowWorkflowExecution.workflow_id == workflow.id,
                        flow_db.FlowWorkflowExecution.status.in_(["failed", "error"]),
                    )
                    .order_by(flow_db.FlowWorkflowExecution.id.desc())
                    .limit(1)
                )
            try:
                job = scheduler.get_workflow_job(workflow.id) if scheduler else None
                next_at = getattr(job, "next_run_time", None)
                schedule = "scheduled" if next_at else "missing"
            except Exception:
                schedule = "unavailable"
        logs = last.logs if last and isinstance(last.logs, list) else []
        messages = [
            x.get("message")
            for x in logs
            if isinstance(x, dict) and isinstance(x.get("message"), str)
        ]
        open_runs = [r for r in runs if r.strategy_id == row.id]
        data = {
            "id": row.id,
            "name": row.name,
            "automation_state": row.automation_state,
            "run_status": row.status,
            "mode": link.mode if link else ("live" if row.live_enabled else "sandbox"),
            "live_enabled": bool(row.live_enabled),
            "webhook_locked": bool(row.webhook_locked),
            "current_run_id": row.current_run_id,
            "open_run_count": len(open_runs),
            "open_runs": [
                {
                    "id": r.id,
                    "mode": r.mode,
                    "started_at": iso(r.started_at),
                    "stop_requested_reason": r.stop_requested_reason,
                }
                for r in open_runs
            ],
            "entry_time": row.entry_time.strftime("%H:%M") if row.entry_time else None,
            "exit_time": row.exit_time.strftime("%H:%M") if row.exit_time else None,
            "workflow_id": workflow.id if workflow else None,
            "workflow_name": workflow.name if workflow else None,
            "workflow_active": bool(link and link.active),
            "link_error": error,
            "interval_seconds": _interval(workflow) if workflow else None,
            "schedule_status": schedule,
            "next_check_at": iso(next_at),
            "last_check_at": iso(last.started_at) if last else None,
            "check_age_seconds": max(0, (now - utc(last.started_at)).total_seconds())
            if last and last.started_at
            else None,
            "latest_execution_id": last.id if last else None,
            "last_check_status": last.status if last else None,
            "last_check_error": last.error if last else None,
            "last_failure": {
                "at": iso(failure.started_at),
                "message": failure.error or "Execution failed",
            }
            if failure
            else None,
            "last_message": messages[-1] if messages else None,
        }
        with Session(store.engine) as db:
            evaluation = db.scalar(
                select(store.SmStrategyEvent)
                .where(
                    store.SmStrategyEvent.strategy_id == row.id,
                    store.SmStrategyEvent.user_id == owner,
                    store.SmStrategyEvent.kind == "signal_evaluation",
                )
                .order_by(store.SmStrategyEvent.id.desc())
                .limit(1)
            )
            rejection = db.scalar(
                select(store.SmStrategyEvent)
                .where(
                    store.SmStrategyEvent.strategy_id == row.id,
                    store.SmStrategyEvent.user_id == owner,
                    store.SmStrategyEvent.kind == "portfolio_governor_rejected",
                )
                .order_by(store.SmStrategyEvent.id.desc())
                .limit(1)
            )
            checkpoint = db.scalar(
                select(store.SmStrategyCheckpoint)
                .join(store.SmStrategyRun)
                .where(
                    store.SmStrategyRun.strategy_id == row.id,
                    store.SmStrategyRun.stopped_at.is_(None),
                )
                .order_by(store.SmStrategyCheckpoint.id.desc())
                .limit(1)
            )
        from services.strategy_module.signal_review import RULES

        data["evaluation"] = (
            {"id": evaluation.id, "recorded_at": iso(evaluation.ts), **(evaluation.payload or {})}
            if evaluation
            else None
        )
        data["rules"] = RULES.get(
            row.scalp_profile,
            ["Entry logic is defined by the linked Flow. Inspect its nodes and execution log."],
        )
        data["configuration"] = {
            "profile": row.scalp_profile,
            "kind": row.strategy_kind,
            "underlying": row.underlying,
            "exchange": row.underlying_exchange,
            "product": row.product,
            "order_type": row.pricetype,
            "broker_connection_id": row.broker_connection_id,
        }
        data["last_risk_rejection"] = (
            {"at": iso(rejection.ts), "message": rejection.message, "details": rejection.payload}
            if rejection
            else None
        )
        data["checkpoint"] = store.checkpoint_to_dict(checkpoint) if checkpoint else None
        data["monitor_status"], data["reason"] = _status(row, data, now, health)
        result.append(clean(data))
    from services.strategy_module.live_authorization import peek_status as live_status

    authorization = live_status(owner)
    return {
        "server_time": iso(now),
        "refresh_interval_seconds": 3,
        "scheduler": health,
        "live_authorization": {
            "active": authorization.active,
            "expires_at": authorization.expires_at,
        },
        "risk": {
            mode: risk_evidence(owner, mode, now.astimezone(IST).date().isoformat())
            for mode in ("sandbox", "live")
        },
        "strategies": result,
    }


def log_page(owner, sid, *, stream="executions", limit=25, before_id=None):
    if stream not in ("executions", "events", "orders"):
        raise ValueError("Choose executions, events or orders")
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or (before_id is not None and (type(before_id) is not int or before_id <= 0))
    ):
        raise ValueError("Invalid log page cursor or limit")
    strategy = owned_strategy(owner, sid)
    if stream == "executions":
        workflow, link, error = linked_workflows(strategy)
        if not link:
            return {"items": [], "next_cursor": None, "stream": stream, "notice": error}
        model, bind = flow_db.FlowWorkflowExecution, flow_db.engine
        query = select(model).where(model.workflow_id == workflow.id)
    elif stream == "events":
        model, bind = store.SmStrategyEvent, store.engine
        query = select(model).where(model.strategy_id == sid, model.user_id == owner)
    else:
        model, bind = store.SmStrategyOrder, store.engine
        query = (
            select(model).join(store.SmStrategyRun).where(store.SmStrategyRun.strategy_id == sid)
        )
    if before_id is not None:
        query = query.where(model.id < before_id)
    with Session(bind) as db:
        rows = db.scalars(query.order_by(model.id.desc()).limit(limit + 1)).all()
    items = []
    for row in rows[:limit]:
        if stream == "executions":
            item = {
                "id": row.id,
                "at": iso(row.started_at),
                "status": row.status,
                "completed_at": iso(row.completed_at),
                "message": row.error or "Workflow execution",
                "details": row.logs,
            }
        elif stream == "events":
            item = {
                "id": row.id,
                "at": iso(row.ts),
                "status": row.severity,
                "message": row.message,
                "kind": row.kind,
                "run_id": row.run_id,
                "details": row.payload,
            }
        else:
            item = {
                "id": row.id,
                "at": iso(row.placed_at),
                "status": row.status,
                "message": f"{row.action} {row.qty} {row.symbol}",
                "run_id": row.run_id,
                "kind": row.kind,
                "details": {
                    "exchange": row.exchange,
                    "broker_order_id": row.broker_order_id,
                    "quantity": row.qty,
                    "filled_quantity": row.filled_qty,
                    "fill_price": float(row.avg_fill_price)
                    if row.avg_fill_price is not None
                    else None,
                    "price": float(row.price) if row.price is not None else None,
                    "trigger_price": float(row.trigger_price)
                    if row.trigger_price is not None
                    else None,
                    "reject_reason": row.reject_reason,
                    "filled_at": iso(row.filled_at),
                },
            }
        items.append(clean(item))
    return {
        "items": items,
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        "stream": stream,
        "notice": None,
    }


def emergency_stop(owner):
    """Block supported managed automation before closure, retaining per-target failures."""
    from services.strategy_module import automation_control as control

    with control._control_lease(owner, include_live=True):
        with Session(store.engine) as db:
            rows = db.scalars(
                select(store.SmStrategy)
                .where(store.SmStrategy.user_id == owner)
                .order_by(store.SmStrategy.id)
            ).all()
            open_ids = set(
                db.scalars(
                    select(store.SmStrategyRun.strategy_id)
                    .join(store.SmStrategy)
                    .where(
                        store.SmStrategy.user_id == owner, store.SmStrategyRun.stopped_at.is_(None)
                    )
                )
            )
            with Session(flow_db.engine) as flows:
                active_ids = {
                    node["data"]["strategyId"]
                    for workflow in flows.scalars(
                        select(flow_db.FlowWorkflow).where(flow_db.FlowWorkflow.is_active.is_(True))
                    )
                    for node in (workflow.nodes if isinstance(workflow.nodes, list) else [])
                    if isinstance(node, dict)
                    and node.get("type") in ("strategyModuleRun", "strategySignal")
                    and isinstance(node.get("data"), dict)
                    and type(node["data"].get("strategyId")) is int
                }
            # Unsupported legacy batch entries do not honor this durable gate.
            # Never claim they are stopped or mutate them into unrecoverable closing.
            unsupported = [
                r
                for r in rows
                if not r.scalp_profile
                and r.strategy_kind != "signal"
                and (
                    r.automation_state != "disabled"
                    or r.current_run_id
                    or r.status == "running"
                    or r.id in open_ids
                    or r.id in active_ids
                )
            ]
            rows = [
                r
                for r in rows
                if (r.scalp_profile or r.strategy_kind == "signal")
                and (
                    r.automation_state != "disabled"
                    or r.current_run_id
                    or r.status == "running"
                    or r.id in open_ids
                    or r.id in active_ids
                )
            ]
            targets = [(r.id, r.name) for r in rows]
            unsupported_items = [
                {
                    "strategy_id": r.id,
                    "name": r.name,
                    "ok": False,
                    "state": r.automation_state,
                    "close_pending": True,
                    "reason": "Legacy batch automation requires its individual strategy stop and broker reconciliation; this control cannot confirm it stopped.",
                }
                for r in unsupported
            ]
            for row in rows:
                row.automation_state = "closing"
                row.automation_state_reason = "Emergency stop requested from automation monitor"
                row.automation_state_updated_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
    items = unsupported_items
    for sid, name in targets:
        try:
            store.record_event(
                sid,
                owner,
                "automation_emergency_stop",
                "Emergency stop: new automation entries blocked",
                severity="warn",
            )
        except Exception:
            logger.exception("Could not record emergency-stop audit for %s", sid)
        try:
            outcome = control.disable_and_close(sid, owner)
            item = {
                "strategy_id": sid,
                "name": name,
                "ok": outcome.ok,
                "state": outcome.state,
                "close_pending": outcome.close_pending,
                "reason": outcome.error,
            }
        except Exception:
            logger.exception("Emergency stop could not close strategy %s", sid)
            try:
                store.set_automation_state(
                    sid,
                    owner,
                    "close_failed",
                    reason="Emergency closure failed; inspect orders and retry",
                )
            except Exception:
                # The initial transaction already blocked all targets. A second
                # audit failure must not prevent requests for remaining exits.
                logger.exception("Could not persist closure failure for %s", sid)
            item = {
                "strategy_id": sid,
                "name": name,
                "ok": False,
                "state": "close_failed",
                "close_pending": True,
                "reason": "Emergency closure failed; inspect orders and retry",
            }
        items.append(clean(item))
    return {
        "items": items,
        "all_stopped": all(
            r["ok"] and r["state"] == "disabled" and not r["close_pending"] for r in items
        ),
    }


def risk_evidence(owner, mode, day):
    """Read ledger without creating accounts, advancing policy or pausing it."""
    from decimal import Decimal

    from database import trading_risk_db as risk
    from services.risk.budget import BudgetTrade, budget_snapshot, policy_for_version

    try:
        with Session(risk.engine) as db:
            account = db.get(risk.RiskAccount, risk._scope(owner, mode))
            settings = db.get(risk.RiskSettings, owner)
            if account is None:
                return {"available": False, "reason": "No saved capital account for this mode"}
            rows = db.scalars(
                select(risk.RiskTrade).where(risk.RiskTrade.scope == account.scope)
            ).all()
            baseline = db.get(risk.RiskDayEquity, (account.scope, day))
            stopped = db.get(risk.RiskDayStop, (account.scope, day))
            policy = policy_for_version(account.policy_version, account.capital)
            equity = account.capital + sum(
                (r.net_pnl for r in rows if r.status != "void"), Decimal(0)
            )
            trades = [
                BudgetTrade(
                    r.ref,
                    r.session_day,
                    r.bucket,
                    r.status,
                    r.planned_risk,
                    r.net_pnl,
                    r.filled,
                    r.close_sequence,
                    r.completion_day,
                )
                for r in rows
            ]
            snapshot = budget_snapshot(
                policy,
                trades,
                day,
                equity,
                account.peak,
                account.paused,
                daily_stopped=stopped is not None or account.daily_stop_day == day,
                day_start_equity=baseline.opening_equity if baseline else None,
            )
            from services.risk.cash_exit import CASH_RISK_RECIPE

            return {
                "available": True,
                "policy_version": account.policy_version,
                "capital": float(account.capital),
                "costs_configured": bool(settings and settings.costs),
                "pause_reason": account.pause_reason,
                "daily_stop_reason": stopped.reason if stopped else account.daily_stop_reason,
                "exit_recipe": CASH_RISK_RECIPE,
                "ledger": {
                    k: float(v) if isinstance(v, Decimal) else v for k, v in snapshot.items()
                },
            }
    except Exception:
        logger.exception("Risk ledger evidence unavailable")
        return {
            "available": False,
            "reason": "Risk ledger could not be read; eligibility is unknown",
        }
