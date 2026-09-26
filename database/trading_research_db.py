"""Immutable research inputs, durable jobs and a single leased offline worker."""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    bindparam,
    case,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, defer, sessionmaker

from database.engine_factory import create_db_engine

Base = declarative_base()


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class ResearchDataset(Base):
    __tablename__ = "tr_dataset"
    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False)
    summary = Column(JSON, nullable=False)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (UniqueConstraint("owner", "content_hash"),)


class ResearchRun(Base):
    __tablename__ = "tr_run"
    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False, index=True)
    dataset_id = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False, default="development")
    candidate = Column(String(40), nullable=False)
    configuration = Column(JSON, nullable=False)
    configuration_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)
    parent_run_id = Column(Integer)
    worker_token = Column(String(64))
    cancel_requested = Column(Boolean, nullable=False, default=False)
    report = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    frozen_at = Column(DateTime)


class ResearchWorker(Base):
    __tablename__ = "tr_worker"
    id = Column(Integer, primary_key=True)
    token = Column(String(64), nullable=False)
    last_seen = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class ResearchSessionUse(Base):
    __tablename__ = "tr_session_use"
    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False)
    underlying = Column(String(200), nullable=False)
    session_day = Column(String(10), nullable=False)
    run_id = Column(Integer, nullable=False)
    role = Column(String(20), nullable=False)
    __table_args__ = (UniqueConstraint("owner", "underlying", "session_day"),)


def run_dict(row, include_report=True):
    if row is None:
        return None
    keys = (
        "id",
        "dataset_id",
        "kind",
        "candidate",
        "configuration",
        "configuration_hash",
        "status",
        "parent_run_id",
        "cancel_requested",
        "error",
        "created_at",
        "started_at",
        "finished_at",
        "frozen_at",
    )
    result = {key: getattr(row, key) for key in keys}
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            result[key] = value.isoformat() + "Z"
    if include_report:
        result["report"] = row.report
    return result


class ResearchStore:
    def __init__(self, database_url=None):
        self.engine = create_db_engine(database_url)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_db(self):
        Base.metadata.create_all(self.engine)

    def import_dataset(self, owner, data):
        summary = {
            key: data[key]
            for key in (
                "name",
                "provider",
                "content_hash",
                "row_count",
                "session_count",
                "start",
                "end",
                "quality",
            )
        }
        with self.sessions.begin() as session:
            existing = session.scalar(
                select(ResearchDataset).where(
                    ResearchDataset.owner == owner,
                    ResearchDataset.content_hash == data["content_hash"],
                )
            )
            if existing:
                return existing.summary | {
                    "id": existing.id,
                    "created_at": existing.created_at.isoformat() + "Z",
                }
            if (
                len(
                    session.scalars(
                        select(ResearchDataset.id).where(ResearchDataset.owner == owner).limit(101)
                    ).all()
                )
                >= 100
            ):
                raise ValueError(
                    "Dataset storage limit reached; archive the deployment before importing more data"
                )
            row = ResearchDataset(
                owner=owner, content_hash=data["content_hash"], summary=summary, content=data
            )
            session.add(row)
            session.flush()
            return summary | {"id": row.id, "created_at": row.created_at.isoformat() + "Z"}

    def get_dataset(self, owner, dataset_id):
        with self.sessions() as session:
            row = session.scalar(
                select(ResearchDataset).where(
                    ResearchDataset.id == dataset_id, ResearchDataset.owner == owner
                )
            )
            return (row.content | {"id": row.id}) if row else None

    def _capacity(self, session, owner):
        active = session.scalars(
            select(ResearchRun.id)
            .where(ResearchRun.owner == owner, ResearchRun.status.in_(["queued", "running"]))
            .limit(11)
        ).all()
        if len(active) >= 10:
            raise ValueError("At most ten research jobs can be queued or running")
        if (
            len(
                session.scalars(
                    select(ResearchRun.id).where(ResearchRun.owner == owner).limit(5001)
                ).all()
            )
            >= 5000
        ):
            raise ValueError("Research run storage limit reached")

    def queue_run(self, owner, dataset_id, configuration, configuration_hash, days, underlying):
        with self.sessions.begin() as session:
            self._capacity(session, owner)
            observed = session.scalars(
                select(ResearchSessionUse).where(
                    ResearchSessionUse.owner == owner,
                    ResearchSessionUse.underlying == underlying.upper(),
                    ResearchSessionUse.session_day.in_(days),
                )
            ).all()
            if any(item.role == "final" for item in observed):
                raise ValueError("Consumed final holdout sessions cannot be reused for development")
            used_days = {item.session_day for item in observed}
            row = ResearchRun(
                owner=owner,
                dataset_id=dataset_id,
                candidate=configuration["candidate"],
                configuration=configuration,
                configuration_hash=configuration_hash,
            )
            session.add(row)
            session.flush()
            for day in days:
                if day not in used_days:
                    session.add(
                        ResearchSessionUse(
                            owner=owner,
                            underlying=underlying.upper(),
                            session_day=day,
                            run_id=row.id,
                            role="development",
                        )
                    )
            session.flush()
            return run_dict(row)

    def get_run(self, owner, run_id):
        with self.sessions() as session:
            return run_dict(
                session.scalar(
                    select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner == owner)
                )
            )

    def overview(self, owner):
        with self.sessions() as session:
            datasets = session.scalars(
                select(ResearchDataset)
                .options(defer(ResearchDataset.content))
                .where(ResearchDataset.owner == owner)
                .order_by(ResearchDataset.id.desc())
                .limit(100)
            ).all()
            runs = session.scalars(
                select(ResearchRun)
                .options(defer(ResearchRun.report))
                .where(ResearchRun.owner == owner)
                .order_by(ResearchRun.id.desc())
                .limit(50)
            ).all()
            worker = session.get(ResearchWorker, 1)
            return {
                "datasets": [
                    row.summary | {"id": row.id, "created_at": row.created_at.isoformat() + "Z"}
                    for row in datasets
                ],
                "runs": [run_dict(row, False) for row in runs],
                "worker": {
                    "online": bool(worker and worker.expires_at > utcnow()),
                    "last_seen": worker.last_seen.isoformat() + "Z" if worker else None,
                },
            }

    def cancel_run(self, owner, run_id):
        with self.sessions.begin() as session:
            session.execute(
                update(ResearchRun)
                .where(
                    ResearchRun.id == run_id,
                    ResearchRun.owner == owner,
                    ResearchRun.status.in_(("queued", "running")),
                )
                .values(
                    cancel_requested=True,
                    status=case(
                        (ResearchRun.status == "queued", "cancelled"), else_=ResearchRun.status
                    ),
                    finished_at=case(
                        (ResearchRun.status == "queued", utcnow()), else_=ResearchRun.finished_at
                    ),
                )
            )
            row = session.scalar(
                select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner == owner)
            )
            if row is None:
                raise LookupError("Research run not found")
            return run_dict(row)

    def freeze_run(self, owner, run_id):
        with self.sessions.begin() as session:
            row = session.scalar(
                select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner == owner)
            )
            if row is None:
                raise LookupError("Research run not found")
            if row.status != "completed" or row.kind != "development":
                raise ValueError("Only a completed development version can be frozen")
            if row.report.get("incomplete_outcomes") or row.report.get("oos", {}).get(
                "incomplete_outcomes"
            ):
                raise ValueError("Resolve incomplete dataset outcomes before freezing a version")
            row.frozen_at = row.frozen_at or utcnow()
            return run_dict(row)

    def queue_final(self, owner, run_id, sessions, underlying):
        try:
            with self.sessions.begin() as session:
                parent = session.scalar(
                    select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner == owner)
                )
                if parent is None:
                    raise LookupError("Research run not found")
                if (
                    not parent.frozen_at
                    or parent.status != "completed"
                    or parent.kind != "development"
                ):
                    raise ValueError("A completed frozen development version is required")
                self._capacity(session, owner)
                row = ResearchRun(
                    owner=owner,
                    dataset_id=parent.dataset_id,
                    kind="final",
                    candidate=parent.candidate,
                    configuration=parent.configuration,
                    configuration_hash=parent.configuration_hash,
                    parent_run_id=parent.id,
                    frozen_at=parent.frozen_at,
                )
                session.add(row)
                session.flush()
                for day in sessions:
                    session.add(
                        ResearchSessionUse(
                            owner=owner,
                            underlying=underlying.upper(),
                            session_day=day,
                            run_id=row.id,
                            role="final",
                        )
                    )
                session.flush()
                return run_dict(row)
        except IntegrityError:
            raise ValueError(
                "Final holdout sessions were already exposed or consumed; cancellation or revised candidates cannot reuse them"
            ) from None

    def acquire_worker(self, token, now=None):
        now = now or utcnow()
        try:
            with self.sessions.begin() as session:
                row = session.get(ResearchWorker, 1)
                if row is None:
                    session.add(
                        ResearchWorker(
                            id=1,
                            token=token,
                            last_seen=now,
                            expires_at=now + timedelta(seconds=120),
                        )
                    )
                    session.flush()
                else:
                    changed = session.execute(
                        update(ResearchWorker)
                        .where(ResearchWorker.id == 1, ResearchWorker.expires_at <= now)
                        .values(token=token, last_seen=now, expires_at=now + timedelta(seconds=120))
                    ).rowcount
                    if not changed:
                        return False
                session.execute(
                    update(ResearchRun)
                    .where(ResearchRun.status == "running")
                    .values(
                        status="interrupted",
                        finished_at=now,
                        error="The research worker stopped before completing this run.",
                    )
                )
                return True
        except IntegrityError:
            return False

    def heartbeat(self, token, now=None):
        now = now or utcnow()
        with self.sessions.begin() as session:
            return bool(
                session.execute(
                    update(ResearchWorker)
                    .where(
                        ResearchWorker.id == 1,
                        ResearchWorker.token == token,
                        ResearchWorker.expires_at > now,
                    )
                    .values(last_seen=now, expires_at=now + timedelta(seconds=120))
                ).rowcount
            )

    def release_worker(self, token):
        with self.sessions.begin() as session:
            session.execute(
                update(ResearchWorker)
                .where(ResearchWorker.id == 1, ResearchWorker.token == token)
                .values(expires_at=utcnow())
            )

    def claim_job(self, token, now=None):
        now = now or utcnow()
        with self.sessions.begin() as session:
            lease = session.get(ResearchWorker, 1)
            if lease is None or lease.token != token or lease.expires_at <= now:
                return None
            row = session.scalar(
                select(ResearchRun)
                .where(ResearchRun.status == "queued")
                .order_by(ResearchRun.id)
                .limit(1)
            )
            if row is None:
                return None
            changed = session.execute(
                update(ResearchRun)
                .where(ResearchRun.id == row.id, ResearchRun.status == "queued")
                .values(status="running", worker_token=token, started_at=now)
            ).rowcount
            if not changed:
                return None
            session.refresh(row)
            return run_dict(row) | {"owner": row.owner}

    def check_job(self, token, owner, run_id):
        if not self.heartbeat(token):
            raise RuntimeError("Research worker lease expired")
        row = self.get_run(owner, run_id)
        return row is not None and row["status"] == "running" and not row["cancel_requested"]

    def finish_job(self, token, run_id, status, report=None, error=None):
        now = utcnow()
        live_lease = (
            select(ResearchWorker.id)
            .where(
                ResearchWorker.id == 1,
                ResearchWorker.token == token,
                ResearchWorker.expires_at > now,
            )
            .exists()
        )
        with self.sessions.begin() as session:
            # Both cancellation and finishing linearize at their UPDATE. Never
            # make this decision from an ORM row read before another commit.
            return bool(
                session.execute(
                    update(ResearchRun)
                    .where(
                        ResearchRun.id == run_id,
                        ResearchRun.status == "running",
                        ResearchRun.worker_token == token,
                        live_lease,
                    )
                    .values(
                        status=case(
                            (ResearchRun.cancel_requested.is_(True), "cancelled"), else_=status
                        ),
                        report=case(
                            (ResearchRun.cancel_requested.is_(True), None),
                            else_=bindparam(
                                "completed_report",
                                value=report if status == "completed" else None,
                                type_=JSON,
                            ),
                        ),
                        error=case((ResearchRun.cancel_requested.is_(True), None), else_=error),
                        finished_at=now,
                    )
                    .execution_options(synchronize_session=False)
                ).rowcount
            )


_default_store = None


def get_store():
    global _default_store
    if _default_store is None:
        _default_store = ResearchStore()
    return _default_store


def init_db():
    get_store().init_db()
