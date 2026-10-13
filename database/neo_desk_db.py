"""Supplemental provider settings; native strategy tables own every order and fill."""

from sqlalchemy import JSON, Boolean, Column, Integer, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from database.engine_factory import create_db_engine

engine = create_db_engine()
db_session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()


class NeoDesk(Base):
    __tablename__ = "neo_desk"
    owner = Column(String(100), primary_key=True)
    profile = Column(String(40), nullable=False, default="orb_trail")
    activation = Column(String(20), nullable=False, default="Stopped")
    mode = Column(String(15), nullable=False, default="sandbox")
    pending = Column(Boolean, nullable=False, default=False)
    strategy_id = Column(Integer)
    run_id = Column(Integer)
    protection = Column(JSON, nullable=False, default=dict)
    status = Column(String(500), nullable=False, default="Entries stopped; no owned exposure.")
    settings = Column(JSON, nullable=False, default=dict)


class NeoClaim(Base):
    __tablename__ = "neo_signal_claim"
    __table_args__ = (UniqueConstraint("owner", "signal_key", name="uq_neo_signal"),)
    id = Column(Integer, primary_key=True)
    owner = Column(String(100), nullable=False)
    signal_key = Column(String(160), nullable=False)
    run_id = Column(Integer)
    setup = Column(JSON, nullable=False)


class NeoRunProtection(Base):
    """Original and ratcheted rules remain attached to the exact native run."""

    __tablename__ = "neo_run_protection"
    run_id = Column(Integer, primary_key=True)
    owner = Column(String(100), nullable=False, index=True)
    protection = Column(JSON, nullable=False)


def get_run_protection(owner, run_id):
    row = db_session.query(NeoRunProtection).filter_by(owner=owner, run_id=run_id).first()
    return dict(row.protection) if row else None


def save_run_protection(owner, run_id, protection):
    row = db_session.get(NeoRunProtection, run_id)
    if row and row.owner != owner:
        raise ValueError("Run protection belongs to a different owner.")
    if row:
        row.protection = dict(protection)
    else:
        db_session.add(NeoRunProtection(run_id=run_id, owner=owner, protection=dict(protection)))
    db_session.query(NeoDesk).filter_by(owner=owner, run_id=run_id).update(
        {"protection": dict(protection)}
    )
    db_session.commit()


def managed_run_ids(owner):
    from database.strategy_module_db import SmStrategyRun

    return [
        rid
        for (rid,) in db_session.query(NeoRunProtection.run_id)
        .join(SmStrategyRun, SmStrategyRun.id == NeoRunProtection.run_id)
        .filter(NeoRunProtection.owner == owner, SmStrategyRun.stopped_at.is_(None))
        .all()
    ]


def init_db():
    Base.metadata.create_all(engine)


def view(owner):
    row = db_session.get(NeoDesk, owner)
    if row is None:
        try:
            db_session.add(NeoDesk(owner=owner))
            db_session.commit()
        except IntegrityError:
            db_session.rollback()
        row = db_session.get(NeoDesk, owner)
    return {c.name: getattr(row, c.name) for c in NeoDesk.__table__.columns}


def configure(owner, **changes):
    view(owner)
    db_session.query(NeoDesk).filter_by(owner=owner).update(changes)
    db_session.commit()
    db_session.expire_all()
    return view(owner)


def claim(owner, key, setup, profile, mode):
    try:
        changed = (
            db_session.query(NeoDesk)
            .filter_by(
                owner=owner,
                profile=profile,
                mode=mode,
                activation="Active",
                pending=False,
                run_id=None,
            )
            .update({"pending": True})
        )
        if changed != 1:
            db_session.rollback()
            return False
        already = (
            db_session.query(NeoClaim.id)
            .filter(
                NeoClaim.owner == owner,
                NeoClaim.setup["execute_at"].as_string() == setup["execute_at"],
            )
            .first()
        )
        if already:
            db_session.rollback()
            return False
        db_session.add(NeoClaim(owner=owner, signal_key=key, setup=setup))
        db_session.commit()
        return True
    except IntegrityError:
        db_session.rollback()
        return False


def bind(owner, key, run_id, protection, error=None):
    db_session.query(NeoClaim).filter_by(owner=owner, signal_key=key).update({"run_id": run_id})
    db_session.query(NeoDesk).filter_by(owner=owner).update(
        {
            "run_id": run_id,
            "pending": False,
            "protection": protection,
            "status": error or "Native entry submitted; awaiting execution facts.",
        }
    )
    if run_id is not None:
        row = db_session.get(NeoRunProtection, run_id)
        if row and row.owner != owner:
            raise ValueError("Native run is already bound to another owner.")
        if row:
            row.protection = dict(protection)
        else:
            db_session.add(
                NeoRunProtection(run_id=run_id, owner=owner, protection=dict(protection))
            )
    db_session.commit()
