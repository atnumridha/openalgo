"""Read-only live setup diagnostics, never an authorization or an order preflight.

Use bounded local evidence. Quotes, funds and the full research binding are
revalidated by admission; this monitor must not acquire campaign write locks,
create risk accounts, renew approval, or call a broker on every UI refresh.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session


def broker_problem(owner, connection_id):
    from services.research.qualification_context import _broker_identity

    try:
        _broker_identity(owner, connection_id)
    except ValueError as exc:
        return str(exc)
    except Exception:
        return "Pinned broker session evidence is unavailable; reconnect and verify the account."
    return None


def cost_problem(owner, exchange, day):
    from database import trading_risk_db as risk
    from services.research.costs import validate_cost_dates, validate_cost_schedule

    try:
        if not risk.policy_enabled(owner):
            return "The capital risk profile is not enabled. Save verified costs in Research."
        costs = validate_cost_schedule(risk.get_costs(owner, exchange))
        if costs.get("exchange") != exchange:
            return f"A verified {exchange} cost schedule is required."
        validate_cost_dates(costs, [day])
    except ValueError as exc:
        return str(exc)
    except Exception:
        return "Cost evidence is unavailable."
    return None


def campaign_approval(owner, strategy_id):
    from database.strategy_qualification_db import QualificationCampaign, digest, get_store

    # active_campaign() uses a write transaction. Monitoring needs only this
    # one owner's saved approval, without loading every forward trade.
    with Session(get_store().engine) as db:
        return db.scalar(
            select(QualificationCampaign.approval).where(
                QualificationCampaign.owner == owner,
                QualificationCampaign.strategy_id == strategy_id,
                QualificationCampaign.active_key == digest([owner, strategy_id]),
            ).limit(1)
        )


def inspect_setup(owner, row, data, approval, risk, scheduler, policy, *, now):
    checks = []

    def add(code, label, status, message, path=None):
        checks.append({"code": code, "label": label, "status": status,
                       "message": message, "action_url": path})

    add("execution_mode", "Execution mode", "passed" if data["mode"] == "live" else "blocked",
        "Linked Flow submits in Live mode." if data["mode"] == "live"
        else "Linked Flow uses Sandbox. Use the strategy's Start live control to change mode safely.",
        f"/strategy/{row.id}")
    add("live_opt_in", "Strategy live permission", "passed" if row.live_enabled else "blocked",
        "Live permission is enabled." if row.live_enabled else "Enable LIVE for this strategy.",
        f"/strategy/{row.id}")
    add("session_approval", "Trading-session approval", "passed" if approval.active else "blocked",
        "Saved approval is active for this broker session." if approval.active
        else "Live session approval is absent, expired, revoked or bound to another broker session. Approve the current session in Strategies.",
        "/strategy")
    problem = broker_problem(owner, row.broker_connection_id)
    add("broker_session", "Pinned broker session", "blocked" if problem else "passed",
        problem or "The saved broker session matches this strategy's pinned account.")
    problem = data.get("link_error")
    if not problem and row.automation_state != "armed":
        problem = "Automation is not enabled for new entries."
    if not problem and not data.get("workflow_active"):
        problem = "The linked Flow is inactive."
    if not problem and scheduler.get("status") != "running":
        problem = "The scheduler is unavailable or paused."
    if not problem and data.get("schedule_status") != "scheduled":
        problem = "No upcoming Flow check is confirmed."
    add("signal_monitor", "Signal monitoring", "blocked" if problem else "passed",
        problem or "Automation, linked Flow and scheduler are enabled.")
    from services.strategy_module.symbol_resolver import derivatives_exchange

    exchange = derivatives_exchange(row.underlying_exchange)
    day = now.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    problem = cost_problem(owner, exchange, day)
    add("cost_schedule", "Risk profile and dated costs", "blocked" if problem else "passed",
        problem or f"Saved costs cover {exchange} on {day}.", "/strategy/research")
    ledger = risk.get("ledger") or {}
    problem = None
    if not risk.get("available"):
        problem = "Live risk ledger is unavailable. Entry eligibility cannot be confirmed."
    elif ledger.get("paused") or ledger.get("daily_stopped"):
        problem = risk.get("pause_reason") or risk.get("daily_stop_reason") or "The risk policy has paused entries."
    elif ledger.get("daily_remaining", 0) <= 0:
        problem = "No daily loss allowance remains."
    elif ledger.get("drawdown_headroom") is not None and ledger["drawdown_headroom"] <= 0:
        problem = "No portfolio loss allowance remains."
    elif ledger.get("prior_session_exposure"):
        problem = "Prior-session exposure still needs reconciliation."
    elif risk.get("max_positions") and ledger.get("position_count", 0) >= risk["max_positions"]:
        problem = "The portfolio's concurrent position limit is already in use."
    elif ledger.get("first_pending"):
        problem = "The first trade's reserved risk still needs reconciliation."
    add("risk_budget", "Daily risk allowance", "blocked" if problem else "passed",
        problem or "The saved live risk ledger has loss allowance remaining. Actual order size and cash are checked at entry.")
    if policy is None:
        add("research_release", "Research requirement", "blocked", "The saved research requirement could not be read.", "/strategy/research")
    elif not policy.get("research_required", True):
        add("research_release", "Research requirement", "passed", "Research qualification is optional under the saved policy; live permission and risk checks still apply.", "/strategy/research")
    else:
        try:
            release = campaign_approval(owner, row.id)
            if not release or release.get("status") != "approved":
                message = "Research qualification is required, but no approved forward release is saved. Complete qualification or review the optional-research policy."
                status = "blocked"
            elif datetime.fromisoformat(release["expires_at"]).astimezone(UTC) <= now:
                status, message = "blocked", "The saved research release expired. Review it again."
            else:
                status, message = "pending", "A release is saved. Its current strategy, Flow, broker and evidence binding must still pass at entry."
        except Exception:
            status, message = "blocked", "Research release evidence is unavailable."
        add("research_release", "Research requirement", status, message, "/strategy/research")
    add("entry_checks", "Checks at the next signal", "pending",
        "A fresh bullish or bearish signal, session window, contract, spread, live cash, protective stop and portfolio limits must pass together. Setup checks alone do not authorize an order.")
    count = sum(c["status"] == "blocked" for c in checks)
    return {"blocked": bool(count), "blocker_count": count, "checks": checks}
