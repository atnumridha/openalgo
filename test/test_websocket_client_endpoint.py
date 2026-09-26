"""The internal client must connect to the configured proxy endpoint."""

from services import websocket_client


def test_ipv6_loopback_is_a_valid_websocket_url():
    client = websocket_client.WebSocketClient("test-key", "::1", 8766)
    assert client.ws_url == "ws://[::1]:8766"


def test_default_client_uses_configured_port_and_loopback_for_bind_address(monkeypatch):
    created = []

    class Client:
        def __init__(self, key, host, port):
            created.append((key, host, port))
            self.connected = True

        def connect(self):
            return True

        def disconnect(self):
            pass

    monkeypatch.setattr(websocket_client, "WebSocketClient", Client)
    monkeypatch.setenv("WEBSOCKET_HOST", "0.0.0.0")
    monkeypatch.setenv("WEBSOCKET_PORT", "8766")
    websocket_client.close_all_clients()
    try:
        websocket_client.get_websocket_client("test-endpoint-key")
        assert created == [("test-endpoint-key", "127.0.0.1", 8766)]
    finally:
        websocket_client.close_all_clients()


def test_endpoint_change_does_not_reuse_a_client_for_the_old_port(monkeypatch):
    created = []
    closed = []

    class Client:
        def __init__(self, key, host, port):
            self.endpoint = (host, port)
            self.connected = True
            created.append(self)

        def connect(self):
            return True

        def disconnect(self):
            closed.append(self.endpoint)

    monkeypatch.setattr(websocket_client, "WebSocketClient", Client)
    websocket_client.close_all_clients()
    try:
        first = websocket_client.get_websocket_client("test-endpoint-key", "127.0.0.1", 8765)
        second = websocket_client.get_websocket_client("test-endpoint-key", "127.0.0.1", 8766)
        assert first is not second
        assert [c.endpoint for c in created] == [("127.0.0.1", 8765), ("127.0.0.1", 8766)]
        assert closed == [("127.0.0.1", 8765)]
    finally:
        websocket_client.close_all_clients()
    assert closed == [("127.0.0.1", 8765), ("127.0.0.1", 8766)]
