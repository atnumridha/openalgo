"""Flow signal dispatch and completed opening-range evidence."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from services import indicator_service
from services.flow_executor_service import NodeExecutor, WorkflowContext, execute_node_chain
from services.flow_workflow_validator import validate_workflow


def _executor():
    context = WorkflowContext(workflow_id=7)
    context.execution_id = 9
    return NodeExecutor(SimpleNamespace(api_key="key"), context, [], "test")


@pytest.mark.parametrize("action", ["start", "stop", "long_entry", "long_exit", "short_entry", "short_exit"])
def test_strategy_signal_requires_explicit_owner_mode_and_action(action):
    data = {"strategyId": 3, "action": action, "mode": "sandbox", "brokerOwner": "alice"}
    if action in {"start", "long_entry", "short_entry"}:
        data.update({"marketHoursExchange": "NSE", "barEvidence": {"5m": ["five", "fivePrev"], "15m": ["fifteen", "fifteenPrev"]}})
    graph = {
        "name": "Signal test",
        "nodes": [
            {"id": "start", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "signal", "type": "strategySignal", "position": {"x": 0, "y": 100}, "data": data},
        ],
        "edges": [{"id": "edge", "source": "start", "target": "signal"}],
    }
    assert validate_workflow(graph, strict=True) == []
    graph["nodes"][1]["data"].pop("brokerOwner")
    assert any(error["path"].endswith("brokerOwner") for error in validate_workflow(graph, strict=True))


def test_strategy_signal_stop_never_starts_and_uses_owned_strategy(monkeypatch):
    from database import auth_db, strategy_module_db
    from services.strategy_module import engine

    executor = _executor()
    executor.context.broker_connection_id = "connection-1"
    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch", broker_connection_id="connection-1", current_run_id=44)
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda sid, owner: strategy if (sid, owner) == (3, "alice") else None)
    monkeypatch.setattr(strategy_module_db, "get_run", lambda run_id: SimpleNamespace(mode="sandbox", broker_connection_id="connection-1") if run_id == 44 else None)
    monkeypatch.setattr(engine, "start_run", lambda *_args, **_kwargs: pytest.fail("stop became start"))
    monkeypatch.setattr(engine, "stop_run", lambda run_id, owner, reason: {"ok": run_id == 44 and owner == "alice"})

    result = executor.execute_strategy_signal({"strategyId": 3, "action": "stop", "mode": "sandbox", "brokerOwner": "alice"})
    assert result["status"] == "success"
    assert result["action"] == "stop"


def test_legacy_run_node_cannot_start_without_explicit_owner_and_connection(monkeypatch):
    from database import auth_db, strategy_module_db
    from services.strategy_module import engine

    executor = _executor()
    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch",
                               broker_connection_id="connection-1", current_run_id=None)
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: strategy)
    monkeypatch.setattr(engine, "start_run", lambda *_args, **_kwargs: pytest.fail("legacy unpinned entry"))

    result = executor.execute_strategy_module_run({"strategyId": 3, "mode": "sandbox"})
    assert result["status"] == "error"
    assert "owner" in result["message"].lower()

    executor.context.broker_connection_id = "connection-2"
    result = executor.execute_strategy_module_run({"strategyId": 3, "mode": "sandbox", "brokerOwner": "alice"})
    assert result["status"] == "error"
    assert "connection" in result["message"].lower()


def test_strategy_signal_rejects_connection_mismatch_before_dispatch(monkeypatch):
    from database import auth_db, strategy_module_db
    from services.strategy_module import engine

    executor = _executor()
    executor.context.broker_connection_id = "connection-1"
    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch", broker_connection_id="connection-2")
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: strategy)
    monkeypatch.setattr(engine, "start_run", lambda *_args, **_kwargs: pytest.fail("wrong broker connection dispatched"))

    result = executor.execute_strategy_signal({"strategyId": 3, "action": "start", "mode": "sandbox", "brokerOwner": "alice"})
    assert result["status"] == "error"
    assert "connection" in result["message"].lower()


def test_strategy_signal_rejects_active_run_on_other_connection(monkeypatch):
    from database import auth_db, strategy_module_db
    from services.strategy_module import engine

    executor = _executor()
    executor.context.broker_connection_id = "connection-1"
    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch",
                               broker_connection_id="connection-1", current_run_id=44)
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: strategy)
    monkeypatch.setattr(strategy_module_db, "get_run", lambda _: SimpleNamespace(mode="sandbox", broker_connection_id="connection-2"))
    monkeypatch.setattr(engine, "stop_run", lambda *_args, **_kwargs: pytest.fail("wrong connection stopped"))

    result = executor.execute_strategy_signal({"strategyId": 3, "action": "stop", "mode": "sandbox", "brokerOwner": "alice"})
    assert result["status"] == "error"
    assert "connection" in result["message"].lower()


def test_strategy_signal_entry_requires_current_bar_evidence(monkeypatch):
    from database import auth_db, strategy_module_db
    from services.strategy_module import engine

    executor = _executor()
    executor.context.broker_connection_id = "connection-1"
    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch", broker_connection_id="connection-1")
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: strategy)
    monkeypatch.setattr(engine, "start_run", lambda *_args, **_kwargs: pytest.fail("entry without current bar"))

    result = executor.execute_strategy_signal({"strategyId": 3, "action": "start", "mode": "sandbox", "brokerOwner": "alice"})
    assert result["status"] == "error"
    assert "candle" in result["message"].lower()


def test_strategy_signal_claims_completed_bar_before_entry(monkeypatch):
    from database import auth_db, flow_db, strategy_module_db
    from services.strategy_module import engine

    executor = _executor()
    executor.context.broker_connection_id = "connection-1"
    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch", broker_connection_id="connection-1")
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: strategy)
    stamp = datetime(2026, 9, 25, 9, 40, tzinfo=ZoneInfo("Asia/Kolkata"))
    monkeypatch.setattr(indicator_service, "validate_current_bar_set", lambda *_: stamp)
    claims = []

    def claim(_execution_id, _workflow_id, _stamp):
        claims.append(_stamp)
        return "claimed" if len(claims) == 1 else "duplicate"

    monkeypatch.setattr(flow_db, "claim_execution_bar", claim)
    starts = []

    def start(*_args, **_kwargs):
        starts.append(True)
        return SimpleNamespace(ok=True, run_id=5)

    monkeypatch.setattr(engine, "start_run", start)
    monkeypatch.setattr(NodeExecutor, "broker_connection_ready", lambda *_args: True)
    node = {"strategyId": 3, "action": "start", "mode": "sandbox", "brokerOwner": "alice",
            "marketHoursExchange": "NSE", "barEvidence": {"5m": ["a", "b"], "15m": ["c", "d"]}}
    first = executor.execute_strategy_signal(node)
    second = executor.execute_strategy_signal(node)
    assert first["status"] == "success"
    assert second["status"] == "error"
    assert len(starts) == 1


def test_strategy_signal_entry_is_risk_blocked_when_pinned_broker_is_expired(monkeypatch):
    from database import auth_db, flow_db, strategy_module_db
    from services.strategy_module import engine

    executor = _executor()
    executor.context.broker_connection_id = "connection-1"
    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch",
                               broker_connection_id="connection-1", current_run_id=None)
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: strategy)
    monkeypatch.setattr(NodeExecutor, "broker_connection_ready", lambda *_args: False, raising=False)
    monkeypatch.setattr(indicator_service, "validate_current_bar_set", lambda *_: datetime(2026, 9, 25, 9, 40, tzinfo=ZoneInfo("Asia/Kolkata")))
    monkeypatch.setattr(flow_db, "claim_execution_bar", lambda *_: pytest.fail("expired broker claimed an entry bar"))
    monkeypatch.setattr(engine, "start_run", lambda *_args, **_kwargs: pytest.fail("expired broker started a run"))

    result = executor.execute_strategy_signal({
        "strategyId": 3, "action": "start", "mode": "sandbox", "brokerOwner": "alice",
        "marketHoursExchange": "NSE", "barEvidence": {"5m": ["a", "b"], "15m": ["c", "d"]},
    })

    assert result["status"] == "risk_blocked"


def test_opening_range_requires_complete_closed_one_minute_candles(monkeypatch):
    from database import market_calendar_db

    ist = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 9, 25, 9, 15, tzinfo=ist)
    end = datetime(2026, 9, 25, 15, 30, tzinfo=ist)
    monkeypatch.setattr(market_calendar_db, "get_effective_session_window", lambda *_: {"start_ms": int(start.timestamp() * 1000), "end_ms": int(end.timestamp() * 1000)})
    rows = [
        {"timestamp": datetime(2026, 9, 25, 9, minute, tzinfo=ist).isoformat(), "open": 100, "high": 101 + minute, "low": 95, "close": 100, "volume": 2}
        for minute in (15, 16, 17)
    ]
    monkeypatch.setattr(indicator_service, "fetch_history_cached", lambda *_args, **_kwargs: {"status": "success", "data": rows})
    executor = _executor()
    node = {"symbol": "SENSEX", "exchange": "BSE_INDEX", "rangeMinutes": 3, "outputVariable": "opening"}
    result = executor.execute_opening_range(node, now=datetime(2026, 9, 25, 9, 18, 6, tzinfo=ist))
    assert result["status"] == "success"
    assert result["high"] == 118
    assert result["low"] == 95
    assert executor.context.get_variable("opening")["high"] == 118

    rows.pop(1)
    incomplete = executor.execute_opening_range(node, now=datetime(2026, 9, 25, 9, 18, 6, tzinfo=ist))
    assert incomplete["status"] == "collecting_history"


def test_indicator_uses_only_completed_candles(monkeypatch):
    ist = ZoneInfo("Asia/Kolkata")
    rows = [
        {"timestamp": datetime(2026, 9, 25, 9, minute, tzinfo=ist).isoformat(),
         "open": 100, "high": 101, "low": 99, "close": close}
        for minute, close in ((15, 100), (16, 101), (17, 999))
    ]
    monkeypatch.setattr(indicator_service, "fetch_history_cached", lambda *_args, **_kwargs: {"status": "success", "data": rows})
    seen = []

    def compute(records, *_args, **_kwargs):
        seen.extend(records)
        return {"status": "success", "latest": {"value": records[-1]["close"]}}

    monkeypatch.setattr(indicator_service, "compute_indicator", compute)
    executor = _executor()
    result = executor.execute_indicator(
        {"symbol": "RELIANCE", "exchange": "NSE", "interval": "1m", "indicatorName": "sma"},
        now=datetime(2026, 9, 25, 9, 17, 30, tzinfo=ist),
    )
    assert result["latest"]["value"] == 101
    assert [bar["close"] for bar in seen] == [100, 101]


def test_existing_flow_table_gains_connection_pin_idempotently(monkeypatch):
    from pathlib import Path

    from sqlalchemy import create_engine, inspect, text

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "upgrade"))
    from upgrade.migrate_flow import add_broker_connection_column

    db = create_engine("sqlite://")
    try:
        with db.begin() as conn:
            conn.execute(text("CREATE TABLE flow_workflows (id INTEGER PRIMARY KEY, name TEXT)"))
            conn.execute(text("INSERT INTO flow_workflows (id, name) VALUES (1, 'Existing')"))
        assert add_broker_connection_column(db)
        assert add_broker_connection_column(db)
        assert "broker_connection_id" in {column["name"] for column in inspect(db).get_columns("flow_workflows")}
        with db.connect() as conn:
            assert conn.execute(text("SELECT name, broker_connection_id FROM flow_workflows WHERE id = 1")).one() == ("Existing", None)
    finally:
        db.dispose()


@pytest.mark.parametrize(
    "status,label",
    [
        ("collecting_history", "Collecting history"),
        ("data_unavailable", "Data unavailable"),
        ("risk_blocked", "Risk blocked"),
    ],
)
def test_history_readiness_stops_entry_without_execution_error(status, label):
    client = SimpleNamespace(
        api_key="key",
        get_history=lambda **_kwargs: {"status": status, "readiness": label, "data": [], "message": label},
    )
    context = WorkflowContext(workflow_id=7)
    executor = NodeExecutor(client, context, [], "readiness")
    executor.execute_place_order = lambda _data: pytest.fail("history readiness reached order")
    nodes = [
        {"id": "start", "type": "start", "data": {}},
        {"id": "history", "type": "history", "data": {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m", "outputVariable": "history"}},
        {"id": "order", "type": "placeOrder", "data": {}},
    ]
    edge_map = {"start": [{"target": "history"}], "history": [{"target": "order"}]}

    execute_node_chain("start", nodes, edge_map, {}, executor, context, {})

    assert executor.errors == []
    assert executor.readiness_status == status
    assert context.get_variable("history")["readiness"] == label


@pytest.mark.parametrize("node_type", ["execute_bar_offset", "execute_prior_period_ohlc", "execute_indicator"])
def test_calculated_history_nodes_preserve_collecting_state(monkeypatch, node_type):
    monkeypatch.setattr(indicator_service, "fetch_history_cached", lambda *_args, **_kwargs: {
        "status": "collecting_history", "readiness": "Collecting history", "data": [], "message": "Warming up"
    })
    executor = _executor()
    result = getattr(executor, node_type)({
        "symbol": "RELIANCE", "exchange": "NSE", "interval": "5m",
        "indicatorName": "sma", "period": "previous_day",
    })
    assert result["status"] == "collecting_history"
    assert result["readiness"] == "Collecting history"
