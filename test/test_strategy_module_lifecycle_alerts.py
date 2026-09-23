"""Material strategy events are audited, streamed, and best-effort alerted."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import restx_api  # noqa: F401
from services.strategy_module import lifecycle_events
from services.whatsapp_alert_service import WhatsAppAlertService


class _ImmediateExecutor:
    """Run submitted work now, so notification isolation is observable."""

    def submit(self, func, *args, **kwargs):
        return func(*args, **kwargs)


class _CapturingExecutor:
    """Records scheduling without running notification work on the caller."""

    def __init__(self):
        self.submissions = []

    def submit(self, func, *args, **kwargs):
        self.submissions.append((func, args, kwargs))


@pytest.mark.parametrize(
    "kind",
    [
        "run_started",
        "live_authorization_required",
        "portfolio_governor_rejected",
        "run_stopped",
        "overall_target_hit",
        "daily_loss_limit",
        "exit_order_unrecorded",
        "webhook_locked",
        "recovery_failed",
    ],
)
def test_material_lifecycle_events_enqueue_a_whatsapp_alert(kind):
    """Removing a material event from the allowlist must stop this alert."""
    row = SimpleNamespace(
        id=14,
        strategy_id=7,
        run_id=3,
        kind=kind,
        severity="critical" if kind in {"daily_loss_limit", "webhook_locked"} else "info",
        leg_id=None,
        message="Operator should see this lifecycle change",
        payload=None,
        ts=None,
    )
    event = {"id": 14, "strategy_id": 7, "kind": kind, "message": row.message}
    notifier = Mock()

    with (
        patch.object(lifecycle_events.store, "record_event", return_value=row),
        patch.object(lifecycle_events.store, "event_to_dict", return_value=event),
        patch.object(lifecycle_events.store, "get_strategy_unscoped", return_value=SimpleNamespace(name="Trend")),
        patch.object(lifecycle_events.store, "get_run", return_value=SimpleNamespace(mode="sandbox")),
        patch.object(lifecycle_events.broadcast, "push_event"),
        patch.object(lifecycle_events, "alert_executor", _ImmediateExecutor()),
        patch.object(lifecycle_events, "whatsapp_alert_service", notifier),
    ):
        assert lifecycle_events.record_and_notify(7, "owner", kind, row.message, run_id=3) is row

    notifier.send_strategy_lifecycle_alert.assert_called_once_with(
        "owner",
        {
            "id": 14,
            "strategy_id": 7,
            "kind": kind,
            "message": row.message,
            "user_id": "owner",
        },
    )


def test_a_routine_delta_is_audited_and_streamed_without_a_whatsapp_alert():
    """Treating high-frequency deltas as material would flood the paired device."""
    row = SimpleNamespace(id=15)
    event = {"id": 15, "strategy_id": 7, "kind": "pnl_delta", "message": "10.0"}
    notifier = Mock()

    with (
        patch.object(lifecycle_events.store, "record_event", return_value=row),
        patch.object(lifecycle_events.store, "event_to_dict", return_value=event),
        patch.object(lifecycle_events.broadcast, "push_event"),
        patch.object(lifecycle_events, "alert_executor", _ImmediateExecutor()),
        patch.object(lifecycle_events, "whatsapp_alert_service", notifier),
    ):
        assert lifecycle_events.record_and_notify(7, "owner", "pnl_delta", "10.0") is row

    notifier.send_strategy_lifecycle_alert.assert_not_called()


def test_recording_a_lifecycle_event_does_not_lookup_notification_context():
    """A slow strategy/run lookup must stay in the alert worker, not the order path."""
    row = SimpleNamespace(id=18)
    executor = _CapturingExecutor()
    event = {"id": 18, "strategy_id": 7, "kind": "run_started", "message": "Started"}

    with (
        patch.object(lifecycle_events.store, "record_event", return_value=row),
        patch.object(lifecycle_events.store, "event_to_dict", return_value=event),
        patch.object(lifecycle_events.store, "get_strategy_unscoped") as strategy_lookup,
        patch.object(lifecycle_events.store, "get_run") as run_lookup,
        patch.object(lifecycle_events.broadcast, "push_event"),
        patch.object(lifecycle_events, "alert_executor", executor),
    ):
        assert lifecycle_events.record_and_notify(7, "owner", "run_started", "Started", run_id=3) is row

    strategy_lookup.assert_not_called()
    run_lookup.assert_not_called()
    assert executor.submissions[0][1] == (
        "owner",
        {"id": 18, "strategy_id": 7, "kind": "run_started", "message": "Started", "user_id": "owner"},
    )


def test_a_whatsapp_failure_does_not_change_the_recorded_event_return_value():
    """A sender outage must not turn a successful lifecycle write into a trading failure."""
    row = SimpleNamespace(id=16)
    event = {"id": 16, "strategy_id": 7, "kind": "run_started", "message": "Started"}
    notifier = Mock()
    notifier.send_strategy_lifecycle_alert.side_effect = RuntimeError("WhatsApp unavailable")

    with (
        patch.object(lifecycle_events.store, "record_event", return_value=row),
        patch.object(lifecycle_events.store, "event_to_dict", return_value=event),
        patch.object(lifecycle_events.broadcast, "push_event"),
        patch.object(lifecycle_events, "alert_executor", _ImmediateExecutor()),
        patch.object(lifecycle_events, "whatsapp_alert_service", notifier),
    ):
        assert lifecycle_events.record_and_notify(7, "owner", "run_started", "Started") is row


def test_mode_is_alert_context_not_an_unknown_audit_column():
    """Lifecycle callers may enrich WhatsApp without changing the event schema."""
    row = SimpleNamespace(id=17)
    notifier = Mock()

    def record_event(*args, **kwargs):
        assert kwargs == {"run_id": 3}
        return row

    with (
        patch.object(lifecycle_events.store, "record_event", side_effect=record_event),
        patch.object(
            lifecycle_events.store,
            "event_to_dict",
            return_value={"id": 17, "strategy_id": 7, "kind": "run_started", "message": "Started"},
        ),
        patch.object(lifecycle_events.store, "get_strategy_unscoped", return_value=None),
        patch.object(lifecycle_events.broadcast, "push_event"),
        patch.object(lifecycle_events, "alert_executor", _ImmediateExecutor()),
        patch.object(lifecycle_events, "whatsapp_alert_service", notifier),
    ):
        assert (
            lifecycle_events.record_and_notify(
                7, "owner", "run_started", "Started", run_id=3, mode="live"
            )
            is row
        )

    assert notifier.send_strategy_lifecycle_alert.call_args.args[1]["mode"] == "live"


def test_lifecycle_whatsapp_format_has_context_without_generic_order_fields():
    """Formatting must identify the run while leaving order details to order alerts."""
    message = WhatsAppAlertService().format_strategy_lifecycle_alert(
        {
            "strategy_id": 7,
            "strategy_name": "NIFTY trend",
            "mode": "live",
            "kind": "exit_order_unrecorded",
            "message": "Exit SELL 50 RELIANCE was sent as broker order B-12345",
            "severity": "critical",
            "ts": "2026-09-23T09:30:00+00:00",
        }
    )

    assert "NIFTY trend (#7)" in message
    assert "Mode: LIVE" in message
    assert "durable order record" in message
    assert "IST" in message
    assert "Action required:" in message
    assert "Symbol:" not in message
    assert "Order ID:" not in message
    assert "RELIANCE" not in message
    assert "B-12345" not in message
    assert "SELL" not in message
    assert "50" not in message
