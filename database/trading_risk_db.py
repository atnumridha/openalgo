"""Durable allocation and trade evidence, independent of deletable strategy runs.

Every budget mutation locks the account in one transaction. SQLite uses a short
write transaction and NullPool; no network or broker calls occur under that lock.
"""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Integer,
    Numeric,
    String,
    Text,
    and_,
    func,
    inspect,
    or_,
    select,
    text,
    true,
)
from sqlalchemy.orm import Session, declarative_base

from database.engine_factory import create_db_engine
from services.risk.budget import (
    EQUITY_POLICY_VERSION,
    FIXED_POLICY_VERSION,
    SHARED_POLICY_VERSIONS,
    BudgetDecision,
    BudgetTrade,
    budget_snapshot,
    current_policy,
    evaluate_budget,
    policy_for_version,
)

engine = create_db_engine()
Base = declarative_base()
POLICY = current_policy()
ZERO = Decimal("0")


class RiskAccount(Base):
    __tablename__ = "trading_risk_account"
    scope = Column(String(180), primary_key=True)
    capital = Column(Numeric(20, 4), nullable=False, default=10000)
    peak = Column(Numeric(20, 4), nullable=False, default=10000)
    allocation_revision = Column(Integer, nullable=False, default=0, server_default=text("0"))
    paused = Column(Boolean, nullable=False, default=False)
    pause_reason = Column(Text, nullable=True)
    policy_version = Column(String(40), nullable=False, default=POLICY.version,
                            server_default=text("'two-bucket-v1'"))
    close_sequence = Column(Integer, nullable=False, default=0, server_default=text("0"))
    daily_stop_day = Column(String(10), nullable=True)
    daily_stop_reason = Column(String(80), nullable=True)


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
    closed_at = Column(String(40), nullable=True)
    close_sequence = Column(Integer, nullable=True)
    completion_day = Column(String(10), nullable=True)


class RiskSettings(Base):
    __tablename__ = "trading_risk_settings"
    user_id = Column(String(80), primary_key=True)
    costs = Column(JSON, nullable=True)


class RiskLiveEntryPolicy(Base):
    """An explicit research preference; absence always retains qualification."""

    __tablename__ = "trading_risk_live_entry_policy"
    user_id = Column(String(80), primary_key=True)
    research_required = Column(Boolean, nullable=False, default=True, server_default=true())
    revision = Column(Integer, nullable=False, default=0)
    updated_at = Column(String(40), nullable=False)
    reason = Column(Text, nullable=False)


class RiskCostSchedule(Base):
    """Each market keeps its own fees; the legacy default remains readable."""

    __tablename__ = "trading_risk_cost_schedule"
    user_id = Column(String(80), primary_key=True)
    exchange = Column(String(10), primary_key=True)
    costs = Column(JSON, nullable=False)


class RiskDayEquity(Base):
    """Immutable funded-equity baseline established under the account lock."""

    __tablename__ = "trading_risk_day_equity"
    scope = Column(String(180), primary_key=True)
    session_day = Column(String(10), primary_key=True)
    opening_equity = Column(Numeric(20, 4), nullable=False)


class RiskDayStop(Base):
    __tablename__ = "trading_risk_day_stop"
    scope = Column(String(180), primary_key=True)
    session_day = Column(String(10), primary_key=True)
    reason = Column(String(80), nullable=False)
    at = Column(String(40), nullable=False)


class RiskReview(Base):
    __tablename__ = "trading_risk_review"
    id = Column(Integer, primary_key=True)
    scope = Column(String(180), nullable=False, index=True)
    at = Column(String(40), nullable=False)
    reason = Column(Text, nullable=False)
    details = Column(JSON, nullable=False)


def init_db():
    Base.metadata.create_all(engine)
    ensure_allocation_revision(engine)
    ensure_policy_columns(engine)


def ensure_policy_columns(target_engine):
    """Preserve existing accounts as legacy and leave unknown close times unknown."""
    additions = {
        "trading_risk_account": {
            "policy_version": "VARCHAR(40) NOT NULL DEFAULT 'two-bucket-v1'",
            "close_sequence": "INTEGER NOT NULL DEFAULT 0",
            "daily_stop_day": "VARCHAR(10)",
            "daily_stop_reason": "VARCHAR(80)",
        },
        "trading_risk_trade": {
            "closed_at": "VARCHAR(40)",
            "close_sequence": "INTEGER",
            "completion_day": "VARCHAR(10)",
        },
    }
    inspector = inspect(target_engine)
    for table, columns in additions.items():
        if not inspector.has_table(table):
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        for name, definition in columns.items():
            if name not in present:
                with target_engine.begin() as db:
                    db.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def allocation_revision_missing(target_engine):
    """Inspect without changing an existing risk account table."""
    inspector = inspect(target_engine)
    return inspector.has_table("trading_risk_account") and "allocation_revision" not in {
        column["name"] for column in inspector.get_columns("trading_risk_account")
    }


def ensure_allocation_revision(target_engine):
    """Add the durable revision to preexisting accounts without changing their facts."""
    if allocation_revision_missing(target_engine):
        with target_engine.begin() as db:
            db.exec_driver_sql(
                "ALTER TABLE trading_risk_account ADD COLUMN allocation_revision INTEGER NOT NULL DEFAULT 0"
            )


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
                    scope=scope, capital=POLICY.capital, peak=POLICY.capital, paused=False,
                    policy_version=POLICY.version,
                )
                db.add(account)
                db.flush()
            yield db, account
            db.commit()
        except BaseException:
            db.rollback()
            raise


def _policy(account):
    return policy_for_version(account.policy_version, account.capital)


def _day_start_equity(db, account, day, equity, rows):
    baseline = db.get(RiskDayEquity, (account.scope, day))
    if baseline is None:
        # Reconstruct only the first observation of a day. Existing daily marks
        # and completed P&L do not fund a larger allowance; older P&L does.
        today_net = sum((row.net_pnl for row in rows if row.status != "void" and (
            row.status == "closed" and (row.completion_day or row.session_day) == day
            or row.status in {"pending", "open"} and row.session_day == day
        )), ZERO)
        baseline = RiskDayEquity(scope=account.scope, session_day=day,
                                opening_equity=equity - today_net)
        db.add(baseline)
        db.flush()
    return baseline.opening_equity


def _snapshot(db, account, day):
    policy = _policy(account)
    relevant = or_(RiskTrade.session_day == day,
                   RiskTrade.status.in_(["pending", "open"]))
    if policy.version in SHARED_POLICY_VERSIONS:
        relevant = or_(relevant, RiskTrade.completion_day == day,
                       and_(RiskTrade.status == "closed", RiskTrade.filled.is_(True),
                            RiskTrade.completion_day.is_(None)))
    rows = list(
        db.scalars(
            select(RiskTrade).where(
                RiskTrade.scope == account.scope,
                relevant,
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
        BudgetTrade(r.ref, r.session_day, r.bucket, r.status, r.planned_risk, r.net_pnl,
                    r.filled, r.close_sequence, r.completion_day)
        for r in rows
    ]
    day_start_equity = _day_start_equity(db, account, day, equity, rows)
    day_stop = db.get(RiskDayStop, (account.scope, day))
    result = budget_snapshot(policy, trades, day, equity, account.peak, account.paused,
                             daily_stopped=day_stop is not None or account.daily_stop_day == day,
                             day_start_equity=day_start_equity)
    if result.get("daily_stopped") and day_stop is None:
        day_stop = RiskDayStop(scope=account.scope, session_day=day,
                               reason=result["daily_stop_reason"] or account.daily_stop_reason,
                               at=datetime.now(UTC).isoformat())
        db.add(day_stop)
    if day_stop is not None:
        result["daily_stopped"] = True
        result["daily_stop_reason"] = day_stop.reason
        if account.daily_stop_day is None or day >= account.daily_stop_day:
            account.daily_stop_day = day
            account.daily_stop_reason = day_stop.reason
    result["capital"] = account.capital
    result["policy_version"] = account.policy_version
    result["allocation_revision"] = account.allocation_revision
    if result["paused"] and not account.paused:
        account.paused = True
        account.pause_reason = f"Portfolio drawdown reached {policy.drawdown_pct * 100:.0f}% of peak net equity"
    result["pause_reason"] = account.pause_reason
    return result, trades, rows


def status(user, mode, day):
    with _account(user, mode) as (db, account):
        return _snapshot(db, account, day)[0]


def budget_state(user, mode, day):
    """Return the same durable equity, peak and bucket ledger used by admission."""
    ensure_current_policy(user, mode, day)
    with _account(user, mode) as (db, account):
        snapshot, trades, _ = _snapshot(db, account, day)
        return snapshot, trades


def ensure_current_policy(user, mode, day):
    """Upgrade only idle accounts with complete immutable close evidence."""
    if POLICY.version not in SHARED_POLICY_VERSIONS:
        return
    with _account(user, mode) as (db, account):
        if account.policy_version == POLICY.version:
            return
        previous_versions = {"two-bucket-v1", "shared-300-3r-v1"}
        if POLICY.version == FIXED_POLICY_VERSION:
            previous_versions.add(EQUITY_POLICY_VERSION)
        if account.policy_version not in previous_versions:
            raise ValueError("Unknown risk policy version or unsupported policy downgrade")
        if db.scalar(select(RiskTrade.ref).where(
            RiskTrade.scope == account.scope,
            RiskTrade.status.in_(["pending", "open"]),
        )) is not None:
            raise ValueError("Unresolved legacy exposure requires reconciliation")
        if db.scalar(select(RiskTrade.ref).where(
            RiskTrade.scope == account.scope,
            RiskTrade.status == "closed",
            RiskTrade.filled.is_(True),
            or_(RiskTrade.close_sequence.is_(None), RiskTrade.completion_day.is_(None)),
        )) is not None:
            raise ValueError("Legacy close order or completion day is unavailable")
        # Establish the allowance from original funding before switching math;
        # migration changes neither capital nor any trade/history evidence.
        _snapshot(db, account, day)
        old_version = account.policy_version
        account.policy_version = POLICY.version
        db.add(RiskReview(scope=account.scope, at=datetime.now(UTC).isoformat(),
                          reason="Updated managed trading risk policy",
                          details={"action": "policy_transition", "old_policy": old_version,
                                   "new_policy": POLICY.version}))


def review_allocation(user, mode, capital, reason, day):
    """Record an explicit funded-capital change with no outstanding exposure."""
    try:
        amount = Decimal(str(capital)) if not isinstance(capital, bool) else Decimal("NaN")
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Choose a supported capital allocation") from exc
    supported = {Decimal("10000"), Decimal("25000")}
    if mode == "sandbox":
        supported.add(Decimal("50000"))
    if mode not in {"sandbox", "live"} or amount not in supported:
        raise ValueError("Choose ₹10,000 or ₹25,000; sandbox also supports ₹50,000")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 1000:
        raise ValueError("Record an allocation review reason between 3 and 1000 characters")
    with _account(user, mode) as (db, account):
        if db.scalar(select(RiskTrade.ref).where(
            RiskTrade.scope == account.scope, RiskTrade.status.in_(["pending", "open"])
        )) is not None:
            raise ValueError("Reconcile all open or pending risk trades before changing allocation")
        old = Decimal(account.capital)
        if old == amount:
            return _snapshot(db, account, day)[0]
        # A same-session funding change must not create a larger daily budget,
        # including when allocation review is the first action after restart.
        _snapshot(db, account, day)
        prior_peak = Decimal(account.peak)
        delta = amount - old
        account.capital = amount
        account.allocation_revision = int(account.allocation_revision or 0) + 1
        # New funding changes net equity; preserve the accumulated peak/equity
        # gap, pause state and every historical daily loss record.
        account.peak = prior_peak + delta
        db.add(RiskReview(scope=account.scope, at=datetime.now(UTC).isoformat(),
                          reason=reason.strip(),
                          details={"action": "allocation_review", "old_capital": str(old),
                                   "new_capital": str(amount), "old_peak": str(prior_peak),
                                   "new_peak": str(account.peak)}))
        return _snapshot(db, account, day)[0]


def reserve(
    user, mode, ref, day, risk, premium, segment, broker, strategy_id, details, *, broker_cash=None,
    gross_risk=None,
):
    if not ref or len(ref) > 64 or segment not in {"index", "mcx"}:
        raise ValueError("A position reference and supported options segment are required")
    if not premium.is_finite() or premium <= 0:
        raise ValueError("A finite positive entry premium is required")
    with _account(user, mode) as (db, account):
        try:
            metrics, trades, rows = _snapshot(db, account, day)
        except ValueError:
            return BudgetDecision(False, "risk_evidence_missing", "shared", ZERO)
        if details.get("policy_version") and details["policy_version"] != account.policy_version:
            return BudgetDecision(False, "policy_version_mismatch", "shared", ZERO, metrics)
        decision = evaluate_budget(
            _policy(account), trades, day, metrics["equity"], account.peak, risk, account.paused,
            proposed_gross_risk=gross_risk, daily_stopped=metrics.get("daily_stopped", False),
            day_start_equity=metrics["day_start_equity"],
        )
        if db.get(RiskTrade, (account.scope, ref)) is not None:
            return BudgetDecision(
                False, "duplicate_trade", decision.bucket, decision.available, metrics
            )
        if not decision.allowed:
            return decision
        held = [r for r in rows if r.status in {"pending", "open"}]
        if len(held) >= _policy(account).max_positions or any(r.segment == segment for r in held):
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
                closed_at=None,
                close_sequence=None,
                completion_day=None,
            )
        )
        return decision


def update_trade(user, mode, ref, *, status, net_pnl, filled, evidence, expected=None,
                 completed_at=None):
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
        if status == "closed" and not (filled or row.filled):
            raise ValueError("An unfilled reservation cannot be closed")
        if row.status == "closed" and status != "closed":
            raise ValueError("A completed trade cannot be reopened")
        previous_evidence = {key: value for key, value in (row.evidence or {}).items()
                             if key != "_ledger_revision"}
        if (row.status == status and row.net_pnl == net_pnl and row.filled == (filled or row.filled)
                and previous_evidence == evidence):
            return True
        from services.strategy_module import session

        at = completed_at if completed_at is not None else datetime.now(UTC)
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("A timezone-aware completion instant is required")
        observed_day = session.session_day(at.astimezone(session.IST)).isoformat()
        event_day = row.completion_day if row.status == "closed" else observed_day
        # Capture carry-position equity before applying this session's first mark
        # or close. Otherwise an overnight win could raise the opening allowance.
        _snapshot(db, account, event_day)
        if status == "closed" and row.status != "closed":
            account.close_sequence = int(account.close_sequence or 0) + 1
            row.close_sequence = account.close_sequence
            row.closed_at = at.astimezone(UTC).isoformat()
            row.completion_day = observed_day
        row.status, row.net_pnl, row.filled = status, net_pnl, filled or row.filled
        row.evidence = {
            **evidence,
            "_ledger_revision": int((row.evidence or {}).get("_ledger_revision", 0)) + 1,
        }
        db.flush()
        _snapshot(db, account, event_day if account.policy_version in SHARED_POLICY_VERSIONS
                  else row.session_day)
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


def get_costs(user, exchange=None):
    with Session(engine) as db:
        if exchange:
            scoped = db.get(RiskCostSchedule, (str(user), str(exchange).upper()))
            if scoped is not None:
                return dict(scoped.costs)
        # Preserve old unscoped schedules and the explicit mismatch refusal.
        # Never relabel fees from another exchange to make admission pass.
        row = db.get(RiskSettings, str(user))
        return dict(row.costs) if row and row.costs is not None else None


def get_cost_schedules(user):
    with Session(engine) as db:
        settings = db.get(RiskSettings, str(user))
        legacy = settings.costs if settings else None
        schedules = {legacy["exchange"]: dict(legacy)} if legacy and legacy.get("exchange") else {}
        for row in db.scalars(select(RiskCostSchedule).where(RiskCostSchedule.user_id == str(user))):
            schedules[row.exchange] = dict(row.costs)
        return schedules


def set_costs(user, costs):
    with Session(engine) as db, db.begin():
        row = db.get(RiskSettings, str(user))
        exchange = costs.get("exchange")
        if exchange:
            scoped = db.get(RiskCostSchedule, (str(user), exchange))
            if scoped is None:
                db.add(RiskCostSchedule(user_id=str(user), exchange=exchange, costs=dict(costs)))
            else:
                scoped.costs = dict(costs)
        if row is None:
            db.add(RiskSettings(user_id=str(user), costs=dict(costs)))
        elif not row.costs or not exchange or row.costs.get("exchange") == exchange:
            row.costs = dict(costs)


def policy_payload():
    return {
        key: float(value) if isinstance(value, Decimal) else value
        for key, value in asdict(POLICY).items()
    }


def _live_entry_policy_payload(row):
    return {
        "research_required": row.research_required if row is not None else True,
        "revision": row.revision if row is not None else 0,
        "updated_at": row.updated_at if row is not None else None,
        "reason": row.reason if row is not None else None,
    }


def get_live_entry_policy(user):
    """Read without mutation. Storage errors propagate and never waive checks."""
    _scope(user, "live")
    with Session(engine) as db:
        return _live_entry_policy_payload(db.get(RiskLiveEntryPolicy, str(user)))


def review_live_entry_policy(user, research_required, expected_revision, reason):
    """Caller holds the admission/control lease; live exposure must stay flat."""
    if type(research_required) is not bool or type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("Choose a research requirement and refresh its current settings")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 1000:
        raise ValueError("Record a review reason between 3 and 1000 characters")
    with _account(user, "live") as (db, account):
        row = db.get(RiskLiveEntryPolicy, str(user))
        current = _live_entry_policy_payload(row)
        if current["revision"] != expected_revision:
            raise ValueError("Live entry settings changed. Refresh and review them again")
        if db.scalar(select(RiskTrade.ref).where(
            RiskTrade.scope == account.scope, RiskTrade.status.in_(["pending", "open"])
        ).limit(1)):
            raise ValueError("Close and reconcile live positions before changing entry requirements")
        if current["research_required"] == research_required:
            return current
        now = datetime.now(UTC).isoformat()
        if row is None:
            row = RiskLiveEntryPolicy(user_id=str(user))
            db.add(row)
        row.research_required = research_required
        row.revision = current["revision"] + 1
        row.updated_at = now
        row.reason = reason.strip()
        db.add(RiskReview(scope=account.scope, at=now, reason=row.reason, details={
            "action": "live_entry_policy", "research_required": research_required,
            "previous_research_required": current["research_required"], "revision": row.revision,
        }))
        return _live_entry_policy_payload(row)
