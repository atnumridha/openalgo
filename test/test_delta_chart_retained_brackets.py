import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from test_delta_chart import FakeClient

from services.delta_chart.service import Rejected, Store, TradingService, digest


class RetainedBracketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = FakeClient()
        self.store = Store(Path(self.temp.name) / "ledger.db")
        self.service = TradingService(
            self.store, lambda user: ("key", "secret"), lambda key, secret: self.client
        )
        self.account = self.service.state("alice", "BTCUSD")["account"]

    def edit(self, side, entry, stop, target, new_price, fresh_mark=None):
        order = {
            "id": 11,
            "product_id": 27,
            "side": side,
            "order_type": "limit_order",
            "size": 1,
            "unfilled_size": 1,
            "limit_price": str(entry),
            "bracket_stop_loss_price": stop,
            "bracket_take_profit_price": target,
            "reduce_only": False,
            "state": "open",
            "time_in_force": "gtc",
        }
        original_pages = self.client.pages
        self.client.pages = lambda path, params: (
            [order] if path == "/v2/orders" else original_pages(path, params)
        )
        if fresh_mark is not None:
            original = self.client.request
            reads = {"ticker": 0}

            def request(method, path, **kwargs):
                if path.startswith("/v2/tickers/"):
                    reads["ticker"] += 1
                    if reads["ticker"] >= 2:
                        return {"mark_price": str(fresh_mark), "close": str(fresh_mark)}
                return original(method, path, **kwargs)

            self.client.request = request
        return self.service.action(
            "alice",
            {
                "request_id": str(uuid4()),
                "symbol": "BTCUSD",
                "account": self.account,
                "action": "edit",
                "order_id": "11",
                "version": digest(order),
                "price": new_price,
            },
        )

    def assert_no_mutation(self):
        self.assertFalse(any(call[0] != "GET" for call in self.client.calls))

    def test_long_stop_cross_rejected(self):
        with self.assertRaises(Rejected):
            self.edit("buy", 90, "80", "110", 70)
        self.assert_no_mutation()

    def test_long_target_cross_rejected(self):
        with self.assertRaises(Rejected):
            self.edit("buy", 90, "80", "110", 120)
        self.assert_no_mutation()

    def test_short_stop_cross_rejected(self):
        with self.assertRaises(Rejected):
            self.edit("sell", 110, "120", "90", 130)
        self.assert_no_mutation()

    def test_short_target_cross_rejected(self):
        with self.assertRaises(Rejected):
            self.edit("sell", 110, "120", "90", 80)
        self.assert_no_mutation()

    def test_existing_attached_brackets_cannot_be_certified_maker_only(self):
        with self.assertRaisesRegex(Rejected, "Attached bracket exits cannot be maker-only"):
            self.edit("buy", 90, "80", "110", 85)
        self.assert_no_mutation()

    def test_unset_zero_and_null_guards_allow_edit(self):
        self.assertEqual(self.edit("buy", 90, 0, None, 85)["status"], "confirmed")

    def test_invalid_retained_metadata_fails_closed(self):
        for value in ("NaN", "Infinity", "bad", -1, "80.1"):
            with self.subTest(value=value):
                with self.assertRaises(Rejected):
                    self.edit("buy", 90, value, "110", 85)
        self.assert_no_mutation()

    def test_retained_guard_violated_by_fresh_mark_rejected(self):
        with self.assertRaises(Rejected):
            self.edit("buy", 90, "80", "110", 85, fresh_mark=70)
        self.assert_no_mutation()
