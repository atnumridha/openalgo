from datetime import datetime
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
import pytz

from database import trading_risk_db as ledger
from database.engine_factory import create_db_engine
from services.risk.budget import current_policy, legacy_policy, policy_for_version
from services.strategy_module import trading_budget as service

NOW = pytz.timezone("Asia/Kolkata").localize(datetime(2026, 9, 26, 10))
COSTS = {
    "schedule_id": "fixture",
    "source": "test-only",
    "effective_from": "2026-01-01",
    "effective_to": "2026-12-31",
    "brokerage_per_order": 20,
    "exchange_rate": 0,
    "sebi_rate": 0,
    "gst_rate": 0,
    "stamp_buy_rate": 0,
    "stt_sell_rate": 0,
    "slippage_bps": 0,
}
LEG = {
    "position_ref": "p1",
    "leg_id": 1,
    "position": "B",
    "option_type": "CE",
    "exchange": "NFO",
    "symbol": "NIFTYTESTCE",
    "lot_size": 50,
    "quantity": 50,
}
STRATEGY = SimpleNamespace(id=1, strategy_type="intraday")
FACTS = SimpleNamespace(
    entry_risk=D("900"),
    estimated_debit=D("5000"),
    available_cash=D("10000000"),
    open_derivative_positions=0,
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", legacy_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/risk.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    yield
    engine.dispose()


def test_missing_costs_blocks_entry_and_explicit_costs_reserve_full_risk():
    assert (
        service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)[0].code
        == "cost_schedule_required"
    )
    ledger.set_costs("u", COSTS)
    decision, ref = service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)
    assert decision.allowed and ref == "p1"
    assert ledger.status("u", "sandbox", "2026-09-26")["reserved_risk"] == D("940")


def test_legacy_shared_admission_caps_gross_and_reserves_fees(monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", policy_for_version("shared-300-3r-v1", D("25000")))
    ledger.set_costs("new", COSTS)
    over = SimpleNamespace(**{**vars(FACTS), "entry_risk": D("301")})
    assert service.reserve_entry("new", STRATEGY, [LEG], "sandbox", "sandbox", over, NOW)[0].code == "per_trade_risk_exceeded"
    facts = SimpleNamespace(**{**vars(FACTS), "entry_risk": D("300")})
    decision, ref = service.reserve_entry("new", STRATEGY, [LEG], "sandbox", "sandbox", facts, NOW)
    assert decision.allowed and ref == "p1"
    snapshot = ledger.status("new", "sandbox", "2026-09-26")
    assert snapshot["per_trade_limit"] == D("300")
    assert snapshot["reserved_risk"] == D("340")


def test_fees_can_make_a_nominally_affordable_stop_unaffordable():
    ledger.set_costs("u", COSTS)
    facts = SimpleNamespace(**{**vars(FACTS), "entry_risk": D("980")})
    assert not service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", facts, NOW)[
        0
    ].allowed


def test_kotak_nse_costs_cannot_be_used_for_bse_or_another_broker():
    ledger.set_costs("u", {**COSTS, "exchange": "NFO", "broker": "kotak"})
    decision, _ = service.reserve_entry(
        "u", STRATEGY, [{**LEG, "exchange": "BFO"}], "sandbox", "kotak", FACTS, NOW
    )
    assert decision.code == "cost_schedule_exchange_mismatch"
    decision, _ = service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "other", FACTS, NOW)
    assert decision.code == "cost_schedule_broker_mismatch"
    decision, _ = service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "kotak", FACTS, NOW)
    assert decision.allowed


def test_kotak_costs_are_modeled_by_virtual_sandbox_but_not_a_live_sandbox_route():
    ledger.set_costs("u", {**COSTS, "exchange": "NFO", "broker": "kotak"})
    decision, _ = service.reserve_entry("u", STRATEGY, [LEG], "live", "sandbox", FACTS, NOW)
    assert decision.code == "cost_schedule_broker_mismatch"
    decision, _ = service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)
    assert decision.allowed


@pytest.mark.parametrize(("exchange", "fee", "expected_risk"), [
    ("NFO", 20, D("940")), ("BFO", 25, D("950")), ("MCX", 30, D("960")),
])
def test_entry_selects_its_saved_exchange_costs_without_replacing_nifty(exchange, fee, expected_risk):
    for market, brokerage in [("NFO", 20), ("BFO", 25), ("MCX", 30)]:
        ledger.set_costs("u", COSTS | {"exchange": market, "broker": "kotak",
                                      "brokerage_per_order": brokerage})
    ledger.init_db()  # schedules survive reload and additive schema initialization
    assert ledger.get_costs("u")["exchange"] == "NFO"
    leg = LEG | {"exchange": exchange, "price_multiplier": 1}
    decision, _ = service.reserve_entry("u", STRATEGY, [leg], "sandbox", "sandbox", FACTS, NOW)
    assert decision.allowed, decision.code
    trade = ledger.list_trades("u", "sandbox")[0]
    assert trade["planned_risk"] == expected_risk
    assert trade["details"]["costs"]["brokerage_per_order"] == fee
    assert trade["details"]["costs"]["exchange"] == exchange


def test_expired_exchange_costs_do_not_fall_back_to_other_market():
    ledger.set_costs("u", COSTS | {"exchange": "NFO"})
    ledger.set_costs("u", COSTS | {"exchange": "BFO", "effective_to": "2026-09-25"})
    decision, _ = service.reserve_entry("u", STRATEGY, [LEG | {"exchange": "BFO"}],
                                        "sandbox", "sandbox", FACTS, NOW)
    assert decision.code == "cost_schedule_expired_or_invalid"
    assert not ledger.list_trades("u", "sandbox")


def test_exchange_schedules_are_owner_scoped_and_keep_reserved_fees():
    ledger.set_costs("u", COSTS | {"exchange": "BFO"})
    ledger.set_costs("other", COSTS | {"exchange": "NFO", "brokerage_per_order": 0})
    decision, _ = service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)
    assert decision.code == "cost_schedule_exchange_mismatch"
    leg = LEG | {"exchange": "BFO"}
    assert service.reserve_entry("u", STRATEGY, [leg], "sandbox", "sandbox", FACTS, NOW)[0].allowed
    ledger.set_costs("u", COSTS | {"exchange": "BFO", "brokerage_per_order": 99})
    assert ledger.list_trades("u", "sandbox")[0]["details"]["costs"]["brokerage_per_order"] == 20


def test_unsupported_naked_option_or_incomplete_lot_is_refused():
    ledger.set_costs("u", COSTS)
    for override in ({"position": "S"}, {"quantity": 51}, {"lot_size": None}, {"exchange": "MCX"}):
        assert not service.reserve_entry(
            "u", STRATEGY, [{**LEG, **override}], "sandbox", "sandbox", FACTS, NOW
        )[0].allowed


def test_order_snapshots_charge_once_per_order_and_keep_partial_trade_identity(monkeypatch):
    from database import strategy_module_db as store
    from services.strategy_module import state

    ledger.set_costs("u", COSTS)
    assert service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)[0].allowed
    ledger.bind_run("u", "sandbox", "p1", 12)
    orders = [
        {
            "id": 1,
            "position_ref": "p1",
            "action": "BUY",
            "filled_qty": 50,
            "avg_fill_price": 100,
            "status": "complete",
        }
    ]
    monkeypatch.setattr(store, "list_orders", lambda _id: orders)
    monkeypatch.setattr(
        state, "get_run_state", lambda _id: {"legs": {"1": {"position_ref": "p1", "ltp": 100}}}
    )
    service.sync_run(12)
    assert ledger.list_trades("u", "sandbox")[0]["status"] == "open"
    orders.append(
        {
            "id": 2,
            "position_ref": "p1",
            "action": "SELL",
            "filled_qty": 20,
            "avg_fill_price": 95,
            "status": "open",
        }
    )
    service.sync_run(12)
    service.sync_run(12)
    orders[1].update(filled_qty=50, status="complete")
    service.sync_run(12)
    row = ledger.list_trades("u", "sandbox")[0]
    assert row["status"] == "closed"
    assert row["net_pnl"] == D("-290")
    assert len(ledger.list_trades("u", "sandbox")) == 1


def test_filled_order_with_missing_price_pauses_account(monkeypatch):
    from database import strategy_module_db as store

    ledger.set_costs("u", COSTS)
    service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)
    ledger.bind_run("u", "sandbox", "p1", 12)
    monkeypatch.setattr(
        store,
        "list_orders",
        lambda _id: [
            {
                "id": 1,
                "position_ref": "p1",
                "action": "BUY",
                "filled_qty": 50,
                "avg_fill_price": None,
                "status": "complete",
            }
        ],
    )
    service.sync_run(12)
    assert ledger.status("u", "sandbox", "2026-09-26")["paused"]


def test_late_fill_after_zero_fill_cancellation_restores_budget_exposure(monkeypatch):
    from database import strategy_module_db as store
    from services.strategy_module import state

    ledger.set_costs("u", COSTS)
    service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)
    ledger.bind_run("u", "sandbox", "p1", 12)
    order = {
        "id": 1,
        "position_ref": "p1",
        "action": "BUY",
        "filled_qty": 0,
        "avg_fill_price": None,
        "status": "cancelled",
    }
    monkeypatch.setattr(store, "list_orders", lambda _id: [order])
    monkeypatch.setattr(
        state, "get_run_state", lambda _id: {"legs": {"1": {"position_ref": "p1", "ltp": 100}}}
    )
    service.sync_run(12)
    assert ledger.list_trades("u", "sandbox")[0]["status"] == "void"
    order.update(filled_qty=50, avg_fill_price=100, status="complete")
    service.sync_run(12)
    row = ledger.list_trades("u", "sandbox")[0]
    assert row["status"] == "open"
    assert row["net_pnl"] == D("-40")
    assert ledger.status("u", "sandbox", "2026-09-26")["first_remaining"] == 60


def test_other_broker_position_cannot_mask_untracked_exposure():
    ledger.set_costs("u", COSTS)
    ledger.reserve(
        "u",
        "sandbox",
        "other",
        "2026-09-26",
        D("500"),
        D("2000"),
        "index",
        "broker-a",
        2,
        {"symbol": "NIFTYTESTCE", "exchange": "NFO"},
    )
    ledger.update_trade(
        "u",
        "sandbox",
        "other",
        status="open",
        net_pnl=D("0"),
        filled=True,
        evidence={"remaining_quantity": "50"},
    )
    facts = SimpleNamespace(
        **{
            **vars(FACTS),
            "entry_risk": D("100"),
            "estimated_debit": D("1000"),
            "open_derivative_positions": 1,
            "broker_quantities": (("NFO", "NIFTYTESTCE", D("50")),),
        }
    )
    leg = {**LEG, "exchange": "MCX", "price_multiplier": 1, "position_ref": "new"}
    decision, _ = service.reserve_entry("u", STRATEGY, [leg], "sandbox", "broker-b", facts, NOW)
    assert decision.code == "untracked_portfolio_exposure"


def test_stale_tick_snapshot_cannot_overwrite_a_newer_closed_loss(monkeypatch):
    from database import strategy_module_db as store
    from services.strategy_module import state

    ledger.set_costs("u", COSTS)
    service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)
    ledger.bind_run("u", "sandbox", "p1", 12)
    buy = {
        "id": 1,
        "position_ref": "p1",
        "action": "BUY",
        "filled_qty": 50,
        "avg_fill_price": 100,
        "status": "complete",
    }
    orders = [buy]
    monkeypatch.setattr(store, "list_orders", lambda _: list(orders))
    monkeypatch.setattr(
        state, "get_run_state", lambda _: {"legs": {"1": {"position_ref": "p1", "ltp": 100}}}
    )
    service.sync_run(12)
    stale_row = ledger.list_trades("u", "sandbox")[0]
    orders.append(
        {
            "id": 2,
            "position_ref": "p1",
            "action": "SELL",
            "filled_qty": 50,
            "avg_fill_price": 80,
            "status": "complete",
        }
    )
    service.sync_run(12)
    monkeypatch.setattr(
        state, "get_run_state", lambda _: {"legs": {"1": {"position_ref": "p1", "ltp": 95}}}
    )
    with pytest.raises(service.StaleTradeSnapshot):
        service._sync_trade(stale_row, [buy])
    result = ledger.list_trades("u", "sandbox")[0]
    assert result["status"] == "closed"
    assert result["net_pnl"] == D("-1040")


def test_partial_working_entry_keeps_full_cash_commitment(monkeypatch):
    from database import strategy_module_db as store
    from services.strategy_module import state

    ledger.set_costs("u", COSTS)
    service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)
    ledger.bind_run("u", "sandbox", "p1", 12)
    monkeypatch.setattr(
        store,
        "list_orders",
        lambda _: [
            {
                "id": 1,
                "position_ref": "p1",
                "action": "BUY",
                "filled_qty": 1,
                "avg_fill_price": 100,
                "status": "open",
            }
        ],
    )
    monkeypatch.setattr(
        state, "get_run_state", lambda _: {"legs": {"1": {"position_ref": "p1", "ltp": 100}}}
    )
    service.sync_run(12)
    facts = SimpleNamespace(
        **{
            **vars(FACTS),
            "open_derivative_positions": 1,
            "broker_quantities": (("NFO", "NIFTYTESTCE", D("1")),),
        }
    )
    candidate = {**LEG, "position_ref": "second", "exchange": "MCX", "price_multiplier": 1}
    decision, _ = service.reserve_entry(
        "u", STRATEGY, [candidate], "sandbox", "sandbox", facts, NOW
    )
    assert decision.code == "cash_buffer"


def test_concurrent_tick_update_retries_new_fill_evidence(monkeypatch):
    from database import strategy_module_db as store
    from services.strategy_module import state

    ledger.set_costs("u", COSTS)
    service.reserve_entry("u", STRATEGY, [LEG], "sandbox", "sandbox", FACTS, NOW)
    ledger.bind_run("u", "sandbox", "p1", 12)
    orders = [
        {
            "id": 1,
            "position_ref": "p1",
            "action": "BUY",
            "filled_qty": 50,
            "avg_fill_price": 100,
            "status": "complete",
        }
    ]
    monkeypatch.setattr(store, "list_orders", lambda _: list(orders))
    monkeypatch.setattr(
        state, "get_run_state", lambda _: {"legs": {"1": {"position_ref": "p1", "ltp": 100}}}
    )
    service.sync_run(12)
    orders.append(
        {
            "id": 2,
            "position_ref": "p1",
            "action": "SELL",
            "filled_qty": 50,
            "avg_fill_price": 80,
            "status": "complete",
        }
    )
    original = ledger.update_trade
    raced = []

    def compete(*args, **kwargs):
        if not raced:
            raced.append(True)
            original(
                *args, status="open", net_pnl=D("-90"), filled=True, evidence={"newer_tick": True}
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger, "update_trade", compete)
    service.sync_run(12)
    row = ledger.list_trades("u", "sandbox")[0]
    assert row["status"] == "closed"
    assert row["net_pnl"] == D("-1040")


def test_closed_loss_triggers_exit_for_other_active_run(monkeypatch):
    monkeypatch.setattr(service, "trading_day", lambda: "2026-09-26")
    monkeypatch.setattr(service, "reconcile_account", lambda *args: None)
    assert ledger.reserve(
        "u", "sandbox", "a", "2026-09-26", D("500"), D("2000"), "index", "sandbox", 1, {}
    ).allowed
    ledger.bind_run("u", "sandbox", "a", 12)
    ledger.update_trade(
        "u", "sandbox", "a", status="open", net_pnl=D("0"), filled=True, evidence={}
    )
    assert ledger.reserve(
        "u", "sandbox", "b", "2026-09-26", D("500"), D("2000"), "mcx", "sandbox", 2, {}
    ).allowed
    ledger.bind_run("u", "sandbox", "b", 13)
    ledger.update_trade(
        "u", "sandbox", "a", status="closed", net_pnl=D("-2000"), filled=True, evidence={}
    )
    assert service.breached_runs(12) == [(13, "u")]


def test_profit_protection_binds_admitted_fees_and_missing_tick_refuses(monkeypatch):
    from services.risk.profit_exit import TECHNICAL_PROFIT_RECIPE
    from services.strategy_module.risk_adapter import evaluate_leg
    from services.strategy_module.state import _new_leg_state
    monkeypatch.setattr(ledger, 'POLICY', current_policy())
    ledger.set_costs('profit', COSTS)
    facts = SimpleNamespace(**{**vars(FACTS), 'entry_risk': D('210')})
    leg = dict(LEG, scalp_context={'risk_recipe': TECHNICAL_PROFIT_RECIPE}, sl_pts=4.2, target_pts=12.6)
    decision, _ = service.reserve_entry('profit', STRATEGY, [leg], 'sandbox', 'sandbox', facts, NOW)
    assert not decision.allowed and decision.code == 'profit_protection_metadata_required'
    assert ledger.list_trades('profit', 'sandbox') == []
    leg['tick_size'] = .05
    decision, _ = service.reserve_entry('profit', STRATEGY, [leg], 'sandbox', 'sandbox', facts, NOW)
    assert decision.allowed
    assert leg['profit_protection']['version'] == TECHNICAL_PROFIT_RECIPE
    assert ledger.list_trades('profit', 'sandbox')[0]['planned_risk'] == D('250')
    ledger.set_costs('profit', COSTS | {'brokerage_per_order': 200})
    live = _new_leg_state(leg)
    live.update(entry_avg=100, status='open')
    decision = evaluate_leg(live, 106)
    assert decision.stop_price == 100.8  # admitted fees40 / units50, not the later400
    assert not decision.breached


def test_equity_admission_caps_total_loss_after_binding_operator_fees(monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", current_policy())
    ledger.set_costs("equity", COSTS)
    # Equity 25,000 permits 250 total: gross 210 plus two 20-rupee fees.
    over = SimpleNamespace(**{**vars(FACTS), "entry_risk": D("210.01")})
    refused, _ = service.reserve_entry("equity", STRATEGY, [LEG], "sandbox", "sandbox", over, NOW)
    assert refused.code == "per_trade_risk_exceeded"
    assert ledger.list_trades("equity", "sandbox") == []
    fits = SimpleNamespace(**{**vars(FACTS), "entry_risk": D("210")})
    decision, ref = service.reserve_entry("equity", STRATEGY, [LEG], "sandbox", "sandbox", fits, NOW)
    assert decision.allowed and ref == "p1"
    snapshot = ledger.status("equity", "sandbox", "2026-09-26")
    assert snapshot["per_trade_limit"] == D("250")
    assert snapshot["reserved_risk"] == D("250")
    assert snapshot["daily_remaining"] == D("500")


def test_legacy_schedule_survives_adding_an_exchange_and_qualification_selects_exact_scope(monkeypatch):
    from sqlalchemy.orm import Session
    from services.research.qualification_context import _risk_context

    original = COSTS | {"exchange": "NFO", "broker": "kotak"}
    with Session(ledger.engine) as db, db.begin():
        db.add(ledger.RiskSettings(user_id="u", costs=original))
    ledger.set_costs("u", COSTS | {"exchange": "BFO", "brokerage_per_order": 7})
    ledger.init_db()
    assert ledger.get_costs("u", "NFO") == original
    monkeypatch.setattr(service, "trading_day", lambda: "2026-09-26")
    assert _risk_context("u", "BFO")["costs"]["brokerage_per_order"] == 7
    assert _risk_context("u", "NFO")["costs"] == original
