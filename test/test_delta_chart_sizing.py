import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from test_delta_chart_maker import MakerClient

from services.delta_chart.service import (
    Rejected,
    Store,
    TradingService,
    affordable_contracts,
    build_sizing,
)

PRODUCT = {
    "id": 27,
    "symbol": "BTCUSD",
    "contract_type": "perpetual_futures",
    "notional_type": "vanilla",
    "settling_asset": {"id": 14, "symbol": "USD"},
    "contract_value": "0.001",
    "initial_margin": "0.5",
    "maker_commission_rate": "0.0002",
    "taker_commission_rate": "0.0005",
}
WALLET = [
    {
        "asset_id": 204,
        "asset_symbol": "INR",
        "available_balance": "999999",
        "balance": "999999",
    },
    {
        "asset_id": 14,
        "asset_symbol": "USD",
        "available_balance": "10",
        "available_balance_inr": "850",
        "balance": "999",
    },
]


class SizingMetadataTests(unittest.TestCase):
    def test_usd_available_balance_selected_without_inr_total_or_credit(self):
        sizing = build_sizing(PRODUCT, WALLET, "owner-account")
        self.assertEqual(sizing["available_balance"], 10)
        self.assertEqual(sizing["currency"], "USD")
        self.assertEqual(sizing["maker_fee_rate"], 0.0002)
        self.assertEqual(sizing["fee_tax_rate"], 0.18)

    def test_missing_available_balance_never_uses_total_balance(self):
        self.assertIsNone(
            build_sizing(
                PRODUCT,
                [{"asset_id": 14, "asset_symbol": "USD", "balance": "999"}],
                "owner-account",
            )
        )

    def test_unsupported_settlement_or_contract_disables_sizing(self):
        for product in (
            dict(PRODUCT, settling_asset={"id": 204, "symbol": "INR"}),
            dict(PRODUCT, notional_type="inverse"),
            dict(PRODUCT, maker_commission_rate=None),
        ):
            with self.subTest(product=product):
                self.assertIsNone(build_sizing(product, WALLET, "owner-account"))

    def test_asset_id_and_symbol_must_both_match(self):
        self.assertIsNone(
            build_sizing(
                PRODUCT,
                [{"asset_id": 204, "asset_symbol": "USD", "available_balance": "10"}],
                "owner-account",
            )
        )

    def test_budget_includes_margin_maker_fee_gst_and_one_percent_buffer(self):
        sizing = build_sizing(PRODUCT, WALLET, "owner-account")
        # At price 100, 5x, each contract costs .0200236 USD including entry fee+GST.
        self.assertEqual(
            affordable_contracts(
                sizing, Decimal("100"), Decimal("0.001"), Decimal("5"), Decimal("1")
            ),
            494,
        )
        self.assertEqual(
            affordable_contracts(
                sizing, Decimal("100"), Decimal("0.001"), Decimal("5"), Decimal(".25")
            ),
            123,
        )

    def test_version_changes_when_available_balance_or_fee_changes(self):
        first = build_sizing(PRODUCT, WALLET, "owner-account")
        other = build_sizing(PRODUCT, [dict(WALLET[1], available_balance="11")], "owner-account")
        fees = build_sizing(dict(PRODUCT, maker_commission_rate="0.0003"), WALLET, "owner-account")
        self.assertNotEqual(first["version"], other["version"])
        self.assertNotEqual(first["version"], fees["version"])

    def test_zero_available_affords_zero_contracts(self):
        sizing = build_sizing(PRODUCT, [dict(WALLET[1], available_balance="0")], "owner-account")
        self.assertEqual(
            affordable_contracts(
                sizing, Decimal("100"), Decimal("0.001"), Decimal("5"), Decimal("1")
            ),
            0,
        )


class SizingClient(MakerClient):
    def __init__(self):
        super().__init__()
        self.wallet_sequence = []
        self.wallet = "10"
        self.maker_sequence = []
        self.maker_rate = "0.0002"

    def request(self, method, path, **kwargs):
        if method == "GET" and path == "/v2/wallet/balances":
            self.calls.append((method, path, None))
            if self.wallet_sequence:
                self.wallet = self.wallet_sequence.pop(0)
            if self.wallet is None:
                return [{"asset_id": 14, "asset_symbol": "USD", "balance": "999"}]
            return [dict(WALLET[1], available_balance=self.wallet), WALLET[0]]
        result = super().request(method, path, **kwargs)
        if method == "GET" and path.startswith("/v2/products/BTC"):
            if self.maker_sequence:
                self.maker_rate = self.maker_sequence.pop(0)
            return dict(result, **dict(PRODUCT, maker_commission_rate=self.maker_rate))
        return result


class PercentageEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = SizingClient()
        self.client.size = 0
        self.service = TradingService(
            Store(Path(self.tmp.name) / "ledger.db"),
            lambda user: ("key", "secret"),
            lambda key, secret: self.client,
        )
        self.initial = self.service.state("alice", "BTCUSD")

    def entry(self, fraction=0.25, size=120, **kwargs):
        data = {
            "request_id": str(uuid4()),
            "symbol": "BTCUSD",
            "account": self.initial["account"],
            "action": "entry",
            "side": "buy",
            "size": size,
            "price": 99.5,
            "balance_fraction": fraction,
            "sizing_version": self.initial["sizing"]["version"],
        }
        data.update(kwargs)
        return self.service.action("alice", data)

    def mutations(self):
        return [call for call in self.client.calls if call[0] != "GET"]

    def test_state_exposes_supported_usd_sizing(self):
        self.assertEqual(self.initial["sizing"]["currency"], "USD")
        self.assertEqual(self.initial["sizing"]["available_balance"], 10)

    def test_reviewed_quantity_is_never_auto_increased(self):
        result = self.entry(size=1)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.mutations()[0][2]["size"], 1)
        self.assertIs(self.mutations()[0][2]["post_only"], True)

    def test_fraction_allowlist_rejects_other_percentages(self):
        for value in (0, 0.2, 0.3, 1.01, -1):
            with self.subTest(value=value):
                with self.assertRaises(Rejected):
                    self.entry(fraction=value)
        self.assertEqual(self.mutations(), [])

    def test_ten_percent_is_supported(self):
        self.assertEqual(self.entry(fraction=0.1, size=1)["status"], "confirmed")

    def test_fresh_balance_drop_rejects_before_order(self):
        self.client.wallet_sequence = ["10", "1"]
        with self.assertRaises(Rejected):
            self.entry()
        self.assertEqual(self.mutations(), [])

    def test_balance_drop_rejects_before_leverage_mutation(self):
        self.client.wallet_sequence = ["10", "1"]
        with self.assertRaises(Rejected):
            self.entry(leverage=10)
        self.assertEqual(self.mutations(), [])

    def test_balance_increase_requires_review_again(self):
        self.client.wallet_sequence = ["10", "11"]
        with self.assertRaises(Rejected):
            self.entry(size=1)
        self.assertEqual(self.mutations(), [])

    def test_zero_affordable_rejects(self):
        self.client.wallet = "0"
        self.initial = self.service.state("alice", "BTCUSD")
        with self.assertRaises(Rejected):
            self.entry(size=1)
        self.assertEqual(self.mutations(), [])

    def test_missing_sizing_disables_percent_but_allows_manual_entry(self):
        self.client.wallet = None
        state = self.service.state("alice", "BTCUSD")
        self.assertIsNone(state["sizing"])
        result = self.service.action(
            "alice",
            {
                "request_id": str(uuid4()),
                "symbol": "BTCUSD",
                "account": state["account"],
                "action": "entry",
                "side": "buy",
                "size": 1,
                "price": 99.5,
            },
        )
        self.assertEqual(result["status"], "confirmed")

    def test_percentage_budget_uses_fresh_ask_even_for_buy_limit(self):
        # 100% with price99.5 would afford496; mark100 affords494; ask100.5 affords491.
        with self.assertRaises(Rejected):
            self.entry(fraction=1, size=494)
        self.assertEqual(self.mutations(), [])

    def test_missing_sizing_version_rejected_without_mutation(self):
        with self.assertRaises(Rejected):
            self.entry(sizing_version=None)
        self.assertEqual(self.mutations(), [])

    def test_fee_change_rejects_before_leverage_mutation(self):
        self.client.maker_sequence = ["0.0002", "0.0003"]
        with self.assertRaises(Rejected):
            self.entry(size=1, leverage=10)
        self.assertEqual(self.mutations(), [])

    def test_fresh_quote_move_recomputes_affordability(self):
        original = self.client.request
        reads = {"ticker": 0}

        def request(method, path, **kwargs):
            if method == "GET" and path.startswith("/v2/tickers/"):
                reads["ticker"] += 1
                if reads["ticker"] >= 2:
                    return {
                        "mark_price": "100",
                        "close": "100",
                        "quotes": {"best_bid": "99.5", "best_ask": "200"},
                    }
            return original(method, path, **kwargs)

        self.client.request = request
        with self.assertRaises(Rejected):
            self.entry()
        self.assertEqual(self.mutations(), [])

    def test_default_five_times_leverage_preserved(self):
        self.entry(size=1)
        self.assertEqual([call[1] for call in self.mutations()], ["/v2/orders"])

    def test_wallet_read_failure_only_disables_sizing(self):
        original = self.client.request

        def request(method, path, **kwargs):
            if path == "/v2/wallet/balances":
                raise TimeoutError()
            return original(method, path, **kwargs)

        self.client.request = request
        state = self.service.state("alice", "BTCUSD")
        self.assertTrue(state["connected"])
        self.assertIsNone(state["sizing"])
