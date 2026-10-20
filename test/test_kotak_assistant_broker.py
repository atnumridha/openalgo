import pytest

from broker.kotak.mapping import transform_data as mapping


@pytest.mark.parametrize('underlying,exchange', [('NIFTY', 'NFO'), ('BANKNIFTY', 'NFO'), ('SENSEX', 'BFO')])
def test_metadata_preserves_supported_index_and_contract_sizes(monkeypatch, underlying, exchange):
    from types import SimpleNamespace
    from database import token_db, qty_freeze_db
    from services.kotak_assistant.broker import Gateway

    monkeypatch.setattr(token_db, 'get_symbol_info', lambda *a: SimpleNamespace(
        instrumenttype='CE', expiry='27-OCT-26', lotsize=35, tick_size=0.05,
    ))
    monkeypatch.setattr(qty_freeze_db, 'get_freeze_qty_for_option', lambda *a: 1050)
    gateway = object.__new__(Gateway)
    result = gateway.metadata(f'{underlying}27OCT2650000CE', exchange)
    assert result == {'underlying': underlying, 'expiry': '2026-10-27', 'lot': 35, 'tick': 0.05, 'freeze': 1050}


def test_banknifty_metadata_rejects_bse_contract_routing(monkeypatch):
    from types import SimpleNamespace
    from database import token_db
    from services.kotak_assistant.broker import Gateway

    monkeypatch.setattr(token_db, 'get_symbol_info', lambda *a: SimpleNamespace(instrumenttype='CE'))
    with pytest.raises(ValueError, match='Contract exchange mismatch'):
        object.__new__(Gateway).metadata('BANKNIFTY27OCT2650000CE', 'BFO')


def test_banknifty_ladder_looks_up_nse_index_options(monkeypatch):
    from services import option_chain_service
    from services.kotak_assistant.broker import Gateway

    calls = []
    chain = {'atm_strike': 50000, 'chain': [{'strike': 50000, 'ce': None, 'pe': None}]}
    def lookup(*args, **kwargs):
        calls.append((args, kwargs))
        return True, {'status': 'success', 'data': chain}, 200
    monkeypatch.setattr(option_chain_service, 'get_option_chain', lookup)
    gateway = object.__new__(Gateway)
    gateway.credentials = lambda: ('fixture', 'fixture')
    gateway.cached = lambda key, ttl, loader: loader()
    assert gateway.ladder('BANKNIFTY', '27OCT26', 8) == chain
    assert calls == [(('BANKNIFTY', 'NSE_INDEX', '27OCT26', 8, 'fixture'), {'with_quotes': True})]


def test_unique_internal_tag_retains_default_for_other_orders(monkeypatch):
    monkeypatch.setattr(mapping, "get_br_symbol", lambda *a: "NIFTYCE")
    payload = {
        "symbol": "NIFTYCE",
        "exchange": "NFO",
        "action": "BUY",
        "quantity": 65,
        "product": "MIS",
        "pricetype": "LIMIT",
        "price": 100,
    }
    assert mapping.transform_data(payload, "123")["ig"] == "openalgo"
    assert (
        mapping.transform_data({**payload, "_kotak_assistant_tag": "ka0123"}, "123")["ig"]
        == "ka0123"
    )


def test_gateway_normalizes_order_side_before_ownership_checks(monkeypatch):
    from broker.kotak.api import order_api
    from services import funds_service
    from services.kotak_assistant.broker import Gateway

    row = {
        "trdSym": "NIFTYCE",
        "exSeg": "nse_fo",
        "trnsTp": "B",
        "qty": "65",
        "avgPrc": "100",
        "trgPrc": "0",
        "prcTp": "L",
        "prod": "MIS",
        "nOrdNo": "1",
        "ordSt": "open",
        "GuiOrdId": "ka123",
    }
    monkeypatch.setattr(order_api, "get_order_book", lambda *a: {"stat": "Ok", "data": [row]})
    monkeypatch.setattr(order_api, "get_positions", lambda *a: {"stat": "Ok", "data": []})
    monkeypatch.setattr(order_api, "get_trade_book", lambda *a: {"stat": "Ok", "data": []})
    monkeypatch.setattr(
        funds_service,
        "get_funds_with_auth",
        lambda *a: (True, {"status": "success", "data": {"availablecash": 100000}}, 200),
    )
    g = object.__new__(Gateway)
    g.mode = "live"
    g.credentials = lambda: ("test", "test")
    g.cached = lambda k, ttl, loader: loader()
    assert g.books()["orders"][0]["action"] == "BUY"


def test_depth_tick_supplies_fresh_two_sided_quote():
    import threading

    from services.kotak_assistant.broker import Gateway

    g = object.__new__(Gateway)
    g._watched = {("NIFTYCE", "NFO")}
    g._ticks = {}
    g._lock = threading.RLock()
    g._tick(
        {
            "symbol": "NIFTYCE",
            "exchange": "NFO",
            "data": {"ltp": 100, "depth": {"buy": [{"price": 99.95}], "sell": [{"price": 100}]}},
        }
    )
    assert g._ticks[("NIFTYCE", "NFO")]["bid"] == 99.95


def test_slow_history_read_does_not_block_live_quote_cache():
    import threading

    from services.kotak_assistant.broker import Gateway

    g = object.__new__(Gateway)
    g._cache = {}
    g._lock = threading.RLock()
    g._flights = {}
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow():
        entered.set()
        release.wait(2)
        return []

    history = threading.Thread(target=lambda: g.cached("history", 60, slow))
    history.start()
    assert entered.wait(1)
    quote = threading.Thread(
        target=lambda: (g.cached("quote", 2, lambda: {"bid": 100}), finished.set())
    )
    quote.start()
    try:
        assert finished.wait(0.5)
    finally:
        release.set()
        history.join(2)
        quote.join(2)


def test_server_websocket_client_uses_configured_feed_endpoint(monkeypatch):
    from services import websocket_client as wc

    endpoints = []

    class Client:
        alive = True

        def __init__(self, key, host, port):
            endpoints.append((host, port))

        def connect(self):
            return True

    monkeypatch.setenv("WEBSOCKET_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBSOCKET_PORT", "8767")
    monkeypatch.setattr(wc, "WebSocketClient", Client)
    monkeypatch.setattr(wc, "_client_instances", {})
    monkeypatch.setattr(wc, "_pending_connects", {})
    wc.get_websocket_client("endpoint-test")
    assert endpoints == [("127.0.0.1", 8767)]


def test_documented_no_data_response_is_an_empty_book(monkeypatch):
    from broker.kotak.api import order_api
    from services import funds_service
    from services.kotak_assistant.broker import Gateway

    empty = {"stat": "Not_Ok", "stCode": 5203, "errMsg": "No Data", "desc": "data not found"}
    for name in ("get_order_book", "get_positions", "get_trade_book"):
        monkeypatch.setattr(order_api, name, lambda *a: dict(empty))
    monkeypatch.setattr(
        funds_service,
        "get_funds_with_auth",
        lambda *a: (True, {"status": "success", "data": {"availablecash": 100000}}, 200),
    )
    g = object.__new__(Gateway)
    g.mode = "live"
    g.credentials = lambda: ("test", "test")
    g.cached = lambda k, ttl, loader: loader()
    assert g.books() == {
        "orders": [],
        "positions": [],
        "fills": [],
        "cash": 100000,
        "time": pytest.approx(__import__("time").time(), abs=2),
    }


def test_lowercase_success_with_http_200_book_code_is_normalized(monkeypatch):
    from broker.kotak.api import order_api
    from services import funds_service
    from services.kotak_assistant.broker import Gateway

    for name in ("get_order_book", "get_positions", "get_trade_book"):
        monkeypatch.setattr(order_api, name, lambda *a: {"stat": "ok", "stCode": 200, "data": []})
    monkeypatch.setattr(funds_service, "get_funds_with_auth", lambda *a: (
        True, {"status": "success", "data": {"availablecash": 100000}}, 200
    ))
    g = object.__new__(Gateway)
    g.mode = "live"
    g.credentials = lambda: ("test", "test")
    g.cached = lambda k, ttl, loader: loader()
    books = g.books()
    assert books["orders"] == books["positions"] == books["fills"] == []


def test_read_only_books_do_not_require_or_fetch_account_funds(monkeypatch):
    from broker.kotak.api import order_api
    from services import funds_service
    from services.kotak_assistant.broker import Gateway

    for name in ('get_order_book', 'get_positions', 'get_trade_book'):
        monkeypatch.setattr(order_api, name, lambda *a: {'stat':'Ok', 'data':[]})
    def no_funds(*args):
        pytest.fail('Position monitoring must not depend on account funds')
    monkeypatch.setattr(funds_service, 'get_funds_with_auth', no_funds)
    gateway = object.__new__(Gateway)
    gateway.mode = 'live'
    gateway.credentials = lambda: ('fixture', 'fixture')
    gateway.cached = lambda key, ttl, loader: loader()
    books = gateway.books(include_cash=False)
    assert books['positions'] == books['fills'] == books['orders'] == []
    assert 'cash' not in books



@pytest.mark.parametrize(
    "raw",
    [
        {"stat": "Not_Ok", "stCode": 401, "errMsg": "Session expired"},
        {"stat": "ok", "stCode": 401, "data": []},
        {"stat": "Not_Ok", "stCode": 5203, "errMsg": "Session expired"},
        {"stat": "Ok", "data": None},
        {"stat": "Ok", "data": {}},
    ],
)
def test_failed_or_malformed_book_is_never_normalized_to_empty(monkeypatch, raw):
    from broker.kotak.api import order_api
    from services.kotak_assistant.broker import Gateway

    monkeypatch.setattr(order_api, "get_order_book", lambda *a: raw)
    g = object.__new__(Gateway)
    g.mode = "live"
    g.credentials = lambda: ("test", "test")
    with pytest.raises(ValueError, match="book read failed"):
        g.books()


def test_watch_replaces_a_stopped_feed_client(monkeypatch):
    import threading

    from services import websocket_client
    from services.kotak_assistant.broker import Gateway

    class Feed:
        alive = True

        def __init__(self):
            self.subscriptions = []

        def register_callback(self, *a):
            pass

        def subscribe(self, symbols, mode):
            self.subscriptions += symbols
            return {"status": "success"}

    old, replacement = Feed(), Feed()
    old.alive = False
    g = object.__new__(Gateway)
    g._ws, g._watched, g._lock = old, {("NIFTY", "NSE_INDEX")}, threading.RLock()
    g.credentials = lambda: ("test", "test")
    monkeypatch.setattr(websocket_client, "get_websocket_client", lambda *a: replacement)
    g.watch("NIFTY", "NSE_INDEX")
    assert replacement.subscriptions == [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]


@pytest.mark.parametrize(
    "http_status, body, expected_state, fragments",
    [
        (401, {"stat": "Not_Ok", "stCode": 100008, "errMsg": "unauthorized"},
         "rejected", ("100008", "HTTP 401", "IP", "whitelisted")),
        (401, {"stat": "Not_Ok", "stCode": 1037,
               "errMsg": "session ip doesnt match with reqest ip"},
         "rejected", ("1037", "different IP", "Reconnect")),
        (200, {"stat": "Not_Ok", "errMsg": "Insufficient margin"},
         "rejected", ("Insufficient margin",)),
        (400, {"stat": "Not_Ok", "emsg": "Invalid quantity"},
         "rejected", ("Invalid quantity",)),
        (503, {"stat": "Not_Ok", "errMsg": "Service unavailable"},
         "unknown", ("outcome unknown", "Service unavailable")),
        (200, None, "unknown", ("outcome unknown",)),
    ],
)
def test_live_submit_preserves_broker_error_and_outcome_certainty(
    monkeypatch, http_status, body, expected_state, fragments
):
    from types import SimpleNamespace

    from broker.kotak.api import order_api
    from database import settings_db
    from services.kotak_assistant.broker import Gateway

    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(order_api, "place_order_api", lambda *a: (
        SimpleNamespace(status_code=http_status), body, None
    ))
    g = object.__new__(Gateway)
    g.mode = "live"
    g.credentials = lambda: ("fixture", "fixture")
    result = g.submit({"action": "BUY", "tag": "fixture-tag"})
    assert result["state"] == expected_state
    for text in fragments:
        assert text in result["message"]
    assert result["http_status"] == http_status
    assert result["broker_code"] == (body or {}).get("stCode")
    if expected_state == "rejected":
        assert "outcome unknown" not in result["message"]
