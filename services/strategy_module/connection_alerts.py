"""Durable WhatsApp transitions for active broker-pinned sandbox workflows."""

from __future__ import annotations

from sqlalchemy import text

from database import strategy_module_db as store
from utils.logging import get_logger

logger = get_logger(__name__)


def _active_connections() -> list[dict]:
    with store.engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT DISTINCT bc.id, bc.user_id, bc.broker, bc.status, bc.is_revoked "
            "FROM broker_connections bc JOIN flow_workflows fw "
            "ON fw.broker_connection_id = bc.id "
            "WHERE fw.is_active = 1 AND bc.broker = 'kotak'"
        )).mappings().all()
    return [dict(row) for row in rows]


def check_active_connections() -> int:
    """Alert on unavailable/recovered transitions, never on unchanged state."""
    emitted = 0
    try:
        for connection in _active_connections():
            user_id = connection["user_id"]
            connection_id = connection["id"]
            healthy = (
                connection["status"] in {"connected", "authenticated"}
                and not connection["is_revoked"]
            )
            emitted += int(
                store.record_broker_data_transition(
                    user_id, connection_id, healthy=healthy,
                    broker_status=connection["status"],
                )
            )
    except Exception:
        logger.exception("Could not check active strategy broker connections")
    finally:
        store.db_session.remove()
    return emitted
