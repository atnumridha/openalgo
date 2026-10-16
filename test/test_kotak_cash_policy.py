"""Cash policy boundaries and its durable, user-clicked execution lifecycle."""

import pytest
from test_kotak_assistant_execution import desk as desk

from services.kotak_assistant.execution import Coordinator


def test_cash_core_selects_widest_safe_stop_and_first_net_target_tick():
    from services.risk.cash_budget import cash_budget

    result = cash_budget(100, 65, 0.05, lambda exit_price: 10, slippage=0.1)
    assert result["fits"]
    assert result["sl"] == 92.6
    assert result["target"] == 123.35
    assert result["risk"] == 497.5
    assert result["reward"] == 1501.25
    assert result["net_target"] == 1500


def test_cash_core_refuses_budget_consumed_by_costs_and_one_stop_tick():
    from services.risk.cash_budget import cash_budget

    result = cash_budget(100, 65, 0.05, lambda exit_price: 10, loss_budget=12, slippage=0.1)
    assert not result["fits"]
    assert result["sl"] is None
    assert "budget" in result["reason"].lower()


def test_cash_adapter_includes_conservative_fees_and_whole_lots():
    from services.kotak_assistant.analysis import fees
    from services.kotak_assistant.risk_policy import plan_cash

    result = plan_cash(100, 65, 0.05, "NFO", {}, day="2026-10-16", lot=65)
    assert result["fits"] and result["risk"] <= 500 and result["reward"] >= 1500
    stop_exit = result["sl"] - 0.1
    lower_exit = stop_exit - 0.05
    assert (100 - lower_exit) * 65 + fees(6500, lower_exit * 65, "NFO", day="2026-10-16")[
        "total"
    ] > 500
    previous_target = result["target"] - 0.15
    assert (previous_target - 100) * 65 - fees(6500, previous_target * 65, "NFO", day="2026-10-16")[
        "total"
    ] < 1500
    assert result["cost_basis"]["slippage_per_unit"] == 0.1
    assert result["risk_policy"]["kind"] == "cash_budget"
    with pytest.raises(ValueError, match="whole lots"):
        plan_cash(100, 66, 0.05, "NFO", {}, day="2026-10-16", lot=65)


def test_trend_premium_stop_uses_lower_structural_reference_then_rounds_up():
    from services.risk.cash_budget import trend_premium_stop

    assert trend_premium_stop(100, 4, 95, 0.05) == 94
    assert trend_premium_stop(100, 2, 94.03, 0.05) == 94


def cash_request(**overrides):
    return {
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 65,
        "entry": 100,
        "sl": 1,
        "target": 101,
        "auto_target": True,
        "strategy": "opening_reversal",
        "strategy_version": "1.0",
        "risk_policy": {"kind": "cash_budget", "loss_budget": 500, "target_multiple": 3},
        **overrides,
    }


def test_preview_ignores_client_prices_and_persists_server_cash_policy(desk):
    c, g, _ = desk
    preview = c.preview(cash_request())
    assert preview["plan"]["risk"] <= 500
    assert preview["plan"]["reward"] >= 1500
    assert 90 < preview["plan"]["sl"] < 100 < 120 < preview["plan"]["target"]
    ticket = c.state()["tickets"][preview["ticket"]]
    assert ticket["strategy"] == "opening_reversal" and ticket["strategy_version"] == "1.0"
    assert ticket["sl"] == preview["plan"]["sl"]
    assert ticket["risk_policy"]["net_target"] == 1500
    assert not g.calls


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {},
        {"kind": "unknown"},
        {"kind": "cash_budget", "loss_budget": True, "target_multiple": 3},
        {"kind": "cash_budget", "loss_budget": -500, "target_multiple": 3},
        {"kind": "cash_budget", "loss_budget": 500, "target_multiple": float("nan")},
    ],
)
def test_opening_cash_policy_rejects_malformed_policy(desk, policy):
    c, g, _ = desk
    with pytest.raises(ValueError, match="[Pp]olicy|[Bb]udget|finite|positive"):
        c.preview(cash_request(sl=90, target=125, risk_policy=policy))
    assert not c.state()["tickets"] and not g.calls


def test_actual_fill_average_recomputes_target_without_loosening_stop_after_restart(desk):
    c, g, store = desk
    preview = c.preview(cash_request(quantity=130))
    tid = preview["ticket"]
    initial_stop, initial_target = preview["plan"]["sl"], preview["plan"]["target"]
    c.enter(tid)
    g.fill("1", 65, 99.5)
    c.reconcile()
    partial = c.state()["trades"][tid]
    assert partial["average_entry"] == 99.5
    assert g.calls[-1]["trigger_price"] >= initial_stop
    assert partial["target"] > initial_target
    partial_stop = max(partial["sl"], partial.get("desired_sl", 0))
    g.fill("1", 65, 100)
    restarted = Coordinator(store, g, clock=g.clock)
    restarted.reconcile()
    trade = restarted.state()["trades"][tid]
    assert trade["average_entry"] == 99.75 and trade["entry_quantity"] == 130
    assert trade["sl"] >= partial_stop
    assert trade["target"] < initial_target
    assert trade["risk_policy"]["net_target"] == 1500
    assert trade["strategy_version"] == "1.0"
    assert trade["fill_plan"]["cost_basis"]["basis"] == "confirmed_fills"
    assert trade["fill_plan"]["risk"] <= 500


def test_cash_target_uses_reconciled_fill_plan_before_automatic_exit(desk):
    c, g, _ = desk
    preview = c.preview(cash_request())
    tid = preview["ticket"]
    c.enter(tid)
    g.fill("1", 65, 99)
    c.reconcile()
    trade = c.state()["trades"][tid]
    assert trade["target"] < preview["plan"]["target"]
    g.quote = lambda symbol, exchange: {
        "bid": trade["target"],
        "ask": trade["target"] + 0.05,
        "time": g.clock(),
    }
    c.reconcile()
    assert c.state()["trades"][tid]["exit_reason"] == "Target reached"
    c.reconcile()
    assert len([order for order in g.calls if order["pricetype"] == "MARKET"]) == 1


def test_broker_fill_basis_regression_does_not_replace_confirmed_cash_plan(desk):
    c, g, _ = desk
    tid = c.preview(cash_request())["ticket"]
    c.enter(tid)
    g.fill("1", 65, 99)
    c.reconcile()
    previous = c.state()["trades"][tid]
    g.fills[0]["average_price"] = 98
    c.reconcile()
    blocked = c.state()["trades"][tid]
    assert blocked["status"] == "blocked"
    assert blocked["average_entry"] == previous["average_entry"]
    assert blocked["target"] == previous["target"]


def test_cash_core_includes_realized_gross_in_whole_trade_net_goal():
    from services.risk.cash_budget import cash_budget

    # A prior realized loss of 100 uses that much of the same 500 budget.
    result = cash_budget(100, 65, 0.05, lambda exit_price: 10, realized_gross=-100, slippage=0.1)
    assert result["sl"] == 94.1 and result["target"] == 124.9
    assert result["risk"] == 500 and result["reward"] == 1502


def test_partial_exit_replans_remaining_contracts_for_whole_trade_net_target(desk):
    from services.kotak_assistant.analysis import fees

    c, g, store = desk
    c.configure({**c.state()["settings"], "brokerage": 20})
    preview = c.preview(cash_request(quantity=130))
    tid = preview["ticket"]
    c.enter(tid)
    g.fill("1", 130, 100)
    c.reconcile()
    c.reconcile()
    initial_stop = c.state()["trades"][tid]["sl"]
    c.exit(tid, quantity=65, request_id="take-half")
    c.reconcile()
    exit_order = next(o for o in g.orders if o["action"] == "SELL" and o["pricetype"] == "MARKET")
    g.fill(exit_order["orderid"], 65, 100)
    restarted = Coordinator(store, g, clock=g.clock)
    restarted.reconcile()
    trade = restarted.state()["trades"][tid]
    assert trade["remaining"] == 65 and trade["target"] > preview["plan"]["target"]
    assert trade["sl"] >= initial_stop
    # Three charged orders: one entry, the confirmed partial exit, future exit.
    future_sell = (trade["target"] - 0.1) * 65
    estimated_fees = fees(13000, 6500 + future_sell, "NFO", 0, "2026-10-14")["total"] + 60 * 1.18
    whole_net = 6500 + future_sell - 13000 - estimated_fees
    assert whole_net >= 1500
    lower_sell = (trade["target"] - 0.15) * 65
    lower_costs = fees(13000, 6500 + lower_sell, "NFO", 0, "2026-10-14")["total"] + 60 * 1.18
    assert 6500 + lower_sell - 13000 - lower_costs < 1500
    assert trade["fill_plan"]["cost_basis"]["closed_quantity"] == 65
    assert trade["fill_plan"]["cost_basis"]["filled_order_count"] == 2


def test_split_partial_fill_protection_counts_every_possible_brokerage_order(desk):
    c, g, _ = desk
    c.configure({**c.state()["settings"], "brokerage": 20})
    tid = c.preview(cash_request(quantity=130))["ticket"]
    c.enter(tid)
    g.fill("1", 65, 100)
    c.reconcile()
    first_stop = g.calls[-1]["trigger_price"]
    g.fill("1", 65, 100)
    c.reconcile()
    trade = c.state()["trades"][tid]
    assert trade["fill_plan"]["cost_basis"]["expected_exit_orders"] == 2
    assert trade["sl"] > first_stop
    assert trade["fill_plan"]["risk"] <= 500
    # Allow cancellation confirmation and replacement to settle. Every live
    # stop must meet the tighter cash-budget floor, including the first one.
    for _ in range(4):
        c.reconcile()
    trade = c.state()["trades"][tid]
    active = [o for o in g.orders if o["action"] == "SELL" and o["order_status"] == "open"]
    assert active and all(o["trigger_price"] >= trade["sl"] for o in active)
