"""Pure versioned capital policy. No clock, database or broker access."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")
EQUITY_POLICY_VERSION = "equity-1pct-v2"
SHARED_POLICY_VERSIONS = frozenset({"shared-300-3r-v1", EQUITY_POLICY_VERSION})


@dataclass(frozen=True)
class BudgetPolicy:
    capital: Decimal = Decimal("10000")
    first_trade_limit: Decimal = Decimal("1000")
    later_trades_limit: Decimal = Decimal("1000")
    daily_limit: Decimal = Decimal("2000")
    drawdown_pct: Decimal = Decimal("0.20")
    cash_buffer_pct: Decimal = Decimal("0.20")
    version: str = "two-bucket-v1"
    per_trade_limit: Decimal | None = None
    per_trade_equity_pct: Decimal | None = None
    daily_equity_pct: Decimal | None = None
    reduced_risk_drawdown_pct: Decimal | None = None
    risk_reduction_factor: Decimal = Decimal("1")
    max_positions: int = 2


def legacy_policy(capital=Decimal("10000")):
    return BudgetPolicy(capital=capital)


def policy_for_version(version, capital=Decimal("25000")):
    """Select immutable policy math for both live accounts and historical research."""
    if version == "two-bucket-v1":
        return legacy_policy(capital)
    if version == "shared-300-3r-v1":
        return BudgetPolicy(capital=capital, first_trade_limit=ZERO, later_trades_limit=ZERO,
                            per_trade_limit=Decimal("300"), version=version)
    if version == EQUITY_POLICY_VERSION:
        return BudgetPolicy(capital=capital, first_trade_limit=ZERO, later_trades_limit=ZERO,
                            per_trade_limit=Decimal("300"), drawdown_pct=Decimal("0.08"),
                            per_trade_equity_pct=Decimal("0.01"),
                            daily_equity_pct=Decimal("0.03"),
                            reduced_risk_drawdown_pct=Decimal("0.05"),
                            risk_reduction_factor=Decimal("0.5"), max_positions=1,
                            version=version)
    raise ValueError("Unknown risk policy version")


def current_policy(capital=Decimal("25000")):
    return policy_for_version(EQUITY_POLICY_VERSION, capital)


@dataclass(frozen=True)
class BudgetTrade:
    trade_id: str
    session_day: str
    bucket: str
    status: str
    planned_risk: Decimal
    net_pnl: Decimal = ZERO
    filled: bool = False
    close_sequence: int | None = None
    completion_day: str | None = None


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    code: str
    bucket: str
    available: Decimal
    metrics: dict[str, Any] = field(default_factory=dict)


def budget_snapshot(policy, trades, session_day, equity, peak_equity, paused=False, *,
                    daily_stopped=False, day_start_equity=None):
    """Losses spend budgets; gains never refill them. Open risk is reserved.

    Pure replay callers may omit the opening baseline when their ledger contains
    all current-day P&L and no intraday funding changes or carried marked exposure.
    Durable/live callers must supply the persisted day-opening equity.
    """
    if not all(value.is_finite() for value in (equity, peak_equity)) or peak_equity <= 0:
        raise ValueError("Finite equity and a positive equity peak are required")
    active = [t for t in trades if t.status != "void"]
    for trade in active:
        if (
            trade.bucket not in {"first", "later", "shared"}
            or trade.status not in {"pending", "open", "closed"}
            or not trade.planned_risk.is_finite()
            or trade.planned_risk < 0
            or not trade.net_pnl.is_finite()
        ):
            raise ValueError("Incomplete trade risk evidence")
    if policy.version in SHARED_POLICY_VERSIONS:
        for trade in active:
            if trade.status == "closed":
                if not trade.filled:
                    if trade.net_pnl != ZERO:
                        raise ValueError("Unfilled close has net P&L")
                    continue
                try:
                    if date.fromisoformat(trade.completion_day).isoformat() != trade.completion_day:
                        raise ValueError("Invalid completion day")
                except (TypeError, ValueError) as exc:
                    raise ValueError("Completion day is unavailable") from exc
        today = [t for t in active if (
            t.status == "closed" and t.filled and t.completion_day == session_day
        ) or (t.status in {"pending", "open"} and t.session_day == session_day)]
        return _shared_snapshot(policy, active, today, session_day, equity, peak_equity,
                                paused, daily_stopped, day_start_equity)
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
        "policy_version": policy.version,
        "daily_limit": policy.daily_limit, "per_trade_limit": policy.per_trade_limit,
        "day_start_equity": day_start_equity,
        "risk_reduced": False, "drawdown_pct": drawdown / peak,
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


def _shared_snapshot(policy, active, today, session_day, equity, peak_equity, paused, daily_stopped,
                     day_start_equity):
    closed = [t for t in today if t.status == "closed"]
    sequences = [t.close_sequence for t in closed]
    if any(not isinstance(seq, int) or seq <= 0 for seq in sequences) or len(set(sequences)) != len(sequences):
        raise ValueError("Completion order is unavailable")
    streak = 0
    stopped = bool(daily_stopped)
    for trade in sorted(closed, key=lambda item: item.close_sequence):
        streak = streak + 1 if trade.net_pnl < 0 else 0
        stopped = stopped or streak >= 3
    actual_loss = sum((max(ZERO, -t.net_pnl) for t in today), ZERO)
    # The open/pending mark may already include some of the planned loss. Reserve
    # only the incremental amount, so adverse marks and costs are not double counted.
    reserved = sum((max(ZERO, t.planned_risk + min(ZERO, t.net_pnl))
                    for t in today if t.status in {"pending", "open"}), ZERO)
    peak = max(peak_equity, equity)
    drawdown = max(ZERO, peak - equity)
    headroom = max(ZERO, peak * policy.drawdown_pct - drawdown - reserved)
    pause = paused or drawdown >= peak * policy.drawdown_pct
    risk_reduced = False
    per_trade_limit = policy.per_trade_limit
    daily_limit = policy.daily_limit
    if policy.version == EQUITY_POLICY_VERSION:
        if day_start_equity is None:
            day_start_equity = equity - sum((t.net_pnl for t in today), ZERO)
        if not day_start_equity.is_finite():
            raise ValueError("A finite day-opening equity is required")
        daily_limit = max(ZERO, min(daily_limit, day_start_equity * policy.daily_equity_pct))
        per_trade_limit = min(per_trade_limit, max(ZERO, equity) * policy.per_trade_equity_pct)
        risk_reduced = drawdown >= peak * policy.reduced_risk_drawdown_pct
        if risk_reduced:
            per_trade_limit *= policy.risk_reduction_factor
    daily_remaining = max(ZERO, daily_limit - actual_loss - reserved)
    return {
        "policy_version": policy.version,
        "exit_buckets": ["first", "later", "shared"] if pause or actual_loss >= daily_limit else [],
        "first_loss": ZERO, "later_loss": ZERO,
        "first_remaining": None, "later_remaining": None,
        "first_trade_used": False, "first_pending": False,
        "equity": equity, "peak_equity": peak, "drawdown": drawdown,
        "drawdown_headroom": headroom, "reserved_risk": reserved,
        "daily_loss": actual_loss, "daily_remaining": daily_remaining,
        "per_trade_limit": per_trade_limit, "daily_limit": daily_limit,
        "day_start_equity": day_start_equity, "risk_reduced": risk_reduced,
        "drawdown_pct": drawdown / peak,
        "position_count": sum(t.status in {"pending", "open"} for t in active),
        "consecutive_losses": streak, "daily_stopped": stopped,
        "daily_stop_reason": "three_consecutive_losses" if stopped else None,
        "prior_session_exposure": any(t.session_day != session_day and t.status in {"pending", "open"}
                                      for t in active),
        "paused": pause, "session_day": session_day,
    }


def evaluate_budget(policy, trades, session_day, equity, peak_equity, proposed_risk, paused=False,
                    *, proposed_gross_risk=None, daily_stopped=False, day_start_equity=None):
    try:
        metrics = budget_snapshot(policy, trades, session_day, equity, peak_equity, paused,
                                  daily_stopped=daily_stopped, day_start_equity=day_start_equity)
    except (ValueError, ArithmeticError, AttributeError):
        return BudgetDecision(False, "risk_evidence_missing", "first", ZERO)
    if policy.version in SHARED_POLICY_VERSIONS:
        available = min(metrics["daily_remaining"], metrics["drawdown_headroom"])
        equity_policy = policy.version == EQUITY_POLICY_VERSION
        if equity_policy:
            available = min(available, metrics["per_trade_limit"])
        code = "entry_allowed"
        gross = proposed_gross_risk
        if gross is None or not gross.is_finite() or gross <= 0 or not proposed_risk.is_finite() or proposed_risk <= 0 or proposed_risk < gross:
            code = "invalid_trade_risk"
        elif (proposed_risk if equity_policy else gross) > metrics["per_trade_limit"]:
            code = "per_trade_risk_exceeded"
        elif paused:
            code = "portfolio_paused"
        elif metrics["paused"]:
            code = "portfolio_drawdown"
        elif metrics["prior_session_exposure"]:
            code = "prior_session_exposure"
        elif equity_policy and metrics["position_count"] >= policy.max_positions:
            code = "position_limit"
        elif metrics["daily_stopped"]:
            code = "consecutive_losses_stop"
        elif proposed_risk > metrics["daily_remaining"]:
            code = "daily_budget_exhausted"
        elif proposed_risk > metrics["drawdown_headroom"]:
            code = "drawdown_headroom"
        return BudgetDecision(code == "entry_allowed", code, "shared", available, metrics)
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
