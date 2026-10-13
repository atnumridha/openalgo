from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal as D

import pytest

from database import neo_desk_db as desk
from database import strategy_module_db as native
from services.neo_desk.entries import submit_setup
from services.neo_desk.presets import get_preset
from services.neo_desk.selection import select_contract
from services.neo_desk.signals import evaluate_setup
from services.strategy_module import engine, state
from services.strategy_module.order_dispatch import DispatchResult
from services.strategy_module.symbol_resolver import ResolvedLeg
from test.neo_desk.conftest import bars, contract, quote, when

OWNER = "neo_fixture_owner"


def clear_owner():
    desk.db_session.query(desk.NeoRunProtection).filter_by(owner=OWNER).delete()
    desk.db_session.query(desk.NeoClaim).filter_by(owner=OWNER).delete()
    desk.db_session.query(desk.NeoDesk).filter_by(owner=OWNER).delete()
    desk.db_session.commit()
    desk.db_session.remove()


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    native.init_db()
    desk.init_db()
    clear_owner()
    for s in native.list_strategies(OWNER):
        if s["current_run_id"]:
            state.clear_run_state(s["current_run_id"])
        native.set_strategy_status(s["id"], "stopped", None)
        native.delete_strategy(s["id"], OWNER)
    desk.configure(OWNER, profile="orb_trail", activation="Active", mode="sandbox")
    monkeypatch.setattr(engine, "_api_key_for", lambda u: "fixture-key")
    monkeypatch.setattr(engine, "_broker_for", lambda *a: "sandbox")
    monkeypatch.setattr(engine, "_subscribe_run", lambda *a: None)
    yield
    clear_owner()


def prepare(side):
    s = evaluate_setup(bars(direction=side), get_preset("orb_trail"))
    c = contract(side)
    chosen = select_contract(
        [c], {c.symbol: quote(c)}, get_preset("orb_trail"), D(10000), when(), direction=side
    )
    return s, chosen


def boundary(monkeypatch, side, orders):
    c = contract(side)
    monkeypatch.setattr(
        engine,
        "resolve_leg",
        lambda *a, **kw: ResolvedLeg(
            ok=True,
            symbol=c.symbol,
            exchange="NFO",
            segment="options",
            lotsize=65,
            tick_size=0.05,
            strike=22500,
            expiry="13-OCT-26",
            expiry_symbol="13OCT26",
            quantity=65,
            lots=1,
            option_type=side,
            underlying="NIFTY",
        ),
    )

    def dispatch(**kw):
        orders.append(kw["order"])
        return DispatchResult(ok=True, broker_order_id="SB-fixture")

    monkeypatch.setattr(engine.order_dispatch, "dispatch_order", dispatch)


@pytest.mark.parametrize("side", ["CE", "PE"])
def test_put_setup_buys_put(monkeypatch, side):
    orders = []
    boundary(monkeypatch, side, orders)
    s, c = prepare(side)
    result = submit_setup(OWNER, s, c, "sandbox", now=when())
    assert result.ok, result.error
    assert len(orders) == 1 and orders[0]["action"] == "BUY"
    assert orders[0]["pricetype"] == "LIMIT" and D(str(orders[0]["price"])) == D("50.70")
    assert orders[0]["symbol"].endswith(side) and int(orders[0]["quantity"]) == 65
    assert len(native.list_orders(result.run_id)) == 1
    assert D(str(native.list_orders(result.run_id)[0]["price"])) == D("50.70")


def test_duplicate_signal_claim(monkeypatch):
    orders = []
    boundary(monkeypatch, "CE", orders)
    s, c = prepare("CE")

    def submit(_):
        try:
            return submit_setup(OWNER, s, c, "sandbox", now=when())
        finally:
            from utils.db_sessions import remove_all_scoped_sessions

            remove_all_scoped_sessions()
            desk.db_session.remove()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sum(r.ok for r in results) == 1 and len(orders) == 1


def test_recovered_signal_and_stopped_mode_refuse(monkeypatch):
    orders = []
    boundary(monkeypatch, "CE", orders)
    s, c = prepare("CE")
    assert not submit_setup(OWNER, s, c, "sandbox", now=when("09:46")).ok
    desk.configure(OWNER, activation="Stopped")
    assert not submit_setup(OWNER, s, c, "sandbox", now=when()).ok and orders == []


def test_research_never_routes_live(monkeypatch):
    desk.configure(OWNER, profile="price_retest", mode="live", activation="Active")
    s = evaluate_setup(bars("price_retest"), get_preset("price_retest"))
    _, c = prepare("CE")
    result = submit_setup(OWNER, s, c, "live", now=s.execute_at)
    assert not result.ok and "Sandbox" in result.error


def test_native_resolver_mismatch_never_dispatches(monkeypatch):
    orders = []
    boundary(monkeypatch, "CE", orders)
    monkeypatch.setattr(
        engine,
        "resolve_leg",
        lambda *a, **k: ResolvedLeg(
            ok=True, symbol="WRONG", exchange="NFO", quantity=65, option_type="CE"
        ),
    )
    s, c = prepare("CE")
    result = submit_setup(OWNER, s, c, "sandbox", now=when())
    assert not result.ok and orders == []
    assert "differs" in result.error


def test_same_confirmed_bar_cannot_trade_again_after_a_profile_switch(monkeypatch):
    from services.neo_desk.lifecycle import manage_once

    orders = []
    boundary(monkeypatch, "CE", orders)
    s, c = prepare("CE")
    first = submit_setup(OWNER, s, c, "sandbox", now=when())
    assert first.ok
    engine.apply_fill(first.run_id, 1, 50, True, filled_qty=65)
    engine.apply_fill(first.run_id, 1, 52, False, filled_qty=65)
    manage_once(OWNER, now=when(), quote_provider=lambda *a: D(50))
    desk.configure(OWNER, profile="orb_controls", activation="Active")
    second = submit_setup(OWNER, replace(s, profile="orb_controls"), c, "sandbox", now=when())
    assert not second.ok and len(orders) == 1


def test_native_manual_start_cannot_bypass_confirmed_provider_setup(monkeypatch):
    from services.neo_desk.service import NeoDeskService

    orders = []
    boundary(monkeypatch, "CE", orders)
    sid = NeoDeskService()._native_strategy(OWNER, desk.view(OWNER))
    result = engine.start_run(sid, OWNER, "sandbox")
    assert not result.ok and "confirmed" in result.error.lower()
    assert orders == []


def test_native_entry_uses_selected_two_lots_and_exact_quantity(monkeypatch):
    orders = []
    boundary(monkeypatch, "CE", orders)
    c = contract("CE")
    q = replace(quote(c), bid_qty=130, ask_qty=130)
    chosen = select_contract(
        [c], {c.symbol: q}, get_preset("orb_trail"), D(10000), when(), direction="CE"
    )
    assert chosen.quantity == 130
    monkeypatch.setattr(
        engine,
        "resolve_leg",
        lambda *a, **kw: ResolvedLeg(
            ok=True,
            symbol=c.symbol,
            exchange="NFO",
            segment="options",
            lotsize=65,
            tick_size=0.05,
            strike=22500,
            expiry="13-OCT-26",
            expiry_symbol="13OCT26",
            quantity=130,
            lots=2,
            option_type="CE",
            underlying="NIFTY",
        ),
    )
    s, _ = prepare("CE")
    result = submit_setup(OWNER, s, chosen, "sandbox", now=when())
    assert result.ok, result.error
    assert len(orders) == 1 and int(orders[0]["quantity"]) == 130
    assert desk.view(OWNER)["protection"]["quantity"] == 130
