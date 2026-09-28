"""The managed option stop, admission and runner must describe the same trade."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from services.strategy_module import portfolio_governor as governor

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 9, 28, 10, 5, 10, tzinfo=IST)
SIGNAL = NOW.replace(second=0)
RECIPE = "one-lot-option-structure-runner-v5"
PROFILES = ("ema915", "macd200", "ema5", "regime50200", "box15", "sma_macd", "bollinger")


def contract(**overrides):
    return {
        "leg_id": 1, "symbol": "NIFTY29SEP2625000CE", "exchange": "NFO",
        "underlying": "NIFTY", "position": "B", "segment": "options",
        "quantity": 65, "lot_size": 65, "tick_size": 0.05, **overrides,
    }


def bars(low="39.5"):
    return [
        {"closed_at": (SIGNAL - timedelta(minutes=n)).isoformat(),
         "open": "39.8", "high": "40", "low": low, "close": "39.9"}
        for n in (2, 1, 0)
    ]


def plan(**overrides):
    from services.risk.option_structure import structure_plan
    return structure_plan(contract(), bars(), SIGNAL.isoformat(), "40", "39.95", **overrides)


def leg(profile="ema915", **overrides):
    p = plan()
    return contract(
        sl_pts=float(Decimal(p["entry_price"]) - Decimal(p["stop_price"])),
        target_pts=None, initial_stop_price=float(p["stop_price"]),
        scalp_context={"profile": profile, "risk_recipe": RECIPE,
                       "risk_policy_version": "equity-1pct-v2", "exit_basis": "option_premium",
                       "structure": p, "entry": 25000, "stop": 24900, "target": 25200,
                       "direction": "CE"},
        **overrides,
    )


def test_stop_uses_completed_option_structure_and_separate_objective():
    p = plan()
    assert Decimal(p["stop_price"]) == Decimal("39.45")
    assert Decimal(p["planned_gross_loss"]) == Decimal("35.75")
    assert p["objective_r"] == 3
    assert p["hard_target"] is False
    assert p["profit_milestone_inr"] == 900


@pytest.mark.parametrize("mutation", ["gap", "future", "duplicate", "yesterday", "invalid_ohlc", "nan"])
def test_bad_option_history_cannot_supply_stop(mutation):
    from services.risk.option_structure import structure_plan
    rows = bars()
    if mutation == "gap": rows[0]["closed_at"] = (SIGNAL - timedelta(minutes=3)).isoformat()
    if mutation == "future": rows[-1]["closed_at"] = (SIGNAL + timedelta(minutes=1)).isoformat()
    if mutation == "duplicate": rows[1]["closed_at"] = rows[0]["closed_at"]
    if mutation == "yesterday": rows[0]["closed_at"] = (SIGNAL - timedelta(days=1)).isoformat()
    if mutation == "invalid_ohlc": rows[0]["low"] = "50"
    if mutation == "nan": rows[0]["low"] = "NaN"
    with pytest.raises(ValueError):
        structure_plan(contract(), rows, SIGNAL.isoformat(), "40", "39.95")


def test_broken_structure_is_rejected_and_wide_stop_is_not_tightened():
    from services.risk.option_structure import structure_plan
    with pytest.raises(ValueError, match="stop"):
        structure_plan(contract(), bars(), SIGNAL.isoformat(), "39.4", "39.35")
    wide = structure_plan(contract(), bars("30"), SIGNAL.isoformat(), "40", "39.95")
    assert Decimal(wide["stop_price"]) == Decimal("29.95")
    assert Decimal(wide["planned_gross_loss"]) > 300


@pytest.mark.parametrize("profile", PROFILES)
def test_all_profiles_use_premium_objective_and_absolute_stop(monkeypatch, profile):
    from database import auth_db, strategy_module_db as store
    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _: ("test", "kotak"))
    monkeypatch.setattr(governor, "_sandbox_account", lambda _: (Decimal("25000"), []))
    monkeypatch.setattr(store, "get_or_create_session_capital", lambda *a: Decimal("25000"))
    monkeypatch.setattr(governor, "_entry_price", lambda *a, **k: Decimal("40.20"))
    monkeypatch.setattr(governor, "_open_configured_risk", lambda *a: Decimal(0))
    monkeypatch.setattr(governor, "_session_history", lambda *a: (Decimal(0), 0, None))
    resolved = leg(profile)
    f = governor.build_entry_facts("alice", {"scalp_profile": profile}, [resolved], "key", "sandbox")
    assert f.minimum_reward_risk == 3
    assert f.reward_risk_basis == "option_premium_objective"
    assert f.entry_risk == Decimal("48.75")  # (40.20 adverse entry - 39.45 stop) * 65
    assert resolved["admission_entry_price"] == "40.20"


def test_entry_payload_uses_the_reserved_price_and_preserves_sandbox_legacy_orders():
    from services.strategy_module.order_dispatch import managed_entry_order
    strategy = {"name": "test", "product": "MIS", "pricetype": "MARKET"}
    row = leg() | {"admission_entry_price": "40.20"}
    for mode in ("sandbox", "live"):
        order = managed_entry_order(strategy, row, mode)
        assert order["pricetype"] == "LIMIT"
        assert Decimal(order["price"]) == Decimal("40.20")
    legacy = contract(sl_pts=2)
    assert managed_entry_order(strategy, legacy, "sandbox")["pricetype"] == "MARKET"
    with pytest.raises(ValueError, match="reserved"):
        managed_entry_order(strategy, legacy, "live")


def test_fill_does_not_reanchor_absolute_stop_and_profit_floor_never_recedes():
    from services.strategy_module import risk_adapter
    from services.risk.profit_exit import profit_config
    from test_trading_research import fees
    row = leg() | {"entry_avg": 40.2, "qty": 65,
                   "profit_protection": profit_config(contract(), fees(), recipe=RECIPE)}
    initial = risk_adapter.leg_to_position_risk(row)
    assert initial.initial_stop_price == 39.45
    risk_adapter.evaluate_leg(row, 50)
    assert row["effective_sl"] >= 50 - 300 / 65
    floor = row["effective_sl"]
    assert risk_adapter.evaluate_leg(row, 49).stop_price == floor
    assert row["effective_target"] is None


@pytest.mark.parametrize("profile", PROFILES)
def test_protect_leg_fetches_only_completed_option_history(monkeypatch, profile):
    from services import indicator_service
    from services.strategy_module import scalping
    rows = [{"timestamp": (datetime.fromisoformat(r["closed_at"]) - timedelta(minutes=1)).isoformat(),
             **{k: float(r[k]) for k in ("open", "high", "low", "close")}} for r in bars()]
    rows.append({"timestamp": SIGNAL.isoformat(), "open": 40, "high": 50, "low": 1, "close": 45})
    calls = []
    def history(client, symbol, exchange, interval, *a, **kw):
        calls.append((symbol, exchange, interval))
        return {"status": "success", "data": rows}
    monkeypatch.setattr(indicator_service, "fetch_history_cached", history)
    monkeypatch.setattr(scalping, "require_option_liquidity", lambda *a: None)
    client = SimpleNamespace(get_quotes=lambda *a: {"status": "success", "data": {
        "bid": 39.95, "ask": 40, "bid_qty": 65, "ask_qty": 65, "timestamp": NOW.isoformat()}})
    context = {"profile": profile, "risk_recipe": RECIPE, "signal_at": SIGNAL.isoformat(), "exit_basis": "option_premium"}
    result = scalping.protect_leg(contract(expiry="29-Sep-26"), context, client, now=NOW)
    assert calls == [(result["symbol"], "NFO", "1m")]
    assert result["initial_stop_price"] == 39.45
    assert result["target_pts"] is None
    assert context["structure"]["stop_price"] == "39.45"


def test_managed_context_and_research_keep_distinct_geometry_with_fixed_risk():
    from services.strategy_module.scalping import trade_context
    from services.risk.cash_exit import CASH_RISK_RECIPE, CASH_RECIPES
    context = trade_context("ema915", {"direction": "CE", "timestamp": SIGNAL.isoformat(), "low": 99, "high": 101}, 100)
    assert context["risk_recipe"] == RECIPE
    assert context["risk_policy_version"] == "fixed-300-v3"
    assert CASH_RISK_RECIPE == "one-lot-fixed300-profit-lock-v6"
    assert RECIPE not in CASH_RECIPES


@pytest.mark.parametrize("fault", ["missing_broker", "old_session", "missing_date"])
@pytest.mark.parametrize("owner", ["alice", "bob"])
def test_unrelated_owner_cannot_poison_history_but_own_invalid_run_blocks(monkeypatch, fault, owner):
    from database import strategy_module_db as store
    from services.strategy_module import state
    stamp = NOW if fault == "missing_broker" else NOW - timedelta(days=1)
    row = SimpleNamespace(id=1, strategy_id=99, mode="sandbox", broker=None if fault == "missing_broker" else "sandbox",
                          started_at=None if fault == "missing_date" else stamp)
    monkeypatch.setattr(store, "list_user_runs", lambda *a, **k: [])
    monkeypatch.setattr(state, "active_run_ids", lambda: [1])
    monkeypatch.setattr(store, "get_run", lambda _: row)
    monkeypatch.setattr(store, "get_strategy_unscoped", lambda _: SimpleNamespace(user_id=owner))
    monkeypatch.setattr(store, "filled_orders_have_usable_evidence", lambda *a, **k: True)
    result = governor._session_history("alice", NOW, "sandbox", "sandbox")
    assert result == ((Decimal(0), 0, None) if owner == "bob" else (None, None, None))


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("wide", [False, True])
def test_real_durable_admission_allows_affordable_structure_and_refuses_wide_stop(monkeypatch, tmp_path, profile, wide):
    from database import auth_db, strategy_module_db as store, trading_risk_db as ledger
    from database.engine_factory import create_db_engine
    from services.strategy_module import trading_budget
    from services.research import qualification
    from services.risk import budget
    from services.risk.option_structure import structure_plan
    from services.strategy_module.order_dispatch import managed_entry_order
    from test_trading_research import fees
    db = create_db_engine(f"sqlite:///{tmp_path}/admission.db")
    monkeypatch.setattr(ledger, "engine", db)
    monkeypatch.setattr(ledger, "POLICY", budget.current_policy(Decimal("10000")))
    ledger.init_db()
    costs = fees(brokerage_per_order=20)
    monkeypatch.setattr(ledger, "get_costs", lambda _, exchange=None: costs)
    monkeypatch.setattr(trading_budget, "reconcile_account", lambda *a: None)
    monkeypatch.setattr(qualification, "register_entry", lambda *a: None)
    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _: ("test", "kotak"))
    monkeypatch.setattr(governor, "_sandbox_account", lambda _: (Decimal("10000"), []))
    monkeypatch.setattr(store, "get_or_create_session_capital", lambda *a: Decimal("10000"))
    monkeypatch.setattr(governor, "_entry_price", lambda *a, **k: Decimal("40.00"))
    monkeypatch.setattr(governor, "_open_configured_risk", lambda *a: Decimal(0))
    monkeypatch.setattr(governor, "_session_history", lambda *a: (Decimal(0), 0, None))
    resolved = leg(profile) | {"position_ref": "fixture-entry"}
    if wide:
        p = structure_plan(contract(), bars("30"), SIGNAL.isoformat(), "40", "39.95")
        resolved.update(initial_stop_price=float(p["stop_price"]), sl_pts=10.05)
        resolved["scalp_context"]["structure"] = p
    strategy = {"id": 1, "name": "fixture", "scalp_profile": profile, "product": "MIS"}
    facts = governor.build_entry_facts("alice", strategy, [resolved], "fixture-key", "sandbox")
    # Force only venue-calendar inputs, keeping the real portfolio evaluator.
    from database import market_calendar_db
    monkeypatch.setattr(market_calendar_db, "get_effective_session_window", lambda *a: {
        "start_ms": int(NOW.replace(hour=9, minute=15).timestamp()*1000),
        "end_ms": int(NOW.replace(hour=15, minute=30).timestamp()*1000)})
    if not wide:
        assert governor.evaluate_entry(facts, governor.GovernorPolicy(), NOW).allowed
    decision, ref = trading_budget.reserve_entry("alice", strategy, [resolved], "sandbox", "sandbox", facts, NOW)
    assert decision.allowed is (not wide)
    if wide:
        assert decision.code == "per_trade_risk_exceeded"
        assert ref is None
        assert resolved["initial_stop_price"] == 29.95
    else:
        assert ref == "fixture-entry"
        row = ledger.list_trades("alice", "sandbox")[0]
        assert Decimal("35.75") < Decimal(str(row["planned_risk"])) <= 100
        assert resolved["profit_protection"]["version"] == RECIPE
        order = managed_entry_order(strategy, resolved, "sandbox")
        assert order["pricetype"] == "LIMIT" and order["price"] == "40.00"
    db.dispose()


@pytest.mark.parametrize("field,value", [("stop_price", "39.40"), ("objective_r", 9), ("hard_target", True)])
def test_tampered_plan_is_rejected(field, value):
    from services.risk.option_structure import objective_ratio
    row = leg()
    row["scalp_context"]["structure"][field] = value
    with pytest.raises(ValueError):
        objective_ratio(row, Decimal("40.20"))


def test_slow_history_cannot_make_a_stale_signal_look_current(monkeypatch):
    from services import indicator_service
    from services.strategy_module import scalping
    from services.risk.option_structure import STRUCTURE_RECIPE
    calls = iter([NOW, NOW + timedelta(seconds=50)])
    class Clock:
        fromisoformat = staticmethod(datetime.fromisoformat)
        now = staticmethod(lambda _: next(calls))
    monkeypatch.setattr(scalping, "datetime", Clock)
    records = [{"timestamp": (datetime.fromisoformat(r["closed_at"])-timedelta(minutes=1)).isoformat(),
                **{k: float(r[k]) for k in ("open", "high", "low", "close")}} for r in bars()]
    monkeypatch.setattr(indicator_service, "fetch_history_cached", lambda *a, **k: {"status": "success", "data": records})
    context = {"profile": "ema915", "risk_recipe": STRUCTURE_RECIPE, "signal_at": SIGNAL.isoformat()}
    with pytest.raises(ValueError, match="expired during"):
        scalping.protect_leg(contract(expiry="29-Sep-26"), context, SimpleNamespace(get_quotes=lambda *a: {}))


@pytest.mark.parametrize("mode", ["sandbox", "live"])
@pytest.mark.parametrize("bid", ["39.40", "39.45", None])
def test_final_dispatch_refuses_crossed_or_missing_structure_quote(monkeypatch, mode, bid):
    from services.strategy_module import order_dispatch as dispatch
    row = leg() | {"admission_entry_price": "40.20"}
    order = dispatch.managed_entry_order({"product": "MIS"}, row, mode)
    monkeypatch.setattr(dispatch, "resolve_live_auth", lambda _: ("token", "kotak", None))
    monkeypatch.setattr(governor, "_quote_price", lambda row, *a, **k: (Decimal(bid) if bid else None) if row["position"] == "S" else Decimal("39.60"))
    sent = []
    if mode == "sandbox":
        from services import sandbox_service
        monkeypatch.setattr(sandbox_service, "sandbox_place_order", lambda *a: sent.append(a))
        result = dispatch._dispatch_sandbox("key", order)
        assert not result.ok and "structure" in result.error.lower()
        assert not sent
    else:
        monkeypatch.setattr(dispatch, "_limit_price_from_quote", lambda *a: Decimal("39.60"))
        result, error = dispatch.bounded_live_entry_order(order, "token", "kotak")
        assert result is None and "structure" in error.lower()


def test_admission_requires_executable_bid_above_the_unchanged_stop(monkeypatch):
    row = leg()
    monkeypatch.setattr(governor, "_quote_price", lambda value, *a, **k: Decimal("39.45") if value["position"] == "S" else Decimal("40"))
    assert governor._entry_price(row, "sandbox", "token", "kotak") is None


def test_pending_structure_entry_expires_without_closing_a_filled_trade():
    from services.strategy_module.scalping import pending_structure_expired
    context = {"risk_recipe": RECIPE, "signal_at": SIGNAL.isoformat()}
    orders = [{"kind": "entry", "status": "pending", "filled_qty": 0}]
    assert not pending_structure_expired(context, orders, NOW)
    assert pending_structure_expired(context, orders, NOW+timedelta(seconds=50))
    assert not pending_structure_expired(context, [{**orders[0], "status": "complete", "filled_qty": 65}], NOW+timedelta(seconds=50))
    assert pending_structure_expired(context, [{**orders[0], "status": "partially_filled", "filled_qty": 20}], NOW+timedelta(seconds=50))


def test_sandbox_rechecks_signal_age_after_the_final_quote(monkeypatch):
    from services.strategy_module import order_dispatch as dispatch, scalping
    from services import sandbox_service
    order = dispatch.managed_entry_order({}, leg() | {"admission_entry_price": "40.20"}, "sandbox")
    steps = []
    monkeypatch.setattr(dispatch, "resolve_live_auth", lambda _: ("token", "kotak", None))
    def quote(*a):
        steps.append("quote")
        return None
    monkeypatch.setattr(dispatch, "_structure_quote_reason", quote)
    def recheck(*a):
        assert steps == ["quote"]
        steps.append("freshness")
        return "Scalping signal expired before order submission"
    monkeypatch.setattr(scalping, "dispatch_reason", recheck)
    monkeypatch.setattr(sandbox_service, "sandbox_place_order", lambda *a: pytest.fail("Stale signal must not submit"))
    result = dispatch._dispatch_sandbox("key", order, scalp_metadata={"signal_at": SIGNAL.isoformat()})
    assert not result.ok and "expired" in result.error
    assert steps == ["quote", "freshness"]
