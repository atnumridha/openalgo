"""Explicit live grants, bound to the current locally stored broker session.

One row per owner is authoritative; audit events are never an approval source.
All connections are context-managed and SQLite uses the shared NullPool factory.
"""

import hashlib
import hmac
import json
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Boolean, Column, MetaData, String, Table, inspect, select, text

from database.engine_factory import create_db_engine

engine = create_db_engine()
metadata = MetaData()
authorizations = Table(
    "live_session_authorization", metadata,
    Column("user_id", String(255), primary_key=True),
    Column("active", Boolean, nullable=False),
    Column("session_day", String(10), nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("binding_digest", String(64), nullable=False),
)


def init_db():
    # Empty by design: previous audit-event grants cannot be adopted safely.
    metadata.create_all(engine)


def _current_binding(connection, user_id):
    """HMAC stable plaintext identity, never Fernet's randomized ciphertext.

    The Auth table is the broker-session authority. Read it directly, bypassing
    token caches and their identity maps. Account pins are included on schemas
    supporting broker_connections; legacy single-broker schemas use Auth alone.
    Nothing sensitive leaves this function except a keyed, irreversible digest.
    """
    from database import auth_db

    row = connection.execute(
        select(
            auth_db.Auth.broker, auth_db.Auth.user_id, auth_db.Auth.auth,
            auth_db.Auth.feed_token, auth_db.Auth.is_revoked,
        ).where(auth_db.Auth.name == user_id)
    ).mappings().first()
    if (
        not row or row["is_revoked"] or not str(row["broker"] or "").strip()
        or not isinstance(row["user_id"], str) or not row["user_id"].strip()
    ):
        return None
    token = auth_db.decrypt_token(row["auth"])
    feed_token = auth_db.decrypt_token(row["feed_token"]) if row["feed_token"] else ""
    if not token or feed_token is None:
        return None
    broker = str(row["broker"]).strip().lower()
    if broker == "kotak":
        from utils.config import get_broker_api_key

        if row["user_id"] != get_broker_api_key():
            return None
    pin = None
    inspector = inspect(connection)
    if inspector.has_table("api_keys") and "broker_connection_id" in {
        column["name"] for column in inspector.get_columns("api_keys")
    }:
        pins = connection.execute(text(
            "SELECT bc.id, bc.broker FROM api_keys ak JOIN broker_connections bc "
            "ON bc.id=ak.broker_connection_id AND bc.user_id=ak.user_id "
            "WHERE ak.user_id=:owner AND bc.status IN ('connected','authenticated') "
            "AND bc.is_revoked=0 LIMIT 2"
        ), {"owner": user_id}).mappings().all()
        if len(pins) != 1 or str(pins[0]["broker"]).strip().lower() != broker:
            return None
        pin = str(pins[0]["id"])
    payload = json.dumps(
        [user_id, broker, row["user_id"], token, feed_token, pin],
        separators=(",", ":"), ensure_ascii=True,
    ).encode()
    return hmac.new(auth_db.PEPPER.encode(), payload, hashlib.sha256).hexdigest()


@contextmanager
def _write():
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.execute(text("BEGIN IMMEDIATE"))
        yield connection


def _row(connection, user_id, *, for_update=False):
    query = select(authorizations).where(authorizations.c.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    row = connection.execute(query).mappings().first()
    return dict(row) if row else None


def read(user_id):
    """Return one durable grant and a fresh binding, without any writes."""
    with engine.connect() as connection:
        row = _row(connection, user_id)
        binding = _current_binding(connection, user_id) if row and row["active"] else None
        return row, binding


def grant(user_id, session_day, expires_at, now, *, discard_previous=False):
    """Commit before acknowledging permission; preserve a still-valid grant."""
    with _write() as connection:
        previous = _row(connection, user_id, for_update=True)
        binding = _current_binding(connection, user_id)
        if not binding:
            raise ValueError("An authenticated broker account is required")
        if discard_previous:
            # A failed revocation leaves its outcome uncertain. Recovery must
            # invalidate every prior grant before acknowledging a new one.
            connection.execute(authorizations.update().values(active=False))
        if (
            not discard_previous and previous and previous["active"]
            and previous["session_day"] == session_day
            and previous["binding_digest"] == binding
            and datetime.fromisoformat(previous["expires_at"]) > now
        ):
            return previous, previous, False
        current = {
            "user_id": user_id, "active": True, "session_day": session_day,
            "expires_at": expires_at, "binding_digest": binding,
        }
        if previous:
            connection.execute(authorizations.update().where(
                authorizations.c.user_id == user_id
            ).values(**current))
        else:
            connection.execute(authorizations.insert().values(**current))
        return previous, current, True


def revoke(user_id, *, expected=None):
    """Persist revocation, optionally only for the exact observed grant."""
    with _write() as connection:
        previous = _row(connection, user_id, for_update=True)
        if not previous or not previous["active"]:
            return None
        if expected is not None and previous != expected:
            return None
        connection.execute(authorizations.update().where(
            authorizations.c.user_id == user_id
        ).values(active=False))
        return previous
