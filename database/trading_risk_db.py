"""Durable allocation and trade evidence, independent of deletable strategy runs.

Every budget mutation locks the account in one transaction. SQLite uses a short
write transaction and NullPool; no network or broker calls occur under that lock.
"""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Integer,
    Numeric,
    String,
    Text,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.orm import Session, declarative_base

from database.engine_factory import create_db_engine
from services.risk.budget import (
    BudgetDecision,
    BudgetPolicy,
    BudgetTrade,
    budget_snapshot,
    evaluate_budget,
)

engine = create_db_engine()
Base = declarative_base()
POLICY = BudgetPolicy()
ZERO = Decimal("0")


class RiskAccount(Base):
    __tablename__ = "trading_risk_account"
    scope = Column(String(180), primary_key=True)
    capital = Column(Numeric(20, 4), nullable=False, default=10000)
    peak = Column(Numeric(20, 4), nullable=False, default=10000)
    paused = Column(Boolean, nullable=False, default=False)
    pause_reason = Column(Text, nullable=True)


class RiskTrade(Base):
    __tablename__ = "trading_risk_trade"
    scope = Column(String(180), primary_key=True)
    ref = Column(String(64), primary_key=True)
    session_day = Column(String(10), nullable=False, index=True)
    bucket = Column(String(10), nullable=False)
    status = Column(String(12), nullable=False)
    planned_risk = Column(Numeric(20, 4), nullable=False)
    premium = Column(Numeric(20, 4), nullable=False)
    net_pnl = Column(Numeric(20, 4), nullable=False, default=0)
    filled = Column(Boolean, nullable=False, default=False)
    segment = Column(String(12), nullable=False)
    broker = Column(String(50), nullable=False)
    strategy_id = Column(Integer, nullable=False)
    run_id = Column(Integer, nullable=True, index=True)
    details = Column(JSON, nullable=False, default=dict)
    evidence = Column(JSON, nullable=False, default=dict)


class RiskSettings(Base):
    __tablename__ = "trading_risk_settings"
    user_id = Column(String(80), primary_key=True)
    costs = Column(JSON, nullable=True)


class RiskReview(Base):
    __tablename__ = "trading_risk_review"
    id = Column(Integer, primary_key=True)
    scope = Column(String(180), nullable=False, index=True)
    at = Column(String(40), nullable=False)
    reason = Column(Text, nullable=False)
    details = Column(JSON, nullable=False)


def init_db():
    Base.metadata.create_all(engine)


def _scope(user, mode):
    if not user or mode not in {"live", "sandbox"}:
        raise ValueError("A user and live/sandbox execution mode are required")
    return f"{user}|{mode}"


@contextmanager
def _account(user, mode):
    scope = _scope(user, mode)
    with Session(engine) as db:
        try:
            if engine.dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            account = db.scalar(
                select(RiskAccount).where(RiskAccount.scope == scope).with_for_update()
            )
            if account is None:
                account = RiskAccount(
                    scope=scope, capital=POLICY.capital, peak=POLICY.capital, paused=False
                )
                db.add(account)
                db.flush()
            yield db, account
            db.commit()
        except BaseException:
            db.rollback()
            raise


def _snapshot(db, account, day):
    rows = list(
        db.scalars(
            select(RiskTrade).where(
                RiskTrade.scope == account.scope,
                or_(RiskTrade.session_day == day, RiskTrade.status.in_(["pending", "open"])),
            )
        )
    )
    net = db.scalar(
        select(func.coalesce(func.sum(RiskTrade.net_pnl), 0)).where(
            RiskTrade.scope == account.scope, RiskTrade.status != "void"
        )
    )
    equity = account.capital + Decimal(net)
    account.peak = max(account.peak, equity)
    trades = [
        BudgetTrade(r.ref, r.session_day, r.bucket, r.status, r.planned_risk, r.net_pnl, r.filled)
        for r in rows
    ]
    result = budget_snapshot(POLICY, trades, day, equity, account.peak, account.paused)
    if result["paused"] and not account.paused:
        account.paused = True
        account.pause_reason = "Portfolio drawdown reached 20% of peak net equity"
    result["pause_reason"] = account.pause_reason
    return result, trades, rows


def status(user, mode, day):
    with _account(user, mode) as (db, account):
        return _snapshot(db, account, day)[0]


def reserve(
    user, mode, ref, day, risk, premium, segment, broker, strategy_id, details, *, broker_cash=None
):
    if not ref or len(ref) > 64 or segment not in {"index", "mcx"}:
        raise ValueError("A position reference and supported options segment are required")
    if not premium.is_finite() or premium <= 0:
        raise ValueError("A finite positive entry premium is required")
    with _account(user, mode) as (db, account):
        metrics, trades, rows = _snapshot(db, account, day)
        decision = evaluate_budget(
            POLICY, trades, day, metrics["equity"], account.peak, risk, account.paused
        )
        if db.get(RiskTrade, (account.scope, ref)) is not None:
            return BudgetDecision(
                False, "duplicate_trade", decision.bucket, decision.available, metrics
            )
        if not decision.allowed:
            return decision
        held = [r for r in rows if r.status in {"pending", "open"}]
        if len(held) >= 2 or any(r.segment == segment for r in held):
            return BudgetDecision(
                False, "position_limit", decision.bucket, decision.available, metrics
            )
        closed_net = db.scalar(
            select(func.coalesce(func.sum(RiskTrade.net_pnl), 0)).where(
                RiskTrade.scope == account.scope, RiskTrade.status == "closed"
            )
        )
        # Open profits change equity but cannot finance another entry.
        cash = (
            account.capital
            + Decimal(closed_net)
            + sum(
                (
                    Decimal(
                        str(
                            r.evidence.get(
                                "committed_cash_flow", r.evidence.get("net_cash_flow", -r.premium)
                            )
                        )
                    )
                    for r in held
                ),
                ZERO,
            )
        )
        if broker_cash is not None:
            if not broker_cash.is_finite() or broker_cash < 0:
                raise ValueError("Broker cash is unavailable")
            cash = min(cash, broker_cash)
        if cash - premium < max(ZERO, metrics["equity"] * POLICY.cash_buffer_pct):
            return BudgetDecision(
                False, "cash_buffer", decision.bucket, decision.available, metrics
            )
        db.add(
            RiskTrade(
                scope=account.scope,
                ref=ref,
                session_day=day,
                bucket=decision.bucket,
                status="pending",
                planned_risk=risk,
                premium=premium,
                net_pnl=ZERO,
                filled=False,
                segment=segment,
                broker=broker,
                strategy_id=strategy_id,
                details=details,
                evidence={},
            )
        )
        return decision


def update_trade(user, mode, ref, *, status, net_pnl, filled, evidence, expected=None):
    if status not in {"pending", "open", "closed", "void"} or not net_pnl.is_finite():
        raise ValueError("Invalid risk evidence")
    with _account(user, mode) as (db, account):
        row = db.get(RiskTrade, (account.scope, ref))
        if row is None:
            raise ValueError("Unknown risk reservation")
        if expected is not None and any(
            getattr(row, key) != expected[key] for key in ("status", "net_pnl", "evidence")
        ):
            # A newer tick/fill already committed. Never replace it with a stale
            # snapshot computed before taking this account lock.
            return False
        if status == "void" and (filled or row.filled):
            raise ValueError("A filled trade cannot be voided")
        if row.status == "closed" and status == "pending":
            raise ValueError("A completed trade cannot become an unfilled order")
        row.status, row.net_pnl, row.filled = status, net_pnl, filled or row.filled
        row.evidence = {
            **evidence,
            "_ledger_revision": int((row.evidence or {}).get("_ledger_revision", 0)) + 1,
        }
        db.flush()
        _snapshot(db, account, row.session_day)
        return True


def bind_run(user, mode, ref, run_id):
    with _account(user, mode) as (db, account):
        row = db.get(RiskTrade, (account.scope, ref))
        if row is None or (row.run_id is not None and row.run_id != run_id):
            raise ValueError("Risk reservation does not belong to this run")
        row.run_id = run_id


def scope_for_run(run_id):
    with Session(engine) as db:
        scope = db.scalar(select(RiskTrade.scope).where(RiskTrade.run_id == run_id).limit(1))
        return scope.rsplit("|", 1) if scope else None


def list_trades(user=None, mode=None, *, run_id=None, active_only=False, ref=None):
    with Session(engine) as db:
        query = select(RiskTrade)
        if user is not None:
            query = query.where(RiskTrade.scope == _scope(user, mode))
        if run_id is not None:
            query = query.where(RiskTrade.run_id == run_id)
        if ref is not None:
            query = query.where(RiskTrade.ref == ref)
        if active_only:
            query = query.where(RiskTrade.status.in_(["open", "pending"]))
        return [
            {
                **{c.name: getattr(r, c.name) for c in RiskTrade.__table__.columns},
                "ledger_revision": int((r.evidence or {}).get("_ledger_revision", 0)),
            }
            for r in db.scalars(query)
        ]


def pause(user, mode, reason):
    with _account(user, mode) as (_db, account):
        account.paused = True
        account.pause_reason = str(reason)[:2000]


def resume(user, mode, day, reason, *, reconciled=False):
    if reconciled is not True or not isinstance(reason, str) or not reason.strip():
        raise ValueError("A reconciliation acknowledgement and review reason are required")
    with _account(user, mode) as (db, account):
        snapshot, _trades, rows = _snapshot(db, account, day)
        if any(r.status in {"open", "pending"} for r in rows):
            raise ValueError("Unresolved exposure must be reconciled before review")
        if snapshot["equity"] <= 0:
            raise ValueError("Positive allocated equity is required")
        db.add(
            RiskReview(
                scope=account.scope,
                at=datetime.now(UTC).isoformat(),
                reason=reason[:2000],
                details={"old_peak": str(account.peak), "reviewed_equity": str(snapshot["equity"])},
            )
        )
        account.peak = snapshot["equity"]
        account.paused, account.pause_reason = False, None


def policy_enabled(user):
    """An explicitly activated account stays managed even if fee evidence is missing."""
    with Session(engine) as db:
        return db.get(RiskSettings, str(user)) is not None


def activate_policy(user):
    with Session(engine) as db, db.begin():
        if db.get(RiskSettings, str(user)) is None:
            db.add(RiskSettings(user_id=str(user), costs=None))


def get_costs(user):
    with Session(engine) as db:
        row = db.get(RiskSettings, str(user))
        return dict(row.costs) if row and row.costs is not None else None


def set_costs(user, costs):
    with Session(engine) as db, db.begin():
        row = db.get(RiskSettings, str(user))
        if row is None:
            db.add(RiskSettings(user_id=str(user), costs=costs))
        else:
            row.costs = costs


def policy_payload():
    return {
        key: float(value) if isinstance(value, Decimal) else value
        for key, value in asdict(POLICY).items()
    }
