"""Executable scalping presets must preserve causal signals and managed exits."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from services.strategy_module import scalping

IST = ZoneInfo("Asia/Kolkata")


def test_three_profiles_have_distinct_rules_and_safe_definitions():
    from blueprints.strategy_module import validate_strategy_config
    from services.flow_workflow_validator import validate_workflow
    from services.strategy_module.scalping_pack import definitions, workflow_definition

    rows = definitions()
    assert {r["scalp_profile"] for r in rows} == {"ema915", "regime50200", "box15"}
    for row in rows:
        config, error = validate_strategy_config(row)
        assert error is None
        assert config["legs"][0]["atm_offset"] == (
            "ITM1" if row["scalp_profile"] == "ema915" else "ATM"
        )
        assert config["scheduler"] is None
        graph = workflow_definition(row, 1, "owner", "connection")
        assert not validate_workflow(graph, strict=True), graph


def test_history_converts_start_to_close_and_drops_forming_rows():
    now = datetime(2026, 9, 25, 10, 5, 10, tzinfo=IST)
    rows = [
        {
            "timestamp": (now.replace(second=0) - timedelta(minutes=n)).isoformat(),
            "open": 100,
            "high": 102,
            "low": 99,
            "close": 101,
        }
        for n in (10, 5, 0)
    ]
    frame = scalping.closed_frame(rows, "5m", now)
    assert list(frame.index.hour) == [10, 10]
    assert list(frame.index.minute) == [0, 5]
    with pytest.raises(ValueError):
        scalping.closed_frame(rows + [rows[0]], "5m", now)


def test_stop_through_entry_rejected_and_two_r_target_is_index_price():
    signal = {"direction": "PE", "low": 95, "high": 105, "timestamp": "2026-09-25T10:00:00+05:30"}
    context = scalping.index_context(signal, 100)
    assert context["stop"] == 105
    assert context["target"] == 90
    assert context["deadline"] == "2026-09-25T10:15:00+05:30"
    with pytest.raises(ValueError, match="stop"):
        scalping.index_context(signal, 106)


def test_deadline_exit_does_not_need_a_quote_and_index_rules_use_risk_core():
    context = scalping.index_context(
        {"direction": "CE", "low": 95, "high": 101, "timestamp": "2026-09-25T10:00:00+05:30"}, 100
    )
    now = datetime(2026, 9, 25, 10, 10, tzinfo=IST)
    assert scalping.exit_reason(context, now, 94) == "overall_sl"
    assert scalping.exit_reason(context, now, 110) == "overall_target"
    assert scalping.exit_reason(context, now, None) is None
    assert scalping.exit_reason(context, now + timedelta(minutes=5), None) == "scheduler"


def test_bad_profile_and_incompatible_configuration_are_rejected():
    from blueprints.strategy_module import validate_strategy_config
    from services.strategy_module.scalping_pack import definitions

    row = definitions()[0]
    assert validate_strategy_config(row | {"scalp_profile": "fake"})[1]
    assert validate_strategy_config(row | {"underlying": "SENSEX"})[1]


def test_no_manual_signal_bypass():
    with pytest.raises(ValueError, match="automation"):
        scalping.prepare({"scalp_profile": "ema915"}, "owner", "key", "sandbox")


def test_generated_flow_waits_for_candle_settle_grace():
    from services.flow_scheduler_service import interval_alignment_offset, uses_completed_candles
    from services.indicator_service import FLOW_BAR_SETTLE_SECONDS
    from services.strategy_module.scalping_pack import definitions, workflow_definition

    graph = workflow_definition(definitions()[0], 1, "owner", "connection")
    assert uses_completed_candles(graph["nodes"])
    assert interval_alignment_offset(True) > FLOW_BAR_SETTLE_SECONDS


@pytest.mark.parametrize("stamp", [None, "2020-01-01T10:00:00+05:30", "2099-01-01T10:00:00+05:30"])
def test_stale_or_missing_native_index_quote_is_rejected(stamp):
    from types import SimpleNamespace

    client = SimpleNamespace(
        get_quotes=lambda *_: {"status": "success", "data": {"ltp": 100, "timestamp": stamp}}
    )
    with pytest.raises(ValueError, match="timestamp"):
        scalping.quote_price(client, "NIFTY", "NSE_INDEX")


def test_fresh_quote_is_accepted():
    from types import SimpleNamespace

    client = SimpleNamespace(
        get_quotes=lambda *_: {
            "status": "success",
            "data": {"ltp": 100, "timestamp": datetime.now(IST).isoformat()},
        }
    )
    assert scalping.quote_price(client, "NIFTY", "NSE_INDEX") == 100


def test_expired_signal_is_rejected_after_dispatch_quote_work(monkeypatch):
    from services.research import qualification_execution
    from services.strategy_module import order_dispatch

    calls = []
    monkeypatch.setattr(
        qualification_execution, "before_dispatch", lambda *a: calls.append("quote") or None
    )
    monkeypatch.setattr(order_dispatch, "_dispatch_sandbox", lambda *a: calls.append("order"))
    result = order_dispatch.dispatch_order(
        mode="sandbox",
        api_key="key",
        intent="entry",
        order={
            "_strategy_qualification": {"owner": "test"},
            "_strategy_scalp": {"signal_at": "2020-01-01T10:00:00+05:30"},
        },
    )
    assert not result.ok and "expired" in result.error
    assert calls == ["quote"]


def test_protect_leg_caps_risk_and_removes_option_target(monkeypatch):
    monkeypatch.setattr(scalping, "quote_price", lambda *a: 150)
    leg = {
        "expiry": (datetime.now(IST) + timedelta(days=3)).strftime("%d-%b-%y"),
        "quantity": 75,
        "lot_size": 75,
        "symbol": "NIFTY-CE",
        "exchange": "NFO",
        "target_pts": 35,
    }
    context = {}
    result = scalping.protect_leg(leg, context, None)
    assert result["sl_pts"] * 75 <= 800
    assert result["target_pts"] is None
    assert context["premium_stop_points"] == result["sl_pts"]
    monkeypatch.setattr(scalping, "quote_price", lambda *a: 300)
    with pytest.raises(ValueError, match="ceiling"):
        scalping.protect_leg(leg, {}, None)


def test_latest_signal_never_reuses_a_stale_signal(monkeypatch):
    from types import SimpleNamespace

    from services import indicator_service

    now = datetime(2026, 9, 25, 10, 1, 6, tzinfo=IST)
    index = pd.date_range(end="2026-09-25 10:00", periods=100, freq="5min", tz=IST)
    frame = pd.DataFrame({"open": 100, "high": 102, "low": 99, "close": 101}, index=index)
    monkeypatch.setattr(scalping, "closed_frame", lambda *a: frame)
    monkeypatch.setattr(scalping, "signals", lambda *a: frame.assign(direction="CE"))
    monkeypatch.setattr(
        indicator_service,
        "current_completed_bar_start",
        lambda *a: now.replace(minute=55, hour=9, second=0),
    )
    monkeypatch.setattr(
        indicator_service,
        "fetch_history_cached",
        lambda *a, **kw: {"status": "success", "data": []},
    )
    with pytest.raises(scalping.WaitingForSignal, match="expired"):
        scalping.latest_signal("ema915", SimpleNamespace(), now)


@pytest.fixture
def saved_scalp(monkeypatch):
    from uuid import uuid4

    from blueprints.strategy_module import validate_strategy_config
    from database import flow_db, trading_risk_db
    from database import strategy_module_db as store
    from services.strategy_module.scalping_pack import definitions, workflow_definition

    owner = "scalp-identity-" + uuid4().hex
    store.init_db()
    flow_db.init_db()
    monkeypatch.setattr(flow_db.db_session(), "expire_on_commit", False)
    config, error = validate_strategy_config(
        definitions()[0] | {"broker_connection_id": str(uuid4())}
    )
    assert error is None
    row, error = store.create_strategy(owner, config)
    assert error is None
    workflow = flow_db.create_workflow(
        **workflow_definition(row, row["id"], owner, row["broker_connection_id"])
    )
    workflow.is_active = True
    flow_db.db_session.commit()
    store.set_automation_state(row["id"], owner, "armed")
    execution = flow_db.create_execution(workflow.id, "running")
    saved = store.strategy_to_dict(store.get_strategy(row["id"], owner))
    store.db_session.remove()
    flow_db.db_session.commit()
    monkeypatch.setattr(trading_risk_db, "policy_enabled", lambda _: True)
    yield owner, saved, workflow, execution.id
    store.set_automation_state(row["id"], owner, "disabled")
    for run in store.list_open_runs():
        if run.strategy_id == row["id"]:
            store.finish_run(run.id, "manual")
    store.set_strategy_status(row["id"], "stopped", None)
    store.delete_strategy(row["id"], owner)
    flow_db.delete_workflow(workflow.id)
    store.db_session.remove()
    flow_db.db_session.remove()


@pytest.mark.parametrize("change", ["deactivate", "graph", "epoch", "mode"])
def test_final_origin_detects_concurrent_change_despite_cached_objects(saved_scalp, change):
    from copy import deepcopy

    from sqlalchemy.orm import Session

    from database import flow_db
    from database import strategy_module_db as store
    from services.research.qualification_context import workflow_digest
    from services.research.qualification_execution import flow_origin

    owner, strategy, cached_flow, execution_id = saved_scalp
    initial_hash = workflow_digest([cached_flow])
    with flow_origin(cached_flow.id, execution_id, initial_hash):
        assert scalping.require_origin(strategy, owner, "sandbox")
        store.db_session.remove()
        flow_db.db_session.commit()
        if change in {"deactivate", "graph"}:
            with Session(flow_db.engine) as db:
                fresh = db.get(flow_db.FlowWorkflow, cached_flow.id)
                if change == "deactivate":
                    fresh.is_active = False
                else:
                    nodes = deepcopy(fresh.nodes)
                    nodes[0]["data"]["intervalValue"] = 2
                    fresh.nodes = nodes
                db.commit()
            assert cached_flow.is_active is True
        else:
            with Session(store.engine) as db:
                fresh = db.get(store.SmStrategy, strategy["id"])
                if change == "epoch":
                    fresh.automation_state_updated_at += timedelta(seconds=1)
                else:
                    fresh.live_enabled = True
                db.commit()
        with pytest.raises(ValueError):
            scalping.require_origin(strategy, owner, "sandbox")


def test_deadline_monitor_persists_exit_without_quote_or_broker_io(saved_scalp, monkeypatch):
    from database import strategy_module_db as store
    from services.flow_openalgo_client import FlowOpenAlgoClient
    from services.strategy_module import engine

    owner, strategy, _, _ = saved_scalp
    context = {"deadline": (datetime.now(IST) - timedelta(seconds=1)).isoformat()}
    run = store.create_run(strategy["id"], "sandbox", "sandbox", scalp_context=context)
    run_id = run.id
    calls = []
    monkeypatch.setattr(FlowOpenAlgoClient, "get_quotes", lambda *a: calls.append("quote"))
    monkeypatch.setattr(engine, "_api_key_for", lambda *a: calls.append("key"))
    scalping.monitor_deadlines()
    store.db_session.remove()
    assert store.get_run(run_id).stop_requested_reason == "scheduler"
    assert calls == []


def test_live_signal_expiry_checked_after_final_quote(monkeypatch):
    import restx_api  # Initialize the existing REST namespace before its order service.
    from services import place_order_service
    from services.strategy_module import live_protection, order_dispatch

    calls = []
    monkeypatch.setattr(order_dispatch, "resolve_live_auth", lambda _: ("token", "kotak", None))
    monkeypatch.setattr(live_protection, "_connection_for_api_key", lambda _: ("pin", "kotak"))
    monkeypatch.setattr(
        order_dispatch,
        "bounded_live_entry_order",
        lambda order, *a: (calls.append("quote") or order, None),
    )
    monkeypatch.setattr(
        place_order_service, "place_order_with_auth", lambda *a, **k: calls.append("order")
    )
    result = order_dispatch._dispatch_live(
        "key",
        {"action": "BUY", "pricetype": "LIMIT", "price": 100},
        intent="entry",
        expected_broker="kotak",
        expected_connection_id="pin",
        scalp_metadata={"signal_at": "2020-01-01T10:00:00+05:30"},
    )
    assert not result.ok and "expired" in result.error
    assert calls == ["quote"]
