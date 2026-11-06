"""Additive SQLite tables for the combined terminal; no legacy table changes."""
from sqlalchemy import Boolean, Column, Float, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Intent(Base):
    __tablename__='combined_terminal_intent'
    id=Column(String(128),primary_key=True)
    owner=Column(String(128),nullable=False,index=True)
    mode=Column(String(16),nullable=False)
    day=Column(String(10),nullable=False)
    connection_id=Column(String(128),nullable=False)
    reference=Column(Text,nullable=False)
    preview_id=Column(String(128),nullable=False)
    payload_hash=Column(String(128),nullable=False)
    state=Column(String(32),nullable=False)
    broker_order_id=Column(String(128))
    worker_trade_id=Column(String(128))
    filled=Column(Boolean,nullable=False,default=False)
    result=Column(Text)
    created=Column(Float,nullable=False)


class Observation(Base):
    __tablename__='combined_terminal_observation'
    connection_id=Column(String(128),primary_key=True)
    snapshot_id=Column(String(64),nullable=False)
    body=Column(Text,nullable=False)
    captured_at=Column(Float,nullable=False)


class Fill(Base):
    __tablename__='combined_terminal_fill'
    id=Column(Text,primary_key=True)
    owner=Column(String(128),nullable=False,index=True)
    mode=Column(String(16),nullable=False)
    day=Column(String(10),nullable=False)
    connection_id=Column(String(128),nullable=False)
    order_key=Column(Text,nullable=False)
    body=Column(Text,nullable=False)


class Day(Base):
    __tablename__='combined_terminal_day'
    id=Column(Text,primary_key=True)
    body=Column(Text,nullable=False)


class Selection(Base):
    __tablename__='combined_terminal_selection'
    id=Column(Text,primary_key=True)
    generation=Column(String(64),nullable=False)
    reference=Column(Text,nullable=False)


class Preview(Base):
    __tablename__='combined_terminal_preview'
    id=Column(String(64),primary_key=True)
    owner=Column(String(128),nullable=False,index=True)
    context_key=Column(Text,nullable=False)
    generation=Column(String(64),nullable=False)
    reference=Column(Text,nullable=False)
    payload=Column(Text,nullable=False)
    payload_hash=Column(String(64),nullable=False)
    worker_ticket=Column(String(128),nullable=False)
    snapshots=Column(Text,nullable=False)
    expires=Column(Float,nullable=False)
    used_by=Column(String(128))


class Preference(Base):
    __tablename__='combined_terminal_preference'
    id=Column(Text,primary_key=True)
    body=Column(Text,nullable=False)
