"""Current exchange-session candles gate starter Flow strategy entries."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from services import indicator_service
from services.flow_executor_service import NodeExecutor, WorkflowContext

IST = ZoneInfo("Asia/Kolkata")


def _session(monkeypatch, day, exchange, start_hour, start_minute, end_hour, end_minute):
    from database import market_calendar_db

    start = datetime(day.year, day.month, day.day, start_hour, start_minute, tzinfo=IST)
    end = datetime(day.year, day.month, day.day, end_hour, end_minute, tzinfo=IST)
    window = {"start_ms": int(start.timestamp() * 1000), "end_ms": int(end.timestamp() * 1000)}
    monkeypatch.setattr(
        market_calendar_db,
        "get_effective_session_window",
        lambda query_day, venue: window if query_day == day and venue == exchange else None,
    )
    return start


def _bar(at, close=101.0):
    return {
        "status": "success",
        "timestamp": at.isoformat(),
        "symbol": "SENSEX",
        "exchange": "BSE_INDEX",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": close,
    }


def test_latest_completed_five_and_fifteen_minute_slots_align_to_session(monkeypatch):
    now = datetime(2026, 9, 25, 9, 37, tzinfo=IST)
    start = _session(monkeypatch, now.date(), "BSE", 9, 15, 15, 30)

    assert indicator_service.current_completed_bar_start("5m", "BSE_INDEX", now) == start + timedelta(minutes=15)
    assert indicator_service.current_completed_bar_start("15m", "BSE_INDEX", now) == start


@pytest.mark.parametrize("interval,close_minute", [("5m", 20), ("15m", 30)])
def test_current_bar_is_not_admissible_until_after_post_close_settle(monkeypatch, interval, close_minute):
    day = datetime(2026, 9, 25, tzinfo=IST).date()
    start = _session(monkeypatch, day, "BSE", 9, 15, 15, 30)

    assert indicator_service.current_completed_bar_start(
        interval, "BSE_INDEX", datetime(2026, 9, 25, 9, close_minute, 1, tzinfo=IST)
    ) is None
    assert indicator_service.current_completed_bar_start(
        interval, "BSE_INDEX", datetime(2026, 9, 25, 9, close_minute, 6, tzinfo=IST)
    ) == start


@pytest.mark.parametrize("interval,close_minute", [("5m", 20), ("15m", 30)])
def test_history_cache_refetches_a_bar_after_its_settle_boundary(monkeypatch, interval, close_minute):
    day = datetime(2026, 9, 25, tzinfo=IST).date()
    start = _session(monkeypatch, day, "BSE", 9, 15, 15, 30)

    class HistoryClient:
        api_key = "cache-boundary-test"

        def __init__(self):
            self.calls = 0

        def get_history(self, **_kwargs):
            self.calls += 1
            return {"data": [_bar(start, close=float(self.calls))]}

    client = HistoryClient()
    indicator_service.clear_history_cache()
    try:
        before = datetime(2026, 9, 25, 9, close_minute - 1, 59, tzinfo=IST)
        grace = datetime(2026, 9, 25, 9, close_minute, 1, tzinfo=IST)
        settled = datetime(2026, 9, 25, 9, close_minute, 6, tzinfo=IST)
        args = (client, "SENSEX", "BSE_INDEX", interval, "2026-09-25", "2026-09-25")

        indicator_service.fetch_history_cached(*args, now=before)
        indicator_service.fetch_history_cached(*args, now=grace)
        calls_before_settle = client.calls
        final = indicator_service.fetch_history_cached(*args, now=settled)

        assert client.calls == calls_before_settle + 1
        assert final["data"][0]["close"] == float(client.calls)
    finally:
        indicator_service.clear_history_cache()


def test_history_read_during_grace_cannot_authorize_a_later_run(monkeypatch):
    day = datetime(2026, 9, 25, tzinfo=IST).date()
    _session(monkeypatch, day, "BSE", 9, 15, 15, 30)
    before_settle = datetime(2026, 9, 25, 9, 45, 1)
    after_settle = datetime(2026, 9, 25, 9, 45, 6, tzinfo=IST)
    five_rows = [_bar(datetime(2026, 9, 25, 9, minute)) for minute in (30, 35, 40, 45)]
    fifteen_rows = [_bar(datetime(2026, 9, 25, 9, minute)) for minute in (0, 15, 30, 45)]

    # Simulate the four barOffset nodes finishing during the grace interval,
    # then the run node inspecting their retained context after grace.
    bars = {
        "5m": tuple(
            indicator_service.bar_at_offset(five_rows, offset, "5m", before_settle)
            for offset in (0, 1)
        ),
        "15m": tuple(
            indicator_service.bar_at_offset(fifteen_rows, offset, "15m", before_settle)
            for offset in (0, 1)
        ),
    }

    assert bars["5m"][0]["timestamp"] == "2026-09-25T09:35:00"
    assert bars["15m"][0]["timestamp"] == "2026-09-25T09:15:00"
    assert indicator_service.validate_current_bar_set(bars, "BSE_INDEX", after_settle) is None
    assert indicator_service.bar_at_offset(five_rows, 0, "5m", after_settle.replace(tzinfo=None))["timestamp"] == "2026-09-25T09:40:00"
    assert indicator_service.bar_at_offset(fifteen_rows, 0, "15m", after_settle.replace(tzinfo=None))["timestamp"] == "2026-09-25T09:30:00"


def test_indicator_keeps_200_completed_bars_when_response_includes_forming_bar(monkeypatch):
    now = datetime(2026, 9, 25, 13, 25, tzinfo=IST)
    rows = [
        {"timestamp": (now - timedelta(minutes=15 * (201 - index))).isoformat(),
         "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
        for index in range(200)
    ]
    rows.append({**rows[-1], "timestamp": (now - timedelta(minutes=5)).isoformat()})
    observed = {}
    monkeypatch.setattr(indicator_service, "fetch_history_cached", lambda *_args, **_kwargs: {"status": "success", "data": rows})
    monkeypatch.setattr(
        indicator_service,
        "compute_indicator",
        lambda records, *_args, **_kwargs: observed.update(count=len(records)) or {"latest": {"value": 100}},
    )
    executor = NodeExecutor(SimpleNamespace(api_key="key"), WorkflowContext(workflow_id=5), [], "HDFCBANK")

    result = executor.execute_indicator(
        {"symbol": "HDFCBANK", "exchange": "NSE", "interval": "15m", "indicatorName": "ema",
         "params": '{"period": 200}', "lookbackBars": 200},
        now=now,
    )

    assert result["latest"]["value"] == 100
    assert observed["count"] == 200


def test_evening_mcx_special_window_is_the_bar_anchor(monkeypatch):
    now = datetime(2026, 9, 25, 19, 2, tzinfo=IST)
    start = _session(monkeypatch, now.date(), "MCX", 18, 15, 23, 30)

    assert indicator_service.current_completed_bar_start("5m", "MCX", now) == start + timedelta(minutes=40)
    assert indicator_service.current_completed_bar_start("15m", "MCX", now) == start + timedelta(minutes=30)


def test_prior_session_latest_closed_bar_is_not_current_evidence(monkeypatch):
    now = datetime(2026, 9, 25, 9, 37, tzinfo=IST)
    start = _session(monkeypatch, now.date(), "BSE", 9, 15, 15, 30)
    prior = start - timedelta(days=1)
    bars = {
        "5m": (_bar(prior + timedelta(minutes=15)), _bar(prior + timedelta(minutes=10))),
        "15m": (_bar(prior), _bar(prior - timedelta(minutes=15))),
    }

    assert indicator_service.validate_current_bar_set(bars, "BSE_INDEX", now) is None


def test_sparse_previous_bar_does_not_complete_signal_evidence(monkeypatch):
    now = datetime(2026, 9, 25, 9, 37, tzinfo=IST)
    start = _session(monkeypatch, now.date(), "BSE", 9, 15, 15, 30)
    bars = {
        "5m": (_bar(start + timedelta(minutes=15)), _bar(start + timedelta(minutes=5))),
        "15m": (_bar(start), _bar(start - timedelta(days=1))),
    }

    assert indicator_service.validate_current_bar_set(bars, "BSE_INDEX", now) is None


def test_complete_current_five_and_fifteen_minute_evidence_is_accepted(monkeypatch):
    now = datetime(2026, 9, 25, 9, 47, tzinfo=IST)
    start = _session(monkeypatch, now.date(), "BSE", 9, 15, 15, 30)
    bars = {
        "5m": (_bar(start + timedelta(minutes=25)), _bar(start + timedelta(minutes=20))),
        "15m": (_bar(start + timedelta(minutes=15)), _bar(start)),
    }

    assert indicator_service.current_completed_bar_start("5m", "BSE_INDEX", now) == start + timedelta(minutes=25)
    assert indicator_service.current_completed_bar_start("15m", "BSE_INDEX", now) == start + timedelta(minutes=15)
    assert indicator_service.validate_current_bar_set(bars, "BSE_INDEX", now) == start + timedelta(minutes=25)


def test_older_fifteen_minute_confirmation_is_not_aligned(monkeypatch):
    now = datetime(2026, 9, 25, 9, 47, tzinfo=IST)
    start = _session(monkeypatch, now.date(), "BSE", 9, 15, 15, 30)
    bars = {
        "5m": (_bar(start + timedelta(minutes=25)), _bar(start + timedelta(minutes=20))),
        "15m": (_bar(start), _bar(start - timedelta(minutes=15))),
    }

    assert indicator_service.validate_current_bar_set(bars, "BSE_INDEX", now) is None


def test_a_bar_without_instrument_identity_is_not_coherent_evidence(monkeypatch):
    now = datetime(2026, 9, 25, 9, 47, tzinfo=IST)
    start = _session(monkeypatch, now.date(), "BSE", 9, 15, 15, 30)
    missing_identity = _bar(start + timedelta(minutes=25))
    missing_identity.pop("symbol")
    bars = {
        "5m": (missing_identity, _bar(start + timedelta(minutes=20))),
        "15m": (_bar(start + timedelta(minutes=15)), _bar(start)),
    }

    assert indicator_service.validate_current_bar_set(bars, "BSE_INDEX", now) is None


@pytest.mark.parametrize(
    "corruption",
    [
        {"status": "error"},
        {"open": None},
        {"close": float("nan")},
        {"low": 103.0},
        {"volume": -1},
    ],
)
def test_error_or_invalid_ohlc_cannot_be_current_entry_evidence(monkeypatch, corruption):
    now = datetime(2026, 9, 25, 9, 47, tzinfo=IST)
    start = _session(monkeypatch, now.date(), "BSE", 9, 15, 15, 30)
    corrupt = _bar(start + timedelta(minutes=25))
    corrupt.update(corruption)
    bars = {
        "5m": (corrupt, _bar(start + timedelta(minutes=20))),
        "15m": (_bar(start + timedelta(minutes=15)), _bar(start)),
    }

    assert indicator_service.validate_current_bar_set(bars, "BSE_INDEX", now) is None


def test_starter_run_refuses_old_bar_before_strategy_engine(monkeypatch):
    from database import auth_db, strategy_module_db
    from services.strategy_module import engine

    now = datetime.now(IST)
    start = _session(monkeypatch, now.date(), "BSE", 9, 15, 15, 30)
    monkeypatch.setattr(
        engine,
        "start_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _key: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: SimpleNamespace(
        broker_connection_id="connection-1", strategy_kind="batch", current_run_id=None
    ))
    context = WorkflowContext(workflow_id=11)
    context.broker_connection_id = "connection-1"
    for name, when in {
        "bar5Current": start - timedelta(days=1),
        "bar5Previous": start - timedelta(days=1, minutes=5),
        "bar15Current": start - timedelta(days=1),
        "bar15Previous": start - timedelta(days=1, minutes=15),
    }.items():
        context.set_variable(name, _bar(when))
    executor = NodeExecutor(SimpleNamespace(api_key="key"), context, [], "starter")

    result = executor.execute_strategy_module_run(
        {
            "strategyId": 101,
            "mode": "sandbox",
            "brokerOwner": "alice",
            "barEvidence": {"5m": ["bar5Current", "bar5Previous"], "15m": ["bar15Current", "bar15Previous"]},
            "marketHoursExchange": "BSE_INDEX",
        }
    )

    assert result["status"] == "error"
    assert "current" in result["message"].lower()


def test_installed_starter_without_bar_guard_fails_closed_until_repaired(monkeypatch):
    from database import auth_db
    from services.strategy_module import engine

    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _key: "alice")
    monkeypatch.setattr(
        engine,
        "start_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    executor = NodeExecutor(
        SimpleNamespace(api_key="key"),
        WorkflowContext(workflow_id=11),
        [],
        "SENSEX 5/15-Minute Trend Signal Receiver Workflow",
    )

    result = executor.execute_strategy_module_run({"strategyId": 101, "mode": "sandbox"})

    assert result["status"] == "error"
    assert "current candle" in result["message"].lower()


def test_renamed_bar_signal_cannot_remove_current_candle_guard(monkeypatch):
    from database import auth_db
    from services.strategy_module import engine

    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _key: "alice")
    monkeypatch.setattr(
        engine,
        "start_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    context = WorkflowContext(workflow_id=11)
    context.requires_bar_evidence = True
    executor = NodeExecutor(SimpleNamespace(api_key="key"), context, [], "Renamed signal")

    result = executor.execute_strategy_module_run({"strategyId": 101, "mode": "sandbox"})

    assert result["status"] == "error"
    assert "current candle" in result["message"].lower()


def test_graph_detection_survives_renaming_and_ignores_historical_lookback():
    from services.flow_executor_service import workflow_requires_bar_evidence

    current = {"id": "anything", "type": "barOffset", "data": {"interval": "5m", "offsetBars": 0}}
    older = {"id": "anything", "type": "barOffset", "data": {"interval": "5m", "offsetBars": 1}}

    assert workflow_requires_bar_evidence([current]) is True
    assert workflow_requires_bar_evidence([older]) is False


def test_starter_run_claims_bar_before_start_and_refuses_repeat(monkeypatch):
    from database import auth_db, flow_db, strategy_module_db
    from services.strategy_module import engine

    bar = datetime(2026, 9, 25, 9, 40, tzinfo=IST)
    calls = []
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _key: "alice")
    monkeypatch.setattr(strategy_module_db, "get_strategy", lambda *_: SimpleNamespace(
        broker_connection_id="connection-1", strategy_kind="batch", current_run_id=None
    ))
    monkeypatch.setattr(indicator_service, "validate_current_bar_set", lambda _bars, _exchange: bar)
    monkeypatch.setattr(NodeExecutor, "broker_connection_ready", lambda *_args: True)

    def claim(execution_id, workflow_id, bar_start):
        calls.append(("claim", execution_id, workflow_id, bar_start))
        return "claimed" if len(calls) == 1 else "duplicate"

    monkeypatch.setattr(flow_db, "claim_execution_bar", claim)

    def start_run(*_args, **_kwargs):
        calls.append(("start",))
        return SimpleNamespace(ok=True, run_id=77, error=None, legs=[])

    monkeypatch.setattr(engine, "start_run", start_run)
    context = WorkflowContext(workflow_id=11)
    context.broker_connection_id = "connection-1"
    context.execution_id = 88
    for name in ("bar5Current", "bar5Previous", "bar15Current", "bar15Previous"):
        context.set_variable(name, _bar(bar))
    executor = NodeExecutor(SimpleNamespace(api_key="key"), context, [], "starter")
    node = {
        "strategyId": 101,
        "mode": "sandbox",
        "brokerOwner": "alice",
        "barEvidence": {"5m": ["bar5Current", "bar5Previous"], "15m": ["bar15Current", "bar15Previous"]},
        "marketHoursExchange": "BSE_INDEX",
    }

    first = executor.execute_strategy_module_run(node)
    second = executor.execute_strategy_module_run(node)

    assert first["status"] == "success"
    assert second["status"] == "error"
    assert calls == [("claim", 88, 11, bar), ("start",), ("claim", 88, 11, bar)]
    assert any(log.get("bar_claim") == bar.isoformat() for log in executor.logs)
