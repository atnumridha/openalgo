"""Durable account state, compare-and-swap writes and cross-process operation leases."""

import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Column, Float, Integer, String, Text, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase


def host_identity():
    # uuid.getnode() can silently return a new random value per Python process
    # on macOS. Use the OS host identity, and never guess when unavailable.
    try:
        if sys.platform == "darwin":
            import ctypes

            identity = ctypes.create_string_buffer(16)
            timeout = (ctypes.c_long * 2)(1, 0)
            gethostuuid = ctypes.CDLL(None).gethostuuid
            gethostuuid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            gethostuuid.restype = ctypes.c_int
            if gethostuuid(identity, timeout) != 0:
                return "unverified"
            value = identity.raw
        else:
            value = Path("/etc/machine-id").read_bytes().strip()
        if not value or not value.strip(b"\0"):
            return "unverified"
        return hashlib.sha256(value).hexdigest()[:12]
    except (OSError, AttributeError, ValueError):
        return "unverified"


_HOST = host_identity()


def abandoned_owner(owner):
    """Only reclaim a provably exited process on this host; never steal live work."""
    if os.name != "posix" or not isinstance(owner, str):
        return False
    match = re.fullmatch(r"([0-9a-f]{12}):([0-9a-f]+):([0-9a-f]{8,})", owner)
    if not match or match[1] != _HOST or int(match[2], 16) <= 0:
        return False
    try:
        os.kill(int(match[2], 16), 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "kotak_assistant_account"
    scope = Column(String(180), primary_key=True)
    body = Column(Text, nullable=False, default="{}")
    version = Column(Integer, nullable=False, default=0)
    owner = Column(String(32), nullable=True)
    lease_until = Column(Float, nullable=False, default=0)


class Store:
    def __init__(self, engine=None):
        if engine is None:
            from database.engine_factory import create_db_engine

            engine = create_db_engine()
        self.engine = engine
        Base.metadata.create_all(engine)

    def ensure(self, scope):
        try:
            with self.engine.begin() as c:
                if c.execute(select(Account.scope).where(Account.scope == scope)).first() is None:
                    c.execute(
                        Account.__table__.insert().values(
                            scope=scope, body="{}", version=0, lease_until=0
                        )
                    )
        except IntegrityError:
            pass

    def read(self, scope):
        self.ensure(scope)
        with self.engine.connect() as c:
            return json.loads(
                c.execute(select(Account.body).where(Account.scope == scope)).scalar_one()
            )

    def all(self):
        with self.engine.connect() as c:
            return [
                (r.scope, json.loads(r.body))
                for r in c.execute(select(Account.scope, Account.body))
            ]

    @contextmanager
    def lock(self, scope):
        self.ensure(scope)
        owner = f"{_HOST}:{os.getpid():x}:{uuid.uuid4().hex}"[:32]
        now = time.time()
        with self.engine.begin() as c:
            previous = c.execute(select(Account.owner).where(Account.scope == scope)).scalar_one()
            available = Account.lease_until < now
            if abandoned_owner(previous):
                # Compare the exact former owner again in the atomic claim;
                # another worker's newer lease must never be overwritten.
                available = or_(available, Account.owner == previous)
            ok = c.execute(
                update(Account)
                .where(Account.scope == scope, available)
                .values(owner=owner, lease_until=now + 300)
            ).rowcount
        if not ok:
            raise ValueError("Trade operation already in progress; wait for reconciliation")
        try:
            yield owner
        finally:
            with self.engine.begin() as c:
                c.execute(
                    update(Account)
                    .where(Account.scope == scope, Account.owner == owner)
                    .values(owner=None, lease_until=0)
                )

    def save(self, scope, body, owner):
        encoded = json.dumps(body, allow_nan=False, separators=(",", ":"))
        with self.engine.begin() as c:
            ok = c.execute(
                update(Account)
                .where(
                    Account.scope == scope,
                    Account.owner == owner,
                    Account.lease_until > time.time(),
                )
                .values(body=encoded, version=Account.version + 1)
            ).rowcount
        if not ok:
            raise ValueError("Operation lease lost; broker outcome requires reconciliation")
