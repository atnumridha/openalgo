"""Market-feed reconnect regressions without sockets, timers or live accounts."""

import pytest

import websocket_proxy  # noqa: F401 - initialize adapter package before Kotak
from broker.kotak.streaming import kotak_adapter as module


class FakeTimer:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        assert not self.cancelled
        self.callback()


class FakeFeed:
    def __init__(self):
        self.callbacks = {}
        self.connects = 0
        self.closes = 0

    def set_callbacks(self, **callbacks):
        self.callbacks = callbacks

    def connect(self):
        self.connects += 1

    def close(self):
        self.closes += 1
        # HSM can notify close during deliberate retirement. SFeed does not
        # expose wait_until_closed, so this fake deliberately omits it too.
        self.callbacks['on_close']()


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(module.BaseBrokerWebSocketAdapter, '__init__',
                        lambda self: setattr(self, 'subscriptions', {}))
    monkeypatch.setattr(module.BaseBrokerWebSocketAdapter, 'cleanup_zmq', lambda self: None)
    monkeypatch.setattr(module.threading, 'Timer', FakeTimer)
    item = module.KotakWebSocketAdapter()
    item.cleanup_zmq = lambda: None
    item._running = True
    item._ws_client = FakeFeed()
    item._setup_internal_callbacks()

    def recreate():
        item._ws_client = FakeFeed()
        item._setup_internal_callbacks()

    monkeypatch.setattr(item, '_recreate_ws_client', recreate)
    yield item
    item.disconnect()
    # Callbacks retain the fixture; its destructor can run after pytest closes
    # captured streams. Cleanup has already completed synchronously above.
    item.cleanup = lambda: None


def retry_once(adapter):
    adapter._ws_client.callbacks['on_close']()
    pending = adapter._reconnect_timer
    assert pending is not None
    pending.fire()
    assert adapter._ws_client.connects == 1


def test_failed_async_retry_schedules_another_attempt(adapter):
    retry_once(adapter)
    adapter._ws_client.callbacks['on_close']()
    assert adapter._reconnect_timer is not None
    assert adapter._reconnect_timer.delay == 10


def test_retired_feed_callbacks_cannot_change_current_connection(adapter):
    old = adapter._ws_client
    retry_once(adapter)
    current = adapter._ws_client
    current.callbacks['on_open']()
    old.callbacks['on_close']()
    old.callbacks['on_open']()
    assert adapter._connected is True
    assert adapter._reconnect_timer is None


def test_repeated_close_notifications_keep_one_pending_timer(adapter):
    adapter._ws_client.callbacks['on_close']()
    pending = adapter._reconnect_timer
    adapter._ws_client.callbacks['on_close']()
    assert adapter._reconnect_timer is pending
    assert not pending.cancelled


def test_stopped_adapter_does_not_retry(adapter):
    callbacks = adapter._ws_client.callbacks
    adapter.disconnect()
    callbacks['on_close']()
    callbacks['on_open']()
    assert adapter._reconnect_timer is None
    assert not adapter._running
    assert not adapter._connected


def test_retry_budget_remains_bounded_without_successful_open(adapter):
    adapter._max_reconnect_attempts = 3
    delays = []
    for _ in range(3):
        adapter._ws_client.callbacks['on_close']()
        timer = adapter._reconnect_timer
        assert timer is not None
        delays.append(timer.delay)
        timer.fire()
    adapter._ws_client.callbacks['on_close']()
    assert delays == [5, 10, 20]
    assert adapter._reconnect_timer is None
    assert not adapter._running


def test_authenticated_recovery_resets_retry_budget(adapter):
    retry_once(adapter)
    adapter._ws_client.callbacks['on_open']()
    assert adapter._connected
    assert adapter._reconnect_attempts == 0
    assert not adapter._reconnecting
    adapter._ws_client.callbacks['on_close']()
    assert adapter._reconnect_timer.delay == 5


def test_stop_during_client_recreation_does_not_start_a_new_feed(adapter, monkeypatch):
    replacement = FakeFeed()

    def recreate_after_stop():
        # Credential/feed lookup can overlap an explicit disconnect.
        adapter.disconnect()
        adapter._ws_client = replacement
        adapter._setup_internal_callbacks()

    monkeypatch.setattr(adapter, '_recreate_ws_client', recreate_after_stop)
    adapter._ws_client.callbacks['on_close']()
    adapter._reconnect_timer.fire()
    assert replacement.connects == 0
    assert replacement.closes == 1
    assert adapter._ws_client is None
    assert adapter._reconnect_timer is None


def test_stop_while_retiring_the_old_feed_prevents_recreation(adapter, monkeypatch):
    recreated = []
    monkeypatch.setattr(adapter._ws_client, 'close', adapter.disconnect)
    monkeypatch.setattr(adapter, '_recreate_ws_client', lambda: recreated.append(True))
    adapter._ws_client.callbacks['on_close']()
    adapter._reconnect_timer.fire()
    assert recreated == []
    assert adapter._ws_client is None
    assert adapter._reconnect_timer is None


def test_retired_close_between_retry_lock_sections_cannot_schedule_extra_retry(adapter):
    original_lock = adapter._lock
    old = adapter._ws_client

    class ClosingLock:
        """Inject a late close immediately after the retry's first lock release."""
        fired = False

        def __enter__(self):
            original_lock.acquire()

        def __exit__(self, *args):
            original_lock.release()
            if not self.fired:
                self.fired = True
                old.callbacks['on_close']()

    old.callbacks['on_close']()
    adapter._lock = ClosingLock()
    adapter._reconnect_timer.fire()
    adapter._ws_client.callbacks['on_open']()
    assert adapter._connected
    assert adapter._reconnect_timer is None
