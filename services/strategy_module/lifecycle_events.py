"""Best-effort delivery for material strategy lifecycle events.

The strategy audit trail and Socket.IO feed remain the source of truth. WhatsApp
is deliberately downstream of both: a missing paired device, executor issue,
or sender failure must never affect an order, protective exit, or stop.
"""

from __future__ import annotations

from typing import Any

from database import strategy_module_db as store
from services.strategy_module import broadcast
from services.whatsapp_alert_service import alert_executor, whatsapp_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)

# These are state changes an operator needs promptly. Placement detail is
# already delivered by the generic order alert, and high-frequency progress
# events stay in the Events tab and live feed only.
STRATEGY_MATERIAL_EVENT_KINDS = frozenset(
    {
        "run_started",
        "run_stopped",
        "live_authorization_required",
        "run_stop_failed",
        "portfolio_governor_rejected",
        "portfolio_governor_admitted",
        "leg_entry_rejected",
        "leg_exit_rejected",
        "order_ack_unrecorded",
        "exit_order_unrecorded",
        "overall_sl_hit",
        "overall_target_hit",
        "leg_sl_hit",
        "leg_target_hit",
        "daily_loss_limit",
        "daily_loss_lock",
        "webhook_locked",
        "kill_switch_engaged",
        "flip_outgoing_exit_rejected",
        "stale_feed_stop",
        "recovery_failed",
    }
)
AUTOMATION_EVENT_KINDS = frozenset(store.AUTOMATION_EVENT_KINDS)
AUTOMATION_MATERIAL_EVENT_KINDS = AUTOMATION_EVENT_KINDS

_AUDIT_FIELDS = frozenset({"run_id", "leg_id", "severity", "payload"})
_USER_AUDIT_FIELDS = frozenset({"severity", "payload"})


def record_and_notify(
    strategy_id: int,
    user_id: str,
    kind: str,
    message: str,
    **fields: Any,
) -> Any:
    """Record, stream, then asynchronously notify for an allowlisted event.

    Returns exactly the stored row (or ``None`` when it could not be written),
    regardless of broadcast or WhatsApp availability.
    """
    try:
        audit_fields = {key: value for key, value in fields.items() if key in _AUDIT_FIELDS}
        row = store.record_event(strategy_id, user_id, kind, message, **audit_fields)
    except Exception:
        logger.exception("Could not record lifecycle event %s for strategy %s", kind, strategy_id)
        return None
    if row is None:
        return None

    try:
        event = store.event_to_dict(row)
    except Exception:
        logger.exception("Could not serialise lifecycle event %s for strategy %s", kind, strategy_id)
        event = {"strategy_id": strategy_id, "kind": kind, "message": message}

    try:
        broadcast.push_event(strategy_id, event)
    except Exception:
        logger.exception("Could not broadcast lifecycle event %s for strategy %s", kind, strategy_id)

    if kind not in STRATEGY_MATERIAL_EVENT_KINDS:
        return row

    try:
        notification = dict(event)
        notification["strategy_id"] = strategy_id
        notification["user_id"] = user_id
        if fields.get("mode"):
            notification["mode"] = str(fields["mode"])
        alert_executor.submit(
            whatsapp_alert_service.send_strategy_lifecycle_alert,
            user_id,
            notification,
        )
    except Exception:
        logger.exception("Could not queue WhatsApp lifecycle event %s for strategy %s", kind, strategy_id)
    return row


def record_user_and_notify(
    user_id: str,
    kind: str,
    message: str,
    **fields: Any,
) -> Any:
    """Record, stream, and alert an account event with no strategy owner.

    Authorization is user-scoped state and can precede every strategy row.
    Keeping a separate persistence seam avoids a sentinel strategy id and
    preserves the foreign-key meaning of ``sm_strategy_event``.
    """
    if kind not in AUTOMATION_EVENT_KINDS:
        logger.warning("Refusing strategy event kind %r on the account event stream", kind)
        return None
    try:
        audit_fields = {
            key: value for key, value in fields.items() if key in _USER_AUDIT_FIELDS
        }
        row = store.record_automation_event(user_id, kind, message, **audit_fields)
    except Exception:
        logger.exception("Could not record lifecycle event %s for user %s", kind, user_id)
        return None
    if row is None:
        return None

    try:
        event = store.automation_event_to_dict(row)
    except Exception:
        logger.exception("Could not serialise lifecycle event %s for user %s", kind, user_id)
        event = {"user_id": str(user_id), "kind": kind, "message": message}

    try:
        broadcast.push_user_event(user_id, event)
    except Exception:
        logger.exception("Could not broadcast lifecycle event %s for user %s", kind, user_id)

    if kind not in AUTOMATION_MATERIAL_EVENT_KINDS:
        return row

    try:
        notification = dict(event)
        notification["user_id"] = str(user_id)
        alert_executor.submit(
            whatsapp_alert_service.send_strategy_lifecycle_alert,
            str(user_id),
            notification,
        )
    except Exception:
        logger.exception("Could not queue WhatsApp lifecycle event %s for user %s", kind, user_id)
    return row
