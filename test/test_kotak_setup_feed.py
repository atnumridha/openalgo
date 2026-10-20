import threading
from collections import deque

from services.kotak_assistant.broker import Gateway


def gateway():
    g = object.__new__(Gateway)
    g._watched = {("NIFTY", "NSE_INDEX")}
    g._lock = threading.RLock()
    g._ticks = {}
    g._setup_events = deque(maxlen=10000)
    g._setup_sequence = 0
    g._setup_epoch = "test"
    g._setup_dropped = 0
    return g


def test_every_observed_index_event_is_queued_without_reducing_to_last_snapshot(monkeypatch):
    g = gateway()
    monkeypatch.setattr("services.kotak_assistant.broker.time.time", lambda: 1000)
    for p in (22609, 22607, 22610):
        g._tick({"symbol": "NIFTY", "exchange": "NSE_INDEX", "data": {"ltp": p}})
    batch = g.drain_setup_events("NIFTY", "NSE_INDEX")
    assert [e["price"] for e in batch["events"]] == [22609, 22607, 22610]
    assert len({e["id"] for e in batch["events"]}) == 3
    assert g.drain_setup_events("NIFTY", "NSE_INDEX")["events"] == []


def test_stale_exchange_timestamp_does_not_become_fresh_observation(monkeypatch):
    g = gateway()
    monkeypatch.setattr("services.kotak_assistant.broker.time.time", lambda: 1792122360)
    g._tick(
        {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "data": {"ltp": 22600, "timestamp": 1792035960},
        }
    )
    batch = g.drain_setup_events("NIFTY", "NSE_INDEX")
    assert batch["events"] == []


def test_buffer_overflow_is_reported_as_coverage_gap(monkeypatch):
    g = gateway()
    g._setup_events = deque(maxlen=2)
    monkeypatch.setattr("services.kotak_assistant.broker.time.time", lambda: 1000)
    for p in (1, 2, 3):
        g._tick({"symbol": "NIFTY", "exchange": "NSE_INDEX", "data": {"ltp": p}})
    assert g.drain_setup_events("NIFTY", "NSE_INDEX")["dropped"] == 1
