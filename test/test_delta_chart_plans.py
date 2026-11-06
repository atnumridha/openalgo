import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

from test_delta_chart_accounting import fill
from test_delta_chart_sizing import SizingClient

from services.delta_chart.plans import ManagedPlans
from services.delta_chart.service import DeltaError, Rejected, Store, TradingService


class PlanClient(SizingClient):
    def __init__(self):
        super().__init__()
        self.size = 0
        self.entry = "99.5"
        self.rows = []
        self.next_id = 100
        self.timeout_next = False

    def request(self, method, path, params=None, payload=None, private=True):
        if method == "GET" and path == "/v2/history/candles":
            span = {
                "1m": 60,
                "3m": 180,
                "5m": 300,
                "15m": 900,
                "30m": 1800,
                "1h": 3600,
                "1d": 86400,
            }[params["resolution"]]
            return [
                {
                    "time": params["start"] + i * span,
                    "open": 99,
                    "high": 100,
                    "low": 99,
                    "close": 99.5,
                }
                for i in range(21)
            ]
        if method == "GET" and path == "/v2/positions":
            self.calls.append((method, path, None))
            return {"size": self.size, "entry_price": self.entry}
        if method == "GET" and path.startswith("/v2/orders/"):
            self.calls.append((method, path, None))
            key = path.removeprefix("/v2/orders/")
            row = next(
                (
                    row
                    for row in self.orders
                    if str(row["id"]) == key
                    or key == "client_order_id/" + str(row.get("client_order_id"))
                ),
                None,
            )
            if row is None:
                raise DeltaError("Order unavailable")
            return dict(row)
        if method in ("POST", "PUT", "DELETE") and path == "/v2/orders":
            self.calls.append((method, path, payload))
            if self.timeout_next:
                self.timeout_next = False
                raise TimeoutError()
            if method == "POST":
                row = dict(
                    payload,
                    id=self.next_id,
                    unfilled_size=payload["size"],
                    state="pending" if payload.get("stop_order_type") else "open",
                )
                self.next_id += 1
                self.orders.append(row)
            else:
                row = next(row for row in self.orders if row["id"] == payload["id"])
                row.update(payload)
                if method == "DELETE":
                    row["state"] = "cancelled"
            return dict(row)
        return super().request(
            method, path, params=params, payload=payload, private=private
        )

    def pages(self, path, params):
        if path == "/v2/fills":
            return list(self.rows)
        if path == "/v2/orders":
            return [
                dict(row) for row in self.orders if row["state"] in ("open", "pending")
            ]
        return super().pages(path, params)


class ManagedPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = PlanClient()
        self.service = TradingService(
            Store(Path(self.temp.name) / "ledger.db"),
            lambda user: ("key", "secret"),
            lambda key, secret: self.client,
        )
        self.initial = self.service.state("alice", "BTCUSD")
        self.source = int(time.time()) // 60 * 60 - 60

    def entry(self, **changes):
        data = {
            "request_id": str(uuid4()),
            "symbol": "BTCUSD",
            "account": self.initial["account"],
            "action": "entry",
            "side": "buy",
            "size": 1,
            "price": 99.5,
            "auto_protection": {
                "stop": 95,
                "target": 110,
                "source_time": self.source,
                "interval_seconds": 60,
                "reason": "Reviewed trend levels",
            },
        }
        data.update(changes)
        result = self.service.action("alice", data)
        self.plan = self.service.state("alice", "BTCUSD")["managed_plans"][0]
        self.parent = next(
            row for row in self.client.orders if str(row["id"]) == result["order_id"]
        )
        return result

    def filled(self):
        self.parent["unfilled_size"] = 0
        self.parent["state"] = "closed"
        self.client.size = 1
        row = fill("1", "buy", 1, 1, price="99.5", fee=".000023482")
        row["meta_data"]["rack_commision"] = ".000023482"
        row["meta_data"]["rack_commission_without_gst"] = ".0000199"
        row["order_id"] = self.parent["id"]
        row["created_at"] = str(int(time.time()) - 5)
        self.client.rows = [row]

    def manage(self, decision="sync", **changes):
        data = {
            "plan_id": self.plan["id"],
            "decision": decision,
            "source_time": self.source,
        }
        data.update(changes)
        return self.service.manage("alice", data)

    def mutations(self):
        return [call for call in self.client.calls if call[0] != "GET"]

    def test_stale_unfilled_scalp_cancelled_by_background_sync(self):
        self.entry()
        self.parent["created_at"] = str(time.time() - 16)
        result = self.service.plans.manage(
            "alice",
            {"plan_id": self.plan["id"], "decision": "sync"},
            protection_only=True,
        )
        self.assertEqual(self.mutations()[-1][0], "DELETE")
        self.assertEqual(self.parent["state"], "cancelled")

    def test_manual_resting_entry_is_not_expired(self):
        self.entry(entry_mode="manual")
        self.parent["created_at"] = str(time.time() - 60)
        before = len(self.mutations())
        self.manage()
        self.assertEqual(len(self.mutations()), before)

    def test_early_risk_reduction_without_fee_breakeven(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.profit_mark(102)
        result = self.manage("reduce_risk", stop=97.5)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.mutations()[-1][0], "PUT")
        self.assertEqual(self.service.plans.list("alice", "BTCUSD")[0]["stop"], 97.5)

    def test_early_risk_reduction_rejects_no_profit_and_fake_profit_floor(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.profit_mark(99.5)
        with self.assertRaises(Rejected):
            self.manage("reduce_risk", stop=97.5)
        self.profit_mark(102)
        with self.assertRaises(Rejected):
            self.manage("reduce_risk", stop=100.5)

    def test_trailing_can_tighten_twice_in_the_same_candle_without_duplicate_submission(
        self,
    ):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.profit_mark(106)
        self.manage("trail", stop=101)
        before = len(self.mutations())
        self.manage("trail", stop=102)
        self.assertEqual(len(self.mutations()), before + 1)
        self.manage("trail", stop=102)
        self.assertEqual(len(self.mutations()), before + 1)
        self.assertEqual(self.service.plans.list("alice", "BTCUSD")[0]["stop"], 102)

    def test_risk_cap_rejects_before_broker_entry_mutation(self):
        with self.assertRaisesRegex(Rejected, "₹20"):
            self.entry(size=100000)
        self.assertEqual(self.mutations(), [])

    def test_smart_profit_peak_is_durable_before_stop_mutation(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.profit_mark(500)
        result = self.manage()
        self.assertEqual(self.mutations()[-1][0], "PUT")
        with self.service.store.db() as db:
            peak = float(
                db.execute(
                    "SELECT peak_inr FROM delta_plan_profit_peaks WHERE plan_id=?",
                    (self.plan["id"],),
                ).fetchone()[0]
            )
        self.assertGreater(peak, 30)
        self.service.plans = ManagedPlans(self.service)  # reload must retain the recorded peak
        self.profit_mark(350)
        result = self.manage()
        self.assertEqual(result["plan_status"], "closing")
        self.assertEqual(self.mutations()[-1][2]["order_type"], "market_order")

    def test_plan_persisted_before_entry_mutation(self):
        original = self.client.request

        def request(method, path, **kwargs):
            if method == "POST" and path == "/v2/orders":
                self.assertEqual(len(self.service.plans.list("alice", "BTCUSD")), 1)
            return original(method, path, **kwargs)

        self.client.request = request
        self.entry()
        self.assertEqual(self.plan["initial_stop"], 95)
        self.assertEqual(self.plan["entry_order_id"], str(self.parent["id"]))

    def test_first_fill_clock_survives_missing_rolling_history_without_get_writes(self):
        self.entry()
        self.filled()
        self.manage()
        first = self.service.plans.list("alice", "BTCUSD")[0]["first_fill_at"]
        self.assertIsNotNone(first)
        self.client.rows = []
        self.assertEqual(
            self.service.plans.list("alice", "BTCUSD")[0]["first_fill_at"], first
        )

    def test_manual_entry_keeps_durable_managed_protection_mode(self):
        self.entry(entry_mode="manual")
        self.assertTrue(self.plan["manual_entry"])
        self.filled()
        self.manage()
        self.assertEqual(self.mutations()[-1][2]["order_type"], "market_order")
        self.assertTrue(self.mutations()[-1][2]["reduce_only"])

    def test_manual_override_requires_managed_protection(self):
        with self.assertRaisesRegex(Rejected, "automatic SL/target"):
            self.entry(entry_mode="manual", auto_protection=None)
        self.assertEqual(self.mutations(), [])

    def test_manual_override_still_requires_maker_limit_entry(self):
        with self.assertRaisesRegex(Rejected, "Maker-only entries"):
            self.entry(entry_mode="manual", order_type="market_order")
        self.assertEqual(self.mutations(), [])

    def test_sharp_manual_entry_keeps_post_only_and_durable_managed_protection(self):
        original = self.client.request

        def sharp(method, path, **kwargs):
            value = original(method, path, **kwargs)
            if method == "GET" and path == "/v2/history/candles":
                value[-1].update(high=105, low=95)
            return value

        self.client.request = sharp
        self.entry(entry_mode="manual")
        self.assertTrue(self.plan["manual_entry"])
        self.assertTrue(self.parent["post_only"])
        self.assertEqual(self.parent["order_type"], "limit_order")
        self.assertEqual(self.plan["initial_stop"], 95)
        self.filled()
        self.manage()
        stop = self.mutations()[-1][2]
        self.assertTrue(stop["reduce_only"])
        self.assertEqual(stop["order_type"], "market_order")

    def test_get_state_never_progresses_protection(self):
        self.entry()
        self.filled()
        before = len(self.mutations())
        self.service.state("alice", "BTCUSD")
        self.assertEqual(len(self.mutations()), before)

    def test_full_fill_places_one_maker_leg_per_sync(self):
        self.entry()
        self.filled()
        self.manage()
        self.assertEqual(len(self.mutations()), 2)
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")
        self.manage()
        self.assertEqual(len(self.mutations()), 3)
        self.assertEqual(
            self.mutations()[-1][2]["stop_order_type"], "take_profit_order"
        )
        for call in self.mutations():
            if call[2]["order_type"] == "limit_order":
                self.assertIs(call[2]["post_only"], True)
            else:
                self.assertEqual(call[2]["order_type"], "market_order")
                self.assertNotIn("post_only", call[2])
        result = self.manage()
        self.assertEqual(result["plan_status"], "active")
        self.assertEqual(len(self.mutations()), 3)

    def test_partial_fill_places_stop_then_cancels_remainder_then_target(self):
        self.entry(size=2)
        self.parent["unfilled_size"] = 1
        self.client.size = 1
        row = fill("1", "buy", 1, 1, price="99.5")
        row["order_id"] = self.parent["id"]
        self.client.rows = [row]
        self.manage()
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")
        self.assertEqual(self.mutations()[-1][2]["size"], 1)
        self.manage()
        self.assertEqual(self.mutations()[-1][0], "DELETE")
        self.manage()
        self.assertEqual(
            self.mutations()[-1][2]["stop_order_type"], "take_profit_order"
        )
        self.assertEqual(self.manage()["plan_status"], "active")

    def test_foreign_position_never_managed(self):
        self.entry()
        self.filled()
        self.client.rows[0]["order_id"] = 999
        result = self.manage()
        self.assertIn(result["plan_status"], ("pending", "blocked"))
        self.assertEqual(len(self.mutations()), 1)

    def test_owner_binding(self):
        self.entry()
        with self.assertRaises(Rejected):
            self.service.manage(
                "bob",
                {
                    "plan_id": self.plan["id"],
                    "decision": "sync",
                    "source_time": self.source,
                },
            )

    def test_stale_candle_rejected_without_mutation(self):
        self.entry()
        with self.assertRaises(Rejected):
            self.manage(source_time=self.source - 1000)
        self.assertEqual(len(self.mutations()), 1)

    def test_profitable_stop_allowed_and_only_tightens(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.client.entry = "99.5"
        self.profit_mark(105)
        result = self.manage("trail", stop=101)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.mutations()[-1][0], "PUT")
        with self.assertRaises(Rejected):
            self.manage("trail", stop=98)

    def test_unknown_protective_outcome_is_not_retried(self):
        self.entry()
        self.filled()
        self.client.timeout_next = True
        first = self.manage()
        self.assertEqual(first["status"], "pending")
        count = len(self.mutations())
        self.manage()
        self.assertEqual(len(self.mutations()), count)

    def test_full_owned_lifecycle_exit_and_sibling_cleanup(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.manage()
        self.profit_mark(105)
        self.manage("trail", stop=101)
        count = len(self.mutations())
        result = self.manage("exit")
        self.assertEqual(result["plan_status"], "closing")
        self.assertEqual(len(self.mutations()), count + 1)
        self.assertEqual(self.mutations()[-1][2]["order_type"], "market_order")
        self.assertNotIn("limit_price", self.mutations()[-1][2])
        self.assertTrue(self.mutations()[-1][2]["reduce_only"])
        count = len(self.mutations())
        self.manage("exit")
        self.assertEqual(len(self.mutations()), count)
        close = next(
            row
            for row in self.client.orders
            if not row.get("stop_order_type") and row["id"] != self.parent["id"]
        )
        close["state"] = "closed"
        close["unfilled_size"] = 0
        flat = fill(
            "exit-fill", "sell", 1, 0, price="100.5", when=str(int(time.time()))
        )
        flat["order_id"] = close["id"]
        self.client.rows.append(flat)
        self.client.size = 0
        self.manage()
        self.assertEqual(len(self.mutations()), count + 1)
        self.assertEqual(self.mutations()[-1][0], "DELETE")
        self.manage()
        self.assertEqual(len(self.mutations()), count + 2)
        result = self.manage()
        self.assertEqual(result["plan_status"], "completed")
        self.assertEqual(len(self.mutations()), count + 2)

    def test_cancel_entry_only_cancels_its_owned_unfilled_order(self):
        self.entry()
        result = self.manage("cancel_entry")
        self.assertEqual(self.mutations()[-1][0], "DELETE")
        self.assertEqual(self.mutations()[-1][2]["id"], self.parent["id"])
        result = self.manage()
        self.assertEqual(result["plan_status"], "cancelled")

    def test_unproven_partial_cannot_be_managed(self):
        self.entry(size=2)
        self.parent["unfilled_size"] = 1
        self.client.size = 1
        result = self.manage("cancel_entry")
        self.assertEqual(result["plan_status"], "pending")
        self.assertEqual(len(self.mutations()), 1)

    def test_stop_beyond_known_liquidation_blocks_protection(self):
        self.entry()
        self.filled()
        original = self.client.request

        def request(method, path, **kwargs):
            if path == "/v2/positions/margined":
                return [
                    {
                        "product_id": 27,
                        "size": self.client.size,
                        "entry_price": self.client.entry,
                        "liquidation_price": "96",
                    }
                ]
            return original(method, path, **kwargs)

        self.client.request = request
        result = self.manage()
        self.assertEqual(result["plan_status"], "blocked")
        self.assertIn("liquidation", result["message"])
        self.assertEqual(len(self.mutations()), 1)

    def test_explicit_manual_close_pauses_plan_before_mutation(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.manage()
        original = self.client.request

        def request(method, path, **kwargs):
            if (
                method == "POST"
                and path == "/v2/orders"
                and not kwargs["payload"].get("stop_order_type")
            ):
                self.assertEqual(
                    self.service.plans.list("alice", "BTCUSD")[0]["status"], "closing"
                )
            return original(method, path, **kwargs)

        self.client.request = request
        state = self.service.state("alice", "BTCUSD")
        self.service.action(
            "alice",
            {
                "request_id": str(uuid4()),
                "symbol": "BTCUSD",
                "account": state["account"],
                "action": "close",
                "position_version": state["position"]["version"],
                "price": 100.5,
            },
        )
        count = len(self.mutations())
        result = self.manage()
        self.assertEqual(result["plan_status"], "closing")
        self.assertEqual(len(self.mutations()), count)

    def test_missing_gst_metadata_does_not_block_owned_initial_protection_or_exit(self):
        self.entry()
        self.filled()
        self.client.rows[0]["meta_data"].pop("rack_commission_without_gst")
        self.manage()
        self.manage()
        self.assertEqual(len(self.mutations()), 3)
        result = self.manage("exit")
        self.assertEqual(result["plan_status"], "closing")
        self.assertEqual(len(self.mutations()), 4)

    def test_missing_fee_evidence_pauses_fee_aware_trailing(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.client.rows[0]["meta_data"].pop("rack_commission_without_gst")
        result = self.manage("trail", stop=99.5)
        self.assertEqual(result["plan_status"], "pending")
        self.assertEqual(len(self.mutations()), 3)

    def test_profitable_stop_can_cross_entry_when_below_fresh_mark(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        original = self.client.request

        def request(method, path, **kwargs):
            if path.startswith("/v2/tickers/"):
                return {
                    "mark_price": "102",
                    "close": "102",
                    "quotes": {"best_bid": "100.5", "best_ask": "101.5"},
                }
            return original(method, path, **kwargs)

        self.client.request = request
        result = self.manage("trail", stop=100.5)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.mutations()[-1][2]["stop_price"], "100.5")

    def test_auto_trail_cannot_loosen_a_manually_tightened_broker_stop(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        stop = next(
            row
            for row in self.client.orders
            if row.get("stop_order_type") == "stop_loss_order"
        )
        stop["stop_price"] = "99.5"
        stop["limit_price"] = "99.5"
        with self.assertRaises(Rejected):
            self.manage("trail", stop=99)
        self.assertEqual(len(self.mutations()), 3)

    def test_manual_target_cannot_be_on_loss_side_of_entry(self):
        self.client.size = 1
        self.client.entry = "110"
        state = self.service.state("alice", "BTCUSD")
        with self.assertRaisesRegex(Rejected, "beyond the position entry"):
            self.service.action(
                "alice",
                {
                    "request_id": str(uuid4()),
                    "symbol": "BTCUSD",
                    "account": state["account"],
                    "action": "protect",
                    "position_version": state["position"]["version"],
                    "target": 105,
                },
            )
        self.assertEqual(len(self.mutations()), 0)

    def test_partial_stop_resizes_before_remaining_entry_is_cancelled(self):
        self.entry(size=3)
        self.parent["unfilled_size"] = 2
        self.client.size = 1
        first = fill("1", "buy", 1, 1, price="99.5")
        first["order_id"] = self.parent["id"]
        first["created_at"] = str(int(time.time()) - 10)
        self.client.rows = [first]
        self.manage()
        self.parent["unfilled_size"] = 1
        self.client.size = 2
        second = fill("2", "buy", 1, 2, price="99.5")
        second["order_id"] = self.parent["id"]
        second["created_at"] = str(int(time.time()) - 5)
        self.client.rows.append(second)
        self.manage()
        method, _, payload = self.mutations()[-1]
        self.assertEqual(method, "PUT")
        self.assertEqual(payload["size"], 2)
        self.assertNotIn("post_only", payload)
        self.assertEqual(float(payload["stop_price"]), 95)
        self.manage()
        self.assertEqual(self.mutations()[-1][0], "DELETE")

    def test_manual_close_rejects_owned_entry_remainder_without_mutation(self):
        self.entry(size=2)
        self.parent["unfilled_size"] = 1
        self.client.size = 1
        state = self.service.state("alice", "BTCUSD")
        with self.assertRaisesRegex(Rejected, "Cancel remainder first"):
            self.service.action(
                "alice",
                {
                    "request_id": str(uuid4()),
                    "account": state["account"],
                    "symbol": "BTCUSD",
                    "action": "close",
                    "price": 100.5,
                    "position_version": state["position"]["version"],
                },
            )
        self.assertEqual(len(self.mutations()), 1)

    def test_worker_protects_reviewed_fills_without_chart_or_fresh_candles(self):
        from services.delta_chart.worker import ProtectionWorker

        self.entry()
        self.filled()
        worker = ProtectionWorker(self.service)
        worker.tick()
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")
        worker.tick()
        self.assertEqual(
            self.mutations()[-1][2]["stop_order_type"], "take_profit_order"
        )
        worker.tick()
        self.assertEqual(len(self.mutations()), 3)
        self.assertIsNone(worker.thread)

    def test_worker_never_retries_unknown_child(self):
        from services.delta_chart.worker import ProtectionWorker

        self.entry()
        self.filled()
        self.client.timeout_next = True
        worker = ProtectionWorker(self.service)
        worker.tick()
        worker.tick()
        self.assertEqual(len(self.mutations()), 2)
        self.assertEqual(
            self.service.plans.get("alice", self.plan["id"])["status"], "pending"
        )

    def test_rejected_trailing_replay_does_not_update_stop_or_confirm(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.profit_mark(105)
        original = self.service.action
        self.service.action = lambda *args: {
            "status": "rejected",
            "message": "Maker-only order rejected",
        }
        result = self.manage("trail", stop=101)
        self.service.action = original
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(
            float(self.service.plans.get("alice", self.plan["id"])["stop"]), 95
        )

    def test_account_product_lock_serializes_cross_service_workers(self):
        import threading
        import time

        other = TradingService(
            self.service.store,
            lambda user: ("key", "secret"),
            lambda key, secret: self.client,
        )
        entered = threading.Event()
        completed = threading.Event()

        def contender():
            entered.set()
            with other.plans.lock("alice", self.initial["account"], "BTCUSD"):
                completed.set()

        with self.service.plans.lock("alice", self.initial["account"], "BTCUSD"):
            thread = threading.Thread(target=contender)
            thread.start()
            entered.wait(1)
            time.sleep(0.08)
            self.assertFalse(completed.is_set())
            # Nested child actions use the same lock reentrantly.
            with self.service.plans.lock("alice", self.initial["account"], "BTCUSD"):
                self.assertFalse(completed.is_set())
        thread.join(2)
        self.assertTrue(completed.is_set())

    def test_explicit_target_edit_updates_visible_plan_without_resetting_it(self):
        from services.delta_chart.service import digest

        self.entry()
        self.filled()
        self.manage()
        self.manage()
        plan = self.service.plans.get("alice", self.plan["id"])
        target = next(
            row
            for row in self.client.orders
            if str(row["id"]) == plan["target_order_id"]
        )
        result = self.service.action(
            "alice",
            {
                "request_id": str(uuid4()),
                "account": self.initial["account"],
                "symbol": "BTCUSD",
                "action": "edit",
                "order_id": target["id"],
                "version": digest(target),
                "price": 115,
            },
        )
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.service.plans.list("alice", "BTCUSD")[0]["target"], 115)
        self.manage()
        self.assertEqual(float(target["stop_price"]), 115)

    def test_flat_partial_cancels_remainder_before_completing(self):
        self.entry(size=2)
        self.parent["unfilled_size"] = 1
        self.client.size = 1
        row = fill("1", "buy", 1, 1, price="99.5")
        row["order_id"] = self.parent["id"]
        self.client.rows = [row]
        self.manage()
        self.client.size = 0
        self.client.orders[-1]["state"] = "closed"
        result = self.manage()
        self.assertEqual(self.mutations()[-1][0], "DELETE")
        self.assertEqual(self.parent["state"], "cancelled")
        self.assertNotEqual(result["plan_status"], "completed")

    def adopt(self, **changes):
        from services.delta_chart.service import digest

        self.client.size = 1
        self.legacy = {
            "id": 90,
            "product_id": 27,
            "side": "sell",
            "size": 1,
            "unfilled_size": 1,
            "state": "pending",
            "reduce_only": True,
            "order_type": "market_order",
            "stop_order_type": "stop_loss_order",
            "stop_price": "95",
            "post_only": False,
            "client_order_id": "foreign-owned-reviewed",
        }
        self.client.orders.append(self.legacy)
        self.client.rows = [
            fill(
                "adopt-fill", "buy", 1, 1, price="99.5", when=str(int(time.time()) - 5)
            )
        ]
        state = self.service.state("alice", "BTCUSD")
        data = {
            "request_id": str(uuid4()),
            "symbol": "BTCUSD",
            "account": state["account"],
            "action": "adopt",
            "position_version": state["position"]["version"],
            "existing_stop": {"id": "90", "version": digest(self.legacy)},
            "auto_protection": {
                "stop": 96,
                "target": 110,
                "source_time": self.source,
                "interval_seconds": 60,
                "reason": "Explicit existing-position review",
            },
        }
        data.update(changes)
        result = self.service.action("alice", data)
        self.plan = self.service.plans.list("alice", "BTCUSD")[0]
        return result

    def test_adoption_registration_is_read_only_and_replaces_sl_before_cancel(self):
        result = self.adopt()
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.mutations(), [])
        self.manage()
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")
        self.assertEqual(self.legacy["state"], "pending")
        self.manage()
        self.assertEqual(self.mutations()[-1][0], "DELETE")
        self.assertEqual(self.legacy["state"], "cancelled")
        self.manage()
        self.assertEqual(
            self.mutations()[-1][2]["stop_order_type"], "take_profit_order"
        )
        self.assertEqual(self.manage()["plan_status"], "active")

    def test_adoption_cannot_loosen_reviewed_legacy_stop(self):
        with self.assertRaisesRegex(Rejected, "loosen"):
            self.adopt(
                auto_protection={
                    "stop": 94,
                    "target": 110,
                    "source_time": self.source,
                    "interval_seconds": 60,
                    "reason": "Review",
                }
            )
        self.assertEqual(self.mutations(), [])

    def test_adoption_position_change_pauses_without_mutation(self):
        self.adopt()
        self.client.size = 2
        result = self.manage()
        self.assertEqual(result["plan_status"], "blocked")
        self.assertEqual(self.mutations(), [])

    def test_adoption_unknown_replacement_never_cancels_old_stop(self):
        self.adopt()
        self.client.timeout_next = True
        self.manage()
        self.manage()
        self.assertEqual(len(self.mutations()), 1)
        self.assertEqual(self.legacy["state"], "pending")

    def test_stale_opposite_liquidation_never_blocks_current_owned_stop(self):
        self.entry()
        self.filled()
        original = self.client.request

        def request(method, path, **kwargs):
            if path == "/v2/positions/margined":
                return [
                    {
                        "product_id": 27,
                        "size": -1,
                        "entry_price": "110",
                        "liquidation_price": "120",
                    }
                ]
            return original(method, path, **kwargs)

        self.client.request = request
        state = self.service.state("alice", "BTCUSD")
        self.assertIsNone(state["position"]["liquidation"])
        result = self.manage()
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")

    def test_definite_manual_close_rejection_allows_worker_fixed_protection(self):
        from services.delta_chart.worker import ProtectionWorker

        self.entry()
        self.filled()
        state = self.service.state("alice", "BTCUSD")
        with self.assertRaises(Rejected):
            self.service.action(
                "alice",
                {
                    "request_id": str(uuid4()),
                    "symbol": "BTCUSD",
                    "account": state["account"],
                    "action": "close",
                    "side": "buy",
                    "position_version": state["position"]["version"],
                },
            )
        self.assertEqual(
            self.service.plans.get("alice", self.plan["id"])["status"],
            "placing_protection",
        )
        ProtectionWorker(self.service).tick()
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")

    def test_legacy_stop_not_cancelled_without_observed_market_replacement(self):
        self.adopt()
        self.manage()
        self.client.orders[-1]["reduce_only"] = False
        result = self.manage()
        self.assertEqual(result["plan_status"], "blocked")
        self.assertEqual(self.legacy["state"], "pending")
        self.assertEqual(len(self.mutations()), 1)

    def test_legacy_order_changed_after_review_is_not_replaced_or_cancelled(self):
        self.adopt()
        self.legacy["stop_price"] = "97"
        result = self.manage()
        self.assertEqual(result["plan_status"], "blocked")
        self.assertEqual(self.mutations(), [])

    def test_numeric_margined_match_requires_size_and_entry(self):
        from services.delta_chart.service import matching_margined

        row = {
            "product_id": 27,
            "size": "1.0",
            "entry_price": "99.500",
            "liquidation_price": "80",
        }
        self.assertEqual(
            matching_margined([row], 27, {"size": 1, "entry_price": "99.5"}), row
        )
        self.assertEqual(
            matching_margined([row], 27, {"size": -1, "entry_price": "99.5"}), {}
        )
        self.assertEqual(
            matching_margined([row], 27, {"size": 1, "entry_price": "100"}), {}
        )
        self.assertEqual(
            matching_margined([row, row], 27, {"size": 1, "entry_price": "99.5"}), {}
        )

    def test_same_size_entry_reopened_position_does_not_inherit_adopted_plan(self):
        self.adopt()
        self.client.rows = [
            fill(
                "different-fill", "buy", 1, 1, price="99.5", when=str(int(time.time()))
            )
        ]
        result = self.manage()
        self.assertEqual(result["plan_status"], "blocked")
        self.assertEqual(self.mutations(), [])

    def test_adoption_requires_latest_fill_snapshot_without_guessing_ownership(self):
        from unittest.mock import patch

        with patch.object(
            self.service.plans,
            "position_marker",
            side_effect=Rejected("Latest fill evidence unavailable"),
        ):
            with self.assertRaisesRegex(Rejected, "fill evidence"):
                self.adopt()
        self.assertEqual(self.mutations(), [])

    def test_adopted_fill_marker_is_rechecked_immediately_before_order_submission(self):
        self.adopt()
        original = self.service.recent_fills
        observations = []

        def recent(*args, **kwargs):
            observations.append(True)
            if len(observations) >= 3:
                return [
                    fill(
                        "reopened",
                        "buy",
                        1,
                        1,
                        price="99.5",
                        when=str(int(time.time())),
                    )
                ]
            return original(*args, **kwargs)

        self.service.recent_fills = recent
        result = self.manage()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.legacy["state"], "pending")

    def test_adopted_legacy_cancel_rechecks_late_reopened_fill_marker(self):
        self.adopt()
        self.manage()
        original = self.service.action

        def interleave(user, data):
            if data.get("action") == "cancel":
                self.client.rows = [
                    fill(
                        "late-reopened",
                        "buy",
                        1,
                        1,
                        price="99.5",
                        when=str(int(time.time())),
                    )
                ]
            return original(user, data)

        self.service.action = interleave
        result = self.manage()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.legacy["state"], "pending")
        self.assertFalse(any(method == "DELETE" for method, _, _ in self.mutations()))

    def test_adopted_flat_cleanup_can_cancel_reviewed_legacy_without_open_position_marker(
        self,
    ):
        self.adopt()
        self.client.size = 0
        self.client.rows = []
        self.manage()
        self.assertEqual(self.mutations()[-1][0], "DELETE")
        self.assertEqual(self.legacy["state"], "cancelled")

    def test_owned_maker_create_without_echoed_flag_uses_confirmed_exact_provenance(
        self,
    ):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        stop = self.client.orders[-1]
        stop.pop("post_only")
        stop["created_at"] = stop["updated_at"] = "2026-11-01T08:36:11.367835Z"
        state = self.service.state("alice", "BTCUSD")
        self.assertTrue(
            next(order for order in state["orders"] if order["kind"] == "target")[
                "post_only"
            ]
        )
        self.assertTrue(self.service.maker_verified("alice", stop))

    def test_missing_maker_echo_cannot_override_false_or_external_edit(self):
        self.entry()
        self.filled()
        self.manage()
        stop = self.client.orders[-1]
        stop["created_at"] = stop["updated_at"] = "2026-11-01T08:36:11Z"
        stop["post_only"] = False
        self.assertFalse(self.service.maker_verified("alice", stop))
        stop.pop("post_only")
        stop["updated_at"] = "2026-11-01T08:36:12Z"
        self.assertFalse(self.service.maker_verified("alice", stop))
        stop["updated_at"] = stop["created_at"]
        stop["size"] = 2
        self.assertFalse(self.service.maker_verified("alice", stop))

    def test_foreign_order_missing_maker_flag_never_inherits_provenance(self):
        self.adopt()
        self.legacy.pop("post_only")
        self.legacy["created_at"] = self.legacy["updated_at"] = "2026-11-01T08:36:11Z"
        self.assertFalse(self.service.maker_verified("alice", self.legacy))

    def test_exact_missing_flag_block_recovery_is_read_only_then_continues_target(self):
        from services.delta_chart.worker import ProtectionWorker

        stop = self.legacy_managed_maker_stop()
        stop.pop("post_only")
        stop["created_at"] = stop["updated_at"] = "2026-11-01T08:36:11Z"
        self.service.plans.update(
            self.plan["id"],
            status="blocked",
            message="Owned protective order no longer satisfies the reviewed plan",
        )
        worker = ProtectionWorker(self.service)
        before = len(self.mutations())
        worker.tick()
        self.assertEqual(len(self.mutations()), before)
        self.assertEqual(
            self.service.plans.get("alice", self.plan["id"])["status"],
            "placing_protection",
        )
        worker.tick()
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")
        self.assertEqual(self.mutations()[-1][2]["order_type"], "market_order")

    def test_owned_edit_ack_timestamp_proves_maker_when_broker_omits_flag(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        stop = self.client.orders[2]
        stop["created_at"] = stop["updated_at"] = "2026-11-01T08:36:11Z"
        original = self.client.request

        def request(method, path, **kwargs):
            result = original(method, path, **kwargs)
            if method == "PUT":
                stop.pop("post_only", None)
                stop["updated_at"] = "2026-11-01T08:36:12Z"
                return dict(stop)
            return result

        self.client.request = request
        from services.delta_chart.service import digest

        result = self.service.action(
            "alice",
            {
                "request_id": str(uuid4()),
                "account": self.initial["account"],
                "symbol": "BTCUSD",
                "action": "edit",
                "order_id": stop["id"],
                "version": digest(stop),
                "price": 115,
            },
        )
        self.assertEqual(result["status"], "confirmed")
        self.assertTrue(self.service.maker_verified("alice", stop))
        stop["updated_at"] = "2026-11-01T08:36:13Z"
        self.assertFalse(self.service.maker_verified("alice", stop))

    def test_entry_ack_exposes_broker_placement_time_and_request_binding(self):
        original = self.client.request
        placed = int(time.time()) - 3

        def request(method, path, **kwargs):
            result = original(method, path, **kwargs)
            if method == "POST" and path == "/v2/orders":
                result["created_at"] = str(placed)
            return result

        self.client.request = request
        result = self.entry()
        self.assertEqual(result["placed_at"], placed)
        self.assertEqual(self.plan["placed_at"], placed)
        self.assertEqual(self.plan["entry_order_id"], result["order_id"])
        self.assertEqual(self.plan["entry_request_id"], result["request_id"])

    def test_adopt_registration_does_not_invent_entry_placement_time(self):
        result = self.adopt()
        self.assertNotIn("placed_at", result)
        self.assertIsNone(self.plan["placed_at"])

    def test_chased_entry_rejected_before_plan_leverage_or_order(self):
        with self.assertRaisesRegex(Rejected, "Sharp move"):
            self.entry(price=101, leverage=10)
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.service.plans.list("alice", "BTCUSD"), [])

    def test_entry_rechecks_candles_before_final_order_without_blind_retry(self):
        original = self.client.request
        calls = []

        def request(method, path, **kwargs):
            result = original(method, path, **kwargs)
            if path == "/v2/history/candles":
                calls.append(True)
                if len(calls) == 2:
                    result[-1]["high"] = 105
            return result

        self.client.request = request
        with self.assertRaises(Rejected):
            self.entry()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.mutations(), [])

    def readopt_current(self):
        import json

        plan = self.service.plans.get("alice", self.plan["id"])
        data = json.loads(plan["payload"])
        data["request_id"] = str(uuid4())
        data["position_version"] = self.service.state("alice", "BTCUSD")["position"][
            "version"
        ]
        return self.service.action("alice", data)

    def test_reviewed_readoption_supersedes_only_blocked_plans_without_broker_actions(
        self,
    ):
        self.adopt()
        old_id = self.plan["id"]
        self.service.plans.update(
            old_id, status="blocked", message="Legacy stop changed externally"
        )
        result = self.readopt_current()
        self.assertEqual(result["status"], "confirmed")
        self.assertNotEqual(result["plan_id"], old_id)
        old = self.service.plans.get("alice", old_id)
        self.assertEqual(old["status"], "rejected")
        self.assertEqual(
            old["message"], "Superseded by reviewed current-position protection"
        )
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.legacy["state"], "pending")

    def test_reviewed_readoption_rejects_active_plan_without_superseding(self):
        self.adopt()
        old_id = self.plan["id"]
        self.service.plans.update(
            old_id, status="active", message="Existing active protection"
        )
        with self.assertRaisesRegex(Rejected, "already has"):
            self.readopt_current()
        self.assertEqual(self.service.plans.get("alice", old_id)["status"], "active")
        self.assertEqual(len(self.service.plans.list("alice", "BTCUSD")), 1)
        self.assertEqual(self.mutations(), [])

    def test_filled_parent_flat_position_lag_keeps_worker_waiting_then_places_stop(
        self,
    ):
        from services.delta_chart.worker import ProtectionWorker

        self.entry()
        self.filled()
        self.client.size = 0
        worker = ProtectionWorker(self.service)
        worker.tick()
        self.assertNotEqual(
            self.service.plans.get("alice", self.plan["id"])["status"], "completed"
        )
        self.assertEqual(len(self.mutations()), 1)
        self.client.size = 1
        worker.tick()
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")

    def test_completed_unobserved_entry_recovers_only_exact_current_parent_exposure(
        self,
    ):
        from services.delta_chart.worker import ProtectionWorker

        self.entry()
        self.filled()
        self.service.plans.update(
            self.plan["id"],
            status="completed",
            message="Owned position is flat and owned sibling exits are no longer active",
        )
        worker = ProtectionWorker(self.service)
        worker.tick()
        self.assertEqual(len(self.mutations()), 1)
        self.assertEqual(
            self.service.plans.get("alice", self.plan["id"])["status"],
            "placing_protection",
        )
        worker.tick()
        self.assertEqual(self.mutations()[-1][2]["stop_order_type"], "stop_loss_order")

    def test_completed_unobserved_entry_does_not_recover_foreign_reopened_position(
        self,
    ):
        from services.delta_chart.worker import ProtectionWorker

        self.entry()
        self.filled()
        self.service.plans.update(
            self.plan["id"],
            status="completed",
            message="Owned position is flat and owned sibling exits are no longer active",
        )
        self.client.rows[0]["order_id"] = 999
        ProtectionWorker(self.service).tick()
        self.assertEqual(
            self.service.plans.get("alice", self.plan["id"])["status"], "completed"
        )
        self.assertEqual(len(self.mutations()), 1)

    def test_completed_unobserved_entry_already_closed_stays_terminal_without_orders(
        self,
    ):
        from services.delta_chart.worker import ProtectionWorker

        self.entry()
        self.filled()
        self.client.size = 0
        flat = fill("closed", "sell", 1, 0, price="100", when=str(int(time.time())))
        flat["order_id"] = 999
        self.client.rows.append(flat)
        self.service.plans.update(
            self.plan["id"],
            status="completed",
            message="Owned position is flat and owned sibling exits are no longer active",
        )
        worker = ProtectionWorker(self.service)
        worker.tick()
        worker.tick()
        saved = self.service.plans.get("alice", self.plan["id"])
        self.assertEqual(saved["status"], "completed")
        self.assertIn("confirmed flat", saved["message"])
        self.assertEqual(len(self.mutations()), 1)

    def test_short_entry_to_flat_proof_requires_original_parent_for_all_increases(self):
        import json

        plan = {
            "pid": "27",
            "entry_order_id": "42",
            "payload": json.dumps({"side": "sell"}),
        }
        opening = fill("short-entry", "sell", 2, -2, price="99.5", when="1")
        opening["order_id"] = 42
        closing = fill("short-exit", "buy", 2, 0, price="99", when="2")
        closing["order_id"] = 43
        self.assertTrue(
            self.service.plans.flat_after_entry(plan, [opening, closing], True, 2)
        )
        opening["order_id"] = 999
        self.assertFalse(
            self.service.plans.flat_after_entry(plan, [opening, closing], True, 2)
        )

    def test_close_is_reduce_only_market_without_price_or_maker_flags(self):
        self.entry()
        self.filled()
        state = self.service.state("alice", "BTCUSD")
        self.service.action(
            "alice",
            {
                "request_id": str(uuid4()),
                "symbol": "BTCUSD",
                "account": state["account"],
                "action": "close",
                "position_version": state["position"]["version"],
            },
        )
        payload = self.mutations()[-1][2]
        self.assertEqual(payload["order_type"], "market_order")
        self.assertIs(payload["reduce_only"], True)
        self.assertNotIn("limit_price", payload)
        self.assertNotIn("post_only", payload)
        self.assertNotIn("time_in_force", payload)

    def test_initial_stop_is_reduce_only_market_trigger_and_target_stays_maker(self):
        self.entry()
        self.filled()
        self.manage()
        payload = self.mutations()[-1][2]
        self.assertEqual(payload["order_type"], "market_order")
        self.assertEqual(payload["stop_order_type"], "stop_loss_order")
        self.assertEqual(payload["stop_trigger_method"], "mark_price")
        self.assertNotIn("limit_price", payload)
        self.assertNotIn("post_only", payload)
        self.manage()
        payload = self.mutations()[-1][2]
        self.assertEqual(payload["order_type"], "limit_order")
        self.assertIs(payload["post_only"], True)

    def test_market_stop_edit_changes_trigger_without_limit_or_maker_flags(self):
        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.profit_mark(105)
        self.manage("trail", stop=101)
        payload = self.mutations()[-1][2]
        self.assertEqual(self.mutations()[-1][0], "PUT")
        self.assertEqual(float(payload["stop_price"]), 101)
        self.assertNotIn("limit_price", payload)
        self.assertNotIn("post_only", payload)
        self.assertNotIn("order_type", payload)

    def legacy_managed_maker_stop(self):
        import json

        self.entry()
        self.filled()
        self.manage()
        stop = self.client.orders[-1]
        stop.update(
            order_type="limit_order",
            limit_price=stop["stop_price"],
            post_only=True,
            time_in_force="gtc",
        )
        plan = self.service.plans.get("alice", self.plan["id"])
        operation = next(
            row for row in self.service.plans.operations(plan) if row["kind"] == "stop"
        )
        rid = json.loads(operation["payload"])["request_id"]
        payload = {
            key: value
            for key, value in stop.items()
            if key not in ("id", "state", "unfilled_size")
        }
        self.service.store.evidence(
            "alice", rid, {"method": "POST", "path": "/v2/orders", "payload": payload}
        )
        return stop

    def test_managed_maker_stop_migration_acknowledges_market_before_old_cancel(self):
        old = self.legacy_managed_maker_stop()
        self.manage()
        market = self.client.orders[-1]
        self.assertEqual(market["order_type"], "market_order")
        self.assertEqual(market["stop_order_type"], "stop_loss_order")
        self.assertEqual(old["state"], "pending")
        self.assertNotEqual(market["id"], old["id"])
        self.manage()
        self.assertEqual(old["state"], "cancelled")
        self.assertEqual(self.mutations()[-1][0], "DELETE")
        self.manage()
        self.assertEqual(
            self.mutations()[-1][2]["stop_order_type"], "take_profit_order"
        )

    def test_managed_stop_migration_unknown_never_cancels_old_or_retries(self):
        old = self.legacy_managed_maker_stop()
        self.client.timeout_next = True
        self.manage()
        count = len(self.mutations())
        self.manage()
        self.assertEqual(len(self.mutations()), count)
        self.assertEqual(old["state"], "pending")

    def test_managed_market_stop_migration_retains_current_tighter_stop(self):
        old = self.legacy_managed_maker_stop()
        old["stop_price"] = old["limit_price"] = "98"
        self.manage()
        self.assertEqual(float(self.mutations()[-1][2]["stop_price"]), 98)

    def test_managed_market_stop_migration_does_not_cancel_when_new_stop_invalid(self):
        old = self.legacy_managed_maker_stop()
        self.manage()
        self.client.orders[-1]["reduce_only"] = False
        result = self.manage()
        self.assertEqual(result["plan_status"], "blocked")
        self.assertEqual(old["state"], "pending")
        self.assertFalse(any(call[0] == "DELETE" for call in self.mutations()))

    def test_managed_market_stop_migration_does_not_cancel_externally_changed_old_stop(
        self,
    ):
        old = self.legacy_managed_maker_stop()
        self.manage()
        old["stop_price"] = "98"
        result = self.manage()
        self.assertEqual(result["plan_status"], "blocked")
        self.assertEqual(old["state"], "pending")
        self.assertFalse(any(call[0] == "DELETE" for call in self.mutations()))

    def test_market_stop_migration_resizes_new_partial_before_cancelling_old(self):
        self.entry(size=3)
        self.parent["unfilled_size"] = 2
        self.client.size = 1
        first = fill(
            "first", "buy", 1, 1, price="99.5", when=str(int(time.time()) - 10)
        )
        first["order_id"] = self.parent["id"]
        self.client.rows = [first]
        self.manage()
        old = self.client.orders[-1]
        old.update(
            order_type="limit_order",
            limit_price=old["stop_price"],
            post_only=True,
            time_in_force="gtc",
        )
        self.manage()
        new = self.client.orders[-1]
        self.assertEqual(new["order_type"], "market_order")
        self.parent["unfilled_size"] = 1
        self.client.size = 2
        second = fill(
            "second", "buy", 1, 2, price="99.5", when=str(int(time.time()) - 5)
        )
        second["order_id"] = self.parent["id"]
        self.client.rows.append(second)
        self.manage()
        self.assertEqual(self.mutations()[-1][0], "PUT")
        self.assertEqual(self.mutations()[-1][2]["id"], new["id"])
        self.assertEqual(self.mutations()[-1][2]["size"], 2)
        self.assertEqual(old["state"], "pending")
        self.manage()
        self.assertEqual(old["state"], "cancelled")

    def test_managed_market_exit_needs_no_best_bid_or_ask(self):
        self.entry()
        self.filled()
        original = self.client.request

        def request(method, path, **kwargs):
            if path.startswith("/v2/tickers/"):
                return {"mark_price": "100", "close": "100", "quotes": {}}
            return original(method, path, **kwargs)

        self.client.request = request
        result = self.manage("exit")
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.mutations()[-1][2]["order_type"], "market_order")
        self.assertNotIn("limit_price", self.mutations()[-1][2])

    def profit_mark(self, value):
        original = self.client.request

        def request(method, path, **kwargs):
            if path.startswith("/v2/tickers/"):
                return {
                    "mark_price": str(value),
                    "close": str(value),
                    "quotes": {
                        "best_bid": str(value - 0.5),
                        "best_ask": str(value + 0.5),
                    },
                }
            return original(method, path, **kwargs)

        self.client.request = request

    def test_server_trail_rejects_candidate_covering_only_smaller_maker_fees(self):
        from unittest.mock import patch

        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.profit_mark(105)
        before = len(self.mutations())
        with patch(
            "services.delta_chart.service.build_accounting",
            return_value={
                "fee_status": "verified",
                "position_entry_fees": 0.001,
                "estimated_exit_fee": 0.001,
            },
        ):
            with self.assertRaisesRegex(Rejected, "taker"):
                self.manage("trail", stop=100.5)
        self.assertEqual(len(self.mutations()), before)

    def test_server_long_trail_accepts_fresh_taker_fee_floor(self):
        from unittest.mock import patch

        self.entry()
        self.filled()
        self.manage()
        self.manage()
        self.profit_mark(105)
        with patch(
            "services.delta_chart.service.build_accounting",
            return_value={
                "fee_status": "verified",
                "position_entry_fees": 0.001,
                "estimated_exit_fee": 0.001,
            },
        ):
            result = self.manage("trail", stop=102)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(float(self.mutations()[-1][2]["stop_price"]), 102)

    def test_server_short_trail_accepts_mirrored_taker_fee_floor(self):
        from unittest.mock import patch

        self.entry(
            side="sell",
            auto_protection={
                "stop": 105,
                "target": 90,
                "source_time": self.source,
                "interval_seconds": 60,
                "reason": "Short review",
            },
        )
        self.parent.update(state="closed", unfilled_size=0)
        self.client.size = -1
        self.client.rows = [
            fill("short", "sell", 1, -1, price="99.5", when=str(int(time.time()) - 5))
        ]
        self.client.rows[0]["order_id"] = self.parent["id"]
        self.manage()
        self.manage()
        self.profit_mark(95)
        with patch(
            "services.delta_chart.service.build_accounting",
            return_value={
                "fee_status": "verified",
                "position_entry_fees": 0.001,
                "estimated_exit_fee": 0.001,
            },
        ):
            result = self.manage("trail", stop=97)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(float(self.mutations()[-1][2]["stop_price"]), 97)

    def test_server_fee_floor_accepts_frontend_rounded_two_tick_candidate(self):
        from unittest.mock import patch

        self.entry(price=100)
        self.filled()
        self.client.entry = "100"
        self.client.rows[0]["price"] = "100"
        self.client.rows[0]["meta_data"]["new_position"]["entry_price"] = "100"
        self.manage()
        self.manage()
        self.profit_mark(105)
        with patch(
            "services.delta_chart.service.build_accounting",
            return_value={
                "fee_status": "verified",
                "position_entry_fees": 0.0001,
                "estimated_exit_fee": 0.00015,
            },
        ):
            result = self.manage("trail", stop=101)
        self.assertEqual(result["status"], "confirmed")
