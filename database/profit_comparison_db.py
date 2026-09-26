"""Durable, isolated sandbox comparison rows.

The comparison table carries shadow observations only. It has no order or
broker reference, and shares OpenAlgo's configured NullPool engine without
creating a new long-lived session per market tick.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sqlalchemy import JSON, Column, DateTime, Integer, String, UniqueConstraint, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

from database.strategy_module_db import engine
from services.strategy_module.profit_comparison import observe_comparison

Base = declarative_base()
Session = sessionmaker(bind=engine, expire_on_commit=False)


class Comparison(Base):
    __tablename__ = "sm_profit_comparison"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, nullable=False, index=True)
    position_ref = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    __table_args__ = (UniqueConstraint("run_id", "position_ref", name="uq_sm_comparison_entry"),)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def load_comparison(run_id: int, position_ref: str) -> dict | None:
    with Session() as session:
        row = (
            session.query(Comparison)
            .filter_by(
                run_id=run_id,
                position_ref=position_ref,
            )
            .one_or_none()
        )
        return deepcopy(row.snapshot) if row is not None else None


def list_for_runs(run_ids: list[int], limit: int = 100) -> list[dict]:
    """Read-only bounded snapshots for runs already owner-scoped by the caller."""
    if not run_ids:
        return []
    with Session() as session:
        rows = (
            session.query(Comparison)
            .filter(Comparison.run_id.in_(run_ids))
            .order_by(Comparison.id.desc())
            .limit(min(max(int(limit), 1), 500))
            .all()
        )
        return [deepcopy(row.snapshot) for row in rows]


def list_pending(now: datetime, limit: int = 500) -> list[dict]:
    """Bounded prospective shadows; no old session is polled forever."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff = now.astimezone(UTC)
    with Session() as session:
        rows = (
            session.query(Comparison)
            .filter(Comparison.created_at >= (cutoff - timedelta(days=2)).replace(tzinfo=None))
            .order_by(Comparison.id.desc())
            .limit(max(1, min(limit, 2000)) + 1)
            .all()
        )
        if len(rows) > limit:
            raise RuntimeError("too many sandbox comparisons to scan safely")
        return [
            deepcopy(row.snapshot) for row in rows
            if datetime.fromisoformat(row.snapshot["cutoff_at"]) >= cutoff
            and any(
                profile["status"] not in {"closed", "trigger_only", "cutoff"}
                for profile in row.snapshot["profiles"].values()
            )
        ]


def list_created_between(start: datetime, end: datetime, limit: int = 5000) -> list[dict]:
    """Read all comparison entries from one completed platform session."""
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("session bounds must be ordered and timezone-aware")
    with Session() as session:
        rows = (
            session.query(Comparison)
            .filter(
                Comparison.created_at >= start.astimezone(UTC).replace(tzinfo=None),
                Comparison.created_at < end.astimezone(UTC).replace(tzinfo=None),
            )
            .order_by(Comparison.id)
            .limit(limit + 1)
            .all()
        )
        if len(rows) > limit:
            raise RuntimeError("session comparison count exceeds safe report limit")
        return [deepcopy(row.snapshot) for row in rows]


def finalize_due(now: datetime, limit: int = 500) -> int:
    """At cutoff, mark unresolved shadow exits unfilled without inventing a price."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    changed = 0
    with Session.begin() as session:
        rows = (
            session.query(Comparison)
            .filter(Comparison.created_at >= (now.astimezone(UTC) - timedelta(days=2)).replace(tzinfo=None))
            .order_by(Comparison.id.desc())
            .limit(max(1, min(limit, 2000)) + 1)
            .all()
        )
        if len(rows) > limit:
            raise RuntimeError("too many sandbox comparisons to finalize safely")
        for row in rows:
            snapshot = deepcopy(row.snapshot)
            if datetime.fromisoformat(snapshot["cutoff_at"]) > now.astimezone(UTC):
                continue
            unfinished = False
            for profile in snapshot["profiles"].values():
                if profile["status"] in {"closed", "trigger_only", "cutoff"}:
                    continue
                profile["status"] = "cutoff"
                profile["missed_fill"] = True
                profile["reason"] = profile["reason"] or "intraday_cutoff_without_executable_quote"
                profile["exit_fill_quality"] = "unfilled_at_cutoff"
                unfinished = True
            if unfinished:
                updated = session.execute(
                    update(Comparison)
                    .where(Comparison.id == row.id, Comparison.version == row.version)
                    .values(snapshot=snapshot, version=row.version + 1)
                )
                changed += int(updated.rowcount == 1)
    return changed


def _same_entry(existing: dict, proposed: dict) -> bool:
    return all(
        existing.get(field) == proposed.get(field)
        for field in (
            "broker_connection_id",
            "symbol",
            "exchange",
            "side",
            "entry_price",
            "quantity",
        )
    )


def create_if_absent(snapshot: dict) -> dict:
    """Idempotently attach a shadow entry to a confirmed sandbox position."""
    if snapshot.get("mode") != "sandbox":
        raise ValueError("only sandbox entries may have shadow comparisons")
    run_id = int(snapshot["run_id"])
    position_ref = str(snapshot["position_ref"])
    existing = load_comparison(run_id, position_ref)
    if existing is not None:
        if not _same_entry(existing, snapshot):
            raise ValueError("duplicate comparison identity disagrees with admitted entry")
        return existing
    try:
        with Session.begin() as session:
            session.add(
                Comparison(
                    run_id=run_id,
                    position_ref=position_ref,
                    snapshot=deepcopy(snapshot),
                )
            )
    except IntegrityError as exc:
        # Another worker inserted the same entry first; never overwrite its
        # already advancing floor or its frozen risk budget.
        existing = load_comparison(run_id, position_ref)
        if existing is not None:
            if not _same_entry(existing, snapshot):
                raise ValueError(
                    "duplicate comparison identity disagrees with admitted entry"
                ) from exc
            return existing
        raise
    return deepcopy(snapshot)


class _VersionConflict(Exception):
    pass


def observe(run_id: int, position_ref: str, **observation) -> dict:
    """Persist one ordered observation with an optimistic version check."""
    for attempt in range(4):
        try:
            with Session.begin() as session:
                row = (
                    session.query(Comparison)
                    .filter_by(
                        run_id=run_id,
                        position_ref=position_ref,
                    )
                    .one_or_none()
                )
                if row is None:
                    raise LookupError("sandbox comparison does not exist")
                snapshot = observe_comparison(deepcopy(row.snapshot), **observation)
                changed = session.execute(
                    update(Comparison)
                    .where(Comparison.id == row.id, Comparison.version == row.version)
                    .values(snapshot=snapshot, version=row.version + 1),
                )
                if changed.rowcount != 1:
                    raise _VersionConflict
            return snapshot
        except (_VersionConflict, OperationalError) as exc:
            if attempt == 3:
                raise RuntimeError("sandbox comparison was updated concurrently") from exc
    raise RuntimeError("unreachable")
