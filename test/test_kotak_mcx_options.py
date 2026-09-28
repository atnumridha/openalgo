"""MCX option premium history uses verified contracts and observed trades only."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from database import symbol as symbols
from database.engine_factory import create_db_engine
from services import kotak_mcx_candles as mcx

IST = ZoneInfo("Asia/Kolkata")
FUTURE = "SILVERM30NOV26FUT"
CALL = "SILVERM26NOV26125000CE"
PUT = "SILVERM26NOV26125000PE"
NEXT_CALL = "SILVERM26NOV26125500CE"
NEXT_PUT = "SILVERM26NOV26125500PE"
THIRD_CALL = "SILVERM26NOV26126000CE"
THIRD_PUT = "SILVERM26NOV26126000PE"


def at(minute, second=0):
    return datetime(2026, 9, 25, 9, minute, second, tzinfo=IST)


def packet(symbol, minute, second=0, **overrides):
    when = at(minute, second)
    data = {"ltt": int(when.timestamp()), "ltp": 100 + minute,
            "volume": 1000 + minute * 10 + second, "volume_fresh": True,
            "timestamp": int((when + timedelta(seconds=1)).timestamp() * 1000)}
    data.update(overrides)
    return {"mode": 2, "symbol": symbol, "exchange": "MCX", "data": data}


class Socket:
    connected = authenticated = True

    def __init__(self, *_args, **_kwargs):
        self.callbacks = {}
        self.subscriptions = set()
        self.closed = False
        self.refused_unsubscribe = set()

    def connect(self):
        return True

    def register_callback(self, event, callback):
        self.callbacks[event] = callback

    def unregister_callback(self, event, _callback):
        self.callbacks.pop(event, None)

    def subscribe(self, items, mode="Quote"):
        assert mode == "Quote"
        self.subscriptions.update(row["symbol"] for row in items)
        return {"status": "success"}

    def unsubscribe(self, items, mode="Quote"):
        assert mode == "Quote"
        if self.refused_unsubscribe.intersection(row["symbol"] for row in items):
            return {"status": "error"}
        self.subscriptions.difference_update(row["symbol"] for row in items)
        return {"status": "success"}

    def disconnect(self):
        self.closed = True
        self.subscriptions.clear()


@pytest.fixture
def contracts(tmp_path, monkeypatch):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'master.db'}")
    symbols.SymToken.__table__.create(engine)
    monkeypatch.setattr(symbols, "engine", engine)
    with engine.begin() as connection:
        for name, strike, side in ((CALL, 125000, "CE"), (PUT, 125000, "PE"),
                                  (NEXT_CALL, 125500, "CE"), (NEXT_PUT, 125500, "PE"),
                                  (THIRD_CALL, 126000, "CE"), (THIRD_PUT, 126000, "PE")):
            connection.execute(symbols.SymToken.__table__.insert().values(
                symbol=name, name="SILVERM", exchange="MCX", brexchange="mcx_fo",
                brsymbol=name, token=name, expiry="26-NOV-26", strike=strike,
                instrumenttype=side, lotsize=5, tick_size=0.5,
            ))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at(4, 10).astimezone(tz) if tz else at(4, 10).replace(tzinfo=None)
    monkeypatch.setattr(mcx, "datetime", Clock)
    monkeypatch.setattr(mcx, "_verified_connection", lambda key, pin: key == "key" and pin == "pin")
    monkeypatch.setattr(mcx, "_is_current_future", lambda symbol: symbol == FUTURE)
    yield engine
    engine.dispose()


@pytest.fixture
def collector(tmp_path, contracts):
    candles = mcx.McxCandleStore(f"sqlite:///{tmp_path / 'candles.db'}")
    ws = Socket()
    collector = mcx.KotakMcxStreamCollector(
        "pin", "key", candles, ws_factory=lambda _key: ws, start_worker=False,
    )
    yield collector, ws
    collector.close()


def test_verified_option_is_subscribed_and_produces_native_premium_candles(collector):
    stream, ws = collector
    assert stream.ensure(CALL) == "Collecting history"
    assert ws.subscriptions == {CALL}
    for minute in range(5):
        ws.callbacks["market_data"](packet(CALL, minute))
        stream.drain_once()

    result = stream.store.history("pin", CALL, "1m", "2026-09-25", "2026-09-25", at(4, 10))
    assert result["readiness"] == "Ready"
    assert result["data"] == [
        {"timestamp": int(at(minute).timestamp()), "open": 100.0 + minute,
         "high": 100.0 + minute, "low": 100.0 + minute, "close": 100.0 + minute,
         "volume": 10.0, "oi": None} for minute in (1, 2, 3)
    ]


def test_public_option_history_uses_same_verified_collector(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    result = mcx.get_kotak_mcx_history("key", "pin", CALL, "1m", "2026-09-25", "2026-09-25")

    assert result["status"] == "collecting_history"
    assert ws.subscriptions == {CALL}


def test_collector_owns_socket_without_touching_shared_consumers(tmp_path, contracts, monkeypatch):
    from services import websocket_client

    shared, owned = Socket(), Socket()
    shared.subscriptions.add("EXTERNAL")
    monkeypatch.setattr(websocket_client, "get_websocket_client", lambda _key: shared)
    monkeypatch.setattr(websocket_client, "WebSocketClient", lambda *_a, **_k: owned)
    candles = mcx.McxCandleStore(f"sqlite:///{tmp_path / 'owned.db'}")
    stream = mcx.KotakMcxStreamCollector("pin", "key", candles, start_worker=False)
    try:
        assert stream.ensure(FUTURE) == "Collecting history"
        assert owned.subscriptions == {FUTURE}
        assert shared.subscriptions == {"EXTERNAL"}
    finally:
        stream.close()
    assert owned.closed
    assert not shared.closed
    assert owned.callbacks == {}


def test_warmup_rotates_exact_pair_preserving_future_and_subscription_bound(collector, monkeypatch):
    stream, ws = collector
    # With room for only one pair, eviction must still honor the hard ceiling.
    monkeypatch.setattr(stream, "MAX_SYMBOLS", 3)
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    assert stream.ensure(FUTURE) == "Collecting history"
    first = mcx.warm_kotak_mcx_options("key", "pin", [CALL, PUT])
    assert first["status"] == "collecting_history"
    assert ws.subscriptions == {FUTURE, CALL, PUT}
    # Queued packets from a removed option may not re-establish its coverage.
    ws.callbacks["market_data"](packet(CALL, 0))
    second = mcx.warm_kotak_mcx_options("key", "pin", [NEXT_CALL, NEXT_PUT])
    assert second["status"] == "collecting_history"
    stream.drain_once()
    assert ws.subscriptions == {FUTURE, NEXT_CALL, NEXT_PUT}
    assert stream.store.history("pin", CALL, "1m", "2026-09-25", "2026-09-25", at(4))["data"] == []
    for index in range(25):
        pair = [CALL, PUT] if index % 2 else [NEXT_CALL, NEXT_PUT]
        mcx.warm_kotak_mcx_options("key", "pin", pair)
        assert ws.subscriptions == {FUTURE, *pair}
        assert len(stream._symbols) == 3
        assert len(stream.store._active_keys) <= 3


def test_atm_oscillation_keeps_observed_option_candles_ready(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    stream.ensure(FUTURE)
    for pair in ([CALL, PUT], [NEXT_CALL, NEXT_PUT]):
        mcx.warm_kotak_mcx_options("key", "pin", pair)
    for minute in range(5):
        pair = [CALL, PUT] if minute % 2 else [NEXT_CALL, NEXT_PUT]
        mcx.warm_kotak_mcx_options("key", "pin", pair)
        for symbol in tuple(ws.subscriptions):
            ws.callbacks["market_data"](packet(symbol, minute))
        stream.drain_once()
    # Switching ATM back must not reset three completed native premium bars.
    for pair in ([CALL, PUT], [NEXT_CALL, NEXT_PUT]):
        result = mcx.warm_kotak_mcx_options("key", "pin", pair)
        assert result["readiness"] == "Ready"
        assert result["symbols"] == pair
    assert ws.subscriptions == {FUTURE, CALL, PUT, NEXT_CALL, NEXT_PUT}


def test_third_atm_pair_evicts_oldest_and_discards_queued_old_ticks(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    stream.ensure(FUTURE)
    for pair in ([CALL, PUT], [NEXT_CALL, NEXT_PUT]):
        mcx.warm_kotak_mcx_options("key", "pin", pair)
    ws.callbacks["market_data"](packet(CALL, 0))
    mcx.warm_kotak_mcx_options("key", "pin", [THIRD_CALL, THIRD_PUT])
    stream.drain_once()
    assert ws.subscriptions == {FUTURE, NEXT_CALL, NEXT_PUT, THIRD_CALL, THIRD_PUT}
    assert stream.store.history("pin", CALL, "1m", "2026-09-25", "2026-09-25", at(4))["data"] == []
    assert len(stream._symbols) == 5


def test_warmup_ready_requires_three_recent_closed_candles_for_both_options(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    def warm():
        return mcx.warm_kotak_mcx_options("key", "pin", [CALL, PUT])
    assert warm()["readiness"] == "Collecting history"
    for minute in range(4):
        for option in (CALL, PUT):
            ws.callbacks["market_data"](packet(option, minute))
        stream.drain_once()
    assert warm()["readiness"] == "Collecting history"
    for option in (CALL, PUT):
        ws.callbacks["market_data"](packet(option, 4))
    stream.drain_once()
    assert warm()["readiness"] == "Ready"
    ws.callbacks["auth"]({"status": "success"})
    stream.drain_once()
    assert warm()["readiness"] == "Collecting history"


@pytest.mark.parametrize("values", [
    {"exchange": "NFO"}, {"instrumenttype": "FUT"}, {"instrumenttype": "PE"},
    {"expiry": "24-SEP-26"}, {"expiry": "27-NOV-26"}, {"strike": 125500},
    {"token": ""}, {"brexchange": "nse_fo"}, {"lotsize": 0}, {"tick_size": 0},
    {"name": "SILVER"},
])
def test_invalid_option_master_evidence_never_subscribes(collector, contracts, values):
    stream, ws = collector
    with contracts.begin() as connection:
        connection.execute(symbols.SymToken.__table__.update().where(
            symbols.SymToken.symbol == CALL
        ).values(**values))
    assert stream.ensure(CALL) == "Data unavailable"
    assert ws.subscriptions == set()


def test_mismatched_warmup_pair_is_rejected_without_subscriptions(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    for pair in ([CALL, NEXT_PUT], [CALL, CALL], [CALL], [CALL, PUT, NEXT_CALL]):
        assert mcx.warm_kotak_mcx_options("key", "pin", pair)["readiness"] == "Data unavailable"
    assert ws.subscriptions == set()


def test_refused_pair_unsubscribe_does_not_grow_subscriptions(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(stream, "MAX_SYMBOLS", 2)
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    mcx.warm_kotak_mcx_options("key", "pin", [CALL, PUT])
    ws.refused_unsubscribe.update((CALL, PUT))
    assert mcx.warm_kotak_mcx_options("key", "pin", [NEXT_CALL, NEXT_PUT])["readiness"] == "Data unavailable"
    assert ws.subscriptions == {CALL, PUT}


def test_warmup_respects_existing_symbol_ceiling(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    monkeypatch.setattr(stream, "MAX_SYMBOLS", 2)
    stream.ensure(FUTURE)
    assert mcx.warm_kotak_mcx_options("key", "pin", [CALL, PUT])["readiness"] == "Risk blocked"
    assert ws.subscriptions == {FUTURE}


@pytest.mark.parametrize("bad", [
    {"ltt": None}, {"volume_fresh": False}, {"volume": 1},
    {"ltt": int(at(7).timestamp())},
])
def test_option_quality_failure_requires_fresh_warmup(collector, bad):
    stream, ws = collector
    assert stream.ensure(CALL) == "Collecting history"
    for minute in range(5):
        ws.callbacks["market_data"](packet(CALL, minute))
        stream.drain_once()
    ws.callbacks["market_data"](packet(CALL, 4, 20, **bad))
    stream.drain_once()
    assert stream.store.history("pin", CALL, "1m", "2026-09-25", "2026-09-25", at(4, 30))["data"] == []


@pytest.mark.parametrize("broken", ["unauthenticated", "callback_failure"])
def test_new_owned_client_is_closed_when_setup_fails(tmp_path, contracts, monkeypatch, broken):
    from services import websocket_client

    owned = Socket()
    if broken == "unauthenticated":
        owned.authenticated = False
    else:
        def fail_callback(*_args):
            raise RuntimeError("callback failed")
        owned.register_callback = fail_callback
    monkeypatch.setattr(websocket_client, "WebSocketClient", lambda *_a, **_k: owned)
    candles = mcx.McxCandleStore(f"sqlite:///{tmp_path / 'failed-client.db'}")
    stream = mcx.KotakMcxStreamCollector("pin", "key", candles, start_worker=False)
    try:
        assert stream.ensure(FUTURE) == "Data unavailable"
        assert owned.closed
    finally:
        stream.close()


def test_owned_close_releases_client_even_if_callback_cleanup_raises(tmp_path, contracts, monkeypatch):
    from services import websocket_client

    owned = Socket()
    monkeypatch.setattr(websocket_client, "WebSocketClient", lambda *_a, **_k: owned)
    candles = mcx.McxCandleStore(f"sqlite:///{tmp_path / 'failed-close.db'}")
    stream = mcx.KotakMcxStreamCollector("pin", "key", candles, start_worker=False)
    assert stream.ensure(FUTURE) == "Collecting history"
    def fail_unregister(*_args):
        raise RuntimeError("callback cleanup failed")
    owned.unregister_callback = fail_unregister

    stream.close()

    assert owned.closed
    assert stream._symbols == set()


def test_ambiguous_master_contract_never_subscribes(collector, contracts):
    stream, ws = collector
    with contracts.begin() as connection:
        row = dict(connection.execute(symbols.SymToken.__table__.select().where(
            symbols.SymToken.symbol == CALL
        )).mappings().one())
        row.pop("id")
        connection.execute(symbols.SymToken.__table__.insert().values(**row))
    assert stream.ensure(CALL) == "Data unavailable"
    assert ws.subscriptions == set()


def test_warmup_pin_mismatch_never_touches_subscriptions(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    assert mcx.warm_kotak_mcx_options("other-key", "pin", [CALL, PUT])["readiness"] == "Risk blocked"
    assert mcx.warm_kotak_mcx_options("key", "other-pin", [CALL, PUT])["readiness"] == "Risk blocked"
    assert ws.subscriptions == set()


def test_option_queue_overflow_discards_coverage(collector):
    stream, ws = collector
    assert stream.ensure(CALL) == "Collecting history"
    for minute in range(5):
        ws.callbacks["market_data"](packet(CALL, minute))
        stream.drain_once()
    stream._overflow = True
    ws.callbacks["market_data"](packet(CALL, 4, 20))
    stream.drain_once()
    assert stream.store.history("pin", CALL, "1m", "2026-09-25", "2026-09-25", at(4, 30))["data"] == []


def test_rotating_back_cannot_reuse_queued_packets_from_previous_subscription(collector, monkeypatch):
    stream, ws = collector
    monkeypatch.setattr(stream, "MAX_SYMBOLS", 2)
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    mcx.warm_kotak_mcx_options("key", "pin", [CALL, PUT])
    for minute in range(5):
        ws.callbacks["market_data"](packet(CALL, minute))
    mcx.warm_kotak_mcx_options("key", "pin", [NEXT_CALL, NEXT_PUT])
    mcx.warm_kotak_mcx_options("key", "pin", [CALL, PUT])
    stream.drain_once()

    result = stream.store.history("pin", CALL, "1m", "2026-09-25", "2026-09-25", at(4, 10))
    assert result["data"] == []
    assert result["readiness"] == "Collecting history"


def test_repeated_pair_rotation_releases_db_connections(collector, contracts, monkeypatch):
    from sqlalchemy import event

    stream, _ws = collector
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    checked_out = set()

    def checkout(connection, _record, _proxy):
        checked_out.add(id(connection))

    def checkin(connection, _record):
        checked_out.discard(id(connection))

    engines = (contracts, stream.store.engine)
    for engine in engines:
        event.listen(engine, "checkout", checkout)
        event.listen(engine, "checkin", checkin)
    try:
        for index in range(100):
            pair = [CALL, PUT] if index % 2 else [NEXT_CALL, NEXT_PUT]
            assert mcx.warm_kotak_mcx_options("key", "pin", pair)["readiness"] == "Collecting history"
            assert not checked_out
    finally:
        for engine in engines:
            event.remove(engine, "checkout", checkout)
            event.remove(engine, "checkin", checkin)


def test_terminal_owned_socket_recovers_with_fresh_history(tmp_path, contracts, monkeypatch):
    from services import websocket_client

    old, replacement = Socket(), Socket()
    clients = iter((old, replacement))
    monkeypatch.setattr(websocket_client, "WebSocketClient", lambda *_a, **_k: next(clients))
    stream = mcx.KotakMcxStreamCollector(
        "pin", "key", mcx.McxCandleStore(f"sqlite:///{tmp_path / 'recovery.db'}"), start_worker=False,
    )
    monkeypatch.setattr(mcx, "_collectors", {"pin": stream})
    try:
        assert stream.ensure(FUTURE) == "Collecting history"
        assert mcx.warm_kotak_mcx_options("key", "pin", [CALL, PUT])["readiness"] == "Collecting history"
        for minute in range(5):
            for symbol in (FUTURE, CALL, PUT):
                old.callbacks["market_data"](packet(symbol, minute))
            stream.drain_once()
        assert mcx.warm_kotak_mcx_options("key", "pin", [CALL, PUT])["readiness"] == "Ready"
        # Retries exhausted, but the dispatch worker's running flag remains true.
        old.connected = old.authenticated = False
        old.running = True
        old.loop = SimpleNamespace(is_closed=lambda: True)
        old.thread = SimpleNamespace(is_alive=lambda: False)
        old.refused_unsubscribe = {CALL, PUT}
        for minute in range(5):
            old.callbacks["market_data"](packet(CALL, minute))

        assert mcx.warm_kotak_mcx_options("key", "pin", [NEXT_CALL, NEXT_PUT])["readiness"] == "Collecting history"
        assert old.closed
        assert old.callbacks == {}
        assert replacement.subscriptions == {NEXT_CALL, NEXT_PUT}
        assert stream.ensure(FUTURE) == "Collecting history"
        assert stream.ensure(CALL) == "Collecting history"
        stream.drain_once()
        for symbol in (FUTURE, CALL, PUT):
            assert stream.store.history("pin", symbol, "1m", "2026-09-25", "2026-09-25", at(4, 10))["data"] == []
    finally:
        stream.close()


def test_temporarily_disconnected_owned_socket_keeps_reconnecting(tmp_path, contracts, monkeypatch):
    from services import websocket_client

    old = Socket()
    clients = iter((old,))
    monkeypatch.setattr(websocket_client, "WebSocketClient", lambda *_a, **_k: next(clients))
    stream = mcx.KotakMcxStreamCollector(
        "pin", "key", mcx.McxCandleStore(f"sqlite:///{tmp_path / 'retry.db'}"), start_worker=False,
    )
    try:
        assert stream.ensure(FUTURE) == "Collecting history"
        old.connected = old.authenticated = False
        old.running = True
        old.loop = SimpleNamespace(is_closed=lambda: False)
        old.thread = SimpleNamespace(is_alive=lambda: True)
        assert stream.ensure(FUTURE) == "Data unavailable"
        assert not old.closed
        assert stream._ws is old
        old.connected = old.authenticated = True
        assert stream.ensure(FUTURE) == "Collecting history"
    finally:
        stream.close()


def test_failed_terminal_replacement_closes_both_clients_and_discards_history(tmp_path, contracts, monkeypatch):
    from services import websocket_client

    old, failed, recovered = Socket(), Socket(), Socket()
    failed.connect = lambda: False
    clients = iter((old, failed, recovered))
    monkeypatch.setattr(websocket_client, "WebSocketClient", lambda *_a, **_k: next(clients))
    stream = mcx.KotakMcxStreamCollector(
        "pin", "key", mcx.McxCandleStore(f"sqlite:///{tmp_path / 'failed-recovery.db'}"), start_worker=False,
    )
    try:
        assert stream.ensure(CALL) == "Collecting history"
        for minute in range(5):
            old.callbacks["market_data"](packet(CALL, minute))
            stream.drain_once()
        old.connected = old.authenticated = False
        old.thread = SimpleNamespace(is_alive=lambda: False)
        assert stream.ensure(CALL) == "Data unavailable"
        assert old.closed and failed.closed
        assert not old.callbacks
        assert stream._ws is None
        assert stream.store.history("pin", CALL, "1m", "2026-09-25", "2026-09-25", at(4, 10))["data"] == []
        assert stream.ensure(CALL) == "Collecting history"
        assert recovered.subscriptions == {CALL}
    finally:
        stream.close()


def test_terminal_real_client_cleanup_stops_dispatcher_without_closed_loop_schedule(tmp_path, contracts):
    import asyncio
    import threading

    from services.websocket_client import WebSocketClient

    ws = WebSocketClient("key")
    ws.loop = asyncio.new_event_loop()
    ws.loop.close()
    ws.ws = object()
    ws.running = True
    ws.active_subscriptions["old"] = object()
    ws.market_data_cache["old"] = object()
    ws._dispatch_thread = threading.Thread(target=ws._run_dispatch_loop, daemon=True)
    ws._dispatch_thread.start()
    stream = mcx.KotakMcxStreamCollector(
        "pin", "key", mcx.McxCandleStore(f"sqlite:///{tmp_path / 'cleanup.db'}"), start_worker=False,
    )
    stream._ws = ws
    ws.register_callback("market_data", stream._on_market_data)
    try:
        stream.close()
        assert not ws.running
        assert not ws._dispatch_thread.is_alive()
        assert ws.active_subscriptions == {}
        assert ws.market_data_cache == {}
        assert ws.callbacks["market_data"] == []
    finally:
        ws.running = False
        ws._dispatch_thread.join(timeout=1)


def test_repeated_terminal_recovery_releases_threads_clients_and_descriptors(tmp_path, contracts, monkeypatch):
    import asyncio
    import gc
    import threading
    import weakref

    import psutil

    from services import websocket_client

    client_type = websocket_client.WebSocketClient
    created = []

    def client_factory(*args):
        ws = client_type(*args)

        def connect():
            ws.running = ws.connected = ws.authenticated = True
            ws._dispatch_thread = threading.Thread(target=ws._run_dispatch_loop, daemon=True)
            ws._dispatch_thread.start()
            return True

        def subscribe(_items, mode):
            assert mode == "Quote"
            return {"status": "success"}

        # Replace only external transport operations; use real callback,
        # dispatcher and disconnect lifecycle without any network connection.
        ws.connect = connect
        ws.subscribe = subscribe
        created.append(weakref.ref(ws))
        return ws

    monkeypatch.setattr(websocket_client, "WebSocketClient", client_factory)
    stream = mcx.KotakMcxStreamCollector(
        "pin", "key", mcx.McxCandleStore(f"sqlite:///{tmp_path / 'repeated-recovery.db'}"), start_worker=False,
    )
    try:
        assert stream.ensure(CALL) == "Collecting history"
        gc.collect()
        baseline = psutil.Process().num_fds()
        for _ in range(100):
            old = stream._ws
            old.connected = old.authenticated = False
            old.loop = asyncio.new_event_loop()
            old.loop.close()
            old.ws = object()
            assert stream.ensure(CALL) == "Collecting history"
            assert not old._dispatch_thread.is_alive()
            assert not old.running
            assert not old.callbacks["market_data"]
            assert not old.callbacks["auth"]
        old = None
        gc.collect()
        assert sum(reference() is not None for reference in created) == 1
        assert psutil.Process().num_fds() <= baseline
    finally:
        stream.close()
