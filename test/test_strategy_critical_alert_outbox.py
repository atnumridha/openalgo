"""Critical WhatsApp alerts survive disconnects and worker restarts."""

from datetime import UTC, datetime, timedelta

import pytest

from database import strategy_module_db as store
from services.strategy_module import critical_alerts
from services.whatsapp_alert_service import WhatsAppAlertService

USER = "critical_alert_outbox_test"


@pytest.fixture(autouse=True)
def clean_alerts():
    store.db_session.remove()
    store.init_db()
    store.db_session.query(store.SmCriticalAlert).filter_by(user_id=USER).delete()
    store.db_session.query(store.SmStrategyEvent).filter_by(user_id=USER).delete()
    store.db_session.query(store.SmAutomationEvent).filter_by(user_id=USER).delete()
    store.db_session.commit()
    yield
    store.db_session.query(store.SmCriticalAlert).filter_by(user_id=USER).delete()
    store.db_session.query(store.SmStrategyEvent).filter_by(user_id=USER).delete()
    store.db_session.query(store.SmAutomationEvent).filter_by(user_id=USER).delete()
    store.db_session.commit()
    store.db_session.remove()


def test_critical_account_event_and_alert_are_one_commit():
    row = store.record_automation_event(
        USER, "live_authorization_revoked", "Live entry revoked", severity="critical"
    )
    assert row is not None
    alerts = store.list_critical_alerts(USER)
    assert len(alerts) == 1
    assert alerts[0]["source_id"] == row.id
    assert alerts[0]["status"] == "pending"
    assert alerts[0]["event_ts"] == store.automation_event_to_dict(row)["ts"]


def test_disconnected_bot_keeps_critical_alert_pending(monkeypatch):
    row = store.record_automation_event(
        USER, "live_authorization_revoked", "Live entry revoked", severity="critical"
    )
    source_id = row.id
    monkeypatch.setattr(critical_alerts, "deliver", lambda *_args: False)
    summary = critical_alerts.process_due(now=datetime.now(UTC).replace(tzinfo=None), user_id=USER)
    assert summary["retrying"] == 1
    alert = store.list_critical_alerts(USER)[0]
    assert alert["status"] == "pending"
    assert alert["attempts"] == 1
    assert alert["source_id"] == source_id


def test_retry_exhaustion_is_visible_after_restart(monkeypatch):
    store.record_automation_event(
        USER, "live_authorization_revoked", "Live entry revoked", severity="critical"
    )
    monkeypatch.setattr(critical_alerts, "deliver", lambda *_args: False)
    now = datetime.now(UTC).replace(tzinfo=None)
    for attempt in range(critical_alerts.MAX_ATTEMPTS):
        critical_alerts.process_due(now=now + timedelta(hours=attempt), user_id=USER)
        store.db_session.remove()  # new worker/session can see durable state
    alert = store.list_critical_alerts(USER)[0]
    assert alert["status"] == "failed"
    assert alert["attempts"] == critical_alerts.MAX_ATTEMPTS
    assert alert["last_attempt_at"] is not None


def test_late_delivery_preserves_original_event_time(monkeypatch):
    row = store.record_automation_event(
        USER, "live_authorization_revoked", "Live entry revoked", severity="critical"
    )
    event_ts = store.automation_event_to_dict(row)["ts"]
    seen = []
    monkeypatch.setattr(critical_alerts, "deliver", lambda event: seen.append(event) or True)
    now = row.ts + timedelta(minutes=4)
    critical_alerts.process_due(now=now, user_id=USER)
    alert = store.list_critical_alerts(USER)[0]
    assert alert["status"] == "late"
    assert seen[0]["ts"] == event_ts
    assert seen[0]["delayed"] is True


def test_expired_alert_is_not_delivered(monkeypatch):
    row = store.record_automation_event(
        USER, "live_authorization_revoked", "Live entry revoked", severity="critical"
    )
    seen = []
    monkeypatch.setattr(critical_alerts, "deliver", lambda event: seen.append(event) or True)
    critical_alerts.process_due(
        now=row.ts + timedelta(hours=critical_alerts.TTL_HOURS + 1), user_id=USER
    )
    assert store.list_critical_alerts(USER)[0]["status"] == "failed"
    assert seen == []


def test_direct_strategy_audit_write_enqueues_unknown_broker_order_once():
    row = store.record_event(
        987654,
        USER,
        "order_outcome_unknown",
        "Broker reply was lost",
        severity="critical",
    )
    assert row is not None
    alerts = store.list_critical_alerts(USER, strategy_id=987654)
    assert len(alerts) == 1
    assert alerts[0]["source_key"].startswith(f"strategy:{row.id}:")
    assert store.list_events(987654)[0]["whatsapp_delivery"]["status"] == "pending"


def test_process_crash_reclaims_expired_lease_without_duplicate_active_claim(monkeypatch):
    store.record_automation_event(
        USER, "live_authorization_revoked", "Live entry revoked", severity="critical"
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    first = store.claim_due_critical_alerts(now, user_id=USER)
    assert len(first) == 1
    assert store.claim_due_critical_alerts(now + timedelta(seconds=1), user_id=USER) == []
    store.db_session.remove()
    seen = []
    monkeypatch.setattr(critical_alerts, "deliver", lambda event: seen.append(event) or True)
    critical_alerts.process_due(now=now + timedelta(minutes=2), user_id=USER)
    assert len(seen) == 1
    assert store.list_critical_alerts(USER)[0]["status"] == "late"


def test_sender_requires_explicit_upstream_acceptance_and_labels_late(monkeypatch):
    service = WhatsAppAlertService()
    from services import whatsapp_alert_service as sender

    monkeypatch.setattr(
        sender,
        "get_bot_config",
        lambda: {
            "is_paired": True,
            "owner_username": USER,
        },
    )
    monkeypatch.setattr(sender, "get_whatsapp_user_by_username", lambda _user: None)
    messages = []
    monkeypatch.setattr(
        service, "send_alert_sync", lambda _to, message: messages.append(message) or False
    )
    event = {
        "user_id": USER,
        "strategy_id": 7,
        "kind": "order_outcome_unknown",
        "severity": "critical",
        "ts": "2026-09-25T04:00:00+00:00",
        "delayed": True,
    }
    assert service.send_critical_strategy_alert(event) is False
    assert "DELAYED SAFETY ALERT" in messages[0]
    assert "25 Sep 2026, 09:30:00 IST" in messages[0]


def test_crashed_sends_cannot_exceed_retry_budget():
    store.record_automation_event(
        USER, "live_authorization_revoked", "Live entry revoked", severity="critical"
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    for attempt in range(critical_alerts.MAX_ATTEMPTS):
        claimed = store.claim_due_critical_alerts(
            now + timedelta(minutes=attempt * 2),
            user_id=USER,
            max_attempts=critical_alerts.MAX_ATTEMPTS,
        )
        assert len(claimed) == 1
        store.db_session.remove()  # sender died without settling
    assert (
        store.claim_due_critical_alerts(
            now + timedelta(minutes=critical_alerts.MAX_ATTEMPTS * 2),
            user_id=USER,
            max_attempts=critical_alerts.MAX_ATTEMPTS,
        )
        == []
    )
    assert store.list_critical_alerts(USER)[0]["status"] == "failed"


def test_deleting_stopped_strategy_keeps_unsent_safety_alert():
    strategy, error = store.create_strategy(
        USER,
        {
            "name": "Critical alert deletion probe",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "legs": [],
        },
    )
    assert error is None
    sid = strategy["id"]
    assert (
        store.record_event(
            sid,
            USER,
            "protective_stop_uncovered",
            "Unprotected 50 units",
            severity="critical",
        )
        is not None
    )
    deleted, error = store.delete_strategy(sid, USER)
    assert (deleted, error) == (True, None)
    assert store.list_events(sid) == []
    alert = store.list_critical_alerts(USER, strategy_id=sid)[0]
    assert alert["message"] == "Unprotected 50 units"
    assert alert["status"] == "pending"


def test_critical_exit_audit_does_not_call_whatsapp_on_exit_path(monkeypatch):
    monkeypatch.setattr(
        critical_alerts,
        "deliver",
        lambda _event: pytest.fail("WhatsApp network I/O reached the exit audit path"),
    )
    row = store.record_event(
        987654,
        USER,
        "leg_exit_rejected",
        "Exit failed; position still held",
        severity="critical",
    )
    assert row is not None
    assert store.list_critical_alerts(USER, strategy_id=987654)[0]["status"] == "pending"


def test_reused_sqlite_audit_id_does_not_collide_with_retained_alert():
    first = store.record_event(
        987654, USER, "order_outcome_unknown", "First unknown order", severity="critical"
    )
    assert first is not None
    original_id = first.id
    store.db_session.query(store.SmStrategyEvent).filter_by(id=original_id).delete()
    store.db_session.commit()
    store.db_session.add(
        store.SmStrategyEvent(
            id=original_id,
            strategy_id=987654,
            user_id=USER,
            kind="order_outcome_unknown",
            severity="critical",
            message="Second unknown order",
        )
    )
    store.db_session.flush()
    second = store.db_session.get(store.SmStrategyEvent, original_id)
    store._enqueue_critical_alert(second, account=False)
    store.db_session.commit()
    alerts = store.list_critical_alerts(USER, strategy_id=987654)
    assert len(alerts) == 2
    assert alerts[0]["source_key"] != alerts[1]["source_key"]
    assert store.list_events(987654)[0]["whatsapp_delivery"]["message"] == "Second unknown order"


def test_terminal_delivery_records_are_pruned_only_after_retention():
    row = store.record_automation_event(
        USER, "live_authorization_revoked", "Live entry revoked", severity="critical"
    )
    alert = store.db_session.query(store.SmCriticalAlert).filter_by(user_id=USER).one()
    alert.status = "failed"
    alert.event_ts = row.ts - timedelta(days=31)
    store.db_session.commit()
    assert store.prune_terminal_critical_alerts(row.ts, limit=20) == 1
    assert store.list_critical_alerts(USER) == []


def test_slow_batch_claims_each_alert_only_when_its_send_begins(monkeypatch):
    for kind in ("live_authorization_revoked", "live_authorization_expired"):
        assert store.record_automation_event(USER, kind, kind, severity="critical") is not None
    start = datetime.now(UTC).replace(tzinfo=None)
    times = [start]
    claims = []
    original_claim = store.claim_due_critical_alerts

    def claim(at, **kwargs):
        claims.append(at)
        return original_claim(at, **kwargs)

    def slow_send(_event):
        times[0] += timedelta(seconds=35)
        return True

    monkeypatch.setattr(store, "claim_due_critical_alerts", claim)
    monkeypatch.setattr(critical_alerts, "deliver", slow_send)
    critical_alerts.process_due(now=start, user_id=USER, clock=lambda: times[0])
    assert len(claims) >= 2
    assert claims[1] - claims[0] >= timedelta(seconds=35)
    alerts = store.list_critical_alerts(USER)
    assert sorted(alert["status"] for alert in alerts) == ["late", "sent"]


def test_critical_message_points_to_exact_in_app_event_without_raw_secrets():
    formatted = WhatsAppAlertService().format_strategy_lifecycle_alert(
        {
            "id": 418,
            "strategy_id": 7,
            "kind": "order_outcome_unknown",
            "severity": "critical",
            "message": "NIFTY order 75 qty failed; token super-secret-token",
            "ts": "2026-09-25T04:00:00+00:00",
        }
    )
    assert "unknown" in formatted.lower()
    assert "/strategy/7" in formatted
    assert "#418" in formatted
    assert "super-secret-token" not in formatted
    assert "not a current trade signal" in formatted.lower()


def test_expired_head_does_not_delay_a_fresh_critical_alert(monkeypatch):
    for kind in ("live_authorization_revoked", "live_authorization_expired"):
        assert store.record_automation_event(USER, kind, kind, severity="critical") is not None
    rows = (
        store.db_session.query(store.SmCriticalAlert)
        .filter_by(user_id=USER)
        .order_by(store.SmCriticalAlert.id)
        .all()
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    rows[0].expires_at = now - timedelta(seconds=1)
    store.db_session.commit()
    seen = []
    monkeypatch.setattr(critical_alerts, "deliver", lambda event: seen.append(event) or True)
    critical_alerts.process_due(now=now, user_id=USER)
    assert len(seen) == 1
    assert store.list_critical_alerts(USER)[0]["status"] in {"sent", "late"}


def test_expired_backlog_over_one_scan_does_not_starve_fresh_alert(monkeypatch):
    for number in range(26):
        assert (
            store.record_automation_event(
                USER,
                "live_authorization_revoked",
                f"safety event {number}",
                severity="critical",
            )
            is not None
        )
    rows = (
        store.db_session.query(store.SmCriticalAlert)
        .filter_by(user_id=USER)
        .order_by(store.SmCriticalAlert.id)
        .all()
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    for row in rows[:-1]:
        row.expires_at = now - timedelta(seconds=1)
    store.db_session.commit()
    seen = []
    monkeypatch.setattr(critical_alerts, "deliver", lambda event: seen.append(event) or True)
    critical_alerts.process_due(now=now, user_id=USER)
    assert len(seen) == 1
    assert seen[0]["message"] == "safety event 25"
