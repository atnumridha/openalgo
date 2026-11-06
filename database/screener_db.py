"""Owner-scoped analytical screens and idempotent browser alert observations."""

from threading import RLock

from sqlalchemy import JSON, Column, Integer, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.db_sessions import register_scoped_session

engine = create_db_engine()
db_session = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))
Base = declarative_base()
register_scoped_session(__name__)
_write_lock = RLock()
MAX_SCREENS = 100
MAX_EVENTS = 1000


class NotFound(ValueError):
    pass


class Conflict(ValueError):
    pass


class Screen(Base):
    __tablename__ = "screener_screens"
    id = Column(Integer, primary_key=True)
    owner = Column(String(100), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    definition = Column(JSON, nullable=False)


class ScreenEvent(Base):
    __tablename__ = "screener_events"
    id = Column(Integer, primary_key=True)
    owner = Column(String(100), nullable=False, index=True)
    screen_id = Column(Integer, nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    mode = Column(String(12), nullable=False)
    symbol = Column(String(100), nullable=False)
    exchange = Column(String(20), nullable=False)
    closed_time = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "owner",
            "screen_id",
            "revision",
            "mode",
            "symbol",
            "exchange",
            "closed_time",
            name="uq_screener_event",
        ),
    )


def init_db():
    Base.metadata.create_all(engine)


def _serialize(row):
    return {"id": row.id, "name": row.name, "revision": row.revision, "definition": row.definition}


def _screen(owner, screen_id):
    row = db_session.query(Screen).filter_by(owner=owner, id=screen_id).first()
    if row is None:
        raise NotFound("Screen not found")
    return row


def list_screens(owner):
    try:
        return [
            _serialize(row)
            for row in db_session.query(Screen).filter_by(owner=owner).order_by(Screen.id).all()
        ]
    finally:
        db_session.remove()


def save_screen(owner, definition, screen_id=None, expected_revision=None):
    from services.screener import validate_definition

    definition = validate_definition(definition)
    with _write_lock:
        try:
            if screen_id is None:
                if db_session.query(Screen).filter_by(owner=owner).count() >= MAX_SCREENS:
                    raise Conflict("Maximum 100 saved screens reached")
                row = Screen(
                    owner=owner, name=definition["name"], definition=definition, revision=1
                )
                db_session.add(row)
                db_session.flush()
                result = _serialize(row)
            else:
                _screen(owner, screen_id)
                if type(expected_revision) is not int or expected_revision < 1:
                    raise ValueError("expected_revision is required")
                changed = (
                    db_session.query(Screen)
                    .filter_by(owner=owner, id=screen_id, revision=expected_revision)
                    .update(
                        {
                            "name": definition["name"],
                            "definition": definition,
                            "revision": expected_revision + 1,
                        },
                        synchronize_session=False,
                    )
                )
                if not changed:
                    raise Conflict("Screen changed; reload before saving")
                result = {
                    "id": screen_id,
                    "name": definition["name"],
                    "revision": expected_revision + 1,
                    "definition": definition,
                }
            db_session.commit()
            return result
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.remove()


def delete_screen(owner, screen_id):
    with _write_lock:
        try:
            row = _screen(owner, screen_id)
            db_session.query(ScreenEvent).filter_by(owner=owner, screen_id=screen_id).delete()
            db_session.delete(row)
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.remove()


def get_events(owner, screen_id):
    try:
        _screen(owner, screen_id)
        return [
            row.payload
            for row in db_session.query(ScreenEvent)
            .filter_by(owner=owner, screen_id=screen_id)
            .order_by(ScreenEvent.id.desc())
            .limit(MAX_EVENTS)
            .all()
        ]
    finally:
        db_session.remove()


def add_events(owner, screen_id, revision, mode, events):
    from services.screener import validate_events

    events = validate_events(events, mode)
    with _write_lock:
        try:
            row = _screen(owner, screen_id)
            if type(revision) is not int or row.revision != revision:
                raise Conflict("Screen revision changed; reset alert baseline")
            # Conditional write establishes SQLite's writer reservation before events
            # are inserted, so concurrent edits cannot race the revision check.
            if (
                not db_session.query(Screen)
                .filter_by(owner=owner, id=screen_id, revision=revision)
                .update({"revision": revision}, synchronize_session=False)
            ):
                raise Conflict("Screen revision changed")
            accepted = []
            for event in events:
                payload = {**event, "mode": mode, "revision": revision}
                candidate = ScreenEvent(
                    owner=owner,
                    screen_id=screen_id,
                    revision=revision,
                    mode=mode,
                    symbol=event["symbol"],
                    exchange=event["exchange"],
                    closed_time=event["time"],
                    payload=payload,
                )
                try:
                    with db_session.begin_nested():
                        db_session.add(candidate)
                        db_session.flush()
                    accepted.append(payload)
                except IntegrityError:
                    pass
            ids = [
                r.id
                for r in db_session.query(ScreenEvent.id)
                .filter_by(owner=owner, screen_id=screen_id)
                .order_by(ScreenEvent.id.desc())
                .offset(MAX_EVENTS)
                .all()
            ]
            if ids:
                db_session.query(ScreenEvent).filter(ScreenEvent.id.in_(ids)).delete(
                    synchronize_session=False
                )
            db_session.commit()
            return accepted
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.remove()
