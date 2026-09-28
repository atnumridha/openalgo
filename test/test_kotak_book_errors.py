"""Broker read failures must never look like an empty order/position book."""

import pytest

from broker.kotak.mapping import order_data


INVALID_SESSION = {
    "stCode": 100010,
    "errMsg": "invalid session token",
    "stat": "invalid session token",
}


@pytest.mark.parametrize("mapper", [order_data.map_order_data, order_data.map_position_data])
@pytest.mark.parametrize(
    "payload, message",
    [
        (INVALID_SESSION, "Kotak session is invalid or expired; reconnect the broker"),
        ({"stat": "Not_Ok", "emsg": "session expired", "data": None}, "Kotak rejected"),
        ({"stat": "Ok"}, "missing data"),
        ({"data": []}, "missing status"),
        ({"stat": "Ok", "data": {}}, "not a list"),
        ({"stat": "Ok", "data": [None]}, "invalid rows"),
        (None, "not an object"),
    ],
)
def test_failed_read_is_explicit_and_not_an_empty_book(mapper, payload, message):
    with pytest.raises(ValueError, match=message):
        mapper(payload)


@pytest.mark.parametrize("mapper", [order_data.map_order_data, order_data.map_position_data])
@pytest.mark.parametrize("data", [None, []])
def test_successful_empty_book_is_still_empty(mapper, data):
    assert not mapper({"stat": "Ok", "data": data})


@pytest.mark.parametrize("mapper", [order_data.map_order_data, order_data.map_position_data])
def test_successful_rows_still_resolve_symbols(monkeypatch, mapper):
    monkeypatch.setattr(order_data, "get_symbol", lambda *args: "CRUDEOILM19OCT26FUT")
    rows = mapper({"stat": "Ok", "data": [{"exSeg": "mcx_fo", "tok": "123"}]})
    assert rows == [{"exSeg": "MCX", "tok": "123", "trdSym": "CRUDEOILM19OCT26FUT"}]


@pytest.mark.parametrize("book", ["order", "position"])
def test_service_reports_session_failure_without_empty_success(monkeypatch, book):
    from database import settings_db
    from services import orderbook_service, positionbook_service

    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
    if book == "order":
        service = orderbook_service
        call = service.get_orderbook_with_auth
        funcs = {
            "get_order_book": lambda auth: dict(INVALID_SESSION),
            "map_order_data": order_data.map_order_data,
        }
    else:
        service = positionbook_service
        call = service.get_positionbook_with_auth
        funcs = {
            "get_positions": lambda auth: dict(INVALID_SESSION),
            "map_position_data": order_data.map_position_data,
        }
    monkeypatch.setattr(service, "import_broker_module", lambda broker: funcs)
    success, response, code = call("test-auth", "kotak")
    assert not success and code == 500
    assert response == {
        "status": "error",
        "message": "Kotak session is invalid or expired; reconnect the broker",
    }
