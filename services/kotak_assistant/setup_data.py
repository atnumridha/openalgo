"""Calendar-aware inputs and atomic, bounded durable setup evidence. No broker writes."""

import json
import math
from datetime import datetime

from sqlalchemy import Column, Float, Integer, String, Text, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase

from .analysis import IST


def session_bars(rows, seconds, now, exchange, calendar=None):
    if calendar is None:
        from database.market_calendar_db import get_effective_session_window

        calendar = get_effective_session_window
    windows, result = {}, {}
    for row in rows:
        try:
            t = float(row.get('time', row.get('timestamp')))
            if t > 1e12:
                t /= 1000
            o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            if (
                not all(math.isfinite(v) for v in (t, o, h, low, c))
                or not 0 < low <= min(o, c) <= max(o, c) <= h
            ):
                continue
            if t + seconds > now:
                continue
            day = datetime.fromtimestamp(t, IST).date()
            if day not in windows:
                windows[day] = calendar(day, exchange)
            window = windows[day]
            if (
                not window
                or not window["start_ms"] / 1000 <= t < t + seconds <= window["end_ms"] / 1000
            ):
                continue
            result[t] = dict(row, time=t, open=o, high=h, low=low, close=c)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [result[t] for t in sorted(result)]


def continuity_gaps(rows, seconds):
    gaps = []
    for previous, current in zip(rows, rows[1:], strict=False):
        a, b = previous["time"], current["time"]
        if (
            datetime.fromtimestamp(a, IST).date() == datetime.fromtimestamp(b, IST).date()
            and b - a > seconds
        ):
            gaps.append({"after": a, "before": b, "missing": int((b - a) // seconds) - 1})
    return gaps


class Base(DeclarativeBase):
    pass


class SetupState(Base):
    __tablename__ = "kotak_chart_setup_state"
    scope = Column(String(220), primary_key=True)
    version = Column(Integer, nullable=False, default=0)
    body = Column(Text, nullable=False)
    updated = Column(Float, nullable=False)


class SetupEvent(Base):
    __tablename__ = "kotak_chart_setup_event"
    scope = Column(String(220), primary_key=True)
    event_id = Column(String(180), primary_key=True)
    time = Column(Float, nullable=False, index=True)
    body = Column(Text, nullable=False)


class SetupStore:
    """Uses the existing engine. Every connection closes, no extra pool or thread.

    CAS and event inserts share a transaction, so a restarted evaluator never
    consumes a crossing without saving its consumed-direction flag and evidence.
    Tape retention is 35 days, with an explicit per-request retrieval ceiling.
    """

    def __init__(self, engine):
        self.engine = engine
        Base.metadata.create_all(engine)

    def read(self, scope):
        with self.engine.connect() as c:
            row = c.execute(
                select(SetupState.body, SetupState.version).where(SetupState.scope == scope)
            ).first()
            return (json.loads(row.body), row.version) if row else ({}, 0)

    def scopes(self):
        with self.engine.connect() as c:
            return [
                (r.scope, json.loads(r.body))
                for r in c.execute(select(SetupState.scope, SetupState.body))
            ]

    def commit(self, scope, version, body, events):
        encoded = json.dumps(body, allow_nan=False, separators=(",", ":"))
        now = float(body.get("updated") or max((e["time"] for e in events), default=0))
        try:
            with self.engine.begin() as c:
                if version == 0:
                    c.execute(
                        SetupState.__table__.insert().values(
                            scope=scope, version=1, body=encoded, updated=now
                        )
                    )
                else:
                    ok = c.execute(
                        update(SetupState)
                        .where(SetupState.scope == scope, SetupState.version == version)
                        .values(version=version + 1, body=encoded, updated=now)
                    ).rowcount
                    if not ok:
                        return False
                # Batches are bounded by the input queue. Replayed duplicates
                # never add tape rows or create another trigger.
                unique = {str(e["id"]): e for e in events}
                ids = list(unique)
                known = set()
                for start in range(0, len(ids), 500):
                    known.update(
                        c.execute(
                            select(SetupEvent.event_id).where(
                                SetupEvent.scope == scope,
                                SetupEvent.event_id.in_(ids[start : start + 500]),
                            )
                        ).scalars()
                    )
                values = [
                    {
                        "scope": scope,
                        "event_id": key,
                        "time": float(e["time"]),
                        "body": json.dumps(e, allow_nan=False, separators=(",", ":")),
                    }
                    for key, e in unique.items()
                    if key not in known
                ]
                if values:
                    c.execute(SetupEvent.__table__.insert(), values)
                # Daily pruning, not a table scan for every price event.
                if body.get("prune_before"):
                    c.execute(
                        delete(SetupEvent).where(
                            SetupEvent.scope == scope, SetupEvent.time < body["prune_before"]
                        )
                    )
            return True
        except IntegrityError:
            return False

    def events(self, scope, start, end, limit=250001):
        with self.engine.connect() as c:
            rows = c.execute(
                select(SetupEvent.body)
                .where(SetupEvent.scope == scope, SetupEvent.time >= start, SetupEvent.time <= end)
                .order_by(SetupEvent.time, SetupEvent.event_id)
                .limit(limit)
            )
            return [json.loads(r.body) for r in rows]
