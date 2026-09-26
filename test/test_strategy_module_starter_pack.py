"""Safety and idempotency contract for the sandbox starter strategies."""

import sys
from datetime import datetime
from pathlib import Path

import pytest
import pytz
from flask import Flask

sys.path.insert(0, str(Path(__file__).parents[1]))

from blueprints import strategy_module  # noqa: E402
from database import strategy_module_db as store  # noqa: E402
from database.engine_factory import create_db_engine  # noqa: E402
from limiter import limiter  # noqa: E402
from services import indicator_service  # noqa: E402
from services.strategy_module import starter_pack, starter_workflows  # noqa: E402

USER = "starter-pack-user"


@pytest.fixture(scope="session", autouse=True)
def isolated_store(tmp_path_factory):
    path = tmp_path_factory.mktemp("starter-pack") / "strategy-module-test.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    store.db_session.remove()
    store.db_session.configure(bind=engine)
    store.engine = engine
    store.Base.metadata.create_all(bind=engine)
    yield engine
    store.db_session.remove()
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(isolated_store, monkeypatch):
    real_workflow_install = starter_workflows.install
    monkeypatch.setattr(
        starter_workflows,
        "install",
        lambda _ids, _owner, broker_connection_ids=None: starter_workflows.WorkflowInstallResult((), ()),
    )
    store.db_session.remove()
    with isolated_store.begin() as connection:
        for table in reversed(store.Base.metadata.sorted_tables):
            connection.execute(table.delete())
    yield real_workflow_install
    store.db_session.remove()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    application = Flask(__name__)
    application.config.update(
        TESTING=True,
        SECRET_KEY="starter-pack-tests",
        PROPAGATE_EXCEPTIONS=True,
    )
    application.register_blueprint(strategy_module.strategy_module_bp)
    return application


@pytest.fixture
def client(app):
    test_client = app.test_client()
    with test_client.session_transaction() as flask_session:
        flask_session["logged_in"] = True
        flask_session["user"] = USER
        flask_session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    return test_client


def test_every_starter_definition_is_a_safe_unscheduled_strategy_module_config():
    """A changed template that skips validation or loosens risk must be rejected here."""
    definitions = starter_pack.starter_definitions()

    assert len(definitions) == 12
    assert len({definition["name"] for definition in definitions}) == 12
    for definition in definitions:
        validated, error = strategy_module.validate_strategy_config(definition)

        assert error is None, f"{definition['name']}: {error}"
        assert validated["scheduler"] is None
        assert validated["pricetype"] == "MARKET"
        assert validated["strategy_type"] == "intraday"
        if validated["underlying_exchange"] == "MCX":
            assert validated["entry_time"].strftime("%H:%M") == "09:30"
            assert validated["exit_time"].strftime("%H:%M") == "22:45"
        elif validated["underlying_exchange"] == "BSE_INDEX":
            assert validated["entry_time"].strftime("%H:%M") == "09:20"
            assert validated["exit_time"].strftime("%H:%M") == "15:15"
        else:
            assert validated["entry_time"].strftime("%H:%M") == "09:20"
            assert validated["exit_time"].strftime("%H:%M") == "15:20"
        assert validated["daily_loss_limit_inr"] > 0
        for leg in validated["legs"]:
            assert leg["sl_pts"] > 0
            assert leg["target_pts"] > 0
            assert leg["target_pts"] / leg["sl_pts"] >= 1.5


def test_cash_templates_are_signal_receivers_for_exact_liquid_symbols():
    """Changing a cash template into a stale resolver-dependent leg must fail here."""
    cash_definitions = [
        definition
        for definition in starter_pack.starter_definitions()
        if definition["strategy_kind"] == "signal"
    ]

    assert len(cash_definitions) == 3
    for definition in cash_definitions:
        leg = definition["legs"][0]
        assert leg["segment"] == "cash"
        assert leg["exchange"] == "NSE"
        assert leg["qty_mode"] == "units"
        assert leg["symbol"] in {"RELIANCE", "HDFCBANK", "ICICIBANK"}


def test_option_templates_are_batch_strategies_with_dynamic_atm_legs():
    """Replacing a rolling ATM option with a literal expiring symbol must fail here."""
    option_definitions = [
        definition
        for definition in starter_pack.starter_definitions()
        if definition["strategy_kind"] == "batch"
    ]

    assert len(option_definitions) == 9
    for definition in option_definitions:
        assert len(definition["legs"]) == 1
        leg = definition["legs"][0]
        assert leg["segment"] == "options"
        assert leg["lots"] == 1
        assert leg["strike_mode"] == "atm"
        assert leg["atm_offset"] == "ATM"
        assert "symbol" not in leg


def test_sensex_templates_resolve_bfo_weekly_options():
    definitions = [
        definition
        for definition in starter_pack.starter_definitions()
        if definition["underlying"] == "SENSEX"
    ]

    assert {definition["name"] for definition in definitions} == {
        "SENSEX 5/15-Minute Trend Signal Receiver",
        "SENSEX Breakout and Retest Signal Receiver",
    }
    assert all(definition["underlying_exchange"] == "BSE_INDEX" for definition in definitions)
    assert all(definition["universe_tab"] == "weekly_monthly" for definition in definitions)
    assert all(definition["legs"][0]["expiry"] == "weekly" for definition in definitions)


def test_mcx_templates_resolve_each_requested_current_month_option():
    definitions = [
        definition
        for definition in starter_pack.starter_definitions()
        if definition["underlying_exchange"] == "MCX"
    ]

    assert {definition["underlying"] for definition in definitions} == {
        "GOLDM",
        "CRUDEOILM",
        "SILVERM",
        "NATGASMINI",
    }
    assert all(definition["universe_tab"] == "mcx" for definition in definitions)
    assert all(definition["legs"][0]["expiry"] == "current" for definition in definitions)
    assert all(definition["entry_time"] == "09:30" for definition in definitions)
    assert all(definition["exit_time"] == "22:45" for definition in definitions)


def test_install_creates_stopped_sandbox_strategies_once_and_never_starts_a_run():
    """A duplicate install or accidental activation must fail this user-visible contract."""
    first = starter_pack.install(USER)

    assert len(first.created) == 12
    assert first.existing == ()
    assert len(first.webhook_tokens) == 12
    assert all(token.startswith(store.WEBHOOK_TOKEN_PREFIX) for token in first.webhook_tokens.values())
    rows = store.list_strategies(USER)
    assert len(rows) == 12
    assert all(row["status"] == "stopped" for row in rows)
    assert all(row["live_enabled"] is False for row in rows)
    assert all(row["automation_state"] == "disabled" for row in rows)
    assert all(row["scheduler"] is None for row in rows)
    assert all(store.list_runs(row["id"]) == [] for row in rows)
    token_hashes = {
        row["name"]: store.get_strategy(row["id"], USER).webhook_token_hash for row in rows
    }

    second = starter_pack.install(USER)

    assert second.created == ()
    assert len(second.existing) == 12
    assert second.webhook_tokens == {}
    assert {entry["name"] for entry in second.existing} == {entry["name"] for entry in first.created}
    assert all(store.list_runs(row["id"]) == [] for row in store.list_strategies(USER))
    assert {
        row["name"]: store.get_strategy(row["id"], USER).webhook_token_hash
        for row in store.list_strategies(USER)
    } == token_hashes


def test_install_passes_saved_strategy_connection_to_workflow_installer(monkeypatch):
    starter_pack.install(USER)
    row = next(
        item for item in store.list_strategies(USER)
        if item["name"] == "SENSEX 5/15-Minute Trend Signal Receiver"
    )
    store.db_session.query(store.SmStrategy).filter_by(id=row["id"]).update(
        {"broker_connection_id": "connection-1"}
    )
    store.db_session.commit()
    captured = []

    def capture_install(ids, owner, broker_connection_ids=None):
        captured.append((ids, owner, broker_connection_ids))
        return starter_workflows.WorkflowInstallResult((), ())

    monkeypatch.setattr(starter_workflows, "install", capture_install)

    starter_pack.install(USER)

    assert captured[0][0]["SENSEX 5/15-Minute Trend Signal Receiver"] == row["id"]
    assert captured[0][1] == USER
    assert captured[0][2]["SENSEX 5/15-Minute Trend Signal Receiver"] == "connection-1"


def test_reinstall_preserves_custom_config_and_operator_admission():
    starter_pack.install(USER)
    row = store.list_strategies(USER)[0]
    saved = store.get_strategy(row["id"], USER)
    saved.overall_sl_mtm = 321
    saved.automation_state = "close_failed"
    saved.automation_state_reason = "broker rejected exit"
    saved.automation_state_updated_at = datetime(2026, 9, 25, 9, 30)
    store.db_session.commit()

    result = starter_pack.install(USER)

    assert result.created == ()
    current = store.get_strategy(row["id"], USER)
    assert current.overall_sl_mtm == 321
    assert current.automation_state == "close_failed"
    assert current.automation_state_reason == "broker rejected exit"
    assert current.automation_state_updated_at == datetime(2026, 9, 25, 9, 30)
    assert store.list_runs(row["id"]) == []


def test_installed_starters_have_disabled_admission_and_complete_preserved_flow_links(
    isolated_store, empty_tables, monkeypatch
):
    from copy import deepcopy

    from sqlalchemy.orm import scoped_session, sessionmaker

    from database import flow_db
    from services.strategy_module.automation_control import resolve_workflow_link

    flow_db.Base.metadata.create_all(isolated_store)
    session = scoped_session(sessionmaker(bind=isolated_store))
    monkeypatch.setattr(flow_db, "db_session", session)
    original_query = vars(flow_db.Base)["query"]
    flow_db.Base.query = session.query_property()
    monkeypatch.setattr(starter_workflows, "install", empty_tables)
    try:
        first = starter_pack.install(USER)
        assert len(first.workflows_created) == 12
        linked_signal_ids = set()
        for result in first.workflows_created:
            workflow = session.get(flow_db.FlowWorkflow, result["id"])
            run_node = next(node for node in workflow.nodes if node["type"] in {"strategyModuleRun", "strategySignal"})
            strategy = store.get_strategy(run_node["data"]["strategyId"], USER)
            if strategy.strategy_kind == "signal":
                linked_signal_ids.add(strategy.id)
                assert run_node["type"] == "strategySignal"
                assert run_node["data"]["action"] == "long_entry"
            link, error = resolve_workflow_link(strategy)
            assert error is None
            assert link.workflow_id == workflow.id
            assert link.active is False
            assert strategy.automation_state == "disabled"
            assert store.list_runs(strategy.id) == []
        assert linked_signal_ids == {
            row["id"] for row in store.list_strategies(USER) if row["strategy_kind"] == "signal"
        }
        workflow.is_active = True
        customized_nodes = deepcopy(workflow.nodes)
        customized_nodes[0]["data"]["intervalValue"] = 17
        workflow.nodes = customized_nodes
        session.commit()
        assert store.set_automation_state(strategy.id, USER, "armed") == (True, None)

        second = starter_pack.install(USER)

        assert second.created == ()
        assert second.workflows_created == ()
        session.expire_all()
        assert session.get(flow_db.FlowWorkflow, workflow.id).nodes == customized_nodes
        assert session.get(flow_db.FlowWorkflow, workflow.id).is_active is True
        assert store.get_strategy(strategy.id, USER).automation_state == "armed"
        assert store.list_runs(strategy.id) == []
    finally:
        flow_db.Base.query = original_query
        session.remove()
        with isolated_store.begin() as connection:
            for table in reversed(flow_db.Base.metadata.sorted_tables):
                connection.execute(table.delete())


def test_generated_cash_starter_reaches_real_signal_engine_and_creates_sandbox_run(monkeypatch):
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from database import auth_db, flow_db, market_calendar_db
    from services.flow_executor_service import NodeExecutor, WorkflowContext, execute_node_chain
    from services.strategy_module import signals, state

    starter_pack.install(USER)
    row = next(row for row in store.list_strategies(USER)
               if row["name"] == "NIFTY 50 Cash Momentum Signal Receiver")
    strategy = store.get_strategy(row["id"], USER)
    strategy.broker_connection_id = "connection-1"
    store.db_session.commit()
    assert store.set_automation_state(strategy.id, USER, "armed") == (True, None)
    definitions = starter_workflows.workflow_definitions({strategy.name: strategy.id}, USER)
    assert len(definitions) == 1
    node = next(node for node in definitions[0]["nodes"] if node["id"] == "run")
    assert node["type"] == "strategySignal"

    stamp = datetime(2026, 9, 25, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    now = stamp.replace(minute=5, second=10)
    monkeypatch.setattr(auth_db, "get_username_by_apikey", lambda _key: USER)
    validate_bars = indicator_service.validate_current_bar_set
    monkeypatch.setattr(indicator_service, "validate_current_bar_set",
                        lambda bars, exchange: validate_bars(bars, exchange, now))
    bar_at_offset = indicator_service.bar_at_offset
    monkeypatch.setattr(indicator_service, "bar_at_offset",
                        lambda records, offset, interval: bar_at_offset(
                            records, offset, interval, now.replace(tzinfo=None)
                        ))
    monkeypatch.setattr(market_calendar_db, "get_effective_session_window", lambda *_: {
        "start_ms": int(stamp.replace(hour=9, minute=15).timestamp() * 1000),
        "end_ms": int(stamp.replace(hour=15, minute=30).timestamp() * 1000),
    })
    monkeypatch.setattr(NodeExecutor, "broker_connection_ready", lambda *_: True)
    monkeypatch.setattr(flow_db, "claim_execution_bar", lambda *_: "claimed")
    monkeypatch.setattr(signals, "_window_note", lambda *_: None)
    monkeypatch.setattr(signals, "_api_key_for", lambda *_: "test-key")
    entries = []

    def accept_entry(saved, run_id, leg, side):
        entries.append((saved.id, leg["symbol"], leg["exchange"], side))
        return signals.SignalResult(ok=True, run_id=run_id, leg_id=leg["id"])

    # Only the order-producing boundary is stubbed. handle_signal, durable
    # admission and daily-run creation execute normally against the test DB.
    monkeypatch.setattr(signals, "_enter", accept_entry)
    context = WorkflowContext(workflow_id=11)
    context.execution_id = 22
    context.broker_connection_id = "connection-1"
    history = {"5m": [], "15m": []}
    for interval, at, close in (
        ("5m", stamp.replace(hour=9, minute=55), 100),
        ("5m", stamp, 105),
        ("15m", stamp.replace(hour=9, minute=30), 100),
        ("15m", stamp.replace(hour=9, minute=45), 105),
    ):
        history[interval].append({
            "status": "success", "timestamp": at.isoformat(),
            "symbol": "RELIANCE", "exchange": "NSE",
            "open": 100, "high": close + 1, "low": 99, "close": close, "volume": 100,
        })
    monkeypatch.setattr(indicator_service, "fetch_history_cached",
                        lambda _client, _symbol, _exchange, interval, *_: {
                            "status": "success", "data": history[interval],
                        })
    executor = NodeExecutor(SimpleNamespace(api_key="test-key"), context, [], definitions[0]["name"])
    edge_map = {}
    incoming = {}
    for edge in definitions[0]["edges"]:
        edge_map.setdefault(edge["source"], []).append(edge)
        incoming.setdefault(edge["target"], []).append(edge)
    execute_node_chain("start", definitions[0]["nodes"], edge_map, incoming, executor, context, {})
    assert executor.errors == []
    result = context.get_variable("strategyRun")

    assert result["status"] == "success"
    assert result["action"] == "long_entry"
    assert entries == [(strategy.id, "RELIANCE", "NSE", "long")]
    run = store.get_run(result["run_id"])
    assert run.strategy_id == strategy.id
    assert run.mode == "sandbox"
    assert run.broker_connection_id == "connection-1"
    state.clear_run_state(run.id)


def test_authenticated_install_route_returns_tokens_only_when_it_creates_rows(client):
    """Returning stored tokens on a repeat request would make a credential replayable."""
    first = client.post("/strategy/api/automation/starter-pack")

    assert first.status_code == 201
    first_body = first.get_json()
    assert len(first_body["created"]) == 12
    assert first_body["existing"] == []
    assert len(first_body["webhook_tokens"]) == 12

    second = client.post("/strategy/api/automation/starter-pack")

    assert second.status_code == 200
    second_body = second.get_json()
    assert second_body["created"] == []
    assert len(second_body["existing"]) == 12
    assert second_body["webhook_tokens"] == {}
