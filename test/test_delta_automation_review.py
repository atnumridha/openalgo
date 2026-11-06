"""Offline owner lifecycle regressions; all broker operations use a fake service."""

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from services.delta_chart.automation import Automation
from services.delta_chart.service import Rejected, Store
from test.test_delta_automation import FakeService


@pytest.fixture
def owner():
    with tempfile.TemporaryDirectory() as directory:
        service = FakeService(Store(Path(directory) / "owner.db"))
        auto = Automation(service)
        service.auto = auto
        auto.configure("alice", dict(account="account-a", symbol="BTCUSD", enabled=True))
        yield auto, service


def decision(source):
    return dict(
        context=dict(source_time=source, direction="up", higher_direction="up"),
        action=dict(side="buy", size=1, price=99.5, leverage=50,
                    auto_protection=dict(stop=95, target=108.5, source_time=source,
                                         interval_seconds=60, reason="offline fixture")),
    )


def tick(auto, source):
    with patch.object(auto, "read_histories", return_value=([], [], time.time())), \
         patch("services.delta_chart.automation.evaluate_strategy", return_value=decision(source)):
        auto.tick_one("alice", force=True)


def restart(service):
    service.auto = Automation(service)
    return service.auto


def test_known_generation_does_not_authorize_unreserved_payload(owner):
    auto, service = owner
    generation = auto.row("alice")["generation"]
    body = dict(decision(60)["action"], account="account-a", symbol="BTCUSD",
                automation_generation=generation, request_id="unreserved")
    with pytest.raises(Rejected, match="Unverified"):
        auto.authorize_entry("alice", body)
    assert not service.calls


def test_unknown_entry_blocks_a_new_candle_after_restart(owner):
    auto, service = owner

    def unknown(user, body):
        service.calls.append(body)
        raise RuntimeError("transport outcome unknown")

    service.action = unknown
    tick(auto, 60)
    auto = restart(service)
    tick(auto, 120)
    assert len(service.calls) == 1
    assert auto.status("alice", "account-a", "BTCUSD")["status"] == "reconciling"


def test_restart_consumes_unsubmitted_reservation_without_replaying_candle(owner):
    auto, service = owner
    original = service.action

    def die_before_submission(user, body):
        raise KeyboardInterrupt("simulate worker death before durable intent")

    service.action = die_before_submission
    with pytest.raises(KeyboardInterrupt):
        tick(auto, 60)
    auto = restart(service)
    service.action = original
    tick(auto, 60)
    assert not service.calls
    with service.store.db() as db:
        row = db.execute("SELECT response FROM delta_auto_attempts").fetchone()
    assert json.loads(row["response"])["status"] == "rejected"
    tick(auto, 120)
    assert len(service.calls) == 1


def test_off_remains_revoked_after_restart(owner):
    auto, service = owner
    tick(auto, 60)
    reserved = service.calls[0]
    auto.configure("alice", dict(account="account-a", symbol="BTCUSD", enabled=False))
    auto = restart(service)
    with pytest.raises(Rejected, match="revoked"):
        auto.authorize_entry("alice", reserved)
    tick(auto, 120)
    assert len(service.calls) == 1


def test_saved_connection_change_during_final_preflight_rejects_old_client():
    from test_delta_chart_plans import ManagedPlanTests

    harness = ManagedPlanTests("runTest")
    harness.setUp()
    try:
        service = harness.service
        key = ["key"]
        service.credentials = lambda user: (key[0], "secret")
        auto = Automation(service)
        service.automation = auto
        auto.configure("alice", dict(account=harness.initial["account"], symbol="BTCUSD",
                                     enabled=True, leverage=5, balance_fraction=None,
                                     manual_quantity=1))
        original = harness.client.request
        checks = 0

        def request(method, path, **kwargs):
            nonlocal checks
            if method == "GET" and path == "/v2/positions/margined" and not kwargs.get("params"):
                checks += 1
                if checks == 2:
                    key[0] = "new-account-key"
            return original(method, path, **kwargs)

        harness.client.request = request
        proposed = decision(harness.source)
        proposed["action"]["leverage"] = 5
        with patch.object(auto, "read_histories", return_value=([], [], time.time())), \
             patch("services.delta_chart.automation.evaluate_strategy", return_value=proposed):
            auto.tick_one("alice", force=True)
        assert checks == 2
        assert not [call for call in harness.client.calls
                    if call[0] == "POST" and call[1] == "/v2/orders"]
    finally:
        harness.doCleanups()


def test_connection_save_acknowledgement_waits_for_inflight_entry():
    """Exercise the real entry wrapper and process-safe connection barrier."""
    from services.delta_chart.service import TradingService

    with tempfile.TemporaryDirectory() as directory:
        key = ["old-key"]
        service = TradingService(Store(Path(directory) / "owner.db"),
                                 lambda user: (key[0], "secret"), lambda *args: object())
        entered = threading.Event()
        release = threading.Event()
        saving = threading.Event()
        saved = threading.Event()
        errors = []
        observed = []

        def submit(user, body):
            entered.set()
            assert release.wait(3)
            observed.append(key[0])
            return dict(status="confirmed")

        service._action = submit

        def entry():
            try:
                service.action("alice", dict(action="entry", account="old-account", symbol="BTCUSD"))
            except BaseException as exc:
                errors.append(exc)

        def save():
            try:
                saving.set()
                with service.plans.lock("delta-connection", "alice", "*"):
                    key[0] = "new-key"
                    saved.set()
            except BaseException as exc:
                errors.append(exc)

        entry_thread = threading.Thread(target=entry)
        save_thread = threading.Thread(target=save)
        try:
            entry_thread.start()
            assert entered.wait(3)
            save_thread.start()
            assert saving.wait(3)
            assert not saved.wait(.1)
        finally:
            release.set()
            entry_thread.join(3)
            if save_thread.ident is not None:
                save_thread.join(3)
        assert not errors
        assert not entry_thread.is_alive() and not save_thread.is_alive()
        assert observed == ["old-key"]
        assert saved.is_set() and key[0] == "new-key"
