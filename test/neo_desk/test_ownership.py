from datetime import UTC, timezone
from decimal import Decimal as D

import pytest
from conftest import when
from test_native_entries import OWNER, boundary, isolated, prepare

from database import neo_desk_db as desk
from database import strategy_module_db as native
from services.neo_desk.entries import submit_setup
from services.neo_desk.lifecycle import (
    evaluate_schedule,
    manage_once,
    request_owned_exit,
    update_protection,
)
from services.strategy_module import engine, state
from services.strategy_module.order_dispatch import DispatchResult


def owned(monkeypatch, qty=65, mode="sandbox"):
    orders = []
    boundary(monkeypatch, "CE", orders)
    s, c = prepare("CE")
    result = submit_setup(OWNER, s, c, "sandbox", now=when())
    assert result.ok
    if mode == "live":
        row = native.get_run(result.run_id)
        row.mode = "live"
        native.db_session.commit()
    snap = state.get_run_state(result.run_id)
    leg = snap["legs"]["1"]
    native.update_order(
        leg["entry_order_id"],
        status="cancelled" if qty < 65 else "complete",
        filled_qty=qty,
        avg_fill_price=50,
    )
    engine.apply_fill(result.run_id, 1, 50, True, filled_qty=qty, position_ref=leg["position_ref"])
    return result.run_id, orders


@pytest.mark.parametrize("utc", [False, True])
def test_square_off_ist(monkeypatch, utc):
    rid, orders = owned(monkeypatch)
    for clock, expected in [("15:15", False), ("15:28", False), ("15:29", True)]:
        now = when(clock).astimezone(UTC) if utc else when(clock)
        assert evaluate_schedule(now, state.get_run_state(rid)) == expected
    manage_once(OWNER, now=when("15:29"), quote_provider=lambda *a: None)
    assert len(orders) == 2 and orders[-1]["action"] == "SELL" and int(orders[-1]["quantity"]) == 65


def test_live_origin_exit_after_analyzer_toggle(monkeypatch):
    rid, orders = owned(monkeypatch, mode="live")
    desk.configure(OWNER, mode="sandbox", activation="Stopped")
    calls = []

    def dispatch(**kw):
        calls.append(kw)
        return DispatchResult(ok=True, broker_order_id="LIVE-owned-exit")

    monkeypatch.setattr(engine.order_dispatch, "dispatch_order", dispatch)
    result = request_owned_exit(OWNER, str(rid), "Manual square off", "request-1")
    assert result["ok"] and len(calls) == 1 and calls[0]["mode"] == "live"
    assert int(calls[0]["order"]["quantity"]) == 65


def test_refused_exit_remains_managed(monkeypatch):
    rid, orders = owned(monkeypatch)
    monkeypatch.setattr(
        engine.order_dispatch,
        "dispatch_order",
        lambda **kw: DispatchResult(ok=False, error="Fixture refusal"),
    )
    assert not request_owned_exit(OWNER, str(rid), "Manual", "r1")["ok"]
    leg = state.get_run_state(rid)["legs"]["1"]
    assert leg["qty"] == 65 and leg["exit_claim_token"] is None
    monkeypatch.setattr(
        engine.order_dispatch,
        "dispatch_order",
        lambda **kw: DispatchResult(ok=True, broker_order_id="SB-retry"),
    )
    assert request_owned_exit(OWNER, str(rid), "Retry", "r2")["ok"]


def test_partial_cancelled_fill_exits_only_filled_quantity(monkeypatch):
    rid, orders = owned(monkeypatch, qty=20)
    assert request_owned_exit(OWNER, str(rid), "Manual", "p1")["ok"]
    assert int(orders[-1]["quantity"]) == 20
    assert request_owned_exit(OWNER, str(rid), "Manual", "p1")["stop_pending"]
    assert len(orders) == 2


def test_foreign_owner_cannot_close_or_change_bracket(monkeypatch):
    rid, orders = owned(monkeypatch)
    with pytest.raises(ValueError):
        update_protection(
            "foreign", str(rid), {"option_stop": "49"}, quote_provider=lambda *a: D(50), now=when()
        )
    assert not request_owned_exit("foreign", str(rid), "Manual", "bad")["ok"]
    assert len(orders) == 1


def test_manual_stop_is_persistent_and_cannot_loosen_cash_trail(monkeypatch):
    rid, orders = owned(monkeypatch)
    result = update_protection(
        OWNER,
        str(rid),
        {
            "option_stop": "48",
            "option_target": "80",
            "cash_trail_enabled": True,
            "cash_activation": "1000",
            "cash_distance": "250",
        },
        quote_provider=lambda *a: D(51),
        now=when(),
    )
    assert result["option_stop"] == "48" and result["option_target"] == "80"
    desk.db_session.remove()
    assert desk.view(OWNER)["protection"]["option_stop"] == "48"
    with pytest.raises(ValueError):
        update_protection(
            OWNER, str(rid), {"option_stop": "47"}, quote_provider=lambda *a: D(51), now=when()
        )
    assert len(orders) == 1


def test_stopped_entries_retain_exit_management(monkeypatch):
    rid, orders = owned(monkeypatch)
    desk.configure(OWNER, activation="Stopped")

    def quote(symbol, exchange):
        return D(89) if exchange == "NSE_INDEX" else D(50)

    manage_once(OWNER, now=when(), quote_provider=quote)
    assert len(orders) == 2 and orders[-1]["action"] == "SELL"


def test_running_entry_fees_are_not_charged_twice_by_daily_guard(monkeypatch):
    from services.neo_desk.fees import estimate
    from services.neo_desk.lifecycle import day_performance

    rid, orders = owned(monkeypatch)
    net, count = day_performance(OWNER, when().date())
    assert count == 1 and net == -estimate("BUY", D(50), 65)


def test_quote_read_cannot_block_independent_squareoff(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    rid, orders = owned(monkeypatch)
    entered = threading.Event()
    release = threading.Event()

    def blocked(symbol, exchange):
        entered.set()
        assert release.wait(2)
        return D(100)

    def guard():
        try:
            return manage_once(OWNER, now=when("15:28"), quote_provider=blocked)
        finally:
            from utils.db_sessions import remove_all_scoped_sessions

            remove_all_scoped_sessions()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(guard)
        assert entered.wait(1)
        try:
            from services.neo_desk.lifecycle import run_schedule_once

            run_schedule_once(OWNER, now=when("15:29"))
            assert len(orders) == 2
        finally:
            release.set()
        pending.result()
