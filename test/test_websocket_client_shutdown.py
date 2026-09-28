"""Shutdown still releases client state after its reconnect loop terminates."""

import asyncio

import pytest

from services.websocket_client import WebSocketClient


@pytest.mark.parametrize("closes_during_schedule", [False, True])
def test_disconnect_cleans_up_after_event_loop_closes(monkeypatch, closes_during_schedule):
    client = WebSocketClient("test-key")
    loop = asyncio.new_event_loop()
    client.loop = loop
    client.ws = object()
    client.running = client.connected = client.authenticated = True
    client.active_subscriptions["MCX:OPTION"] = {}
    client.market_data_cache["MCX:OPTION"] = {"ltp": 100}
    if closes_during_schedule:
        def schedule(_callback):
            loop.close()
            raise RuntimeError("Event loop is closed")
        monkeypatch.setattr(loop, "call_soon_threadsafe", schedule)
    else:
        loop.close()
    try:
        client.disconnect()
        assert not client.running
        assert not client.connected
        assert not client.authenticated
        assert not client.active_subscriptions
        assert not client.market_data_cache
    finally:
        loop.close()
