"""MCX stream candles must use native Kotak trade evidence only."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.kotak_mcx_candles import KotakMcxStreamCollector, McxCandleStore

IST = ZoneInfo("Asia/Kolkata")
SYMBOL = "SILVERM30NOV26FUT"


def at(minute, second=0):
    return datetime(2026, 9, 25, 9, minute, second, tzinfo=IST)


def packet(when, price, volume):
    return {"mode": 2, "symbol": SYMBOL, "exchange": "MCX", "data": {
        "ltt": int(when.timestamp()), "ltp": price, "volume": volume,
        "volume_fresh": True,
        "timestamp": int((when + timedelta(seconds=1)).timestamp() * 1000),
    }}


def store(tmp_path):
    return McxCandleStore(f"sqlite:///{tmp_path / 'candles.db'}")


def test_cached_cumulative_volume_cannot_make_a_candle(tmp_path):
    candles = store(tmp_path)
    stale = packet(at(0), 100, 1000)
    stale["data"]["volume_fresh"] = False
    assert candles.ingest("kotak-1", stale) is False
    assert candles.history(
        "kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(1)
    )["readiness"] == "Data unavailable"


def test_completed_minute_uses_native_time_and_cumulative_volume(tmp_path):
    candles = store(tmp_path)
    assert candles.ingest("kotak-1", packet(at(0), 100, 1000))
    assert candles.ingest("kotak-1", packet(at(1), 101, 1005))
    assert candles.ingest("kotak-1", packet(at(1, 20), 103, 1013))
    assert candles.ingest("kotak-1", packet(at(2), 102, 1017))

    result = candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(2, 10))
    assert result["readiness"] == "Ready"
    assert result["data"] == [{
        "timestamp": int(at(1).timestamp()), "open": 101.0, "high": 103.0,
        "low": 101.0, "close": 103.0, "volume": 13.0, "oi": None,
    }]


def test_missing_native_trade_time_never_becomes_arrival_time(tmp_path):
    candles = store(tmp_path)
    no_native = packet(at(0), 100, 1000)
    del no_native["data"]["ltt"]
    assert not candles.ingest("kotak-1", no_native)
    assert candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(2))["readiness"] == "Data unavailable"


def test_hsm_native_ist_time_is_understood_without_using_arrival_clock(tmp_path):
    candles = store(tmp_path)
    first = packet(at(0), 100, 1000)
    first["data"]["ltt"] = "25/09/2026 09:00:00"
    second = packet(at(1), 101, 1010)
    second["data"]["ltt"] = "25/09/2026 09:01:00"
    third = packet(at(2), 102, 1020)
    third["data"]["ltt"] = "25/09/2026 09:02:00"
    assert candles.ingest("kotak-1", first)
    assert candles.ingest("kotak-1", second)
    assert candles.ingest("kotak-1", third)
    assert candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(2, 10))["readiness"] == "Ready"


def test_out_of_order_reset_and_missing_minutes_block_aggregation(tmp_path):
    candles = store(tmp_path)
    candles.ingest("kotak-1", packet(at(0), 100, 1000))
    candles.ingest("kotak-1", packet(at(1), 101, 1005))
    assert not candles.ingest("kotak-1", packet(at(0, 30), 99, 1004))
    candles.ingest("kotak-1", packet(at(1, 20), 102, 3))  # cumulative reset
    candles.ingest("kotak-1", packet(at(3), 104, 10))  # missing 09:02 minute
    result = candles.history("kotak-1", SYMBOL, "5m", "2026-09-25", "2026-09-25", at(3, 10))
    assert result["readiness"] == "Collecting history"
    assert result["data"] == []


def test_five_minute_bar_requires_five_contiguous_complete_minutes(tmp_path):
    candles = store(tmp_path)
    for minute in range(4, 11):
        candles.ingest("kotak-1", packet(at(minute), 100 + minute, 1000 + minute * 10))
    result = candles.history("kotak-1", SYMBOL, "5m", "2026-09-25", "2026-09-25", at(10, 10))
    assert result["readiness"] == "Ready"
    assert result["data"] == [{
        "timestamp": int(at(5).timestamp()), "open": 105.0, "high": 109.0,
        "low": 105.0, "close": 109.0, "volume": 50.0, "oi": None,
    }]


def test_stale_stream_is_unavailable_even_if_old_bars_were_ready(tmp_path):
    candles = store(tmp_path)
    for minute in range(3):
        candles.ingest("kotak-1", packet(at(minute), 100 + minute, 1000 + minute * 10))
    result = candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(4))
    assert result["readiness"] == "Data unavailable"
    assert result["data"] == []


def test_missing_native_time_invalidates_previously_ready_history(tmp_path):
    candles = store(tmp_path)
    for minute in range(3):
        candles.ingest("kotak-1", packet(at(minute), 100 + minute, 1000 + minute * 10))
    assert candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(2, 10))["readiness"] == "Ready"
    missing = packet(at(2, 20), 103, 1030)
    del missing["data"]["ltt"]
    assert not candles.ingest("kotak-1", missing)
    result = candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(2, 30))
    assert result["readiness"] == "Data unavailable"
    assert result["data"] == []


def test_connection_and_contract_never_share_candles(tmp_path):
    candles = store(tmp_path)
    for minute in range(3):
        candles.ingest("kotak-1", packet(at(minute), 100 + minute, 1000 + minute * 10))
    other = candles.history("kotak-2", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(3))
    rolled = candles.history("kotak-1", "SILVERM31DEC26FUT", "1m", "2026-09-25", "2026-09-25", at(3))
    assert other["data"] == rolled["data"] == []
    assert other["readiness"] == rolled["readiness"] == "Collecting history"


def test_interrupted_feed_requires_new_warmup(tmp_path):
    candles = store(tmp_path)
    candles.ingest("kotak-1", packet(at(0), 100, 1000))
    candles.ingest("kotak-1", packet(at(1), 101, 1010))
    candles.mark_interrupted("kotak-1", SYMBOL)
    candles.ingest("kotak-1", packet(at(2), 102, 1020))
    candles.ingest("kotak-1", packet(at(3), 103, 1030))
    result = candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(3, 10))
    assert result["data"] == []
    candles.ingest("kotak-1", packet(at(4), 104, 1040))
    result = candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(4, 10))
    assert [row["timestamp"] for row in result["data"]] == [int(at(3).timestamp())]


def test_stream_collector_subscribes_and_drains_only_pinned_current_future(tmp_path):
    class FakeWs:
        connected = authenticated = True

        def __init__(self):
            self.callbacks = {}
            self.subscriptions = []

        def register_callback(self, event, callback):
            self.callbacks[event] = callback

        def unregister_callback(self, event, _callback):
            self.callbacks.pop(event)

        def subscribe(self, symbols, mode="Quote"):
            self.subscriptions.append((symbols, mode))
            return {"status": "success"}

    ws = FakeWs()
    candles = store(tmp_path)
    collector = KotakMcxStreamCollector(
        "kotak-1", "api-key", candles, ws_factory=lambda _key: ws,
        connection_check=lambda _key, _id: True,
        current_contract=lambda symbol: symbol == SYMBOL,
        start_worker=False,
    )
    assert collector.ensure(SYMBOL) == "Collecting history"
    assert ws.subscriptions == [([{"symbol": SYMBOL, "exchange": "MCX"}], "Quote")]
    assert collector.ensure("SILVERM31DEC26FUT") == "Data unavailable"
    for minute in range(3):
        ws.callbacks["market_data"](packet(at(minute), 100 + minute, 1000 + minute * 10))
        collector.drain_once()
    assert candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(2, 10))["readiness"] == "Ready"
    ws.callbacks["auth"]({"status": "success"})
    collector.drain_once()
    assert candles.history("kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25", at(2, 10))["readiness"] == "Collecting history"
    collector.close()
    assert ws.callbacks == {}


def test_rotated_api_key_replaces_previous_connection_collector(monkeypatch):
    from services import kotak_mcx_candles as module

    made = []

    class FakeCollector:
        def __init__(self, connection_id, api_key, _store):
            self.connection_id = connection_id
            self.api_key = api_key
            self.closed = False
            self.store = self
            made.append(self)

        def ensure(self, _symbol):
            return "Collecting history"

        def history(self, *_args):
            return {"status": "error", "readiness": "Collecting history", "data": []}

        def close(self):
            self.closed = True

    monkeypatch.setattr(module, "_collectors", {})
    monkeypatch.setattr(module, "_verified_connection", lambda _key, _id: True)
    monkeypatch.setattr(module, "_is_current_future", lambda _symbol: True)
    monkeypatch.setattr(module, "KotakMcxStreamCollector", FakeCollector)
    module.get_kotak_mcx_history("old-key", "kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25")
    module.get_kotak_mcx_history("new-key", "kotak-1", SYMBOL, "1m", "2026-09-25", "2026-09-25")
    assert len(made) == 2
    assert made[0].closed is True
    assert made[1].closed is False
