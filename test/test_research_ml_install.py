"""Frozen ML setup is explicit, owner scoped, and starts without activation."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from services.research import ml_install


def test_failed_historical_gate_never_creates_strategy(monkeypatch):
    final = {"id": 2, "parent_run_id": 1}

    class Store:
        def get_run(self, owner, run_id):
            assert owner == "alice"
            return {1: {"id": 1}, 2: final}.get(run_id)

    monkeypatch.setattr(ml_install, "get_store", lambda: Store())
    monkeypatch.setattr(ml_install, "historical_ml_reason", lambda *_: "Final stress loss")
    monkeypatch.setattr(
        ml_install.strategies, "create_strategy", lambda *_: pytest.fail("premature install")
    )
    with pytest.raises(ValueError, match="stress"):
        ml_install.install("alice", 2)


def test_install_saves_one_stopped_sandbox_pair_only_after_gate(monkeypatch):
    model_hash = "a" * 64
    connection = "11111111-1111-4111-8111-111111111111"
    final = {
        "id": 2,
        "parent_run_id": 1,
        "dataset_id": 3,
        "report": {"ml": {"model_hash": model_hash}},
    }

    class Store:
        def get_run(self, owner, run_id):
            return {1: {"id": 1}, 2: final}.get(run_id) if owner == "alice" else None

        def get_dataset(self, owner, dataset_id):
            return {"metadata": {"session_open": "09:15", "session_close": "15:25"}}

    writes = []
    graphs = []

    def create_strategy(owner, config):
        writes.append((owner, config.copy()))
        return (
            {
                "id": 7,
                "name": config["name"],
                "ml_final_run_id": 2,
                "ml_model_hash": model_hash,
                "scalp_profile": "ml_forest",
                "status": "stopped",
                "automation_state": "disabled",
                "live_enabled": False,
                "broker_connection_id": connection,
                "entry_time": "09:15",
                "exit_time": "15:25",
                "webhook_token": "discarded",
            },
            None,
        )

    monkeypatch.setattr(ml_install, "get_store", lambda: Store())
    monkeypatch.setattr(ml_install, "historical_ml_reason", lambda *_: None)
    monkeypatch.setattr(ml_install, "_connection_for_owner", lambda *_: connection)
    monkeypatch.setattr(ml_install.strategies, "list_strategies", lambda _: [])
    monkeypatch.setattr(ml_install.strategies, "create_strategy", create_strategy)
    monkeypatch.setattr(ml_install.flow_db, "flow_link_mutation_lease", lambda: nullcontext())
    monkeypatch.setattr(ml_install.flow_db, "get_workflows_for_strategy", lambda *_args, **_kw: [])

    def create_workflow(**graph):
        graphs.append(graph)
        return SimpleNamespace(id=9)

    monkeypatch.setattr(ml_install.flow_db, "create_workflow", create_workflow)
    monkeypatch.setattr(ml_install, "validate_workflow", lambda *_args, **_kw: [])
    from services.strategy_module import automation_control

    monkeypatch.setattr(automation_control, "_control_lease", lambda *_: nullcontext())
    result = ml_install.install("alice", 2)
    assert result == {"created": True, "strategy_id": 7, "workflow_id": 9, "model_hash": model_hash}
    assert len(writes) == 1
    owner, config = writes[0]
    assert owner == "alice"
    assert config["ml_final_run_id"] == 2 and config["ml_model_hash"] == model_hash
    assert config["scalp_profile"] == "ml_forest"
    assert (config["entry_time"].strftime("%H:%M"), config["exit_time"].strftime("%H:%M")) == (
        "09:15",
        "15:25",
    )
    assert len(graphs) == 1
    assert {
        node["data"]["mode"] for node in graphs[0]["nodes"] if node["type"] == "strategyModuleRun"
    } == {"sandbox"}
    assert graphs[0]["broker_connection_id"] == connection
