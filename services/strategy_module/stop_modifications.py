"""Durable, single-flight intent for modifying an existing protective order.

The order row always stores the last *verified* trigger. A pending intent is
never a fill, an exit owner or permission to resend after a restart. Keeping it
in a separate table also keeps broker-id routing unique to the actual order.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Session

from database import strategy_module_db as store
from utils.logging import get_logger

logger = get_logger(__name__)


class StopModification(store.Base):
    __tablename__ = "sm_protective_stop_modify"

    order_id = Column(
        Integer, ForeignKey("sm_strategy_order.id", ondelete="CASCADE"), primary_key=True
    )
    revision = Column(String(32), nullable=False)
    broker_order_id = Column(String(100), nullable=False)
    position_ref = Column(String(32), nullable=False)
    previous_trigger = Column(Numeric(18, 4), nullable=False)
    trigger_price = Column(Numeric(18, 4), nullable=False)
    quantity = Column(Integer, nullable=False)
    filled_qty = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)


def _ensure_table():
    # Additive and safe on an existing installation; no old order is rewritten.
    StopModification.__table__.create(store.engine, checkfirst=True)


def get(order_id):
    """Read the intent independently of the caller's ORM identity cache."""
    _ensure_table()
    with Session(store.engine) as session:
        row = session.get(StopModification, order_id)
        if row is None:
            return None
        return {
            column.name: getattr(row, column.name) for column in StopModification.__table__.columns
        }


def claim(stop, trigger):
    """Atomically claim one unchanged, working stop; commit before any I/O."""
    try:
        _ensure_table()
        with Session(store.engine) as session, session.begin():
            # This conditional write also serializes claim/verify against fill
            # updates on the real order, without holding the engine state lock.
            unchanged = (
                session.query(store.SmStrategyOrder)
                .filter(
                    store.SmStrategyOrder.id == stop["id"],
                    store.SmStrategyOrder.status == "open",
                    store.SmStrategyOrder.broker_order_id == stop["broker_order_id"],
                    store.SmStrategyOrder.position_ref == stop["position_ref"],
                    store.SmStrategyOrder.trigger_price == stop["trigger_price"],
                    store.SmStrategyOrder.qty == stop["qty"],
                    func.coalesce(store.SmStrategyOrder.filled_qty, 0)
                    == int(stop.get("filled_qty") or 0),
                )
                .update({"trigger_price": stop["trigger_price"]}, synchronize_session=False)
            )
            if unchanged != 1:
                return False
            values = {
                "revision": uuid.uuid4().hex,
                "broker_order_id": stop["broker_order_id"],
                "position_ref": stop["position_ref"],
                "previous_trigger": stop["trigger_price"],
                "trigger_price": trigger,
                "quantity": stop["qty"],
                "filled_qty": int(stop.get("filled_qty") or 0),
                "status": "pending",
            }
            row = session.get(StopModification, stop["id"])
            if row is None:
                session.add(StopModification(order_id=stop["id"], **values))
            elif row.status == "verified":
                for key, value in values.items():
                    setattr(row, key, value)
            else:
                return False
        return True
    except Exception:
        logger.exception("Could not persist stop modification for order %s", stop["id"])
        return False


def verify(intent):
    """Commit exact broker evidence only while its durable owner is unchanged."""
    try:
        with Session(store.engine) as session, session.begin():
            row = session.get(StopModification, intent["order_id"])
            if row is None or row.revision != intent["revision"] or row.status != "pending":
                return False
            changed = (
                session.query(store.SmStrategyOrder)
                .filter(
                    store.SmStrategyOrder.id == intent["order_id"],
                    store.SmStrategyOrder.status == "open",
                    store.SmStrategyOrder.broker_order_id == intent["broker_order_id"],
                    store.SmStrategyOrder.position_ref == intent["position_ref"],
                    store.SmStrategyOrder.trigger_price == intent["previous_trigger"],
                    store.SmStrategyOrder.qty == intent["quantity"],
                    func.coalesce(store.SmStrategyOrder.filled_qty, 0) == intent["filled_qty"],
                )
                .update({"trigger_price": intent["trigger_price"]}, synchronize_session=False)
            )
            if changed != 1:
                return False
            row.status = "verified"
        store.db_session.expire_all()
        return True
    except Exception:
        logger.exception(
            "Could not commit verified stop modification for order %s", intent["order_id"]
        )
        return False
