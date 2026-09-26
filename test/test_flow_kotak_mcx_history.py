"""Flow's commodity history comes from the pinned Kotak stream only."""

from services.flow_openalgo_client import FlowOpenAlgoClient


def test_mcx_history_without_connection_pin_fails_closed(monkeypatch):
    from services import history_service, kotak_mcx_candles

    def broker_history(**_kwargs):
        raise AssertionError("Kotak's unsupported MCX history API was called")

    monkeypatch.setattr(history_service, "get_history", broker_history)
    monkeypatch.setattr(kotak_mcx_candles, "is_kotak_api_key", lambda _key: True)
    client = FlowOpenAlgoClient("api-key")
    response = client.get_history("SILVERM30NOV26FUT", "MCX", "5m", "2026-09-25", "2026-09-25")
    assert response["readiness"] == "Risk blocked"
    assert response["data"] == []


def test_pinned_kotak_mcx_history_uses_stream_collector(monkeypatch):
    from services import history_service, kotak_mcx_candles

    def broker_history(**_kwargs):
        raise AssertionError("Kotak's unsupported MCX history API was called")

    monkeypatch.setattr(history_service, "get_history", broker_history)
    monkeypatch.setattr(kotak_mcx_candles, "is_kotak_api_key", lambda _key: True)
    monkeypatch.setattr(kotak_mcx_candles, "get_kotak_mcx_history", lambda **kwargs: {
        "status": "collecting_history", "readiness": "Collecting history", "data": [],
        "symbol": kwargs["symbol"], "connection_id": kwargs["connection_id"],
    })
    client = FlowOpenAlgoClient("api-key")
    client.broker_connection_id = "kotak-1"
    response = client.get_history("SILVERM30NOV26FUT", "MCX", "5m", "2026-09-25", "2026-09-25")
    assert response["readiness"] == "Collecting history"
    assert response["connection_id"] == "kotak-1"


def test_non_kotak_mcx_does_not_mislabel_other_broker_candles(monkeypatch):
    from services import history_service, kotak_mcx_candles

    monkeypatch.setattr(kotak_mcx_candles, "is_kotak_api_key", lambda _key: False)
    monkeypatch.setattr(history_service, "get_history", lambda **_kwargs: (
        True, {"status": "success", "data": [{"timestamp": 123}]}, 200,
    ))
    client = FlowOpenAlgoClient("other-broker-key")
    client.broker_connection_id = "other-1"
    assert client.get_history("GOLDM30NOV26FUT", "MCX", "1m", "2026-09-25", "2026-09-25")["data"] == [{"timestamp": 123}]


def test_kotak_mcx_flow_rejects_historify_as_a_substitute_feed(monkeypatch):
    from services import history_service, kotak_mcx_candles

    monkeypatch.setattr(kotak_mcx_candles, "is_kotak_api_key", lambda _key: True)
    monkeypatch.setattr(history_service, "get_history", lambda **_kwargs: (
        _ for _ in ()).throw(AssertionError("Historify cannot authorize Kotak MCX entry"))
    )
    client = FlowOpenAlgoClient("kotak-key")
    client.broker_connection_id = "kotak-1"
    response = client.get_history("SILVERM30NOV26FUT", "MCX", "5m", "2026-09-25", "2026-09-25", source="db")
    assert response["readiness"] == "Risk blocked"
    assert response["data"] == []
