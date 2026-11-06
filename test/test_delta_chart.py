import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from services.delta_chart.service import Rejected, Store, TradingService


class FakeClient:
    def __init__(self):
        self.calls = []
        self.timeout = False
        self.size = 2

    def request(self, method, path, params=None, payload=None, private=True):
        self.calls.append((method, path, payload))
        if method != "GET":
            if self.timeout:
                raise TimeoutError()
            return {"id": 44, "leverage": payload.get("leverage", 5)}
        if path.startswith("/v2/products/BTC"):
            return {
                "id": 27,
                "symbol": "BTCUSD",
                "contract_type": "perpetual_futures",
                "tick_size": "0.5",
                "contract_value": "0.001",
                "initial_margin": "0.5",
                "state": "live",
            }
        if path.startswith("/v2/tickers/"):
            return {"mark_price": "100", "close": "100"}
        if path == "/v2/positions":
            return {"size": self.size, "entry_price": "90"}
        if path == "/v2/positions/margined":
            return []
        if path.endswith("/leverage"):
            return {"leverage": 5}
        return []

    def pages(self, path, params):
        return self.request("GET", path, params=params)


class TradingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.db")
        self.client = FakeClient()
        self.service = TradingService(
            self.store, lambda user: ("key", "secret"), lambda k, s: self.client
        )
        initial = self.service.state("alice", "BTCUSD")
        self.account = initial["account"]
        self.initial_position_version = initial["position"]["version"]

    def tearDown(self):
        self.tmp.cleanup()

    def action(self, **kw):
        if kw.get("action") in ("entry", "close"):
            kw.setdefault("price", 99.5 if kw["action"] == "entry" else 100.5)
        if kw.get("action") in ("close", "protect") and "position_version" not in kw:
            kw["position_version"] = self.initial_position_version
        return self.service.action(
            "alice",
            dict(request_id=str(uuid4()), symbol="BTCUSD", account=self.account, **kw),
        )

    def test_close_uses_live_size_reduce_only(self):
        result = self.action(action="close")
        self.assertEqual(result["status"], "confirmed")
        payload = self.client.calls[-1][2]
        self.assertEqual(payload["size"], 2)
        self.assertTrue(payload["reduce_only"])
        self.assertEqual(payload["side"], "sell")

    def test_wrong_account_rejected_without_mutation(self):
        with self.assertRaises(Rejected):
            self.service.action(
                "alice",
                {
                    "request_id": str(uuid4()),
                    "symbol": "BTCUSD",
                    "account": "foreign",
                    "action": "close",
                },
            )
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls))

    def test_invalid_tick_and_leverage_rejected(self):
        for data in (
            {"price": 100.1, "leverage": 5},
            {"price": 100, "leverage": 201},
            {"price": float("nan"), "leverage": 5},
        ):
            with self.assertRaises(Rejected):
                self.action(action="entry", side="buy", size=1, order_type="limit_order", **data)
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls))

    def test_uuid_replay_payload_binding(self):
        data = {
            "request_id": str(uuid4()),
            "symbol": "BTCUSD",
            "account": self.account,
            "action": "close",
            "price": 100.5,
            "position_version": self.service.state("alice", "BTCUSD")["position"]["version"],
        }
        first = self.service.action("alice", data)
        n = len(self.client.calls)
        self.assertEqual(first, self.service.action("alice", data))
        self.assertEqual(n, len(self.client.calls))
        with self.assertRaises(Rejected):
            self.service.action("alice", dict(data, action="cancel", order_id="1"))

    def test_timeout_is_durable_pending_and_blocks_new_action(self):
        self.client.timeout = True
        result = self.action(action="close")
        self.assertEqual(result["status"], "pending")
        service = TradingService(
            Store(self.store.path),
            lambda u: ("key", "secret"),
            lambda k, s: self.client,
        )
        self.assertEqual(len(service.state("alice", "BTCUSD")["pending"]), 1)
        with self.assertRaises(Rejected):
            self.action(action="close")

    def test_stops_correct_side(self):
        with self.assertRaises(Rejected):
            self.action(action="protect", stop=101)

    def test_user_scope(self):
        self.assertNotEqual(self.account, self.service.state("bob", "BTCUSD")["account"])


if __name__ == "__main__":
    unittest.main()


class ReconciliationTests(TradingTests):
    def test_read_only_reconcile_timeout_by_client_id(self):
        self.client.timeout = True
        result = self.action(action="close")
        rid = result["request_id"]
        original = self.client.request

        def request(method, path, **kw):
            if path == "/v2/orders/client_order_id/" + rid.replace("-", ""):
                return {
                    "id": 88,
                    "product_id": 27,
                    "client_order_id": rid.replace("-", ""),
                    "state": "closed",
                }
            return original(method, path, **kw)

        self.client.request = request
        n = len(self.client.calls)
        state = self.service.state("alice", "BTCUSD")
        self.assertEqual(state["pending"], [])
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls[n:]))


class ProtectionTests(TradingTests):
    def test_position_protection_uses_single_market_stop(self):
        self.action(action="protect", stop=95)
        method, path, payload = self.client.calls[-1]
        self.assertEqual(path, "/v2/orders")
        self.assertEqual(payload["order_type"], "market_order")
        self.assertNotIn("post_only", payload)
        self.assertEqual(payload["stop_price"], "95")
        self.assertNotIn("limit_price", payload)

    def test_unknown_symbol_rejected(self):
        with self.assertRaises(Rejected):
            self.service.state("alice", "BTCUSD/../../orders")

    def test_existing_protection_cannot_be_overwritten(self):
        original = self.client.pages
        self.client.pages = lambda path, params: (
            [{"id": 1, "product_id": 27, "reduce_only": True}]
            if path == "/v2/orders"
            else original(path, params)
        )
        with self.assertRaises(Rejected):
            self.action(action="protect", stop=95)
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls))


class PositionBindingTests(TradingTests):
    def test_close_rejects_position_size_changed_since_review(self):
        self.client.size = 3
        with self.assertRaises(Rejected):
            self.action(action="close")
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls))

    def test_close_rejects_position_direction_changed_since_review(self):
        self.client.size = -2
        with self.assertRaises(Rejected):
            self.action(action="close")
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls))

    def test_close_rejects_wrong_reviewed_size(self):
        with self.assertRaises(Rejected):
            self.action(action="close", size=999)
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls))


class AdditionalSafetyTests(TradingTests):
    def test_stop_below_mark_but_above_limit_entry_rejected(self):
        with self.assertRaises(Rejected):
            self.action(
                action="entry",
                side="buy",
                size=1,
                order_type="limit_order",
                price=90,
                stop=95,
            )
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls))

    def test_reconciled_receipt_visible(self):
        result = self.action(action="close")
        self.assertEqual(
            self.service.state("alice", "BTCUSD")["receipts"][0]["request_id"],
            result["request_id"],
        )

    def test_stop_entry_is_not_position_protection(self):
        order = {
            "id": 1,
            "product_id": 27,
            "side": "buy",
            "size": 1,
            "unfilled_size": 1,
            "order_type": "market_order",
            "stop_order_type": "stop_loss_order",
            "stop_price": "110",
            "reduce_only": False,
            "bracket_order": "false",
        }
        original = self.client.pages
        self.client.pages = lambda path, params: (
            [order] if path == "/v2/orders" else original(path, params)
        )
        result = self.service.state("alice", "BTCUSD")["orders"][0]
        self.assertEqual(result["kind"], "entry")
        self.assertFalse(result["reduce_only"])

    def test_leverage_only_timeout_reconciles_without_entry(self):
        original = self.client.request
        changed = {"value": 5}
        self.client.size = 0

        def request(method, path, **kw):
            if path.endswith("/orders/leverage"):
                if method == "POST":
                    changed["value"] = 10
                    raise TimeoutError()
                return {"leverage": changed["value"]}
            return original(method, path, **kw)

        self.client.request = request
        result = self.action(action="entry", side="buy", size=1, leverage=10)
        self.assertEqual(result["status"], "pending")
        state = self.service.state("alice", "BTCUSD")
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["receipts"][0]["status"], "rejected")
        self.assertFalse(any(c[0] == "POST" and c[1] == "/v2/orders" for c in self.client.calls))


class ErrorRedactionTests(unittest.TestCase):
    def test_exchange_whitelist_error_does_not_expose_response_context(self):
        from unittest.mock import Mock, patch

        from services.delta_chart.service import Client, DeltaError

        response = Mock(status_code=401, ok=False)
        response.json.return_value = {
            "success": False,
            "error": {
                "code": "ip_not_whitelisted_for_api_key",
                "context": {"key": "never-print-key", "secret": "never-print-secret"},
            },
        }
        with patch("services.delta_chart.service.requests.request", return_value=response):
            with self.assertRaises(DeltaError) as caught:
                Client("test-key", "test-secret").request("GET", "/v2/positions")
        self.assertEqual(caught.exception.code, "ip_not_whitelisted_for_api_key")
        self.assertIn("server IP", str(caught.exception))
        self.assertNotIn("never-print", str(caught.exception))

    def test_unknown_exchange_error_is_generic(self):
        from services.delta_chart.service import exchange_error

        error = exchange_error(
            {"error": {"code": "secret-unsafe-string", "message": "sensitive-response"}}
        )
        self.assertIsNone(error.code)
        self.assertNotIn("sensitive", str(error))
        self.assertNotIn("secret", str(error))

    def test_only_validated_exchange_client_ip_is_shown(self):
        from services.delta_chart.service import exchange_error

        message = str(
            exchange_error(
                {
                    "error": {
                        "code": "ip_not_whitelisted_for_api_key",
                        "context": {"client_ip": "203.0.113.5", "unrelated": "hidden-secret"},
                    }
                }
            )
        )
        self.assertIn("203.0.113.5", message)
        self.assertNotIn("hidden-secret", message)
        invalid = str(
            exchange_error(
                {
                    "error": {
                        "code": "ip_not_whitelisted_for_api_key",
                        "context": {"client_ip": "not-an-ip-or-secret"},
                    }
                }
            )
        )
        self.assertNotIn("not-an-ip-or-secret", invalid)


class LeveragePreflightTests(TradingTests):
    def test_new_position_prevents_leverage_mutation(self):
        self.client.size = 0
        original = self.client.request
        reads = {"count": 0}

        def request(method, path, **kw):
            if method == "GET" and path == "/v2/positions":
                reads["count"] += 1
                if reads["count"] >= 2:
                    self.client.size = 2
            return original(method, path, **kw)

        self.client.request = request
        with self.assertRaises(Rejected):
            self.action(action="entry", side="buy", size=1, leverage=10)
        self.assertFalse(any(c[0] != "GET" for c in self.client.calls))
