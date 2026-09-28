"""Owner-scoped monitoring; every control test uses isolated databases/fakes."""

from contextlib import nullcontext
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import Flask
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from blueprints import strategy_module as blueprint
from database import flow_db
from database import strategy_module_db as store
from limiter import limiter

NOW = datetime(2026, 9, 28, 4, 30, tzinfo=UTC)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'monitor.db'}")
    for module in (store, flow_db):
        session = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))
        monkeypatch.setattr(module, "engine", engine)
        monkeypatch.setattr(module, "db_session", session)
        monkeypatch.setattr(
            module.FlowWorkflow if module is flow_db else module.SmStrategy,
            "query",
            session.query_property(),
        )
        module.Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "database.market_calendar_db.get_effective_session_window",
        lambda *a: {"start_ms": 1, "end_ms": 2},
    )
    monkeypatch.setattr(
        "services.strategy_module.monitor.risk_evidence", lambda *a: {"available": False}
    )
    yield engine
    store.db_session.remove()
    flow_db.db_session.remove()
    engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="monitor-fixture")
    app.register_blueprint(blueprint.strategy_module_bp)
    app.add_url_rule("/auth/login", endpoint="auth.login", view_func=lambda: "login")
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(user="alice", logged_in=True, login_time=datetime.now(UTC).isoformat())
    return client


def seed(owner="alice", **changes):
    row, error = store.create_strategy(
        owner,
        {
            "name": f"{owner} test {uuid4().hex[:6]}",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "universe_tab": "weekly_monthly",
            "scalp_profile": "sma_macd",
            "entry_time": time(9, 35),
            "exit_time": time(15, 20),
            "legs": [{"id": 1, "segment": "options", "position": "B", "lots": 1, "sl_pts": 3}],
        },
    )
    assert error is None
    sid = row["id"]
    strategy = store.get_strategy(sid, owner)
    strategy.automation_state = "armed"
    for key, value in changes.items():
        setattr(strategy, key, value)
    store.db_session.commit()
    workflow = flow_db.FlowWorkflow(
        name=f"{owner} flow",
        is_active=True,
        nodes=[
            {
                "id": "start",
                "type": "start",
                "data": {"scheduleType": "interval", "intervalValue": 1, "intervalUnit": "minutes"},
            },
            {
                "id": "run",
                "type": "strategyModuleRun",
                "data": {"strategyId": sid, "brokerOwner": owner, "mode": "sandbox"},
            },
        ],
        edges=[],
        schedule_job_id=f"flow_workflow_{sid}",
    )
    flow_db.db_session.add(workflow)
    flow_db.db_session.commit()
    return sid, workflow.id


def execution(wid, *, at=NOW, error=None, status="success", logs=None):
    row = flow_db.FlowWorkflowExecution(
        workflow_id=wid, status=status, started_at=at, completed_at=at, error=error, logs=logs or []
    )
    flow_db.db_session.add(row)
    flow_db.db_session.commit()
    return row.id


def scheduler(monkeypatch, *, running=True, paused=False, next_at=NOW + timedelta(seconds=30)):
    from services.flow_scheduler_service import get_flow_scheduler

    fake = SimpleNamespace(
        scheduler=SimpleNamespace(running=running, state=2 if paused else 1),
        get_workflow_job=lambda _: SimpleNamespace(next_run_time=next_at) if next_at else None,
    )
    monkeypatch.setattr("services.flow_scheduler_service.get_flow_scheduler", lambda: fake)


def test_monitor_endpoint_exists_and_requires_session(client):
    response = client.get("/strategy/api/automation/monitor")
    assert response.status_code == 200
    assert response.json["data"]["strategies"] == []
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/strategy/api/automation/monitor").status_code in (302, 401)


def test_monitor_is_owner_scoped_with_actual_check_and_schedule_evidence(db, monkeypatch):
    from services.strategy_module import monitor

    sid, wid = seed()
    seed("bob")
    execution(wid, at=NOW - timedelta(seconds=20))
    scheduler(monkeypatch)
    data = monitor.overview("alice", now=NOW)
    assert [r["id"] for r in data["strategies"]] == [sid]
    row = data["strategies"][0]
    assert row["monitor_status"] == "watching"
    assert row["run_status"] == "stopped" and row["automation_state"] == "armed"
    assert row["last_check_at"].endswith("+00:00")
    assert row["check_age_seconds"] == 20
    assert row["next_check_at"] is not None
    assert row["open_run_count"] == 0


def test_live_setup_blockers_remain_visible_after_hours(db, monkeypatch):
    from services.strategy_module import monitor

    sid, wid = seed(live_enabled=True)
    flow = flow_db.db_session.get(flow_db.FlowWorkflow, wid)
    flow.nodes = [flow.nodes[0], {**flow.nodes[1], "data": {**flow.nodes[1]["data"], "mode": "live"}}]
    flow_db.db_session.commit()
    execution(wid)
    scheduler(monkeypatch)
    monkeypatch.setattr("services.strategy_module.live_readiness.inspect_setup", lambda *a, **kw: {
        "blocked": True, "blocker_count": 2, "checks": [
            {"code": "session_approval", "status": "blocked", "message": "Approval absent"},
            {"code": "research_release", "status": "blocked", "message": "Research release absent"},
        ]})
    row = monitor.overview("alice", now=NOW + timedelta(hours=6))["strategies"][0]
    assert row["monitor_status"] == "live_blocked"
    assert row["activity_status"] == "outside_session"
    assert row["live_readiness"]["blocker_count"] == 2
    assert row["live_readiness"]["checks"][0]["code"] == "session_approval"
    with Session(store.engine) as session:
        assert session.scalar(select(store.SmStrategyRun).where(store.SmStrategyRun.strategy_id == sid)) is None


def test_live_open_run_remains_visible_with_new_entry_blockers(db, monkeypatch):
    from services.strategy_module import monitor

    sid, wid = seed(live_enabled=True)
    flow = flow_db.db_session.get(flow_db.FlowWorkflow, wid)
    flow.nodes = [flow.nodes[0], {**flow.nodes[1], "data": {**flow.nodes[1]["data"], "mode": "live"}}]
    flow_db.db_session.commit()
    with Session(store.engine) as session:
        session.add(store.SmStrategyRun(strategy_id=sid, mode="live"))
        session.commit()
    scheduler(monkeypatch)
    monkeypatch.setattr("services.strategy_module.live_readiness.inspect_setup", lambda *a, **kw: {
        "blocked": True, "blocker_count": 1, "checks": []})
    row = monitor.overview("alice", now=NOW + timedelta(hours=6))["strategies"][0]
    assert row["monitor_status"] == "in_trade"
    assert row["activity_status"] == "outside_session"
    assert row["live_readiness"]["blocked"]
    assert row["open_run_count"] == 1


@pytest.mark.parametrize(
    "condition,expected",
    [("missing", "schedule_missing"), ("paused", "scheduler_unavailable"), ("stale", "stale")],
)
def test_no_green_status_when_checks_are_unavailable(db, monkeypatch, condition, expected):
    from services.strategy_module import monitor

    _, wid = seed()
    execution(wid, at=NOW - timedelta(minutes=5) if condition == "stale" else NOW)
    scheduler(
        monkeypatch,
        paused=condition == "paused",
        next_at=None if condition == "missing" else NOW + timedelta(seconds=30),
    )
    assert monitor.overview("alice", now=NOW)["strategies"][0]["monitor_status"] == expected


def test_early_entry_window_is_waiting_without_rewriting_raw_audit(db, monkeypatch):
    from services.strategy_module import monitor

    _, wid = seed()
    early = NOW.replace(hour=3, minute=49)
    error = "strategyModuleRun: This intraday strategy can start only between 09:35 and 15:20 IST"
    execution(wid, at=early, error=error, status="failed")
    scheduler(monkeypatch, next_at=early + timedelta(minutes=1))
    row = monitor.overview("alice", now=early)["strategies"][0]
    assert row["monitor_status"] == "waiting_window"
    assert "09:35" in row["reason"]
    assert row["last_check_status"] == "failed"
    assert (
        flow_db.db_session.get(flow_db.FlowWorkflowExecution, row["latest_execution_id"]).status
        == "failed"
    )


def test_error_is_not_hidden_by_armed_or_missing_position(db, monkeypatch):
    from services.strategy_module import monitor

    _, wid = seed()
    execution(wid, error="Broker authentication expired", status="failed")
    scheduler(monkeypatch)
    row = monitor.overview("alice", now=NOW)["strategies"][0]
    assert row["monitor_status"] == "error"
    assert "authentication expired" in row["reason"]


def test_log_pages_preserve_all_records_and_redact_nested_secrets(client):
    sid, wid = seed()
    for i in range(3):
        execution(
            wid,
            logs=[
                {"message": f"event {i} token=hidden", "data": {"apikey": "credential", "safe": i}}
            ],
        )
    response = client.get(
        f"/strategy/api/automation/strategies/{sid}/logs?stream=executions&limit=2"
    )
    assert response.status_code == 200
    page = response.json["data"]
    assert len(page["items"]) == 2 and page["next_cursor"]
    assert "credential" not in response.get_data(as_text=True)
    assert "hidden" not in response.get_data(as_text=True)
    older = client.get(
        f"/strategy/api/automation/strategies/{sid}/logs?stream=executions&limit=2&before_id={page['next_cursor']}"
    ).json["data"]
    assert len(older["items"]) == 1 and older["next_cursor"] is None
    assert not {r["id"] for r in page["items"]} & {r["id"] for r in older["items"]}


@pytest.mark.parametrize(
    "query", ["stream=secrets", "limit=0", "limit=1001", "before_id=no", "before_id=-1"]
)
def test_invalid_log_query_is_rejected(client, query):
    sid, _ = seed()
    assert client.get(f"/strategy/api/automation/strategies/{sid}/logs?{query}").status_code == 400


def test_foreign_logs_are_not_exposed(client):
    sid, _ = seed("bob")
    assert client.get(f"/strategy/api/automation/strategies/{sid}/logs").status_code == 404


def test_emergency_stop_blocks_all_before_any_close_and_reports_partial_results(db, monkeypatch):
    from services.strategy_module import automation_control as control
    from services.strategy_module import monitor

    ids = [seed()[0], seed()[0]]
    foreign, _ = seed("bob")
    monkeypatch.setattr(control, "_control_lease", lambda *a, **k: nullcontext())
    seen = []

    def close(sid, owner):
        with store.engine.connect() as connection:
            states = list(
                connection.execute(
                    select(store.SmStrategy.automation_state).where(store.SmStrategy.id.in_(ids))
                ).scalars()
            )
        assert states == ["closing", "closing"]
        seen.append(sid)
        if sid == ids[0]:
            return control.ControlResult(True, "closing", close_pending=True)
        raise RuntimeError("private token=hide-me")

    monkeypatch.setattr(control, "disable_and_close", close)
    result = monitor.emergency_stop("alice")
    assert seen == ids
    assert [r["state"] for r in result["items"]] == ["closing", "close_failed"]
    assert not result["all_stopped"]
    assert "hide-me" not in str(result)
    assert store.get_strategy(foreign, "bob").automation_state == "armed"


def test_emergency_stop_requires_confirmation_without_mutation(client, monkeypatch):
    from services.strategy_module import monitor

    calls = []
    monkeypatch.setattr(
        monitor,
        "emergency_stop",
        lambda owner: calls.append(owner) or {"items": [], "all_stopped": True},
    )
    assert client.post("/strategy/api/automation/emergency-stop", json={}).status_code == 400
    assert calls == []
    assert (
        client.post(
            "/strategy/api/automation/emergency-stop", json={"confirmation": "STOP ALL"}
        ).status_code
        == 200
    )
    assert calls == ["alice"]


def test_unavailable_source_returns_503_not_empty_healthy_dashboard(client, monkeypatch):
    monkeypatch.setattr(
        "services.strategy_module.monitor.overview",
        lambda *a: (_ for _ in ()).throw(RuntimeError("database offline")),
    )
    response = client.get("/strategy/api/automation/monitor")
    assert response.status_code == 503


def test_disabled_unlinked_draft_is_untouched_by_emergency_stop(db, monkeypatch):
    from services.strategy_module import automation_control as control
    from services.strategy_module import monitor

    sid, wid = seed(automation_state="disabled")
    flow_db.db_session.delete(flow_db.db_session.get(flow_db.FlowWorkflow, wid))
    flow_db.db_session.commit()
    monkeypatch.setattr(control, "_control_lease", lambda *a, **k: nullcontext())
    monkeypatch.setattr(
        control, "disable_and_close", lambda *a: pytest.fail("Draft must not be closed")
    )
    result = monitor.emergency_stop("alice")
    assert result == {"items": [], "all_stopped": True}
    assert store.get_strategy(sid, "alice").automation_state == "disabled"


def test_unsupported_batch_automation_is_reported_without_false_stop(db, monkeypatch):
    from services.strategy_module import automation_control as control
    from services.strategy_module import monitor

    sid, _ = seed(scalp_profile=None)
    monkeypatch.setattr(control, "_control_lease", lambda *a, **k: nullcontext())
    monkeypatch.setattr(control, "disable_and_close", lambda *a: pytest.fail("Unsupported control"))
    result = monitor.emergency_stop("alice")
    assert not result["all_stopped"] and not result["items"][0]["ok"]
    assert "Legacy batch" in result["items"][0]["reason"]
    assert store.get_strategy(sid, "alice").automation_state == "armed"


def test_never_run_noninterval_schedule_never_claims_checks_arriving(db, monkeypatch):
    from services.strategy_module import monitor

    _, wid = seed()
    flow = flow_db.db_session.get(flow_db.FlowWorkflow, wid)
    flow.nodes = [
        dict(n, data={"scheduleType": "daily"}) if n["type"] == "start" else n for n in flow.nodes
    ]
    flow_db.db_session.commit()
    scheduler(monkeypatch)
    row = monitor.overview("alice", now=NOW)["strategies"][0]
    assert row["monitor_status"] == "waiting_check"
    execution(wid, at=NOW - timedelta(days=7))
    row = monitor.overview("alice", now=NOW)["strategies"][0]
    assert row["monitor_status"] == "scheduled"
    assert "not confirmed" in row["reason"]


def test_previous_rejection_remains_visible_after_no_signal_success(db, monkeypatch):
    from services.strategy_module import monitor

    _, wid = seed()
    execution(wid, at=NOW - timedelta(minutes=1), status="failed", error="Risk budget exhausted")
    execution(wid)
    scheduler(monkeypatch)
    row = monitor.overview("alice", now=NOW)["strategies"][0]
    assert row["last_check_status"] == "success"
    assert row["last_failure"]["message"] == "Risk budget exhausted"


def test_option_stop_plan_and_setup_rejection_remain_visible(db, monkeypatch):
    from services.strategy_module import monitor
    sid, wid = seed()
    store.record_event(sid, "alice", "entry_plan", "Stop prepared",
                       payload={"context": {"structure": {"stop_price": "39.45"}}, "token": "hidden"})
    store.record_event(sid, "alice", "entry_setup_rejected", "Option candles missing")
    execution(wid)
    scheduler(monkeypatch)
    row = monitor.overview("alice", now=NOW)["strategies"][0]
    assert row["entry_plan"]["details"]["context"]["structure"]["stop_price"] == "39.45"
    assert row["entry_plan"]["details"]["token"] == "[redacted]"
    assert row["last_risk_rejection"]["message"] == "Option candles missing"


def test_signal_snapshot_and_events_are_owner_scoped_and_redacted(client, monkeypatch):
    from services.strategy_module import monitor

    sid, wid = seed()
    other, _ = seed("bob")
    store.record_event(
        sid,
        "alice",
        "signal_evaluation",
        "No signal",
        payload={"technical": {"metrics": {"ema9": 24000}}, "token": "hide"},
    )
    store.record_event(other, "bob", "signal_evaluation", "Foreign", payload={"private": "bob"})
    execution(wid)
    scheduler(monkeypatch)
    data = monitor.overview("alice", now=NOW)
    assert len(data["strategies"]) == 1
    assert data["strategies"][0]["evaluation"]["token"] == "[redacted]"
    response = client.get(f"/strategy/api/automation/strategies/{sid}/logs?stream=events")
    assert response.status_code == 200 and len(response.json["data"]["items"]) == 1
    assert "hide" not in response.get_data(as_text=True)


def test_detached_open_run_is_still_targeted(db, monkeypatch):
    from services.strategy_module import automation_control as control
    from services.strategy_module import monitor

    sid, wid = seed(automation_state="disabled")
    flow = flow_db.db_session.get(flow_db.FlowWorkflow, wid)
    flow.is_active = False
    flow_db.db_session.commit()
    run = store.SmStrategyRun(strategy_id=sid, mode="sandbox")
    store.db_session.add(run)
    store.db_session.commit()
    monkeypatch.setattr(control, "_control_lease", lambda *a, **k: nullcontext())
    seen = []
    monkeypatch.setattr(
        control,
        "disable_and_close",
        lambda sid, owner: (
            seen.append(sid) or control.ControlResult(True, "closing", close_pending=True)
        ),
    )
    assert not monitor.emergency_stop("alice")["all_stopped"]
    assert seen == [sid]


def test_active_legacy_flow_is_reported_even_if_strategy_looks_disabled(db, monkeypatch):
    from services.strategy_module import automation_control as control
    from services.strategy_module import monitor

    sid, _ = seed(automation_state="disabled", scalp_profile=None)
    monkeypatch.setattr(control, "_control_lease", lambda *a, **k: nullcontext())
    result = monitor.emergency_stop("alice")
    assert not result["all_stopped"]
    assert result["items"][0]["strategy_id"] == sid


def test_failure_to_persist_failure_does_not_skip_remaining_closures(db, monkeypatch):
    from services.strategy_module import automation_control as control
    from services.strategy_module import monitor

    ids = [seed()[0], seed()[0]]
    seen = []
    monkeypatch.setattr(control, "_control_lease", lambda *a, **k: nullcontext())

    def fail(*a, **k):
        raise RuntimeError("database unavailable")

    def close(sid, owner):
        seen.append(sid)
        if sid == ids[0]:
            raise RuntimeError("close unavailable")
        return control.ControlResult(True, "disabled")

    monkeypatch.setattr(control, "disable_and_close", close)
    monkeypatch.setattr(store, "set_automation_state", fail)
    result = monitor.emergency_stop("alice")
    assert seen == ids and not result["all_stopped"]


def test_authorization_peek_does_not_expire_or_notify(monkeypatch, live_authorization_broker):
    from database import live_authorization_db as durable
    from services.strategy_module import live_authorization as live

    old = {"user_id": "monitor-test", "active": True, "session_day": "2020-01-01",
           "expires_at": "2020-01-02T03:00:00+05:30", "binding_digest": "test-monitor-test"}
    with live_authorization_broker.begin() as connection:
        connection.execute(durable.authorizations.insert().values(**old))
    monkeypatch.setattr(live, "_notify_transition", lambda *a: pytest.fail("Read must not notify"))
    assert not live.peek_status("monitor-test").active
    with live_authorization_broker.connect() as connection:
        assert dict(connection.execute(select(durable.authorizations)).mappings().one()) == old


def test_risk_evidence_is_pure_and_reports_effective_caps(db, monkeypatch):
    # Undo only the fixture's risk_evidence stub, then exercise the real pure reader.
    import importlib

    from database import trading_risk_db as risk
    from services.strategy_module import monitor

    monkeypatch.setattr(risk, "engine", db)
    risk.Base.metadata.create_all(db)
    with Session(db) as session:
        session.add(
            risk.RiskAccount(
                scope="alice|sandbox", capital=10000, peak=10000, policy_version="equity-1pct-v2"
            )
        )
        session.commit()
    actual = importlib.reload(monitor).risk_evidence("alice", "sandbox", "2026-09-28")
    assert actual["available"]
    assert actual["ledger"]["per_trade_limit"] == 100
    assert actual["ledger"]["daily_limit"] == 300
    with Session(db) as session:
        assert session.scalar(select(risk.RiskDayEquity)) is None
        assert session.scalar(select(risk.RiskDayStop)) is None
