"""Bounded, restart-safe delivery of critical strategy events to WhatsApp.

The outbox is written by the database audit seam, never by this worker. A
successful result means upstream accepted a send, not that a human read it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic

from database import strategy_module_db as store
from services.whatsapp_alert_service import whatsapp_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)
MAX_ATTEMPTS = 5
TTL_HOURS = 12
BATCH_SIZE = 20


def deliver(event: dict) -> bool:
    """Send one event with an explicit acceptance result (never fire-and-forget)."""
    return whatsapp_alert_service.send_critical_strategy_alert(event)


def process_due(
    *,
    now: datetime | None = None,
    user_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, int]:
    """Drain one bounded batch; scheduler provides the only recurring worker."""
    if clock is None:
        if now is None:

            def clock() -> datetime:
                return datetime.now(UTC).replace(tzinfo=None)
        else:
            started = monotonic()

            def clock() -> datetime:
                return now + timedelta(seconds=monotonic() - started)

    counts = {"accepted": 0, "retrying": 0, "failed": 0}
    try:
        for _ in range(BATCH_SIZE):
            current = clock()
            due = store.claim_due_critical_alerts(
                current,
                limit=BATCH_SIZE,
                user_id=user_id,
                max_attempts=MAX_ATTEMPTS,
                max_claimed=1,
            )
            if not due:
                break
            alert = due[0]
            event = {
                "id": alert["source_id"],
                "strategy_id": alert["strategy_id"],
                "user_id": alert["user_id"],
                "kind": alert["kind"],
                "severity": alert["severity"],
                "message": alert["message"],
                "run_id": alert["run_id"],
                "ts": alert["event_ts"],
                "delayed": (
                    current
                    - datetime.fromisoformat(alert["event_ts"].replace("Z", "+00:00")).replace(
                        tzinfo=None
                    )
                ).total_seconds()
                >= 60,
            }
            try:
                accepted = bool(deliver(event))
            except Exception:
                logger.exception("Critical WhatsApp send failed for outbox %s", alert["id"])
                accepted = False
            finished_at = clock()
            outcome = store.finish_critical_alert(
                alert["id"],
                alert["attempts"],
                accepted=accepted,
                now=finished_at,
                max_attempts=MAX_ATTEMPTS,
            )
            if outcome in {"sent", "late"}:
                counts["accepted"] += 1
            elif outcome == "pending":
                counts["retrying"] += 1
            elif outcome == "failed":
                counts["failed"] += 1
        store.prune_terminal_critical_alerts(clock(), limit=BATCH_SIZE)
        return counts
    finally:
        # APScheduler jobs have no Flask teardown; the scoped connection must
        # not survive indefinitely on its reusable worker thread/greenlet.
        store.db_session.remove()
