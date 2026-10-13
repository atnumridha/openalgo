"""Real native Sandbox persistence/dispatch, synthetic market boundary only."""

from decimal import Decimal as D
from types import SimpleNamespace

from test_native_entries import OWNER, boundary, isolated, prepare

from database import sandbox_db as sb
from database import strategy_module_db as native
from services.neo_desk.entries import submit_setup
from services.neo_desk.lifecycle import manage_once, update_protection
from services.strategy_module import engine, order_events, state
from test.neo_desk.conftest import when


def test_native_sandbox_entry_fill_trail_exit_and_flat(monkeypatch):
    sb.init_db()
    for model in (sb.SandboxOrders, sb.SandboxTrades, sb.SandboxPositions, sb.SandboxFunds):
        sb.db_session.query(model).filter_by(user_id=OWNER).delete()
    sb.db_session.add(
        sb.SandboxFunds(user_id=OWNER, total_capital=10000, available_balance=10000, used_margin=0)
    )
    sb.db_session.commit()
    from services.strategy_module.order_dispatch import dispatch_order

    boundary(monkeypatch, "CE", [])
    monkeypatch.setattr(engine.order_dispatch, "dispatch_order", dispatch_order)
    monkeypatch.setattr("services.sandbox_service.get_user_id_from_apikey", lambda key: OWNER)
    symbol = SimpleNamespace(
        lotsize=65,
        tick_size=0.05,
        instrumenttype="OPTIDX",
        symbol="NIFTY13OCT2622500CE",
        exchange="NFO",
    )
    monkeypatch.setattr("sandbox.order_manager.get_symbol_info", lambda *a: symbol)
    monkeypatch.setattr("sandbox.fund_manager.get_symbol_info", lambda *a: symbol)
    price = [50]
    monkeypatch.setattr(
        "sandbox.execution_engine.ExecutionEngine._fetch_quote",
        lambda *a: {"ltp": price[0], "bid": price[0], "ask": price[0], "high": 100, "low": 1},
    )
    monkeypatch.setattr(
        engine.order_dispatch,
        "_dispatch_live",
        lambda *a: (_ for _ in ()).throw(AssertionError("Live dispatch forbidden")),
    )
    setup, chosen = prepare("CE")
    result = submit_setup(OWNER, setup, chosen, "sandbox", now=when())
    assert result.ok, result.error

    def facts():
        for order in native.list_orders(result.run_id):
            fact = (
                sb.db_session.query(sb.SandboxOrders)
                .filter_by(orderid=order["broker_order_id"])
                .one()
            )
            order_events._apply_update(
                order["broker_order_id"],
                SimpleNamespace(
                    orderid=order["broker_order_id"],
                    order_status=fact.order_status,
                    average_price=float(fact.average_price or 0),
                    filled_quantity=fact.filled_quantity,
                    rejection_reason="",
                ),
            )

    facts()
    leg = state.get_run_state(result.run_id)["legs"]["1"]
    assert leg["qty"] == 65 and leg["entry_avg"] == 50
    price[0] = 70
    update_protection(
        OWNER,
        str(result.run_id),
        {"cash_trail_enabled": True, "cash_activation": "1000", "cash_distance": "250"},
        quote_provider=lambda *a: D(70),
    )
    manage_once(
        OWNER,
        now=when("10:00"),
        quote_provider=lambda s, e: setup.index_reference if e == "NSE_INDEX" else D(70),
    )
    price[0] = 65
    manage_once(
        OWNER,
        now=when("10:01"),
        quote_provider=lambda s, e: setup.index_reference if e == "NSE_INDEX" else D(65),
    )
    facts()
    assert native.get_run(result.run_id).stopped_at is not None
    assert sb.db_session.query(sb.SandboxPositions).filter_by(user_id=OWNER).one().quantity == 0
    assert sb.db_session.query(sb.SandboxTrades).filter_by(user_id=OWNER).count() == 2
    assert len(native.list_orders(result.run_id)) == 2
