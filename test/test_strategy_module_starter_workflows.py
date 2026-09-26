"""Exchange-aware Flow graphs for the SENSEX/MCX sandbox strategy pack."""

from types import SimpleNamespace

import pytest

from services.flow_executor_service import NodeExecutor, WorkflowContext
from services.flow_workflow_validator import validate_workflow
from services.strategy_module import starter_workflows

STRATEGY_IDS = {
    "SENSEX 5/15-Minute Trend Signal Receiver": 101,
    "SENSEX Breakout and Retest Signal Receiver": 102,
    "GOLDM Momentum and Breakout Signal Receiver": 103,
    "CRUDEOILM Momentum and Breakout Signal Receiver": 104,
    "SILVERM Momentum and Breakout Signal Receiver": 105,
    "NATGASMINI Momentum and Breakout Signal Receiver": 106,
}


def test_six_exchange_aware_workflow_graphs_are_strictly_valid():
    definitions = starter_workflows.workflow_definitions(STRATEGY_IDS, "alice")

    assert len(definitions) == 6
    for definition in definitions:
        assert validate_workflow(definition, strict=True) == []
        start = next(node for node in definition["nodes"] if node["type"] == "start")
        run = next(node for node in definition["nodes"] if node["type"] == "strategyModuleRun")
        assert start["data"]["intervalValue"] == 5
        assert start["data"]["intervalUnit"] == "minutes"
        assert start["data"]["marketHoursOnly"] is True
        expected_calendar = "BSE" if definition["metadata"]["exchange"] == "BSE_INDEX" else definition["metadata"]["exchange"]
        assert start["data"]["marketHoursExchange"] == expected_calendar
        assert run["data"]["mode"] == "sandbox"
        assert type(run["data"]["strategyId"]) is int
        assert run["data"]["strategyId"] == STRATEGY_IDS[definition["metadata"]["strategy_name"]]
        assert run["data"]["brokerOwner"] == "alice"
        assert run["data"]["barEvidence"] == {
            "5m": ["bar5Current", "bar5Previous"],
            "15m": ["bar15Current", "bar15Previous"],
        }
        assert run["data"]["marketHoursExchange"] == expected_calendar


def test_mcx_graphs_use_mcx_history_and_stricter_confirmation_for_volatile_minis():
    definitions = starter_workflows.workflow_definitions(STRATEGY_IDS, "alice")
    by_underlying = {definition["metadata"]["underlying"]: definition for definition in definitions}

    for underlying in ("GOLDM", "CRUDEOILM", "SILVERM", "NATGASMINI"):
        bars = [node for node in by_underlying[underlying]["nodes"] if node["type"] == "barOffset"]
        assert bars
        assert all(node["data"]["exchange"] == "MCX" for node in bars)

    assert by_underlying["SILVERM"]["metadata"]["risk_profile"] == "high_volatility"
    assert by_underlying["NATGASMINI"]["metadata"]["risk_profile"] == "high_volatility"


def test_strategy_module_run_node_refuses_missing_owner_before_engine(monkeypatch):
    from services.strategy_module import engine

    monkeypatch.setattr(
        engine,
        "start_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    executor = NodeExecutor(
        SimpleNamespace(api_key="api-key"), WorkflowContext(workflow_id=5), [], "starter"
    )

    result = executor.execute_strategy_module_run(
        {"strategyId": 101, "mode": "sandbox", "outputVariable": "run"}
    )

    assert result["status"] == "error"
    assert "owner" in result["message"].lower()


def test_strategy_module_run_node_refuses_unknown_mode_before_engine(monkeypatch):
    from services.strategy_module import engine

    monkeypatch.setattr(
        engine,
        "start_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    executor = NodeExecutor(
        SimpleNamespace(api_key="api-key"), WorkflowContext(workflow_id=5), [], "starter"
    )

    result = executor.execute_strategy_module_run({"strategyId": 101, "mode": "anything"})

    assert result["status"] == "error"


def test_mcx_history_roots_resolve_to_the_current_future(monkeypatch):
    from services import option_symbol_service

    monkeypatch.setattr(
        option_symbol_service,
        "resolve_underlying_quote",
        lambda symbol, exchange: ("SILVERM30NOV26FUT", "MCX"),
    )
    executor = NodeExecutor(
        SimpleNamespace(api_key="api-key"), WorkflowContext(workflow_id=5), [], "starter"
    )

    assert executor.history_instrument("SILVERM", "MCX") == ("SILVERM30NOV26FUT", "MCX")


def test_workflow_install_is_idempotent(monkeypatch):
    from database import flow_db

    rows = []

    def create_workflow(name, description, nodes, edges, broker_connection_id=None):
        row = SimpleNamespace(
            id=len(rows) + 1,
            name=name,
            description=description,
            nodes=nodes,
            edges=edges,
            is_active=False,
        )
        rows.append(row)
        return row

    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: list(rows))
    monkeypatch.setattr(flow_db, "create_workflow", create_workflow)
    monkeypatch.setattr(flow_db, "update_workflow", lambda *_args, **_kwargs: None)

    first = starter_workflows.install(STRATEGY_IDS, "alice")
    second = starter_workflows.install(STRATEGY_IDS, "alice")

    assert len(first.created) == 6
    assert first.existing == ()
    assert second.created == ()
    assert len(second.existing) == 6
    assert all(item["is_active"] is False for item in second.existing)


def test_install_stores_strategy_connection_and_preserves_activation_on_reinstall(monkeypatch):
    from database import flow_db

    rows = []
    updates = []
    create_arguments = []

    def create_workflow(**kwargs):
        create_arguments.append(kwargs)
        row = SimpleNamespace(id=31, name=kwargs["name"], nodes=kwargs["nodes"],
                              edges=kwargs["edges"], broker_connection_id=kwargs["broker_connection_id"],
                              is_active=True)
        rows.append(row)
        return row

    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: list(rows))
    monkeypatch.setattr(flow_db, "create_workflow", create_workflow)
    monkeypatch.setattr(flow_db, "update_workflow", lambda *_args, **kwargs: updates.append(kwargs))
    strategy_name = "SENSEX 5/15-Minute Trend Signal Receiver"
    ids = {strategy_name: 101}
    connections = {strategy_name: "connection-1"}

    starter_workflows.install(ids, "alice", broker_connection_ids=connections)
    result = starter_workflows.install(ids, "alice", broker_connection_ids=connections)

    run = next(node for node in rows[0].nodes if node["type"] == "strategyModuleRun")
    assert type(run["data"]["strategyId"]) is int
    assert run["data"]["strategyId"] == 101
    assert run["data"]["brokerOwner"] == "alice"
    assert run["data"]["mode"] == "sandbox"
    assert create_arguments[0]["broker_connection_id"] == "connection-1"
    assert rows[0].broker_connection_id == "connection-1"
    assert rows[0].is_active is True
    assert result.existing == ({"id": 31, "name": rows[0].name, "is_active": True},)
    assert updates == []


def test_install_repairs_missing_market_hours_exchange_on_existing_starter(monkeypatch):
    from database import flow_db

    definition = starter_workflows.workflow_definitions(STRATEGY_IDS, "alice")[-1]
    stale_nodes = [dict(node, data=dict(node["data"])) for node in definition["nodes"]]
    start = next(node for node in stale_nodes if node["type"] == "start")
    start["data"].pop("marketHoursExchange")
    row = SimpleNamespace(
        id=12,
        name=definition["name"],
        nodes=stale_nodes,
        edges=definition["edges"],
        is_active=True,
    )
    updates = []

    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: [row])
    monkeypatch.setattr(flow_db, "create_workflow", lambda **_kwargs: None)
    monkeypatch.setattr(
        flow_db, "update_workflow", lambda workflow_id, **kwargs: updates.append((workflow_id, kwargs))
    )

    starter_workflows.install({definition["metadata"]["strategy_name"]: 106}, "alice")

    assert updates[0][0] == 12
    repaired_start = next(
        node for node in updates[0][1]["nodes"] if node["type"] == "start"
    )
    assert repaired_start["data"]["marketHoursExchange"] == "MCX"


def test_installer_adds_bar_guard_to_existing_unmodified_starter(monkeypatch):
    from database import flow_db

    definition = starter_workflows.workflow_definitions(STRATEGY_IDS, "alice")[0]
    old_nodes = [dict(node, data=dict(node["data"])) for node in definition["nodes"]]
    run = next(node for node in old_nodes if node["type"] == "strategyModuleRun")
    run["data"].pop("barEvidence", None)
    run["data"].pop("marketHoursExchange", None)
    row = SimpleNamespace(
        id=18,
        name=definition["name"],
        nodes=old_nodes,
        edges=definition["edges"],
        is_active=True,
    )
    updates = []
    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: [row])
    monkeypatch.setattr(flow_db, "update_workflow", lambda workflow_id, **kwargs: updates.append(kwargs))

    starter_workflows.install({definition["metadata"]["strategy_name"]: 101}, "alice")

    assert updates
    upgraded = next(node for node in updates[0]["nodes"] if node["type"] == "strategyModuleRun")
    assert upgraded["data"]["barEvidence"]["5m"] == ["bar5Current", "bar5Previous"]


def test_installer_preserves_a_customized_existing_graph(monkeypatch):
    from database import flow_db

    definition = starter_workflows.workflow_definitions(STRATEGY_IDS, "alice")[0]
    nodes = [dict(node, data=dict(node["data"])) for node in definition["nodes"]]
    run = next(node for node in nodes if node["type"] == "strategyModuleRun")
    run["data"].pop("barEvidence")
    run["data"].pop("marketHoursExchange")
    trend = next(node for node in nodes if node["id"] == "trend5")
    trend["data"]["rightValue"] = "{{bar5Previous.close}}"
    start = next(node for node in nodes if node["id"] == "start")
    start["data"]["marketHoursExchange"] = "NSE"
    row = SimpleNamespace(id=20, name=definition["name"], nodes=nodes, edges=definition["edges"], is_active=True)
    updates = []
    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: [row])
    monkeypatch.setattr(flow_db, "update_workflow", lambda workflow_id, **kwargs: updates.append(kwargs))

    starter_workflows.install({definition["metadata"]["strategy_name"]: 101}, "alice")

    assert updates == []
    assert "barEvidence" not in run["data"]
    assert start["data"]["marketHoursExchange"] == "NSE"


@pytest.mark.parametrize("node_id", ["start", "run"])
def test_installer_preserves_calendar_only_customization(monkeypatch, node_id):
    from database import flow_db

    definition = starter_workflows.workflow_definitions(STRATEGY_IDS, "alice")[0]
    nodes = [dict(node, data=dict(node["data"])) for node in definition["nodes"]]
    customized = next(node for node in nodes if node["id"] == node_id)
    customized["data"]["marketHoursExchange"] = "NSE"
    row = SimpleNamespace(
        id=21, name=definition["name"], nodes=nodes, edges=definition["edges"], is_active=True
    )
    updates = []
    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: [row])
    monkeypatch.setattr(flow_db, "update_workflow", lambda workflow_id, **kwargs: updates.append(kwargs))

    starter_workflows.install({definition["metadata"]["strategy_name"]: 101}, "alice")

    assert updates == []
    assert customized["data"]["marketHoursExchange"] == "NSE"
