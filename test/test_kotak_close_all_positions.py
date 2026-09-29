"""Close-all reports order submission honestly when Kotak has not confirmed fills."""

import copy
from types import SimpleNamespace

from broker.kotak.api import order_api
from services import close_position_service
from subscribers import socketio_subscriber

POSITIONS = {
    "stat": "Ok",
    "data": [
        {
            "trdSym": "CRUDEOILM19OCT26FUT",
            "tok": "101",
            "exSeg": "mcx_fo",
            "prod": "MIS",
            "flBuyQty": "10",
            "flSellQty": "0",
            "cfBuyQty": "0",
            "cfSellQty": "0",
        },
        {
            "trdSym": "GOLDM05OCT26FUT",
            "tok": "102",
            "exSeg": "mcx_fo",
            "prod": "MIS",
            "flBuyQty": "0",
            "flSellQty": "100",
            "cfBuyQty": "0",
            "cfSellQty": "0",
        },
    ],
}


def test_kotak_close_all_reports_partial_submission_without_claiming_flat(monkeypatch):
    monkeypatch.setattr(order_api, "get_positions", lambda _auth: POSITIONS)
    monkeypatch.setattr(order_api, "get_symbol", lambda token, _exchange: {
        "101": "CRUDEOILM19OCT26FUT", "102": "GOLDM05OCT26FUT"
    }[token])
    submitted = []

    def place(payload, _auth):
        submitted.append(payload)
        if payload["symbol"] == "CRUDEOILM19OCT26FUT":
            return SimpleNamespace(status=200), {"stat": "Ok"}, "order-1"
        return SimpleNamespace(status=200), {"stat": "Not_Ok", "emsg": "rejected"}, None

    monkeypatch.setattr(order_api, "place_order_api", place)

    body, code = order_api.close_all_positions("key", "auth")

    assert code != 200
    assert body["status"] == "error"
    assert body["submitted_order_ids"] == ["order-1"]
    assert body["failed_count"] == 1
    assert "squared off" not in body["message"].lower()
    assert [(row["action"], row["quantity"]) for row in submitted] == [
        ("SELL", "10"), ("BUY", "100")
    ]


def test_kotak_close_all_success_means_submitted_not_filled(monkeypatch):
    positions = copy.deepcopy({**POSITIONS, "data": POSITIONS["data"][:1]})
    monkeypatch.setattr(order_api, "get_positions", lambda _auth: positions)
    monkeypatch.setattr(order_api, "get_symbol", lambda _token, _exchange: "CRUDEOILM19OCT26FUT")
    monkeypatch.setattr(
        order_api, "place_order_api",
        lambda _payload, _auth: (SimpleNamespace(status=200), {"stat": "Ok"}, "order-1"),
    )

    body, code = order_api.close_all_positions("key", "auth")

    assert code == 200
    assert body["submitted_order_ids"] == ["order-1"]
    assert "submitted" in body["message"].lower()
    assert "verify fills" in body["message"].lower()
    assert "squared off" not in body["message"].lower()
    assert positions["data"][0]["exSeg"] == "mcx_fo"


def test_kotak_close_all_empty_book_submits_nothing(monkeypatch):
    monkeypatch.setattr(order_api, "get_positions", lambda _auth: {"stat": "Ok", "data": []})
    monkeypatch.setattr(order_api, "place_order_api", lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected order")))

    body, code = order_api.close_all_positions("key", "auth")

    assert code == 200
    assert body == {"status": "success", "message": "No Open Positions Found", "submitted_order_ids": []}


def test_kotak_close_all_rejects_failed_position_read(monkeypatch):
    monkeypatch.setattr(order_api, "get_positions", lambda _auth: {
        "stat": "Not_Ok", "emsg": "session expired", "data": None
    })

    body, code = order_api.close_all_positions("key", "auth")

    assert code != 200
    assert body["status"] == "error"
    assert "position" in body["message"].lower()


def test_close_service_preserves_kotak_submission_message(monkeypatch):
    monkeypatch.setattr(close_position_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(
        close_position_service, "import_broker_module",
        lambda _broker: SimpleNamespace(close_all_positions=lambda _key, _auth: (
            {"status": "success", "message": "Close orders submitted; verify fills",
             "submitted_order_ids": ["order-1"]}, 200
        )),
    )
    events = []
    monkeypatch.setattr(close_position_service.bus, "publish", events.append)

    ok, body, code = close_position_service.close_position_with_auth({}, "auth", "kotak", {})

    assert (ok, code) == (True, 200)
    assert body["message"] == "Close orders submitted; verify fills"
    assert body["submitted_order_ids"] == ["order-1"]
    assert events[-1].message == body["message"]


def test_close_service_does_not_turn_broker_error_200_into_success(monkeypatch):
    monkeypatch.setattr(close_position_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(
        close_position_service, "import_broker_module",
        lambda _broker: SimpleNamespace(close_all_positions=lambda _key, _auth: (
            {"status": "error", "message": "One exit order failed",
             "submitted_order_ids": ["order-1"], "failed_count": 1}, 200
        )),
    )
    monkeypatch.setattr(close_position_service.bus, "publish", lambda _event: None)

    ok, body, code = close_position_service.close_position_with_auth({}, "auth", "kotak", {})

    assert ok is False
    assert code != 200
    assert body["message"] == "One exit order failed"
    assert body["submitted_order_ids"] == ["order-1"]
    assert body["failed_count"] == 1


def test_close_socket_reports_failed_submission_as_error(monkeypatch):
    sent = []
    monkeypatch.setattr(socketio_subscriber.socketio, "emit", lambda event, data: sent.append((event, data)))

    socketio_subscriber.on_position_closed(SimpleNamespace(
        mode="live", message="One exit order failed", response_data={"status": "error"}
    ))

    assert sent == [("close_position_event", {
        "status": "error", "message": "One exit order failed", "mode": "live"
    })]
