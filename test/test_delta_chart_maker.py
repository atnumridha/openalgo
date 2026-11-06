import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from test_delta_chart import FakeClient

from services.delta_chart.service import Rejected, Store, TradingService, digest


class MakerClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.orders = []

    def request(self, method, path, **kwargs):
        if method == "GET" and path.startswith("/v2/tickers/"):
            self.calls.append((method, path, None))
            return {
                "mark_price": "100",
                "close": "100",
                "quotes": {"best_bid": "99.5", "best_ask": "100.5"},
            }
        result = super().request(method, path, **kwargs)
        if method == "POST" and path == "/v2/orders":
            self.orders.append(
                dict(
                    kwargs["payload"],
                    id=len(self.orders) + 1,
                    state="pending",
                    unfilled_size=kwargs["payload"]["size"],
                )
            )
        return result

    def pages(self, path, params):
        return self.orders if path == "/v2/orders" else super().pages(path, params)


class MakerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = MakerClient()
        self.store = Store(Path(self.tmp.name) / "ledger.db")
        self.service = TradingService(
            self.store, lambda user: ("key", "secret"), lambda key, secret: self.client
        )
        initial = self.service.state("alice", "BTCUSD")
        self.account = initial["account"]
        self.position_version = initial["position"]["version"]

    def action(self, action, **kwargs):
        data = dict(
            request_id=str(uuid4()), symbol="BTCUSD", account=self.account, action=action, **kwargs
        )
        if action in ("close", "protect"):
            data["position_version"] = self.position_version
        return self.service.action("alice", data)

    def mutations(self):
        return [call for call in self.client.calls if call[0] != "GET"]

    def assert_maker(self, payload):
        self.assertEqual(payload["order_type"], "limit_order")
        self.assertIs(payload["post_only"], True)
        self.assertEqual(payload["time_in_force"], "gtc")

    def assert_market_exit(self, payload):
        self.assertEqual(payload["order_type"], "market_order")
        self.assertIs(payload["reduce_only"], True)
        self.assertNotIn("post_only", payload)
        self.assertNotIn("time_in_force", payload)
        self.assertNotIn("limit_price", payload)

    def add_order(self, **kwargs):
        order = dict(
            id=12,
            product_id=27,
            side="sell",
            size=2,
            unfilled_size=2,
            order_type="limit_order",
            limit_price="95",
            stop_price="95",
            stop_order_type="stop_loss_order",
            stop_trigger_method="mark_price",
            reduce_only=True,
            post_only=True,
            time_in_force="gtc",
            state="pending",
            **kwargs,
        )
        self.client.orders.append(order)
        return order

    def test_entry_defaults_to_maker_limit(self):
        self.client.size = 0  # New entries now require a flat account.
        self.action("entry", side="buy", size=1, price=99.5)
        payload = self.mutations()[0][2]
        self.assert_maker(payload)
        self.assertFalse(payload["reduce_only"])

    def test_entry_explicit_market_rejected(self):
        with self.assertRaises(Rejected):
            self.action("entry", side="buy", size=1, order_type="market_order", price=99.5)
        self.assertEqual(self.mutations(), [])

    def test_entry_price_is_required(self):
        with self.assertRaises(Rejected):
            self.action("entry", side="buy", size=1)
        self.assertEqual(self.mutations(), [])

    def test_entry_attached_brackets_rejected(self):
        for field, value in [("stop", 95), ("target", 110)]:
            with self.subTest(field=field):
                with self.assertRaises(Rejected):
                    self.action("entry", side="buy", size=1, price=99.5, **{field: value})
        self.assertEqual(self.mutations(), [])

    def test_close_is_reviewed_reduce_only_market(self):
        self.action("close", price=100.5)
        payload = self.mutations()[0][2]
        self.assert_market_exit(payload)
        self.assertTrue(payload["reduce_only"])
        self.assertNotIn("limit_price", payload)
        self.assertEqual(payload["side"], "sell")
        self.assertEqual(payload["size"], 2)

    def test_close_requires_no_price_but_rejects_limit_order_type(self):
        with self.assertRaises(Rejected):
            self.action("close", order_type="limit_order")
        self.assertEqual(self.mutations(), [])
        self.action("close")
        self.assert_market_exit(self.mutations()[-1][2])

    def test_stop_is_single_reduce_only_market(self):
        self.action("protect", stop=95)
        method, path, payload = self.mutations()[0]
        self.assertEqual(path, "/v2/orders")
        self.assert_market_exit(payload)
        self.assertTrue(payload["reduce_only"])
        self.assertEqual(payload["side"], "sell")
        self.assertEqual(payload["size"], 2)
        self.assertEqual(payload["stop_order_type"], "stop_loss_order")
        self.assertEqual(payload["stop_price"], "95")
        self.assertEqual(payload["stop_trigger_method"], "mark_price")
        self.assertEqual(len(self.mutations()), 1)

    def test_stop_and_target_separate_requests_allowed(self):
        self.action("protect", stop=95)
        self.action("protect", target=110)
        self.assertEqual(len(self.mutations()), 2)
        self.assertEqual(
            [x[2]["stop_order_type"] for x in self.mutations()],
            ["stop_loss_order", "take_profit_order"],
        )
        self.assert_market_exit(self.mutations()[0][2])
        self.assert_maker(self.mutations()[1][2])

    def test_combined_guards_rejected(self):
        with self.assertRaises(Rejected):
            self.action("protect", stop=95, target=110)
        self.assertEqual(self.mutations(), [])

    def test_duplicate_guard_kind_rejected(self):
        self.action("protect", stop=95)
        with self.assertRaises(Rejected):
            self.action("protect", stop=90)
        self.assertEqual(len(self.mutations()), 1)

    def test_protective_edit_keeps_trigger_and_limit_equal_and_maker(self):
        order = self.add_order()
        self.action("edit", order_id="12", version=digest(order), price=96)
        method, path, payload = self.mutations()[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(path, "/v2/orders")
        self.assertIs(payload["post_only"], True)
        self.assertNotIn("order_type", payload)
        self.assertNotIn("time_in_force", payload)
        self.assertEqual(payload["stop_price"], "96")
        self.assertEqual(payload["limit_price"], "96")
        self.assertTrue(payload["reduce_only"])

    def test_existing_market_stop_edits_only_trigger(self):
        order = self.add_order()
        order["order_type"] = "market_order"
        order["post_only"] = False
        self.action("edit", order_id="12", version=digest(order), price=96)
        payload = self.mutations()[-1][2]
        self.assertEqual(payload["stop_price"], "96")
        self.assertNotIn("limit_price", payload)
        self.assertNotIn("post_only", payload)

    def test_state_quotes_and_strict_post_only_flag(self):
        order = self.add_order()
        state = self.service.state("alice", "BTCUSD")
        self.assertEqual(state["ticker"]["bid"], 99.5)
        self.assertEqual(state["ticker"]["ask"], 100.5)
        self.assertIs(state["orders"][0]["post_only"], True)
        order["post_only"] = "true"
        self.assertIs(self.service.state("alice", "BTCUSD")["orders"][0]["post_only"], False)

    def test_short_close_is_reduce_only_market_buy(self):
        self.client.size = -2
        self.position_version = self.service.state("alice", "BTCUSD")["position"]["version"]
        self.action("close", price=99.5)
        payload = self.mutations()[0][2]
        self.assert_market_exit(payload)
        self.assertEqual(payload["side"], "buy")
        self.assertTrue(payload["reduce_only"])

    def test_short_stop_is_market_and_target_maker_buy(self):
        self.client.size = -2
        self.position_version = self.service.state("alice", "BTCUSD")["position"]["version"]
        self.action("protect", stop=105)
        self.action("protect", target=85)
        self.assert_market_exit(self.mutations()[0][2])
        self.assert_maker(self.mutations()[1][2])
        for call in self.mutations():
            self.assertEqual(call[2]["side"], "buy")
            self.assertTrue(call[2]["reduce_only"])

    def test_entry_edit_sets_post_only_without_undocumented_immutable_fields(self):
        order = {
            "id": 12,
            "product_id": 27,
            "side": "buy",
            "size": 1,
            "unfilled_size": 1,
            "order_type": "limit_order",
            "limit_price": "99",
            "reduce_only": False,
            "post_only": False,
            "time_in_force": "gtc",
            "state": "open",
        }
        self.client.orders.append(order)
        self.action("edit", order_id="12", version=digest(order), price=98)
        method, path, payload = self.mutations()[0]
        self.assertEqual(method, "PUT")
        self.assertIs(payload["post_only"], True)
        self.assertEqual(payload["limit_price"], "98")
        self.assertNotIn("order_type", payload)
        self.assertNotIn("time_in_force", payload)

    def test_ioc_order_edit_rejected(self):
        order = self.add_order()
        order["time_in_force"] = "ioc"
        with self.assertRaises(Rejected):
            self.action("edit", order_id="12", version=digest(order), price=96)
        self.assertEqual(self.mutations(), [])

    def test_old_market_orders_never_reported_maker(self):
        order = self.add_order()
        order["order_type"] = "market_order"
        state = self.service.state("alice", "BTCUSD")
        self.assertEqual(state["orders"][0]["type"], "market_order")
        self.assertIs(state["orders"][0]["post_only"], False)

    def test_explicit_post_only_false_cannot_disable_policy(self):
        self.client.size = 0  # New entries now require a flat account.
        self.action("entry", side="buy", size=1, price=99.5, post_only=False)
        self.assert_maker(self.mutations()[0][2])

    def test_protect_timeout_is_pending_without_retry(self):
        self.client.timeout = True
        result = self.action("protect", stop=95)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(len(self.mutations()), 1)
        with self.assertRaises(Rejected):
            self.action("protect", target=110)
        self.assertEqual(len(self.mutations()), 1)

    def test_post_only_rejection_is_rejected_without_retry_or_fallback(self):
        self.client.size = 0  # New entries now require a flat account.
        from services.delta_chart.service import exchange_error

        original = self.client.request

        def request(method, path, **kwargs):
            if method == "POST" and path == "/v2/orders":
                self.client.calls.append((method, path, kwargs["payload"]))
                raise exchange_error(
                    {
                        "error": {
                            "code": "immediate_execution_post_only",
                            "context": {"secret": "never-echo"},
                        }
                    }
                )
            return original(method, path, **kwargs)

        self.client.request = request
        with self.assertRaisesRegex(
            Rejected, "Maker-only order rejected because it would fill immediately"
        ):
            self.action("entry", side="buy", size=1, price=99.5)
        self.assertEqual(len(self.mutations()), 1)
        self.assert_maker(self.mutations()[0][2])
        state = self.service.state("alice", "BTCUSD")
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["receipts"][0]["status"], "rejected")
        self.assertNotIn("never-echo", state["receipts"][0]["message"])

    def test_api_post_only_error_mapping_redacts_context(self):
        from unittest.mock import Mock, patch

        from services.delta_chart.service import Client, DeltaError

        response = Mock(status_code=400, ok=False)
        response.json.return_value = {
            "success": False,
            "error": {"code": "immediate_execution_post_only", "context": {"secret": "never-echo"}},
        }
        with patch("services.delta_chart.service.requests.request", return_value=response):
            with self.assertRaises(DeltaError) as caught:
                Client("test-key", "test-secret").request(
                    "POST",
                    "/v2/orders",
                    payload={
                        "product_id": 27,
                        "side": "buy",
                        "size": 1,
                        "order_type": "limit_order",
                        "limit_price": "99.5",
                        "post_only": True,
                        "time_in_force": "gtc",
                    },
                )
        self.assertEqual(caught.exception.code, "immediate_execution_post_only")
        self.assertIn("Choose another limit price", str(caught.exception))
        self.assertNotIn("never-echo", str(caught.exception))
