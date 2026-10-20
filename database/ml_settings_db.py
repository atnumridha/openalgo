"""ML Signals settings and the crypto fee profile, one row.

One row because there is one operator: the ML shortlist and schedule, how a
trade is sized and exited, and the fee profile every crypto net P&L is
computed with. Read through a short cache; every write invalidates it.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger
from utils.thread_safe_cache import MISSING, LockedTTLCache

logger = get_logger(__name__)

engine = create_db_engine()
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

_cache = LockedTTLCache(maxsize=1, ttl=60)

DEFAULT_SYMBOLS = ("BTCUSD", "ETHUSD", "SOLUSD")

#: Every setting, its default, and how a submitted value is checked.
DEFAULTS: dict[str, Any] = {
    "symbols": list(DEFAULT_SYMBOLS),
    "retrain_enabled": True,
    "retrain_hour_ist": 3,
    "retrain_minute_ist": 30,
    "risk_pct": 1.0,
    "max_leverage": 10,
    "sandbox_balance_usd": 1000.0,
    "smart_exit_enabled": True,
    "smart_exit_confirmations": 2,
    "max_hold_minutes": 28,
    "daily_loss_limit_pct": 3.0,
    "breakeven_buffer_pct": 0.05,
    "fee_gst_pct": 18.0,
    "fee_scalper_offer": True,
    "fee_scalper_minutes_major": 30.0,
    "fee_scalper_minutes_other": 15.0,
    "fee_diwali_offer": False,
    "fee_voucher_earned_month": 0.0,
    "fee_premium_cap_pct": 3.5,
}

_BOUNDS: dict[str, tuple[float, float]] = {
    "retrain_hour_ist": (0, 23),
    "retrain_minute_ist": (0, 59),
    "risk_pct": (0.05, 5.0),
    "max_leverage": (1, 100),
    "sandbox_balance_usd": (10.0, 10_000_000.0),
    "smart_exit_confirmations": (1, 5),
    "max_hold_minutes": (1, 240),
    "daily_loss_limit_pct": (0.1, 50.0),
    "breakeven_buffer_pct": (0.0, 1.0),
    "fee_gst_pct": (0.0, 50.0),
    "fee_scalper_minutes_major": (0.0, 240.0),
    "fee_scalper_minutes_other": (0.0, 240.0),
    "fee_voucher_earned_month": (0.0, 100.0),
    "fee_premium_cap_pct": (0.0, 100.0),
}


class MlSettings(Base):
    __tablename__ = "ml_settings"

    id = Column(Integer, primary_key=True, default=1)
    symbols = Column(Text, nullable=False, default=json.dumps(list(DEFAULT_SYMBOLS)))
    retrain_enabled = Column(Boolean, nullable=False, default=True)
    retrain_hour_ist = Column(Integer, nullable=False, default=3)
    retrain_minute_ist = Column(Integer, nullable=False, default=30)
    risk_pct = Column(Float, nullable=False, default=1.0)
    max_leverage = Column(Integer, nullable=False, default=10)
    sandbox_balance_usd = Column(Float, nullable=False, default=1000.0)
    smart_exit_enabled = Column(Boolean, nullable=False, default=True)
    smart_exit_confirmations = Column(Integer, nullable=False, default=2)
    max_hold_minutes = Column(Integer, nullable=False, default=28)
    daily_loss_limit_pct = Column(Float, nullable=False, default=3.0)
    breakeven_buffer_pct = Column(Float, nullable=False, default=0.05)
    fee_gst_pct = Column(Float, nullable=False, default=18.0)
    fee_scalper_offer = Column(Boolean, nullable=False, default=True)
    fee_scalper_minutes_major = Column(Float, nullable=False, default=30.0)
    fee_scalper_minutes_other = Column(Float, nullable=False, default=15.0)
    fee_diwali_offer = Column(Boolean, nullable=False, default=False)
    fee_voucher_earned_month = Column(Float, nullable=False, default=0.0)
    fee_premium_cap_pct = Column(Float, nullable=False, default=3.5)
    live_strategy_id = Column(Integer, nullable=True)
    sandbox_strategy_id = Column(Integer, nullable=True)
    webhook_tokens = Column(Text, nullable=True)
    last_retrain_status = Column(String(400), nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


def init_db() -> None:
    """Create the table and its one row."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "ML Settings DB", logger)
    try:
        if not MlSettings.query.get(1):
            db_session.add(MlSettings(id=1))
            db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception("ML Settings DB: could not create the default row")
    finally:
        db_session.remove()


def _row_dict(row: MlSettings | None) -> dict[str, Any]:
    values = dict(DEFAULTS)
    values.update(
        {
            "live_strategy_id": None,
            "sandbox_strategy_id": None,
            "last_retrain_status": None,
            "webhook_tokens": {},
        }
    )
    if row is None:
        return values
    for key in DEFAULTS:
        value = getattr(row, key, None)
        if value is None:
            continue
        values[key] = value
    try:
        symbols = json.loads(row.symbols) if row.symbols else list(DEFAULT_SYMBOLS)
        values["symbols"] = [str(s).upper() for s in symbols if str(s).strip()] or list(
            DEFAULT_SYMBOLS
        )
    except (TypeError, ValueError):
        values["symbols"] = list(DEFAULT_SYMBOLS)
    values["live_strategy_id"] = row.live_strategy_id
    values["sandbox_strategy_id"] = row.sandbox_strategy_id
    values["last_retrain_status"] = row.last_retrain_status
    try:
        tokens = json.loads(row.webhook_tokens) if row.webhook_tokens else {}
        values["webhook_tokens"] = tokens if isinstance(tokens, dict) else {}
    except (TypeError, ValueError):
        values["webhook_tokens"] = {}
    return values


def public_settings(values: dict[str, Any]) -> dict[str, Any]:
    """Settings as the browser may see them: no stored webhook tokens."""
    return {key: value for key, value in values.items() if key != "webhook_tokens"}


def get_settings() -> dict[str, Any]:
    """Every setting, defaults filled in. Never raises."""
    cached = _cache.get("settings", MISSING)
    if cached is not MISSING:
        return dict(cached)
    generation = _cache.generation
    try:
        values = _row_dict(MlSettings.query.get(1))
    except Exception:
        logger.exception("Could not read ML settings; using defaults")
        values = _row_dict(None)
    finally:
        db_session.remove()
    _cache.fill("settings", values, generation)
    return dict(values)


def validate(changes: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The accepted subset of ``changes`` and a sentence for each refused key."""
    accepted: dict[str, Any] = {}
    problems: list[str] = []
    for key, raw in changes.items():
        if key not in DEFAULTS:
            continue
        default = DEFAULTS[key]
        if key == "symbols":
            items = raw if isinstance(raw, list) else str(raw).split(",")
            symbols = []
            for item in items:
                text = str(item).strip().upper()
                if text and text.isalnum() and text not in symbols:
                    symbols.append(text)
            if not symbols:
                problems.append("Pick at least one symbol for ML signals.")
            elif len(symbols) > 10:
                problems.append("ML signals cover at most 10 symbols.")
            else:
                accepted[key] = symbols
            continue
        if isinstance(default, bool):
            accepted[key] = (
                bool(raw) if not isinstance(raw, str) else raw.lower() in ("1", "true", "on", "yes")
            )
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            problems.append(f"{key.replace('_', ' ')} must be a number.")
            continue
        low, high = _BOUNDS.get(key, (float("-inf"), float("inf")))
        if not low <= number <= high:
            problems.append(f"{key.replace('_', ' ')} must be between {low:g} and {high:g}.")
            continue
        accepted[key] = int(number) if isinstance(default, int) else number
    return accepted, problems


def update_settings(changes: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply the valid part of ``changes``. Returns the new settings and any refusals."""
    accepted, problems = validate(changes)
    if accepted:
        try:
            row = MlSettings.query.get(1)
            if row is None:
                row = MlSettings(id=1)
                db_session.add(row)
            for key, value in accepted.items():
                setattr(row, key, json.dumps(value) if key == "symbols" else value)
            db_session.commit()
        except Exception:
            db_session.rollback()
            logger.exception("Could not save ML settings")
            problems.append("The settings could not be saved. Details are in the error log.")
        finally:
            db_session.remove()
            _cache.clear()
    return get_settings(), problems


def set_internal(**values: Any) -> None:
    """Record bookkeeping the operator does not edit (strategy ids, retrain status)."""
    allowed = {"live_strategy_id", "sandbox_strategy_id", "last_retrain_status", "webhook_tokens"}
    try:
        row = MlSettings.query.get(1)
        if row is None:
            row = MlSettings(id=1)
            db_session.add(row)
        for key, value in values.items():
            if key not in allowed:
                continue
            if key == "webhook_tokens":
                value = json.dumps(value or {})
            elif key == "last_retrain_status" and value is not None:
                value = str(value)[:400]
            setattr(row, key, value)
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception("Could not record ML bookkeeping")
    finally:
        db_session.remove()
        _cache.clear()
