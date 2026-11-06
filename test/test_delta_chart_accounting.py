import unittest
import time
from decimal import Decimal

from services.delta_chart.service import build_accounting

PRODUCT = {
    "id": 27,
    "symbol": "BTCUSD",
    "contract_type": "perpetual_futures",
    "notional_type": "vanilla",
    "settling_asset": {"id": 14, "symbol": "USD"},
    "contract_value": "0.001",
    "maker_commission_rate": "0.0002",
    "taker_commission_rate": "0.0005",
    "tick_size": "0.5",
}
WALLET = [
    {
        "asset_id": 204,
        "asset_symbol": "INR",
        "balance": "8500",
        "available_balance": "4250",
    },
    {
        "asset_id": 14,
        "asset_symbol": "USD",
        "balance": "100",
        "available_balance": "50",
    },
]


def fill(
    identity,
    side,
    size,
    after,
    price="90",
    fee="0.0236",
    cash=None,
    credit="0",
    entry=None,
    total_paid=None,
    when=None,
):
    entry = str(price) if entry is None else str(entry)
    row = {
        "id": identity,
        "product_id": 27,
        "settling_asset_symbol": "USD",
        "settling_asset_id": 14,
        "fill_type": "normal",
        "created_at": when or str(identity),
        "side": side,
        "size": str(size),
        "price": str(price),
        "commission": str(Decimal(fee) - Decimal(credit))
        if cash is None
        else str(cash),
        "meta_data": {
            "total_commission_in_settling_asset": str(fee),
            "tfc_used_for_commission": str(credit),
            "rack_commision": "0.0236",
            "rack_commission_without_gst": "0.02",
            "new_position": {
                "size": after,
                "entry_price": entry,
                "last_fill_uuid": identity,
                "total_commission_paid": str(fee)
                if total_paid is None
                else str(total_paid),
            },
        },
    }
    return row


class AccountingTests(unittest.TestCase):
    def report(
        self,
        position=None,
        fills=None,
        product=None,
        wallet=None,
        complete=True,
        gross=1,
    ):
        return build_accounting(
            product or PRODUCT,
            WALLET if wallet is None else wallet,
            position or {"size": 1, "entry_price": "90"},
            Decimal("100"),
            gross,
            fills or [],
            complete,
        )

    def test_verified_scalper_window_estimates_zero_but_preserves_standard_fee(self):
        now = time.time()
        product = dict(PRODUCT, _scalper_enabled=True)
        result = self.report(
            product=product, fills=[fill("1", "buy", 1, 1, when=str(now - 100))]
        )
        self.assertEqual(result["estimated_exit_fee"], 0)
        self.assertGreater(result["standard_exit_fee"], 0)
        self.assertAlmostEqual(result["scalper_fee_valid_until"], now - 100 + 1740)
        self.assertIn("estimate", result["message"].lower())

    def test_scalper_estimate_requires_current_optin_and_unexpired_proven_entry(self):
        for enabled, age, symbol in [
            (False, 100, "BTCUSD"),
            (True, 1741, "BTCUSD"),
            (True, 100, "XAUTUSD"),
        ]:
            result = self.report(
                product=dict(PRODUCT, _scalper_enabled=enabled, symbol=symbol),
                fills=[fill("1", "buy", 1, 1, when=str(time.time() - age))],
            )
            self.assertGreater(result["estimated_exit_fee"], 0)

    def test_wallet_is_reported_without_deducting_fees_again(self):
        result = self.report(fills=[fill("1", "buy", 1, 1)])
        self.assertEqual(result["balance"], 100)
        self.assertEqual(result["available_balance"], 50)

    def test_balances_available_when_maker_rate_missing_and_sizing_disabled(self):
        result = self.report(product=dict(PRODUCT, maker_commission_rate=None))
        self.assertEqual(result["balance"], 100)
        self.assertEqual(result["available_balance"], 50)
        self.assertIsNone(result["estimated_maker_exit_fee"])

    def test_verified_actual_entry_fees_and_estimated_exit_gst(self):
        result = self.report(fills=[fill("1", "buy", 1, 1)])
        self.assertEqual(result["fee_status"], "verified")
        self.assertAlmostEqual(result["position_entry_fees"], 0.0236)
        self.assertAlmostEqual(result["estimated_maker_exit_fee"], 0.0000236)
        self.assertAlmostEqual(result["position_net_after_fees"], 1 - 0.0236 - 0.000059)

    def test_credits_count_once_and_actual_total_not_taxed_again(self):
        result = self.report(fills=[fill("1", "buy", 1, 1, credit=".01")])
        self.assertAlmostEqual(result["position_entry_fees"], 0.0236)

    def test_partial_history_does_not_create_net_pnl(self):
        result = self.report(
            fills=[fill("2", "buy", 1, 3)], position={"size": 3, "entry_price": "90"}
        )
        self.assertEqual(result["fee_status"], "incomplete")
        self.assertIsNone(result["position_entry_fees"])
        self.assertIsNone(result["position_net_after_fees"])
        self.assertIsNotNone(result["estimated_maker_exit_fee"])

    def test_explicitly_incomplete_last_page_never_verifies_fees(self):
        result = self.report(fills=[fill("1", "buy", 1, 1)], complete=False)
        self.assertIsNone(result["position_entry_fees"])
        self.assertIsNone(result["position_net_after_fees"])

    def test_multiple_entries_from_flat_prove_exact_current_quantity(self):
        rows = [fill("1", "buy", 1, 1), fill("2", "buy", 1, 2, total_paid=".0472")]
        result = self.report(position={"size": 2, "entry_price": "90"}, fills=rows)
        self.assertEqual(result["fee_status"], "verified")
        self.assertAlmostEqual(result["position_entry_fees"], 0.0472)

    def test_partial_close_fee_attribution_is_unknown(self):
        rows = [
            fill("1", "buy", 2, 2, total_paid=".0236"),
            fill("2", "sell", 1, 1, total_paid=".0472"),
        ]
        result = self.report(fills=rows)
        self.assertIsNone(result["position_entry_fees"])
        self.assertIsNone(result["position_net_after_fees"])

    def test_short_position_attribution(self):
        result = self.report(
            position={"size": -1, "entry_price": "90"}, fills=[fill("1", "sell", 1, -1)]
        )
        self.assertEqual(result["fee_status"], "verified")

    def test_missing_gst_evidence_never_invents_actual_fee_total(self):
        row = fill("1", "buy", 1, 1)
        row["meta_data"].pop("rack_commission_without_gst")
        result = self.report(fills=[row])
        self.assertIsNone(result["position_entry_fees"])
        self.assertIsNone(result["position_net_after_fees"])

    def test_missing_fee_stays_unknown_instead_of_zero(self):
        row = fill("1", "buy", 1, 1)
        row["meta_data"].pop("total_commission_in_settling_asset")
        result = self.report(fills=[row])
        self.assertIsNone(result["position_entry_fees"])

    def test_duplicate_fill_not_double_counted(self):
        row = fill("1", "buy", 1, 1)
        result = self.report(fills=[row, row])
        self.assertAlmostEqual(result["position_entry_fees"], 0.0236)

    def test_flat_position_does_not_relabel_wallet_as_open_net(self):
        result = self.report(
            position={"size": 0, "entry_price": "0"}, fills=[fill("1", "buy", 1, 1)]
        )
        self.assertEqual(result["fee_status"], "flat")
        self.assertEqual(result["position_gross_pnl"], 0)
        self.assertEqual(result["position_entry_fees"], 0)
        self.assertEqual(result["position_net_after_fees"], 0)

    def test_xaut_generic_product_supported(self):
        product = dict(
            PRODUCT,
            id=99,
            symbol="XAUTUSD",
            contract_value=".01",
            maker_commission_rate=".0001",
        )
        row = fill("1", "buy", 1, 1)
        row["product_id"] = 99
        result = self.report(product=product, fills=[row])
        self.assertEqual(result["fee_status"], "verified")
        self.assertAlmostEqual(result["estimated_maker_exit_fee"], 0.000118)

    def test_negative_or_rebate_fee_is_not_replaced_with_estimated_maker_rate(self):
        row = fill("1", "buy", 1, 1, fee="-.0236")
        row["meta_data"].update(
            rack_commision="-.0236", rack_commission_without_gst="-.02"
        )
        result = self.report(fills=[row])
        self.assertEqual(result["fee_status"], "verified")
        self.assertAlmostEqual(result["position_entry_fees"], -0.0236)

    def test_proven_waived_zero_fee_is_known_zero(self):
        result = self.report(fills=[fill("1", "buy", 1, 1, fee="0")])
        self.assertEqual(result["fee_status"], "verified")
        self.assertEqual(result["position_entry_fees"], 0)

    def test_new_position_commission_total_must_reconcile(self):
        result = self.report(fills=[fill("1", "buy", 1, 1, total_paid=".1")])
        self.assertIsNone(result["position_entry_fees"])

    def test_duplicate_timestamp_is_ambiguous_and_fails_closed(self):
        result = self.report(
            position={"size": 2, "entry_price": "90"},
            fills=[
                fill("1", "buy", 1, 1, when="1"),
                fill("2", "buy", 1, 2, total_paid=".0472", when="1"),
            ],
        )
        self.assertIsNone(result["position_entry_fees"])

    def test_wallet_missing_available_does_not_copy_total_balance(self):
        result = self.report(
            wallet=[{"asset_id": 14, "asset_symbol": "USD", "balance": "100"}]
        )
        self.assertEqual(result["balance"], 100)
        self.assertIsNone(result["available_balance"])

    def test_missing_credit_breakdown_cannot_hide_fee_credit_cost(self):
        row = fill("1", "buy", 1, 1, credit=".01")
        row["meta_data"].pop("tfc_used_for_commission")
        result = self.report(fills=[row])
        self.assertIsNone(result["position_entry_fees"])

    def test_current_entry_price_must_match_latest_lifecycle(self):
        result = self.report(
            position={"size": 1, "entry_price": "91"}, fills=[fill("1", "buy", 1, 1)]
        )
        self.assertIsNone(result["position_entry_fees"])


class AccountingStateTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from test_delta_chart_sizing import SizingClient

        from services.delta_chart.service import Store, TradingService

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = SizingClient()
        self.client.size = 1
        self.rows = [fill("1", "buy", 1, 1)]
        original = self.client.pages
        self.client.pages = lambda path, params: (
            self.rows if path == "/v2/fills" else original(path, params)
        )
        self.service = TradingService(
            Store(Path(self.temp.name) / "ledger.db"),
            lambda user: ("key", "secret"),
            lambda key, secret: self.client,
        )

    def test_state_reports_accounting_independent_of_sizing_and_uses_live_gross(self):
        self.client.maker_rate = None
        state = self.service.state("alice", "BTCUSD")
        self.assertIsNone(state["sizing"])
        self.assertEqual(state["accounting"]["balance"], 999)
        self.assertEqual(state["accounting"]["available_balance"], 10)
        self.assertAlmostEqual(state["accounting"]["position_gross_pnl"], 0.01)
        self.assertAlmostEqual(state["accounting"]["position_entry_fees"], 0.0236)
        self.assertIsNone(state["accounting"]["estimated_maker_exit_fee"])
        self.assertIsNotNone(state["accounting"]["estimated_exit_fee"])
        self.assertIsNotNone(state["accounting"]["position_net_after_fees"])

    def test_open_position_fees_bypass_stale_history_cache(self):
        self.assertAlmostEqual(
            self.service.state("alice", "BTCUSD")["accounting"]["position_entry_fees"],
            0.0236,
        )
        row = fill("1", "buy", 1, 1, fee=".0472")
        row["meta_data"].update(
            rack_commision=".0472", rack_commission_without_gst=".04"
        )
        self.rows = [row]
        self.assertAlmostEqual(
            self.service.state("alice", "BTCUSD")["accounting"]["position_entry_fees"],
            0.0472,
        )

    def test_fill_failure_leaves_balance_and_gross_available_with_unknown_fees(self):
        original = self.client.pages

        def pages(path, params):
            if path == "/v2/fills":
                raise TimeoutError()
            return original(path, params)

        self.client.pages = pages
        state = self.service.state("alice", "BTCUSD")
        self.assertTrue(state["connected"])
        self.assertEqual(state["accounting"]["balance"], 999)
        self.assertAlmostEqual(state["accounting"]["position_gross_pnl"], 0.01)
        self.assertEqual(state["accounting"]["fee_status"], "incomplete")
        self.assertIsNone(state["accounting"]["position_entry_fees"])
        self.assertIsNone(state["accounting"]["position_net_after_fees"])

    def test_usd_vanilla_gross_ignores_lagging_margined_snapshot_after_reversal(self):
        original = self.client.request
        self.client.size = -1

        def request(method, path, **kwargs):
            if path == "/v2/positions/margined":
                return [
                    {
                        "product_id": 27,
                        "size": 4,
                        "entry_price": "80",
                        "unrealized_pnl": "999",
                    }
                ]
            return original(method, path, **kwargs)

        self.client.request = request
        state = self.service.state("alice", "BTCUSD")
        self.assertAlmostEqual(state["position"]["pnl"], -0.01)
        self.assertAlmostEqual(state["accounting"]["position_gross_pnl"], -0.01)


class MarketExitAccountingTests(unittest.TestCase):
    def test_taker_exit_estimate_includes_gst_and_net_uses_taker_not_maker(self):
        result = build_accounting(
            PRODUCT,
            WALLET,
            {"size": 1, "entry_price": "90"},
            Decimal("100"),
            Decimal("1"),
            [fill("1", "buy", 1, 1)],
            True,
        )
        self.assertEqual(result["exit_fee_basis"], "taker")
        self.assertAlmostEqual(result["estimated_exit_fee"], 0.000059)
        self.assertAlmostEqual(result["estimated_maker_exit_fee"], 0.0000236)
        self.assertAlmostEqual(result["position_net_after_fees"], 1 - 0.0236 - 0.000059)

    def test_missing_taker_metadata_never_substitutes_maker_exit_cost(self):
        product = dict(PRODUCT)
        product.pop("taker_commission_rate")
        result = build_accounting(
            product,
            WALLET,
            {"size": 1, "entry_price": "90"},
            Decimal("100"),
            Decimal("1"),
            [fill("1", "buy", 1, 1)],
            True,
        )
        self.assertIsNone(result["estimated_exit_fee"])
        self.assertIsNone(result["position_net_after_fees"])
        self.assertIsNotNone(result["estimated_maker_exit_fee"])
