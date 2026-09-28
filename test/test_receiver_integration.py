"""Receiver installation and runtime stay in the managed long-option pipeline."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_receiver_rules import IST, confirmation, momentum_bars


def test_nine_option_templates_have_distinct_durable_profiles_and_valid_graphs():
    from blueprints.strategy_module import validate_strategy_config
    from services.flow_workflow_validator import validate_workflow
    from services.strategy_module import starter_pack, starter_workflows

    rows = starter_pack.starter_definitions()[:9]
    assert {r.get("scalp_profile") for r in rows} == {
        "receiver_trend",
        "receiver_retest",
        "receiver_momentum",
    }
    for i, row in enumerate(rows, 1):
        assert validate_strategy_config(row)[1] is None
        graph = starter_workflows.workflow_definitions({row["name"]: i}, "alice")[0]
        assert validate_workflow(graph, strict=True) == []
        assert len(graph["nodes"]) == 2
        run = next(n for n in graph["nodes"] if n["id"] == "run")
        assert run["data"]["barEvidence"] == {"scalpProfile": row["scalp_profile"]}
        assert run["data"]["mode"] == "sandbox"


def test_receiver_validation_never_allows_naked_short_or_multiple_lots():
    from blueprints.strategy_module import validate_strategy_config
    from services.strategy_module.starter_pack import starter_definitions

    row = deepcopy(starter_definitions()[0])
    row["scalp_profile"] = "receiver_trend"
    assert validate_strategy_config(row)[1] is None
    for field, value in (("position", "S"), ("lots", 2), ("segment", "futures")):
        wrong = deepcopy(row)
        wrong["legs"][0][field] = value
        assert validate_strategy_config(wrong)[1]


def test_recreating_missing_flow_keeps_existing_legacy_strategy_compatible():
    from services.strategy_module import starter_workflows

    name = "NIFTY Breakout and Retest Signal Receiver"
    graph = starter_workflows.workflow_definitions(
        {name: 21}, "alice", strategy_profiles={name: None}
    )[0]
    assert graph == starter_workflows.legacy_definition(
        name, 21, "NIFTY", "NSE_INDEX", "standard", "alice"
    )
    upgraded = starter_workflows.workflow_definitions(
        {name: 21}, "alice", strategy_profiles={name: "receiver_retest"}
    )[0]
    assert len(upgraded["nodes"]) == 2


def test_receiver_prepare_uses_real_candle_claim_and_logs_both_direction_and_rules(monkeypatch):
    from database import flow_db, market_calendar_db
    from database import strategy_module_db as store
    from services import indicator_service, option_symbol_service
    from services.flow_openalgo_client import FlowOpenAlgoClient
    from services.strategy_module import ml_forest, portfolio_governor, receiver, scalping

    flow_db.init_db()
    workflow = flow_db.create_workflow(name="receiver-" + uuid4().hex, nodes=[], edges=[])
    one = flow_db.create_execution(workflow.id, "running")
    origin = {"workflow_id": workflow.id, "execution_id": one.id}
    now = datetime(2026, 9, 28, 12, 0, 10, tzinfo=IST)
    monkeypatch.setattr(
        market_calendar_db,
        "get_effective_session_window",
        lambda *args: {
            "start_ms": int(now.replace(hour=9, minute=15, second=0).timestamp() * 1000),
            "end_ms": int(now.replace(hour=15, minute=30, second=0).timestamp() * 1000),
        },
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(receiver, "datetime", Clock)
    monkeypatch.setattr(scalping, "require_origin", lambda *args: origin)
    monkeypatch.setattr(ml_forest, "require_replay_pacing", lambda *args, **kwargs: None)
    monkeypatch.setattr(portfolio_governor, "entry_window_refusal", lambda *args: None)
    monkeypatch.setattr(
        option_symbol_service, "resolve_underlying_quote", lambda *args: ("NIFTY", "NSE_INDEX")
    )
    monkeypatch.setattr(FlowOpenAlgoClient, "__init__", lambda self, *args: None)
    events = []
    monkeypatch.setattr(
        store, "record_event", lambda *args, **kwargs: events.append((args, kwargs))
    )
    frames = {"5m": momentum_bars(), "15m": confirmation()}

    def history(client, symbol, exchange, interval, *args, **kwargs):
        n = int(interval[:-1])
        rows = [
            {"timestamp": (at - timedelta(minutes=n)).isoformat(), **r.to_dict()}
            for at, r in frames[interval].iterrows()
        ]
        return {"status": "success", "data": rows}

    monkeypatch.setattr(indicator_service, "fetch_history_cached", history)
    strategy = {
        "id": 10,
        "scalp_profile": "receiver_momentum",
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "broker_connection_id": "pin",
        "exit_time": "15:20",
    }
    try:
        context = receiver.prepare(strategy, "alice", "key", "sandbox")
        assert (
            context["direction"] == "CE"
            and context["risk_recipe"] == "one-lot-option-structure-runner-v5"
        )
        assert context["exit_basis"] == "option_premium"
        two = flow_db.create_execution(workflow.id, "running")
        origin["execution_id"] = two.id
        with pytest.raises(scalping.WaitingForSignal, match="already evaluated"):
            receiver.prepare(strategy, "alice", "key", "sandbox")
        assert events[0][0][2] == "signal_evaluation"
        assert events[0][1]["payload"]["technical"]["direction"] == "CE"
        checks = events[0][1]["payload"]["technical"]["checks"]
        assert len(checks) == 4
        assert all(check["passed"] is (check["side"] == "CE") for check in checks)
    finally:
        flow_db.delete_workflow(workflow.id)
        flow_db.db_session.remove()


@pytest.mark.parametrize(
    "exchange,symbol,quantity,factor",
    [
        ("NFO", "NIFTY29SEP2625000CE", 10, None),
        ("BFO", "SENSEX01OCT2680000PE", 10, 1),
        ("MCX", "GOLDM30OCT2675000CE", 100, 0.1),
    ],
)
def test_option_structure_has_identical_rupee_loss_and_durable_units(
    exchange, symbol, quantity, factor
):
    from services.risk.option_structure import structure_plan, validate_structure

    at = datetime(2026, 9, 28, 12, tzinfo=IST)
    contract = {
        "exchange": exchange,
        "symbol": symbol,
        "position": "B",
        "quantity": quantity,
        "lot_size": quantity,
        "tick_size": 0.05,
    }
    if factor is not None:
        contract["price_multiplier"] = factor
    rows = [
        {
            "closed_at": (at - timedelta(minutes=n)).isoformat(),
            "open": 39.8,
            "high": 40,
            "low": 39.5,
            "close": 39.9,
        }
        for n in (2, 1, 0)
    ]
    plan = structure_plan(contract, rows, at.isoformat(), 40, 39.95)
    assert Decimal(plan["planned_gross_loss"]) == Decimal("5.5")
    contract["initial_stop_price"] = plan["stop_price"]
    assert validate_structure(contract, plan) == plan
    if exchange == "MCX":
        with pytest.raises(ValueError):
            validate_structure(contract | {"price_multiplier": 1}, plan)
        with pytest.raises(ValueError):
            structure_plan(
                {k: v for k, v in contract.items() if k != "price_multiplier"},
                rows,
                at.isoformat(),
                40,
                39.95,
            )


def test_mcx_warmup_resolves_one_long_atm_pair_and_reuses_underlying_quote(monkeypatch):
    from services import kotak_mcx_candles
    from services.strategy_module import live_protection, receiver, symbol_resolver

    requests = []
    warmed = []

    def resolve(request, underlying, exchange, strategy_type, **kwargs):
        requests.append((request, underlying, exchange, kwargs))
        return SimpleNamespace(
            ok=True, symbol="GOLDM30OCT2675000" + request["option_type"], underlying_ltp=75000
        )

    monkeypatch.setattr(symbol_resolver, "resolve_leg", resolve)
    monkeypatch.setattr(live_protection, "_active_kotak_pin", lambda *args: True)
    monkeypatch.setattr(
        kotak_mcx_candles,
        "warm_kotak_mcx_options",
        lambda *args: warmed.append(args) or {"status": "collecting_history"},
        raising=False,
    )
    strategy = {
        "underlying": "GOLDM",
        "underlying_exchange": "MCX",
        "strategy_type": "intraday",
        "broker_connection_id": "pin",
        "legs": [
            {
                "id": 1,
                "segment": "options",
                "position": "B",
                "lots": 1,
                "strike_mode": "atm",
                "atm_offset": "ATM",
                "expiry": "current",
            }
        ],
    }
    assert receiver.warm_option_history(strategy, "key")["status"] == "collecting_history"
    assert [r[0]["option_type"] for r in requests] == ["CE", "PE"]
    assert all(r[0]["action"] == "BUY" and r[0]["position"] == "B" for r in requests)
    assert requests[1][3]["underlying_ltp"] == 75000
    assert warmed == [("key", "pin", ["GOLDM30OCT2675000CE", "GOLDM30OCT2675000PE"])]


def test_receiver_profiles_reach_real_option_objective_for_bfo_and_mcx(monkeypatch):
    from database import auth_db
    from database import strategy_module_db as store
    from services.risk.option_structure import STRUCTURE_RECIPE, structure_plan
    from services.strategy_module import portfolio_governor as governor

    monkeypatch.setattr(auth_db, "get_auth_token_broker", lambda _: ("fixture", "kotak"))
    monkeypatch.setattr(governor, "_sandbox_account", lambda _: (Decimal("25000"), []))
    monkeypatch.setattr(store, "get_or_create_session_capital", lambda *args: Decimal("25000"))
    monkeypatch.setattr(governor, "_entry_price", lambda *args, **kwargs: Decimal("40.20"))
    monkeypatch.setattr(governor, "_open_configured_risk", lambda *args: Decimal(0))
    monkeypatch.setattr(governor, "_session_history", lambda *args: (Decimal(0), 0, None))
    at = datetime(2026, 9, 28, 12, tzinfo=IST)
    rows = [
        {
            "closed_at": (at - timedelta(minutes=n)).isoformat(),
            "open": 39.8,
            "high": 40,
            "low": 39.5,
            "close": 39.9,
        }
        for n in (2, 1, 0)
    ]
    for exchange, symbol, qty, factor in [
        ("BFO", "SENSEX01OCT2680000PE", 10, 1),
        ("MCX", "GOLDM30OCT2675000CE", 100, 0.1),
    ]:
        leg = {
            "exchange": exchange,
            "symbol": symbol,
            "position": "B",
            "segment": "options",
            "quantity": qty,
            "lot_size": qty,
            "tick_size": 0.05,
            "price_multiplier": factor,
        }
        p = structure_plan(leg, rows, at.isoformat(), 40, 39.95)
        leg.update(
            initial_stop_price=float(p["stop_price"]),
            sl_pts=0.55,
            target_pts=None,
            scalp_context={
                "profile": "receiver_momentum",
                "risk_recipe": STRUCTURE_RECIPE,
                "risk_policy_version": "fixed-300-v3",
                "exit_basis": "option_premium",
                "structure": p,
            },
        )
        facts = governor.build_entry_facts(
            "alice", {"scalp_profile": "receiver_momentum"}, [leg], "key", "sandbox"
        )
        assert facts.minimum_reward_risk == 3
        assert facts.entry_risk == Decimal("7.50")


def test_mcx_warmup_runs_between_signal_windows_without_claiming_or_fetching_bars(monkeypatch):
    from database import strategy_module_db as store
    from services import indicator_service
    from services.strategy_module import portfolio_governor, receiver, scalping

    now = datetime(2026, 9, 28, 12, 2, 10, tzinfo=IST)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(receiver, "datetime", Clock)
    monkeypatch.setattr(scalping, "require_origin", lambda *args: {})
    monkeypatch.setattr(portfolio_governor, "entry_window_refusal", lambda *args: None)
    monkeypatch.setattr(
        indicator_service,
        "current_completed_bar_start",
        lambda *args: now.replace(minute=0, second=0) - timedelta(minutes=5),
    )
    warmed = []
    monkeypatch.setattr(
        receiver,
        "warm_option_history",
        lambda *args: warmed.append(args) or {"status": "collecting_history"},
    )
    events = []
    monkeypatch.setattr(
        store, "record_event", lambda *args, **kwargs: events.append(kwargs["payload"])
    )
    strategy = {
        "id": 10,
        "scalp_profile": "receiver_momentum",
        "underlying": "GOLDM",
        "underlying_exchange": "MCX",
    }
    with pytest.raises(scalping.WaitingForSignal, match="Signal expired"):
        receiver.prepare(strategy, "alice", "key", "sandbox")
    assert len(warmed) == 1
    assert events[-1]["option_history_warmup"] == {"status": "collecting_history"}
    assert events[-1]["stage"] == "waiting"


def test_mcx_warmup_refuses_changed_connection_before_any_subscription(monkeypatch):
    from services.strategy_module import live_protection, receiver

    monkeypatch.setattr(live_protection, "_active_kotak_pin", lambda *args: False)
    with pytest.raises(receiver.scalping.WaitingForSignal, match="active Kotak connection"):
        receiver.warm_option_history({"broker_connection_id": "wrong"}, "key")
