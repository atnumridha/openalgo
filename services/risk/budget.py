"""Pure, shared two-bucket capital policy. No clock, database or broker access."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")


@dataclass(frozen=True)
class BudgetPolicy:
    capital: Decimal = Decimal("10000")
    first_trade_limit: Decimal = Decimal("1000")
    later_trades_limit: Decimal = Decimal("1000")
    daily_limit: Decimal = Decimal("2000")
    drawdown_pct: Decimal = Decimal("0.20")
    cash_buffer_pct: Decimal = Decimal("0.20")
    version: str = "two-bucket-v1"


@dataclass(frozen=True)
class BudgetTrade:
    trade_id: str
    session_day: str
    bucket: str
    status: str
    planned_risk: Decimal
    net_pnl: Decimal = ZERO
    filled: bool = False


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    code: str
    bucket: str
    available: Decimal
    metrics: dict[str, Any] = field(default_factory=dict)


def budget_snapshot(policy, trades, session_day, equity, peak_equity, paused=False):
    """Losses spend budgets; gains never refill them. Open risk is reserved."""
    if not all(value.is_finite() for value in (equity, peak_equity)) or peak_equity <= 0:
        raise ValueError("Finite equity and a positive equity peak are required")
    active = [t for t in trades if t.status != "void"]
    for trade in active:
        if (
            trade.bucket not in {"first", "later"}
            or trade.status not in {"pending", "open", "closed"}
            or not trade.planned_risk.is_finite()
            or trade.planned_risk < 0
            or not trade.net_pnl.is_finite()
        ):
            raise ValueError("Incomplete trade risk evidence")
    today = [t for t in active if t.session_day == session_day]
    used = {"first": ZERO, "later": ZERO}
    actual_loss = {"first": ZERO, "later": ZERO}
    reserved = ZERO
    for trade in today:
        loss = max(ZERO, -trade.net_pnl)
        actual_loss[trade.bucket] += loss
        if trade.status in {"pending", "open"}:
            loss = max(loss, trade.planned_risk)
            reserved += max(ZERO, loss + min(ZERO, trade.net_pnl))
        used[trade.bucket] += loss
    peak = max(peak_equity, equity)
    drawdown = max(ZERO, peak - equity)
    headroom = max(ZERO, peak * policy.drawdown_pct - drawdown - reserved)
    pause = paused or drawdown >= peak * policy.drawdown_pct
    exit_all = pause or sum(actual_loss.values()) >= policy.daily_limit
    exit_buckets = [
        bucket
        for bucket, limit in (
            ("first", policy.first_trade_limit),
            ("later", policy.later_trades_limit),
        )
        if exit_all or actual_loss[bucket] >= limit
    ]
    return {
        "exit_buckets": exit_buckets,
        "first_loss": actual_loss["first"],
        "later_loss": actual_loss["later"],
        "equity": equity,
        "peak_equity": peak,
        "drawdown": drawdown,
        "drawdown_headroom": headroom,
        "reserved_risk": reserved,
        "first_remaining": max(ZERO, policy.first_trade_limit - used["first"]),
        "later_remaining": max(ZERO, policy.later_trades_limit - used["later"]),
        "daily_remaining": max(ZERO, policy.daily_limit - sum(used.values())),
        "first_trade_used": any(t.filled or t.status in {"open", "closed"} for t in today),
        "first_pending": any(
            t.bucket == "first" and not t.filled and t.status == "pending" for t in today
        ),
        "prior_session_exposure": any(
            t.session_day != session_day and t.status in {"pending", "open"} for t in active
        ),
        "paused": pause,
        "session_day": session_day,
    }


def evaluate_budget(policy, trades, session_day, equity, peak_equity, proposed_risk, paused=False):
    try:
        metrics = budget_snapshot(policy, trades, session_day, equity, peak_equity, paused)
    except (ValueError, ArithmeticError, AttributeError):
        return BudgetDecision(False, "risk_evidence_missing", "first", ZERO)
    bucket = "later" if metrics["first_trade_used"] else "first"
    available = min(
        metrics[f"{bucket}_remaining"], metrics["daily_remaining"], metrics["drawdown_headroom"]
    )
    code = "entry_allowed"
    if not proposed_risk.is_finite() or proposed_risk <= 0:
        code = "invalid_trade_risk"
    elif paused:
        code = "portfolio_paused"
    elif metrics["paused"]:
        code = "portfolio_drawdown"
    elif metrics["prior_session_exposure"]:
        code = "prior_session_exposure"
    elif metrics["first_pending"]:
        code = "first_trade_pending"
    elif proposed_risk > metrics[f"{bucket}_remaining"]:
        code = f"{bucket}_budget_exhausted"
    elif proposed_risk > metrics["daily_remaining"]:
        code = "daily_budget_exhausted"
    elif proposed_risk > metrics["drawdown_headroom"]:
        code = "drawdown_headroom"
    return BudgetDecision(code == "entry_allowed", code, bucket, available, metrics)
