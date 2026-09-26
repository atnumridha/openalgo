"""Regression coverage for the installed intraday flow repair."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from services import flow_executor_service as executor_module
from services import flow_scheduler_service as scheduler_module
from services import indicator_service
from services.flow_executor_service import NodeExecutor, WorkflowContext


def test_reconcile_quarantines_only_unreadable_workflow(monkeypatch):
    from database import flow_db
    from services import flow_readiness_service
    from unittest.mock import MagicMock

    flows = [SimpleNamespace(id=i, nodes=[{"type": "strategyModuleRun"},
             {"type": "start", "data": {"scheduleType": "interval", "intervalValue": 5,
                                       "intervalUnit": "minutes"}}]) for i in [1, 2]]
    scheduler = MagicMock()
    scheduler.get_all_jobs.return_value = []
    scheduler.get_workflow_job.return_value = None
    monkeypatch.setattr(scheduler_module, "get_flow_scheduler", lambda: scheduler)
    monkeypatch.setattr(flow_db, "get_active_workflows", lambda: flows)
    monkeypatch.setattr(flow_db, "get_workflow_api_key", lambda _: "test")
    monkeypatch.setattr(flow_db, "set_schedule_job_id", lambda *_: None)
    def validate(flow, **kw):
        if flow.id == 1:
            raise RuntimeError("temporary database failure")
        return []
    monkeypatch.setattr(flow_readiness_service, "strategy_link_issues", validate)
    assert scheduler_module.reconcile_scheduler_jobs()["restored"] == 1
    scheduler.remove_workflow_job.assert_called_once_with(1, strict=True)
    assert scheduler.add_workflow_job.call_args.kwargs["workflow_id"] == 2


def test_rsi_short_history_is_collecting():
    executor = NodeExecutor(SimpleNamespace(api_key="test"), WorkflowContext(), [])
    result = executor.execute_indicator({"indicatorName": "rsi", "params": '{"period":14}',
                                         "sourceSeries": list(range(1, 15))})
    assert result["status"] == "collecting_history"


def test_strict_strategy_read_does_not_turn_database_failure_into_missing(monkeypatch):
    from database import strategy_module_db
    from unittest.mock import MagicMock

    session = MagicMock()
    session.query.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(strategy_module_db, "db_session", session)
    with pytest.raises(RuntimeError, match="database unavailable"):
        strategy_module_db.get_strategy(1, "alice", strict=True)


def test_candle_schedule_waits_for_settlement(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 25, 10, 0, 1, tzinfo=tz)

    monkeypatch.setattr(scheduler_module, "datetime", Clock)
    monkeypatch.setattr(scheduler_module, "INTERVAL_ALIGN_OFFSET_SECONDS", 2)
    monkeypatch.setattr(indicator_service, "FLOW_BAR_SETTLE_SECONDS", 5)
    result = scheduler_module._next_aligned_start(5, "minutes", candle_driven=True)
    assert (result.hour, result.minute, result.second) == (10, 0, 6)


@pytest.mark.parametrize("method,data", [
    ("execute_time_window", {"startTime": "09:15", "endTime": "15:30"}),
    ("execute_time_condition", {"targetTime": "09:15", "operator": ">="}),
])
def test_intraday_time_gates_use_ist_on_a_utc_host(monkeypatch, method, data):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = cls(2026, 9, 25, 4, 30, tzinfo=ZoneInfo("UTC"))
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(executor_module, "datetime", Clock)
    executor = NodeExecutor(SimpleNamespace(api_key="test"), WorkflowContext(), [])
    assert getattr(executor, method)(data)["condition"] is True


@pytest.mark.parametrize("node_type", ["strategyModuleRun", "strategySignal"])
def test_matching_running_batch_is_a_noop_without_claim_or_dispatch(monkeypatch, node_type):
    from database import auth_db, flow_db, strategy_module_db
    from services.strategy_module import engine

    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch",
                               broker_connection_id="connection-1", current_run_id=44)
    run = SimpleNamespace(id=44, strategy_id=3, user_id="alice", status="running",
                          mode="sandbox", broker_connection_id="connection-1")
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: strategy)
    monkeypatch.setattr(strategy_module_db, "get_run", lambda _: run)
    monkeypatch.setattr(engine, "start_run", lambda *_a, **_k: pytest.fail("duplicate start"))
    monkeypatch.setattr(flow_db, "claim_execution_bar", lambda *_: pytest.fail("noop consumed bar"))
    context = WorkflowContext(workflow_id=7)
    context.broker_connection_id = "connection-1"
    executor = NodeExecutor(SimpleNamespace(api_key="test"), context, [])
    data = {"strategyId": 3, "brokerOwner": "alice", "mode": "sandbox", "action": "start",
            "barEvidence": {"5m": ["a", "b"], "15m": ["c", "d"]}}
    method = executor.execute_strategy_module_run if node_type == "strategyModuleRun" else executor.execute_strategy_signal
    result = method(data)
    assert result["status"] == "success"
    assert result["reason_code"] == "already_running"
    assert result["run_id"] == 44


def test_short_indicator_history_is_collecting_not_failed(monkeypatch):
    now = datetime(2026, 9, 25, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    rows = [{"timestamp": "2026-09-25T10:00:00+05:30", "open": 100,
             "high": 101, "low": 99, "close": 100, "volume": 1}]
    monkeypatch.setattr(indicator_service, "fetch_history_cached", lambda *_a, **_k: {"status": "success", "data": rows})
    executor = NodeExecutor(SimpleNamespace(api_key="test"), WorkflowContext(), [])
    result = executor.execute_indicator({"symbol": "HDFCBANK", "exchange": "NSE", "interval": "15m",
                                         "indicatorName": "ema", "params": '{"period":200}'}, now=now)
    assert result["status"] == "collecting_history"
    assert result["reason_code"] == "insufficient_history"


def test_orphan_strategy_link_blocks_activation(monkeypatch):
    from database import strategy_module_db
    from services.flow_lifecycle_service import execution_blocked

    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_, **kw: None)
    workflow = SimpleNamespace(name="orphan", broker_connection_id="c", nodes=[
        {"id": "start", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "exit", "type": "strategySignal", "position": {"x": 0, "y": 100}, "data": {
            "strategyId": 4, "brokerOwner": "alice", "mode": "sandbox", "action": "stop"}},
    ], edges=[{"id": "e", "source": "start", "target": "exit"}])
    result = execution_blocked(workflow)
    assert result is not None
    assert result["reason_code"] == "missing_strategy"


@pytest.fixture
def linked_flow(monkeypatch):
    from database import auth_db, strategy_module_db
    from services import flow_readiness_service as readiness

    strategy = SimpleNamespace(id=3, user_id="alice", strategy_kind="batch", live_enabled=False,
                               broker_connection_id="c", current_run_id=None)
    node = {"id": "run", "type": "strategyModuleRun", "data": {
        "strategyId": 3, "brokerOwner": "alice", "mode": "sandbox"}}
    flow = SimpleNamespace(id=3, name="test", nodes=[node], broker_connection_id="c", is_active=True)
    connection = {"id": "c", "user_id": "alice", "status": "connected", "is_revoked": False}
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda sid, owner, **kw: strategy if (sid, owner) == (3, "alice") else None)
    monkeypatch.setattr(readiness, "connection_summary", lambda _: connection)
    return flow, strategy, connection


@pytest.mark.parametrize("field,value,code", [
    ("brokerOwner", "other", "owner_mismatch"),
    ("strategyId", 4, "missing_strategy"),
    ("mode", "live", "mode_mismatch"),
    ("mode", "inherit", "mode_mismatch"),
])
def test_link_checks_reject_wrong_account_strategy_and_mode(linked_flow, field, value, code):
    from services.flow_readiness_service import strategy_link_issues

    flow, _, _ = linked_flow
    flow.nodes[0]["data"][field] = value
    assert strategy_link_issues(flow, api_key="test")[0]["code"] == code


def test_expired_connection_is_visible_but_not_a_structural_exit_block(linked_flow):
    from services.flow_readiness_service import strategy_link_issues, workflow_readiness

    flow, _, connection = linked_flow
    connection["status"] = "expired"
    assert strategy_link_issues(flow, api_key="test") == []
    result = workflow_readiness(flow, owner="alice")
    assert result["reasons"][0]["code"] == "broker_expired"
    assert result["reasons"][0]["link"] == "/broker"


def test_wrong_connection_or_action_blocks_link(linked_flow):
    from services.flow_readiness_service import strategy_link_issues

    flow, strategy, _ = linked_flow
    strategy.broker_connection_id = "other"
    assert strategy_link_issues(flow)[0]["code"] == "connection_mismatch"
    strategy.broker_connection_id = "c"
    strategy.strategy_kind = "signal"
    assert strategy_link_issues(flow)[0]["code"] == "action_mismatch"


def test_mismatched_existing_run_is_never_a_success(monkeypatch, linked_flow):
    from database import strategy_module_db

    flow, strategy, _ = linked_flow
    strategy.current_run_id = 42
    run = SimpleNamespace(strategy_id=3, mode="live", broker_connection_id="c", stopped_at=None)
    monkeypatch.setattr(strategy_module_db, "get_run", lambda _: run)
    context = WorkflowContext()
    context.broker_connection_id = "c"
    executor = NodeExecutor(SimpleNamespace(api_key="test"), context, [])
    assert executor.existing_batch_run(strategy, "sandbox", {})["status"] == "error"
    run.mode = "sandbox"
    run.strategy_id = 88
    assert executor.existing_batch_run(strategy, "sandbox", {})["status"] == "error"


def test_indicator_configuration_error_is_not_warmup(monkeypatch):
    monkeypatch.setattr(indicator_service, "fetch_history_cached", lambda *_a, **_k: {
        "status": "success", "data": [{"timestamp": "2026-09-25T10:00:00+05:30", "close": 100}]})
    executor = NodeExecutor(SimpleNamespace(api_key="test"), WorkflowContext(), [])
    result = executor.execute_indicator({"symbol": "X", "exchange": "NSE", "interval": "5m", "indicatorName": "unknown"},
                                        now=datetime(2026, 9, 25, 12, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert result["status"] == "error"
    assert "unknown indicator" in result["message"]


def test_warmup_stops_entry_branch_but_runs_independent_exit(monkeypatch):
    from services.flow_executor_service import execute_node_chain

    executor = NodeExecutor(SimpleNamespace(api_key="test"), WorkflowContext(), [])
    observed = []
    monkeypatch.setattr(executor, "execute_indicator", lambda _: executor.collecting_history({}, "Waiting for candles"))
    monkeypatch.setattr(executor, "execute_strategy_signal", lambda data: observed.append(data["action"]) or {"status": "success"})
    nodes = {
        "start": {"id": "start", "type": "start", "data": {}},
        "data": {"id": "data", "type": "indicator", "data": {}},
        "entry": {"id": "entry", "type": "strategySignal", "data": {"action": "start"}},
        "exit": {"id": "exit", "type": "strategySignal", "data": {"action": "stop"}},
    }
    edges = {"start": [{"source": "start", "target": "data"}, {"source": "start", "target": "exit"}],
             "data": [{"source": "data", "target": "entry"}]}
    execute_node_chain("start", list(nodes.values()), edges, {}, executor, executor.context, {})
    assert observed == ["stop"]
    assert executor.readiness_status == "collecting_history"
