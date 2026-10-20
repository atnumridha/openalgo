import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from test_kotak_assistant_analysis import SETTINGS

from services.kotak_assistant.execution import Coordinator
from services.kotak_assistant.store import Store


class Fake:
    scope = "u:account:live"
    user = "u"
    mode = "live"

    def __init__(self):
        self.now = datetime(2026, 10, 14, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
        self.orders = []
        self.fills = []
        self.positions = []
        self.calls = []
        self.fail = False
        self.unknown = False
        self.books_fail = False

    def clock(self):
        return self.now

    def metadata(self, symbol, exchange):
        return {
            "lot": 65,
            "tick": 0.05,
            "freeze": 1800,
            "underlying": "NIFTY",
            "expiry": "2026-10-15",
        }

    def quote(self, symbol, exchange):
        return {"ltp": 100, "bid": 99.95, "ask": 100, "time": self.clock()}

    def stop_limit(self, symbol, exchange, trigger):
        return round(trigger * 0.97, 2)

    def session_open(self, exchange, cutoff):
        return True

    def other_controller(self, *args):
        return False

    def books(self):
        if self.books_fail:
            raise ValueError("Book unavailable")
        return {
            "orders": self.orders,
            "fills": self.fills,
            "positions": self.positions,
            "time": self.clock(),
            "cash": 100000,
        }

    def submit(self, data):
        self.calls.append(data)
        if self.unknown:
            raise TimeoutError("unknown")
        if self.fail:
            return {"state": "rejected", "message": "Rejected"}
        oid = str(len(self.orders) + 1)
        self.orders.append(
            {
                "orderid": oid,
                "symbol": data["symbol"],
                "exchange": data["exchange"],
                "product": data["product"],
                "action": data["action"],
                "quantity": data["quantity"],
                "filled_quantity": 0,
                "order_status": "open",
                "order_tag": data["tag"],
                "trigger_price": data.get("trigger_price", 0),
                "pricetype": data["pricetype"],
            }
        )
        return {"state": "accepted", "orderid": oid}

    def cancel(self, oid):
        next(o for o in self.orders if o["orderid"] == oid)["order_status"] = "cancelled"
        return {"state": "accepted"}

    def fill(self, oid, qty, price=100):
        o = next(o for o in self.orders if o["orderid"] == oid)
        o["filled_quantity"] += qty
        if o["filled_quantity"] == o["quantity"]:
            o["order_status"] = "complete"
        self.fills.append(
            {
                "orderid": oid,
                "tradeid": str(len(self.fills) + 1),
                "symbol": o["symbol"],
                "exchange": o["exchange"],
                "product": o["product"],
                "action": o["action"],
                "quantity": qty,
                "average_price": price,
                "timestamp": "14-Oct-2026 10:00:00",
            }
        )
        net = sum(f["quantity"] * (1 if f["action"] == "BUY" else -1) for f in self.fills)
        self.positions = (
            [
                {
                    "symbol": o["symbol"],
                    "exchange": o["exchange"],
                    "product": o["product"],
                    "quantity": net,
                    "average_price": 100,
                    "ltp": 100,
                    "pnl": 0,
                }
            ]
            if net
            else []
        )


@pytest.fixture
def desk(tmp_path):
    g = Fake()
    s = Store(create_engine(f"sqlite:///{tmp_path}/desk.db"))
    c = Coordinator(s, g, clock=g.clock)
    c.configure(SETTINGS)
    return c, g, s


def ticket(c, qty=65):
    return c.preview(
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": qty,
            "entry": 100,
            "sl": 90,
            "target": 122,
            "auto_target": False,
            "auto_invalidation": False,
            "auto_risk": False,
        }
    )["ticket"]


def test_banknifty_preview_uses_its_contract_lot_and_allows_index_invalidation(desk):
    c, g, _ = desk
    g.metadata = lambda symbol, exchange: {
        "lot": 35,
        "tick": 0.05,
        "freeze": 1050,
        "underlying": "BANKNIFTY",
        "expiry": "2026-10-27",
    }
    preview = c.preview(
        {
            "symbol": "BANKNIFTY27OCT2650000CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 35,
            "entry": 100,
            "sl": 90,
            "target": 122,
            "underlying": "BANKNIFTY",
            "auto_invalidation": True,
            "index_invalidation": 49900,
        }
    )
    assert preview["plan"]["quantity"] == 35
    assert c.state()["tickets"][preview["ticket"]]["lot"] == 35
    assert g.calls == []


def entered(desk, qty=65):
    c, g, s = desk
    t = c.enter(ticket(c, qty))
    g.fill("1", qty)
    c.reconcile()
    return c, g, s, t["id"]


def test_no_separate_arming_and_duplicate_click_is_one_order(desk):
    c, g, _ = desk
    t = ticket(c)
    a = c.enter(t)
    b = c.enter(t)
    assert a["id"] == b["id"] and len(g.calls) == 1


def test_manual_entry_without_rupee_budgets_keeps_durable_fill_and_stop_management(desk):
    c, g, _ = desk
    c.configure({})
    tid = ticket(c)
    c.enter(tid)
    c.enter(tid)
    assert len(g.calls) == 1
    g.fill("1", 65)
    c.reconcile()
    c.reconcile()
    trade = c.state()["trades"][tid]
    assert trade["status"] == "protected"
    assert g.calls[1]["action"] == "SELL" and g.calls[1]["pricetype"] == "SL"
    assert trade["lifecycle"]
    assert all(
        c.state()["settings"][key] is None for key in ("risk", "premium", "daily_loss", "giveback")
    )


def test_stop_is_sell_and_accepted_is_not_filled(desk):
    c, g, _, tid = entered(desk)
    assert g.calls[1]["action"] == "SELL" and g.calls[1]["pricetype"] == "SL"
    assert c.state()["trades"][tid]["status"] != "closed"


def test_exit_cancels_stop_and_waits_for_fill(desk):
    c, g, _, tid = entered(desk)
    c.exit(tid, request_id="exit1")
    c.reconcile()
    c.reconcile()
    assert g.orders[1]["order_status"] == "cancelled"
    assert len([x for x in g.calls if x["pricetype"] == "MARKET"]) == 1
    assert c.state()["trades"][tid]["status"] != "closed"
    g.fill("3", 65, 110)
    c.reconcile()
    assert c.state()["trades"][tid]["status"] == "closed"


def test_unknown_submission_never_retries_after_restart(desk):
    c, g, s = desk
    g.unknown = True
    t = ticket(c)
    c.enter(t)
    c = Coordinator(s, g, clock=g.clock)
    c.reconcile()
    c.reconcile()
    assert len(g.calls) == 1 and c.state()["trades"][t]["status"] == "unknown"


def test_rejected_entry_keeps_authorization_evidence_after_restart_without_resubmitting(desk):
    c, g, store = desk

    def rejected(payload):
        g.calls.append(payload)
        return {
            "state": "rejected",
            "message": "Kotak rejected order: unauthorized (HTTP 401 · code 100008)",
            "http_status": 401,
            "broker_code": 100008,
            "broker_error": "unauthorized",
        }

    g.submit = rejected
    tid = ticket(c)
    c.enter(tid)
    restarted = Coordinator(store, g, clock=g.clock)
    trade = restarted.enter(tid)
    assert len(g.calls) == 1
    assert trade["status"] == "rejected" and trade["remaining"] == 0
    assert trade["ops"][0]["http_status"] == 401
    assert trade["ops"][0]["broker_code"] == 100008
    assert trade["ops"][0]["broker_error"] == "unauthorized"
    assert trade["lifecycle"][-1]["reason"] == trade["reason"]


def test_trade_lifecycle_is_on_disk_before_submit_and_survives_a_fresh_store(desk):
    c, g, s = desk
    tid = ticket(c)
    original = g.submit

    def submit(payload):
        persisted = Store(create_engine(s.engine.url)).read(c.scope)["trades"][tid]
        assert persisted["lifecycle"][-1]["orders"][-1]["state"] == "prepared"
        return original(payload)

    g.submit = submit
    c.enter(tid)
    g.submit = original
    g.fill("1", 65)
    c = Coordinator(Store(create_engine(s.engine.url)), g, clock=g.clock)
    c.reconcile()
    g.fill("2", 65, 90)
    c = Coordinator(Store(create_engine(s.engine.url)), g, clock=g.clock)
    c.reconcile()
    persisted = Store(create_engine(s.engine.url)).read(c.scope)["trades"][tid]
    assert persisted["status"] == "closed"
    assert persisted["lifecycle"][0]["status"] == "entry_pending"
    assert persisted["lifecycle"][-1]["remaining"] == 0
    assert persisted["lifecycle"][-1]["status"] == "closed"
    assert {op["orderid"] for op in persisted["lifecycle"][-1]["orders"]} == {"1", "2"}
    assert len(g.calls) == 2


def test_book_failure_never_means_closed(desk):
    c, g, _, tid = entered(desk)
    g.books_fail = True
    with pytest.raises(ValueError):
        c.reconcile()
    assert c.state()["trades"][tid]["status"] != "closed"


def test_wrong_quantity_and_wrong_side_cannot_exit(desk):
    c, g, _, tid = entered(desk)
    with pytest.raises(ValueError):
        c.exit(tid, quantity=66, request_id="bad")
    with pytest.raises(ValueError):
        c.exit(tid, quantity=130, request_id="bad2")
    assert len(g.calls) == 2


def test_partial_exit_never_overlaps_full_size_stop(desk):
    c, g, _, tid = entered(desk, 130)
    c.exit(tid, quantity=65, request_id="partial")
    c.reconcile()
    c.reconcile()
    g.fill("3", 65, 110)
    c.reconcile()
    c.reconcile()
    active = [o for o in g.orders if o["order_status"] == "open" and o["action"] == "SELL"]
    assert len(active) == 1 and active[0]["quantity"] == 65 and active[0]["pricetype"] == "SL"


def test_target_not_automatic_without_selected_policy(desk):
    c, g, _, _ = entered(desk)
    g.quote = lambda *a: {"ltp": 130, "bid": 129, "ask": 130, "time": g.clock()}
    c.reconcile()
    assert len(g.calls) == 2


def test_stop_fill_during_cancel_does_not_submit_another_sell(desk):
    c, g, _, tid = entered(desk)

    def cancel(oid):
        g.fill(oid, 65, 90)
        return {"state": "accepted"}

    g.cancel = cancel
    c.exit(tid, request_id="race")
    c.reconcile()
    c.reconcile()
    assert len(g.calls) == 2 and c.state()["trades"][tid]["status"] == "closed"


def test_risk_config_change_invalidates_ticket(desk):
    c, g, _ = desk
    t = ticket(c)
    c.configure({**SETTINGS, "risk": 1000})
    with pytest.raises(ValueError):
        c.enter(t)
    assert not g.calls


def test_foreign_scope_cannot_read_or_exit(desk):
    c, g, s, tid = entered(desk)
    h = Fake()
    h.scope = "v:account:live"
    h.user = "v"
    other = Coordinator(s, h, clock=h.clock)
    assert not other.state()["trades"]
    with pytest.raises(ValueError):
        other.exit(tid, request_id="x")


def test_store_lease_excludes_other_worker(desk):
    c, g, s = desk
    with s.lock(g.scope):
        with pytest.raises(ValueError):
            with s.lock(g.scope):
                pass


def test_stale_quote_cannot_prevent_required_stop(desk):
    c, g, _ = desk
    c.enter(ticket(c))["id"]
    g.fill("1", 65)
    g.quote = lambda *a: {"ltp": 100, "bid": 100, "ask": 100, "time": g.clock() - 6}
    c.reconcile()
    assert any(x["pricetype"] == "SL" for x in g.calls)


def test_quote_exception_cannot_block_manual_exit(desk):
    c, g, _, tid = entered(desk)

    def failed(*args):
        raise ValueError("No market quote")

    g.quote = failed
    c.exit(tid, request_id="exit")
    c.reconcile()
    c.reconcile()
    assert any(x["pricetype"] == "MARKET" for x in g.calls)


def test_rejected_cancel_can_retry_after_fresh_book(desk):
    c, g, _, tid = entered(desk)
    original = g.cancel
    g.cancel = lambda oid: {"state": "rejected", "message": "Busy"}
    c.exit(tid, request_id="exit")
    g.now += 6
    g.cancel = original
    c.reconcile()
    c.reconcile()
    assert any(x["pricetype"] == "MARKET" for x in g.calls)


def test_manual_retry_after_three_rejected_exits(desk):
    c, g, _, tid = entered(desk)
    c.exit(tid, request_id="exit")
    g.fail = True
    for _ in range(5):
        g.now += 6
        c.reconcile()
    assert c.state()["trades"][tid]["status"] == "exit_rejected"
    before = len(g.calls)
    g.fail = False
    c.exit(tid, request_id="retry")
    c.reconcile()
    assert (
        len(g.calls) > before
        and g.calls[-1]["pricetype"] == "MARKET"
        and g.orders[-1]["action"] == "SELL"
    )


def test_cutoff_frozen_in_trade(desk):
    c, g, _ = desk
    tid = c.enter(ticket(c))["id"]
    c.configure({**SETTINGS, "cutoff": "14:00"})
    assert c.state()["trades"][tid]["cutoff"] == "15:15"


def test_consumed_setup_cannot_reenter(desk):
    c, g, _ = desk
    request = {
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 65,
        "entry": 100,
        "sl": 90,
        "target": 122,
        "setup_id": "one-confirmation",
    }
    c.enter(c.preview(request)["ticket"])["id"]
    g.fill("1", 65)
    c.reconcile()
    g.fill("2", 65, 90)
    c.reconcile()
    with pytest.raises(ValueError, match="consumed"):
        c.preview(request)


def test_server_side_partial_loss_halts_entries(desk):
    c, g, _ = desk
    c.configure({**SETTINGS, "daily_loss": 1000})
    # Other day fills may exist before the desk starts; partial losses count now.
    order = {
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 130,
        "action": "BUY",
        "pricetype": "LIMIT",
        "price": 100,
        "tag": "outside",
    }
    g.submit(order)
    g.fill("1", 130)
    g.submit({**order, "quantity": 65, "action": "SELL"})
    g.fill("2", 65, 50)
    c.reconcile()
    assert c.state()["day"]["halt"] == "Daily loss limit reached"


def test_adoption_protects_existing_position_without_new_buy(desk):
    c, g, _ = desk
    g.positions = [
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "average_price": 100,
            "pnl": 0,
        }
    ]
    t = c.adopt(
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "entry": 100,
            "sl": 90,
            "target": 122,
            "order_ids": [],
            "request_id": "adopt",
        }
    )
    c.reconcile()
    assert len(g.calls) == 1 and g.calls[0]["action"] == "SELL" and g.calls[0]["pricetype"] == "SL"
    assert c.state()["trades"][t["id"]]["remaining"] == 65


def test_adoption_rejects_undisclosed_pending_orders(desk):
    c, g, _ = desk
    g.positions = [
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "average_price": 100,
            "pnl": 0,
        }
    ]
    g.submit(
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "action": "SELL",
            "pricetype": "SL",
            "trigger_price": 90,
            "tag": "outside",
        }
    )
    with pytest.raises(ValueError):
        c.adopt(
            {
                "symbol": "NIFTY15OCT2622600CE",
                "exchange": "NFO",
                "product": "MIS",
                "quantity": 65,
                "entry": 100,
                "sl": 90,
                "target": 122,
                "order_ids": [],
                "request_id": "adopt",
            }
        )


def test_direct_external_exit_cancels_disclosed_orders(desk):
    c, g, _ = desk
    g.positions = [
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "average_price": 100,
            "pnl": 0,
        }
    ]
    g.submit(
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "action": "SELL",
            "pricetype": "SL",
            "trigger_price": 90,
            "tag": "outside",
        }
    )
    c.adopt(
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "order_ids": ["1"],
            "request_id": "exit-outside",
            "close": True,
        }
    )
    c.reconcile()
    c.reconcile()
    assert g.orders[0]["order_status"] == "cancelled" and g.calls[-1]["pricetype"] == "MARKET"


def test_option_stop_limit_uses_gateway_tick_aligned_protection(desk):
    c, g, _ = desk
    g.stop_limit = lambda symbol, exchange, trigger: 87.3
    c.enter(ticket(c))
    g.fill("1", 65)
    c.reconcile()
    assert g.calls[1]["trigger_price"] == 90 and g.calls[1]["price"] == 87.3


def test_missing_index_quote_does_not_block_protection_or_manual_exit(desk):
    c, g, _ = desk
    request = {
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 65,
        "entry": 100,
        "sl": 90,
        "target": 122,
        "auto_invalidation": True,
        "index_invalidation": 22500,
        "underlying": "NIFTY",
    }
    tid = c.enter(c.preview(request)["ticket"])["id"]
    g.fill("1", 65)
    original = g.quote

    def quote(symbol, exchange):
        if exchange.endswith("_INDEX"):
            raise ValueError("Index unavailable")
        return original(symbol, exchange)

    g.quote = quote
    c.reconcile()
    assert g.calls[-1]["pricetype"] == "SL"
    c.exit(tid, request_id="exit")
    c.reconcile()
    c.reconcile()
    assert g.calls[-1]["pricetype"] == "MARKET"


def test_delayed_fill_reopens_cancelled_zero_fill_entry(desk):
    c, g, _ = desk
    tid = c.enter(ticket(c))["id"]
    g.now += 6
    c.reconcile()
    c.reconcile()
    assert c.state()["trades"][tid]["status"] == "rejected"
    g.fill("1", 65)
    c.reconcile()
    assert c.state()["trades"][tid]["remaining"] == 65 and g.calls[-1]["pricetype"] == "SL"


def test_repeat_contract_uses_residual_fill_cost_basis(desk):
    c, g, _ = desk
    c.configure({**SETTINGS, "daily_loss": 1000})
    order = {
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 65,
        "action": "BUY",
        "pricetype": "LIMIT",
        "price": 100,
        "tag": "outside",
    }
    g.submit(order)
    g.fill("1", 65, 100)
    g.submit({**order, "action": "SELL"})
    g.fill("2", 65, 50)
    g.submit(order)
    g.fill("3", 65, 200)
    g.positions[0]["average_price"] = 150
    g.quote = lambda *a: {"ltp": 200, "bid": 200, "ask": 200, "time": g.clock()}
    c.reconcile()
    assert (
        c.state()["day"]["open_gross"] == 0
        and c.state()["day"]["halt"] == "Daily loss limit reached"
    )


def test_direct_exit_ignores_blank_stop_and_target(desk):
    c, g, _ = desk
    g.positions = [
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "average_price": 100,
            "pnl": 0,
        }
    ]
    c.adopt(
        {
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "order_ids": [],
            "request_id": "exit-null",
            "close": True,
            "sl": None,
            "target": None,
        }
    )
    assert g.calls[-1]["pricetype"] == "MARKET" and g.calls[-1]["action"] == "SELL"


def test_adoption_uses_remaining_fill_basis_for_repeated_contract(desk):
    c, g, _ = desk
    order = {
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 65,
        "action": "BUY",
        "pricetype": "LIMIT",
        "price": 100,
        "tag": "outside",
    }
    g.submit(order)
    g.fill("1", 65, 100)
    g.submit({**order, "action": "SELL"})
    g.fill("2", 65, 50)
    g.submit(order)
    g.fill("3", 65, 200)
    g.positions[0]["average_price"] = 150
    g.quote = lambda *a: {"ltp": 200, "bid": 200, "ask": 200, "time": g.clock()}
    t = c.adopt(
        {
            "symbol": order["symbol"],
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "order_ids": [],
            "request_id": "manage",
            "sl": 180,
            "target": 222,
        }
    )
    assert t["average_entry"] == 200 and t["average_entry_verified"]


def test_unknown_cancel_can_be_retried_by_new_explicit_exit_click(desk):
    c, g, _, tid = entered(desk)
    original = g.cancel
    g.cancel = lambda oid: {"state": "unknown", "message": "Timeout"}
    c.exit(tid, request_id="first")
    c.reconcile()
    assert c.state()["trades"][tid]["status"] == "cancel_unknown"
    g.cancel = original
    c.exit(tid, request_id="retry")
    c.reconcile()
    c.reconcile()
    assert g.calls[-1]["pricetype"] == "MARKET" and len(g.calls) == 3


def test_day_rollover_preserves_previous_journal(desk):
    c, g, _ = desk
    order = {
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 65,
        "action": "BUY",
        "pricetype": "LIMIT",
        "price": 100,
        "tag": "outside",
    }
    g.submit(order)
    g.fill("1", 65, 100)
    g.submit({**order, "action": "SELL"})
    g.fill("2", 65, 110)
    c.reconcile()
    g.now += 86400
    c.reconcile()
    assert (
        c.state()["day"]["date"] == "2026-10-15"
        and c.state()["journals"]["2026-10-14"]["gross_realised"] == 650
    )


def test_automatic_target_survives_restart_and_confirms_stop_cancel_before_sell(desk):
    c, g, s = desk
    tid = ticket(c)
    with s.lock(c.scope) as owner:
        d = c.state()
        d["tickets"][tid]["auto_target"] = True
        c.save(d, owner)
    c.enter(tid)
    g.fill("1", 65)
    c.reconcile()
    assert g.calls[-1]["pricetype"] == "SL"
    c = Coordinator(s, g, clock=g.clock)
    g.quote = lambda *a: {"bid": 122, "ask": 122.05, "time": g.clock()}
    c.reconcile()
    assert len(g.calls) == 2  # This pass cancels protection only.
    c.reconcile()
    assert g.calls[-1]["pricetype"] == "MARKET"
    assert g.calls[-1]["quantity"] == 65
    assert g.calls[-1]["action"] == "SELL"
    g.fill("3", 65, 122)
    c.reconcile()
    c.reconcile()
    assert c.state()["trades"][tid]["status"] == "closed"
    assert len(g.calls) == 3


def test_automatic_target_ignores_stale_high_price(desk):
    c, g, s, tid = entered(desk)
    with s.lock(c.scope) as owner:
        d = c.state()
        d["trades"][tid]["auto_target"] = True
        c.save(d, owner)
    g.quote = lambda *a: {"bid": 130, "ask": 131, "time": g.clock() - 30}
    c.reconcile()
    assert len(g.calls) == 2
    assert c.state()["trades"][tid]["exit_goal"] is None


def test_broker_stop_fill_closes_without_duplicate_sell_after_restart(desk):
    c, g, s, tid = entered(desk)
    g.fill("2", 65, 90)
    c = Coordinator(s, g, clock=g.clock)
    c.reconcile()
    c.reconcile()
    assert c.state()["trades"][tid]["status"] == "closed"
    assert len(g.calls) == 2


def record_round_trip(g, price=110):
    payload = dict(
        symbol="NIFTY15OCT2622600CE",
        exchange="NFO",
        product="MIS",
        quantity=65,
        action="BUY",
        pricetype="LIMIT",
        price=100,
        tag="external",
    )
    oid = g.submit(payload)["orderid"]
    g.fill(oid, 65, 100)
    oid = g.submit({**payload, "action": "SELL"})["orderid"]
    g.fill(oid, 65, price)


def test_manual_entry_can_proceed_after_streak_guidance_before_three_entries(desk):
    c, g, _ = desk
    c.configure({})
    for _ in range(2):
        record_round_trip(g, 90)
    c.reconcile()
    assert c.state()["day"]["entry_limits"]["blocked_reason"]
    assert c.state()["day"]["entry_limits"]["entries"] == 2
    p = c.preview(
        {
            "manual_entry": True,
            "symbol": "NIFTY15OCT2622600CE",
            "exchange": "NFO",
            "product": "MIS",
            "quantity": 65,
            "entry": 100,
            "sl": 90,
            "target": 122,
        }
    )
    trade = c.enter(p["ticket"])
    assert trade["manual_entry"] is True
    assert g.calls[-1]["action"] == "BUY"


def test_manual_entry_still_honours_a_configured_daily_loss_limit(desk):
    c, g, _ = desk
    c.configure({"daily_loss": 500})
    record_round_trip(g, 90)
    with pytest.raises(ValueError, match="Daily loss limit reached"):
        c.preview(
            {
                "manual_entry": True,
                "symbol": "NIFTY15OCT2622600CE",
                "exchange": "NFO",
                "product": "MIS",
                "quantity": 65,
                "entry": 100,
                "sl": 90,
                "target": 122,
            }
        )
    assert len(g.calls) == 2


def test_three_filled_entries_block_fourth_after_restart(desk):
    c, g, s = desk
    for _ in range(3):
        record_round_trip(g)
    c = Coordinator(s, g, clock=g.clock)
    with pytest.raises(ValueError, match="3 entries"):
        ticket(c)
    c.reconcile()
    assert c.state()["day"]["entry_limits"]["entries"] == 3
    assert c.state()["day"]["entry_limits"]["losses"] == 0


def test_two_net_losing_trades_block_entries_even_with_winner_between(desk):
    c, g, s = desk
    for price in (99.9, 110, 99.9):
        record_round_trip(g, price)
    with pytest.raises(ValueError, match="2 losing trades"):
        ticket(c)
    c.reconcile()
    assert c.state()["day"]["entry_limits"]["losses"] == 2


def test_partial_entry_fills_count_once_and_limits_do_not_block_exit(desk):
    c, g, s = desk
    tid = ticket(c)
    c.enter(tid)
    g.fill("1", 30)
    g.fill("1", 35)
    c.reconcile()
    assert c.state()["day"]["entry_limits"]["entries"] == 1
    with s.lock(c.scope) as owner:
        d = c.state()
        d["day"]["halt"] = "Daily entry limit reached · 3 entries"
        c.save(d, owner)
    c.exit(tid, request_id="exit-despite-limit")
    c.reconcile()
    assert g.calls[-1]["action"] == "SELL" and g.calls[-1]["pricetype"] == "MARKET"


def test_entry_ticket_rechecks_loss_cap_at_click_time(desk):
    c, g, _ = desk
    preview = ticket(c)
    record_round_trip(g, 99.9)
    record_round_trip(g, 99.9)
    with pytest.raises(ValueError, match="2 losing trades"):
        c.enter(preview)
    assert len(g.calls) == 4


def test_daily_entry_limits_survive_book_omission_and_reset_next_ist_day(desk):
    c, g, _ = desk
    for _ in range(3):
        record_round_trip(g)
    c.reconcile()
    g.fills = []
    c.reconcile()
    assert c.state()["day"]["entry_limits"]["entries"] == 3
    assert c.state()["day"]["entry_limits"]["blocked_reason"]
    g.now += 86400
    c.reconcile()
    assert c.state()["day"]["entry_limits"]["entries"] == 0
    assert c.state()["day"]["entry_limits"]["losses"] == 0
    assert not c.state()["day"]["halt"]


def test_entry_cap_does_not_trigger_optional_account_risk_exit(desk):
    c, g, s = desk
    record_round_trip(g, 110)
    record_round_trip(g, 110)
    tid = ticket(c)
    with s.lock(c.scope) as owner:
        d = c.state()
        d["tickets"][tid]["auto_risk"] = True
        c.save(d, owner)
    c.enter(tid)
    g.fill("5", 65)
    c.reconcile()
    assert c.state()["day"]["entry_limits"]["entries"] == 3
    assert c.state()["trades"][tid]["exit_goal"] is None
    assert g.calls[-1]["pricetype"] == "SL"


def test_manual_entry_cannot_bypass_three_filled_entries(desk):
    c, g, s = desk
    c.configure({})
    for _ in range(3):
        record_round_trip(g, 110)
    c = Coordinator(s, g, clock=g.clock)
    with pytest.raises(ValueError, match="3 entries"):
        c.preview(
            {
                "manual_entry": True,
                "symbol": "NIFTY15OCT2622600CE",
                "exchange": "NFO",
                "product": "MIS",
                "quantity": 65,
                "entry": 100,
                "sl": 90,
                "target": 122,
            }
        )
    assert len(g.calls) == 6


def test_entry_counter_detects_new_orders_after_broker_omits_previous_fills(desk):
    c, g, _ = desk
    record_round_trip(g)
    c.reconcile()
    g.fills = []
    record_round_trip(g)
    c.reconcile()
    assert c.state()["day"]["entry_limits"]["entries"] == 2
    assert c.state()["day"]["journal"]["gross_realised"] == 1300


def test_daily_cash_warnings_are_durable_but_do_not_request_exits(desk):
    c, g, s = desk
    record_round_trip(g, 140)
    c.reconcile()
    d = c.state()["day"]["discipline"]
    assert d["profit_reached"] and d["profit_target"] == 2000
    first = d["profit_reached_at"]
    record_round_trip(g, 40)
    c = Coordinator(s, g, clock=g.clock)
    c.reconcile()
    d = c.state()["day"]["discipline"]
    assert d["profit_reached_at"] == first and d["loss_reached"]
    assert d["loss_limit"] == 1000 and d["remaining_entries"] == 1
    assert len(g.calls) == 4
    g.now += 86400
    c.reconcile()
    d = c.state()["day"]["discipline"]
    assert not d["profit_reached"] and not d["loss_reached"] and d["entries"] == 0


@pytest.mark.parametrize("manual", [False, True])
def test_profit_milestone_allows_remaining_entries_but_not_a_fourth(desk, manual):
    c, g, _ = desk
    request = {
        "manual_entry": manual,
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 65,
        "entry": 100,
        "sl": 90,
        "target": 122,
    }
    record_round_trip(g, 140)
    c.reconcile()
    assert c.state()["day"]["discipline"]["profit_reached"]
    assert c.preview(request)["ticket"]
    record_round_trip(g, 140)
    c.reconcile()
    assert c.state()["day"]["discipline"]["entries"] == 2
    assert c.preview(request)["ticket"]
    record_round_trip(g, 140)
    with pytest.raises(ValueError, match="3 entries"):
        c.preview(request)
    assert len(g.calls) == 6


def test_changed_saved_fill_cannot_silently_preserve_old_account_pnl(desk):
    c, g, _ = desk
    record_round_trip(g)
    c.reconcile()
    g.fills[0]["average_price"] = 50
    c.reconcile()
    assert not c.state()["day"]["risk_available"]


def test_missing_fills_with_completed_orders_cannot_allow_fourth_entry(desk):
    c, g, _ = desk
    for _ in range(3):
        record_round_trip(g)
    g.fills = []
    with pytest.raises(ValueError):
        c.preview(
            {
                "manual_entry": True,
                "symbol": "NIFTY15OCT2622600CE",
                "exchange": "NFO",
                "product": "MIS",
                "quantity": 65,
                "entry": 100,
                "sl": 90,
                "target": 122,
            }
        )
    c.reconcile()
    assert not c.state()["day"]["risk_available"]


def test_previous_evening_order_creation_does_not_hide_unknown_today_fills(desk):
    c, g, _ = desk
    for _ in range(3):
        record_round_trip(g)
    for order in g.orders:
        order["timestamp"] = "13-Oct-2026 18:30:00"
    g.fills = []
    with pytest.raises(ValueError):
        c.preview(
            {
                "manual_entry": True,
                "symbol": "NIFTY15OCT2622600CE",
                "exchange": "NFO",
                "product": "MIS",
                "quantity": 65,
                "entry": 100,
                "sl": 90,
                "target": 122,
            }
        )
