"""Explicit Flow linkage for sandbox strategy automation."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from database import flow_db
from services.strategy_module import automation_control


def _strategy(**changes):
    values = {
        "id": 71,
        "user_id": "alice",
        "broker_connection_id": "connection-1",
        "name": "A display name that must not be used for linking",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _workflow(*, workflow_id=12, nodes=None, **changes):
    values = {
        "id": workflow_id,
        "name": "An unrelated Flow display name",
        "nodes": nodes if nodes is not None else [
            {"type": "strategyModuleRun", "data": {
                "strategyId": 71, "brokerOwner": "alice", "mode": "sandbox",
            }},
        ],
        "broker_connection_id": "connection-1",
        "is_active": True,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _resolve(monkeypatch, workflows, strategy=None, **kwargs):
    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: workflows)
    return automation_control.resolve_workflow_link(strategy or _strategy(), **kwargs)


def test_resolves_one_explicit_sandbox_link(monkeypatch):
    workflow = _workflow()

    link, error = _resolve(monkeypatch, [workflow])

    assert error is None
    assert link == automation_control.WorkflowLink(
        workflow_id=12, active=True, mode="sandbox", broker_owner="alice",
        broker_connection_id="connection-1",
    )


def test_signal_entry_nodes_are_explicit_links(monkeypatch):
    workflow = _workflow()
    workflow.nodes[0]["type"] = "strategySignal"
    workflow.nodes[0]["data"]["action"] = "long_entry"

    link, error = _resolve(monkeypatch, [workflow])

    assert error is None
    assert link.workflow_id == 12


@pytest.mark.parametrize("entry_type,entry_action", [
    ("strategyModuleRun", None), ("strategySignal", "start"),
    ("strategySignal", "long_entry"), ("strategySignal", "short_entry"),
])
def test_one_entry_with_two_protective_exits_is_one_admission_link(monkeypatch, entry_type, entry_action):
    data = {"strategyId": 71, "brokerOwner": "alice", "mode": "sandbox"}
    exits = ["stop", "stop"] if entry_action in {None, "start"} else ["long_exit", "long_exit"]
    workflow = _workflow(nodes=[
        {"type": "strategySignal", "data": {**data, "action": exits[0]}},
        {"type": entry_type, "data": {**data, "action": entry_action}},
        {"type": "strategySignal", "data": {**data, "action": exits[1]}},
    ])

    link, error = _resolve(monkeypatch, [workflow])

    assert error is None
    assert link.workflow_id == 12
    assert flow_db.get_workflows_for_strategy(71) == [workflow]
    assert automation_control._shared_workflow_error(workflow, 71) is None


@pytest.mark.parametrize("action", ["stop", "long_exit", "short_exit"])
def test_exit_only_workflow_is_not_an_admission_link(monkeypatch, action):
    workflow = _workflow(nodes=[{"type": "strategySignal", "data": {
        "strategyId": 71, "brokerOwner": "alice", "mode": "sandbox", "action": action,
    }}])

    link, error = _resolve(monkeypatch, [workflow])

    assert link is None
    assert "entry" in error.lower()


@pytest.mark.parametrize("extra_action", ["long_entry", "long_exit", "stop"])
def test_shared_execution_node_rejects_admission_even_for_same_owner(monkeypatch, extra_action):
    workflow = _workflow()
    workflow.nodes.append({"type": "strategySignal", "data": {
        "strategyId": 99, "brokerOwner": "alice", "mode": "sandbox", "action": extra_action,
    }})

    link, error = _resolve(monkeypatch, [workflow])

    assert link is None
    assert "shared" in error.lower()


@pytest.mark.parametrize("exit_changes,reason", [
    ({"action": "long_entry"}, "multiple"),
    ({"mode": "live"}, "sandbox"),
    ({"brokerOwner": "bob"}, "owner"),
    ({"action": "buy"}, "action"),
])
def test_protective_exit_nodes_cannot_hide_unsafe_execution_data(monkeypatch, exit_changes, reason):
    data = {"strategyId": 71, "brokerOwner": "alice", "mode": "sandbox"}
    workflow = _workflow(nodes=[
        {"type": "strategySignal", "data": {**data, "action": "long_entry"}},
        {"type": "strategySignal", "data": {**data, "action": "long_exit", **exit_changes}},
        {"type": "strategySignal", "data": {**data, "action": "long_exit"}},
    ])

    link, error = _resolve(monkeypatch, [workflow], _strategy(strategy_kind="signal"))

    assert link is None
    assert reason in error.lower()


@pytest.mark.parametrize("extra_mode,extra_owner", [("live", "alice"), ("sandbox", "bob")])
def test_mixed_signal_node_cannot_hide_beside_a_safe_run_link(monkeypatch, extra_mode, extra_owner):
    workflow = _workflow()
    workflow.nodes.append({"type": "strategySignal", "data": {
        "strategyId": 99, "brokerOwner": extra_owner, "mode": extra_mode, "action": "long_entry",
    }})

    link, error = _resolve(monkeypatch, [workflow])

    assert link is None
    assert error


def test_signal_node_for_another_strategy_prevents_individual_deactivation():
    workflow = _workflow()
    workflow.nodes.append({"type": "strategySignal", "data": {
        "strategyId": 99, "brokerOwner": "alice", "mode": "sandbox", "action": "long_entry",
    }})
    assert "Shared" in automation_control._shared_workflow_error(workflow, 71)


@pytest.mark.parametrize("action", [None, "buy", "start", "stop"])
def test_signal_strategy_link_rejects_invalid_or_batch_actions(monkeypatch, action):
    workflow = _workflow()
    workflow.nodes[0]["type"] = "strategySignal"
    workflow.nodes[0]["data"]["action"] = action

    link, error = _resolve(monkeypatch, [workflow], _strategy(strategy_kind="signal"))

    assert link is None
    assert "action" in error.lower()


def test_no_link_does_not_match_workflow_display_name(monkeypatch):
    workflow = _workflow(name="A display name that must not be used for linking", nodes=[])

    assert _resolve(monkeypatch, [workflow]) == (
        None, "No Flow workflow is explicitly linked to strategy 71."
    )


def test_two_matching_workflows_are_ambiguous(monkeypatch):
    assert _resolve(monkeypatch, [_workflow(), _workflow(workflow_id=13)]) == (
        None, "Multiple Flow workflows are linked to strategy 71."
    )


def test_two_matching_nodes_in_one_workflow_are_ambiguous(monkeypatch):
    workflow = _workflow()
    workflow.nodes.append(dict(workflow.nodes[0]))

    assert _resolve(monkeypatch, [workflow]) == (
        None, "Flow workflow 12 has multiple entry nodes for strategy 71."
    )


@pytest.mark.parametrize(
    ("node_changes", "workflow_changes", "expected"),
    [
        ({"mode": "live"}, {}, "Flow workflow 12 is not in sandbox mode."),
        ({"mode": True}, {}, "Flow workflow 12 has an invalid mode."),
        ({"brokerOwner": "bob"}, {}, "Flow workflow 12 has a different broker owner."),
        ({"brokerOwner": True}, {}, "Flow workflow 12 has an invalid broker owner."),
        ({}, {"broker_connection_id": "connection-2"},
         "Flow workflow 12 has a different broker connection."),
        ({}, {"broker_connection_id": None},
         "Flow workflow 12 has a different broker connection."),
        ({}, {"is_active": "true"}, "Flow workflow 12 has an invalid activation state."),
    ],
)
def test_invalid_link_fails_closed(monkeypatch, node_changes, workflow_changes, expected):
    workflow = _workflow(**workflow_changes)
    workflow.nodes[0]["data"].update(node_changes)

    assert _resolve(monkeypatch, [workflow]) == (None, expected)


@pytest.mark.parametrize("bad_id", ["71", True, 71.0])
def test_non_integer_node_strategy_id_is_not_a_link(monkeypatch, bad_id):
    workflow = _workflow()
    workflow.nodes[0]["data"]["strategyId"] = bad_id

    assert _resolve(monkeypatch, [workflow]) == (
        None, "No Flow workflow is explicitly linked to strategy 71."
    )


def test_malformed_nodes_in_a_matching_workflow_fail_closed(monkeypatch):
    workflow = _workflow()
    workflow.nodes.append("corrupt node")

    assert _resolve(monkeypatch, [workflow]) == (
        None, "Flow workflow 12 has malformed nodes."
    )


@pytest.mark.parametrize("bad_type", [[], {}])
def test_strict_link_validator_rejects_unhashable_node_types(bad_type):
    from services.strategy_module.workflow_link import validate_workflow_link

    workflow = _workflow()
    workflow.nodes.insert(0, {"type": bad_type, "data": {}})

    link, error = validate_workflow_link(_strategy(), [workflow])

    assert link is None
    assert "malformed" in error.lower()


@pytest.mark.parametrize("bad_type", [[], {}])
@pytest.mark.parametrize("valid_type", ["strategyModuleRun", "strategySignal"])
def test_flow_discovery_skips_unhashable_types_without_hiding_valid_links(monkeypatch, bad_type, valid_type):
    workflow = _workflow()
    workflow.nodes[0]["type"] = valid_type
    workflow.nodes[0]["data"]["action"] = "long_entry"
    workflow.nodes.insert(0, {"type": bad_type, "data": {"strategyId": 71}})
    unrelated = _workflow(workflow_id=13, nodes=[{"type": bad_type, "data": {}}])
    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: [unrelated, workflow])

    assert flow_db.get_workflows_for_strategy(71) == [workflow]
    link, error = automation_control.resolve_workflow_link(_strategy())
    assert link is None
    assert "malformed" in error.lower()


@pytest.mark.parametrize("bad_type", [[], {}])
def test_exclusive_control_check_refuses_unhashable_node_types(bad_type):
    workflow = _workflow()
    workflow.nodes.insert(0, {"type": bad_type, "data": {}})

    error = automation_control._shared_workflow_error(workflow, 71)

    assert error is not None
    assert "malformed" in error.lower()


def test_malformed_run_node_does_not_hide_beside_a_valid_link(monkeypatch):
    workflow = _workflow()
    workflow.nodes.append({
        "type": "strategyModuleRun",
        "data": {"strategyId": "71", "brokerOwner": "alice", "mode": "sandbox"},
    })

    assert _resolve(monkeypatch, [workflow]) == (
        None, "Flow workflow 12 has malformed run-node strategy IDs."
    )


def test_live_run_node_beside_target_sandbox_link_fails_closed(monkeypatch):
    workflow = _workflow()
    workflow.nodes.append({
        "type": "strategyModuleRun",
        "data": {"strategyId": 72, "brokerOwner": "alice", "mode": "live"},
    })

    assert _resolve(monkeypatch, [workflow]) == (
        None, "Flow workflow 12 contains a non-sandbox run node."
    )


def test_foreign_owner_run_node_beside_target_link_fails_closed(monkeypatch):
    workflow = _workflow()
    workflow.nodes.append({
        "type": "strategyModuleRun",
        "data": {"strategyId": 72, "brokerOwner": "bob", "mode": "sandbox"},
    })

    assert _resolve(monkeypatch, [workflow]) == (
        None, "Flow workflow 12 contains a run node for a different broker owner."
    )


@pytest.mark.parametrize(
    ("extra_data", "expected"),
    [
        ({"strategyId": 72, "brokerOwner": "alice", "mode": True},
         "Flow workflow 12 has an invalid mode."),
        ({"strategyId": 72, "brokerOwner": False, "mode": "sandbox"},
         "Flow workflow 12 has an invalid broker owner."),
    ],
)
def test_malformed_extra_run_node_fails_closed(monkeypatch, extra_data, expected):
    workflow = _workflow()
    workflow.nodes.append({"type": "strategyModuleRun", "data": extra_data})

    assert _resolve(monkeypatch, [workflow]) == (None, expected)


def test_live_link_is_available_only_when_sandbox_is_not_required(monkeypatch):
    workflow = _workflow()
    workflow.nodes[0]["data"]["mode"] = "live"

    link, error = _resolve(monkeypatch, [workflow], require_sandbox=False)

    assert error is None
    assert link.mode == "live"


def test_matching_connection_may_be_absent_on_both_sides(monkeypatch):
    link, error = _resolve(
        monkeypatch, [_workflow(broker_connection_id=None)],
        _strategy(broker_connection_id=None),
    )

    assert error is None
    assert link.broker_connection_id is None


def test_flow_storage_helper_only_returns_exact_integer_strategy_links(monkeypatch):
    matching = _workflow()
    wrong_type = _workflow(workflow_id=13)
    wrong_type.nodes[0]["data"]["strategyId"] = "71"
    boolean_id = _workflow(workflow_id=14)
    boolean_id.nodes[0]["data"]["strategyId"] = True
    malformed = _workflow(workflow_id=15, nodes=["corrupt node"])
    monkeypatch.setattr(flow_db, "get_all_workflows", lambda: [matching, wrong_type, boolean_id, malformed])

    assert flow_db.get_workflows_for_strategy(71) == [matching]


@pytest.fixture
def control_env(monkeypatch):
    """Real control/Flow rows; replace only trigger and order side effects."""
    from database import strategy_module_db as store
    from services import (
        flow_executor_service,
        flow_order_update_monitor_service,
        flow_price_monitor_service,
        flow_scheduler_service,
    )
    from services.strategy_module import engine, order_dispatch, starter_workflows, state

    store.init_db()
    flow_db.init_db()
    owner = f"automation_control_test_{uuid4().hex}"
    for item in store.list_strategies(owner):
        store.set_strategy_status(item["id"], "stopped", None)
        store.delete_strategy(item["id"], owner)
    created, error = store.create_strategy(
        owner,
        {
            "name": "Control test",
            "strategy_kind": "signal",
            "underlying": "SENSEX",
            "underlying_exchange": "BSE_INDEX",
            "product": "MIS",
            "legs": [
                {
                    "id": 1,
                    "symbol": "TEST",
                    "exchange": "BSE",
                    "segment": "equity",
                    "qty": 1,
                    "sl_pts": 10,
                    "target_pts": 20,
                }
            ],
            "overall_sl_mtm": 1000,
            "daily_loss_limit_inr": 1000,
        },
    )
    assert error is None
    strategy_id = created["id"]
    definition = starter_workflows._definition(
        "Control test",
        strategy_id,
        "SENSEX",
        "BSE_INDEX",
        "standard",
        owner,
    )
    workflow = flow_db.create_workflow(
        definition["name"],
        nodes=definition["nodes"],
        edges=definition["edges"],
    )
    workflow_id = workflow.id
    calls = []

    def register(**kwargs):
        calls.append("flow:register")
        return f"flow_workflow_{kwargs['workflow_id']}"

    def remove(workflow_id, **kwargs):
        calls.append("flow:unregister")
        return True

    scheduler = SimpleNamespace(
        set_api_key=lambda key: None, add_workflow_job=register, remove_workflow_job=remove
    )
    monkeypatch.setattr(flow_scheduler_service, "get_flow_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        flow_price_monitor_service,
        "get_flow_price_monitor",
        lambda: SimpleNamespace(remove_alert=lambda wid: None),
    )
    monkeypatch.setattr(
        flow_order_update_monitor_service,
        "get_flow_order_update_monitor",
        lambda: SimpleNamespace(remove_watch=lambda wid: None),
    )
    monkeypatch.setattr(flow_executor_service, "release_workflow_subscriptions", lambda wid: 0)

    def unexpected(*args, **kwargs):
        pytest.fail("Automation control must not start a run or dispatch an order")

    monkeypatch.setattr(engine, "start_run", unexpected)
    monkeypatch.setattr(order_dispatch, "dispatch_order", unexpected)
    env = SimpleNamespace(
        owner=owner,
        strategy_id=strategy_id,
        workflow_id=workflow_id,
        store=store,
        calls=calls,
        scheduler=scheduler,
    )
    yield env
    for row in store.db_session.query(store.SmStrategyRun).filter_by(strategy_id=strategy_id):
        state.clear_run_state(row.id)
    for wf in flow_db.get_workflows_for_strategy(strategy_id):
        flow_db.delete_workflow(wf.id)
    store.set_strategy_status(strategy_id, "stopped", None)
    store.delete_strategy(strategy_id, owner)
    store.db_session.remove()
    flow_db.db_session.remove()


def _control_strategy(env):
    env.store.db_session.expire_all()
    return env.store.get_strategy(env.strategy_id, env.owner)


def _control_workflow(env):
    flow_db.db_session.expire_all()
    return flow_db.get_workflow(env.workflow_id)


def test_enable_arms_future_signals_without_starting_or_dispatching(control_env):
    env = control_env

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert result.ok and result.state == "armed" and result.error is None
    assert result.workflow_id == env.workflow_id and result.run_id is None
    assert result.close_pending is False
    assert _control_strategy(env).automation_state == "armed"
    assert _control_strategy(env).current_run_id is None
    assert _control_workflow(env).is_active is True
    assert env.calls == ["flow:register"]


def test_enable_accepts_cash_workflow_with_entry_and_two_protective_exits(control_env):
    env = control_env
    workflow = _control_workflow(env)
    nodes = deepcopy(workflow.nodes)
    entry = next(node for node in nodes if node["id"] == "run")
    entry["type"] = "strategySignal"
    entry["data"].update(action="long_entry", symbol="TEST", exchange="BSE")
    exits = [
        {**deepcopy(entry), "id": exit_id, "data": {**entry["data"], "action": "long_exit"}}
        for exit_id in ("stop-loss-exit", "target-exit")
    ]
    edges = [*workflow.edges,
             {"id": "exit-sl", "source": "trend5", "target": exits[0]["id"], "sourceHandle": "false"},
             {"id": "exit-target", "source": "trend15", "target": exits[1]["id"], "sourceHandle": "false"}]
    assert flow_db.update_workflow(workflow.id, nodes=[*nodes, *exits], edges=edges)

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert result.ok and result.state == "armed"
    assert _control_workflow(env).is_active is True
    assert _control_strategy(env).current_run_id is None
    assert env.calls == ["flow:register"]


def test_enable_already_armed_is_idempotent(control_env):
    env = control_env
    first = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")
    updated_at = _control_strategy(env).automation_state_updated_at

    second = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert first == second
    assert _control_strategy(env).automation_state_updated_at == updated_at
    assert env.calls == ["flow:register"]


def test_enable_arms_batch_workflow_without_starting_or_dispatching(control_env):
    env = control_env
    row = _control_strategy(env)
    row.strategy_kind = "batch"
    env.store.db_session.commit()

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert result.ok and result.state == "armed" and result.error is None
    assert result.workflow_id == env.workflow_id and result.run_id is None
    assert _control_strategy(env).automation_state == "armed"
    assert _control_strategy(env).current_run_id is None
    assert _control_workflow(env).is_active is True
    assert env.calls == ["flow:register"]


@pytest.mark.parametrize(
    "changes",
    [
        {"live_enabled": True},
        {"automation_state": "closing"},
        {"automation_state": "close_failed"},
        {"legs": []},
    ],
)
def test_enable_refuses_ineligible_strategy(control_env, changes):
    env = control_env
    row = _control_strategy(env)
    for name, value in changes.items():
        setattr(row, name, value)
    env.store.db_session.commit()

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert not result.ok and result.error
    assert _control_strategy(env).automation_state != "armed"
    assert _control_workflow(env).is_active is False
    assert env.calls == []


def test_enable_refuses_unknown_account_order(control_env):
    env = control_env
    run = env.store.create_run(env.strategy_id, "sandbox", "sandbox")
    env.store.record_order(
        run.id,
        1,
        "entry",
        {
            "symbol": "TEST",
            "exchange": "BSE",
            "action": "BUY",
            "qty": 1,
            "status": "unknown",
            "pricetype": "MARKET",
        },
    )

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert not result.ok and "outcome" in result.error.lower()
    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is False


@pytest.mark.parametrize("link_problem", ["missing", "ambiguous", "live", "invalid_graph"])
def test_enable_refuses_missing_ambiguous_or_invalid_workflow(control_env, link_problem):
    env = control_env
    wf = _control_workflow(env)
    if link_problem == "missing":
        flow_db.delete_workflow(wf.id)
    elif link_problem == "ambiguous":
        flow_db.create_workflow("Second explicit link", nodes=wf.nodes, edges=wf.edges)
    elif link_problem == "live":
        nodes = [
            dict(node, data={**node["data"], "mode": "live"})
            if node["type"] == "strategyModuleRun"
            else node
            for node in wf.nodes
        ]
        flow_db.update_workflow(wf.id, nodes=nodes)
    else:
        flow_db.update_workflow(wf.id, edges=[])

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert not result.ok and result.error
    assert _control_strategy(env).automation_state == "disabled"
    assert env.calls == []


def test_enable_activation_failure_rolls_back_workflow(control_env):
    env = control_env

    def broken_register(**kwargs):
        assert _control_workflow(env).is_active is True
        raise RuntimeError("trigger registration unavailable")

    env.scheduler.add_workflow_job = broken_register

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert not result.ok and "registration unavailable" in result.error
    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is False
    assert "flow:unregister" in env.calls


def test_enable_state_write_failure_compensates_activation(control_env, monkeypatch):
    env = control_env
    original = env.store.set_automation_state
    monkeypatch.setattr(
        env.store,
        "set_automation_state",
        lambda sid, owner, state, **kw: (
            (False, "state write failed") if state == "armed" else original(sid, owner, state, **kw)
        ),
    )

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert not result.ok and "state write failed" in result.error
    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is False
    assert env.calls == ["flow:register", "flow:unregister"]


def test_enable_failed_compensation_records_critical_inconsistency(control_env, monkeypatch):
    env = control_env
    monkeypatch.setattr(
        env.store, "set_automation_state", lambda *args, **kwargs: (False, "state write failed")
    )

    def broken_remove(*args, **kwargs):
        raise RuntimeError("jobstore unavailable")

    env.scheduler.remove_workflow_job = broken_remove

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert not result.ok and "inconsistent" in result.error.lower()
    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is True
    alerts = env.store.list_critical_alerts(env.owner, strategy_id=env.strategy_id)
    assert alerts and "inconsistent" in str(alerts[0]).lower()


def test_enable_wrong_owner_cannot_touch_strategy_or_flow(control_env):
    env = control_env

    result = automation_control.enable_sandbox(env.strategy_id, "somebody-else", "test-key")

    assert not result.ok and result.workflow_id is None and result.run_id is None
    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is False
    assert env.calls == []


def _armed_run(env, monkeypatch, *, outcome=None, finalise=False):
    from services.strategy_module import engine, state

    env.store.set_automation_state(env.strategy_id, env.owner, "armed")
    flow_db.activate_workflow(env.workflow_id, api_key="test-key")
    run = env.store.create_run(env.strategy_id, "sandbox", "sandbox")
    run_id = run.id
    env.store.set_strategy_status(env.strategy_id, "running", run_id)
    state.init_run_state(run_id, env.strategy_id, [])
    original = env.store.set_automation_state

    def persist(sid, owner, value, **kwargs):
        env.calls.append(f"persist:{value}")
        return original(sid, owner, value, **kwargs)

    def stop(rid, owner, reason="manual"):
        assert (rid, owner) == (run_id, env.owner)
        assert _control_strategy(env).automation_state == "closing"
        env.calls.append("engine.stop_run")
        if finalise:
            env.store.finish_run_and_release_strategy(run_id, env.strategy_id, "manual")
            state.clear_run_state(run_id)
        return outcome or {"ok": True, "stop_pending": not finalise, "exits": []}

    monkeypatch.setattr(env.store, "set_automation_state", persist)
    monkeypatch.setattr(engine, "stop_run", stop)
    return run_id


def test_disable_persists_closing_before_accepted_pending_stop(control_env, monkeypatch):
    env = control_env
    run_id = _armed_run(env, monkeypatch)

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert env.calls[:2] == ["persist:closing", "engine.stop_run"]
    assert result.ok and result.state == "closing" and result.close_pending
    assert result.run_id == run_id
    assert _control_strategy(env).automation_state == "closing"
    assert _control_workflow(env).is_active is True


def test_disable_flat_strategy_deactivates_before_disabled(control_env, monkeypatch):
    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "armed")
    flow_db.activate_workflow(env.workflow_id, api_key="test-key")
    original = env.store.set_automation_state

    def persist(sid, owner, value, **kwargs):
        if value == "disabled":
            assert _control_workflow(env).is_active is False
        env.calls.append(f"persist:{value}")
        return original(sid, owner, value, **kwargs)

    monkeypatch.setattr(env.store, "set_automation_state", persist)

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert result.ok and result.state == "disabled" and not result.close_pending
    assert env.calls == ["persist:closing", "flow:unregister", "persist:disabled"]
    assert _control_strategy(env).automation_state == "disabled"


def test_disable_requires_durable_stop_not_only_success_response(control_env, monkeypatch):
    env = control_env
    _armed_run(env, monkeypatch, outcome={"ok": True, "stop_pending": False, "exits": []})

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert result.state in {"closing", "close_failed"} and result.close_pending
    assert _control_workflow(env).is_active is True


def test_disable_durably_finished_run_completes(control_env, monkeypatch):
    env = control_env
    _armed_run(env, monkeypatch, finalise=True)

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert result.ok and result.state == "disabled" and not result.close_pending
    assert _control_workflow(env).is_active is False


@pytest.mark.parametrize(
    "outcome",
    [
        {"ok": False, "stop_pending": True, "error": "broker refused exit", "exits": []},
        {"ok": False, "stop_pending": True, "error": "unknown order outcome", "exits": []},
        {"ok": True, "stop_pending": True, "exits": [{"ok": False, "error": "exit rejected"}]},
    ],
)
def test_disable_exit_failure_stays_blocked_and_keeps_flow(control_env, monkeypatch, outcome):
    env = control_env
    _armed_run(env, monkeypatch, outcome=outcome)

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert not result.ok and result.state == "close_failed" and result.close_pending
    assert result.error
    assert _control_strategy(env).automation_state_reason == result.error
    assert _control_workflow(env).is_active is True
    assert env.store.list_critical_alerts(env.owner, strategy_id=env.strategy_id)


def test_disable_cannot_stop_before_closing_is_durable(control_env, monkeypatch):
    env = control_env
    _armed_run(env, monkeypatch)
    monkeypatch.setattr(
        env.store, "set_automation_state", lambda *args, **kwargs: (False, "state unavailable")
    )

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert not result.ok and "state unavailable" in result.error
    assert "engine.stop_run" not in env.calls
    assert _control_strategy(env).automation_state == "armed"
    assert _control_workflow(env).is_active is True


def test_disable_deactivation_failure_retains_close_failed(control_env):
    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "armed")
    flow_db.activate_workflow(env.workflow_id, api_key="test-key")

    def broken_remove(*args, **kwargs):
        raise RuntimeError("jobstore unavailable")

    env.scheduler.remove_workflow_job = broken_remove

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert not result.ok and result.state == "close_failed" and result.close_pending
    assert "jobstore unavailable" in result.error
    assert _control_workflow(env).is_active is True


def test_disable_missing_link_blocks_entries_before_reporting_error(control_env):
    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "armed")
    flow_db.delete_workflow(env.workflow_id)

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert not result.ok and result.state == "close_failed" and result.close_pending
    assert _control_strategy(env).automation_state == "close_failed"


def test_disable_wrong_owner_leaves_other_strategy_armed(control_env):
    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "armed")
    flow_db.activate_workflow(env.workflow_id, api_key="test-key")

    result = automation_control.disable_and_close(env.strategy_id, "somebody-else")

    assert not result.ok and result.workflow_id is None and result.run_id is None
    assert _control_strategy(env).automation_state == "armed"
    assert _control_workflow(env).is_active is True


def test_disable_stopped_run_with_residual_orders_remains_blocked(control_env):
    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "armed")
    flow_db.activate_workflow(env.workflow_id, api_key="test-key")
    run = env.store.create_run(env.strategy_id, "sandbox", "sandbox")
    order = env.store.record_order(
        run.id,
        1,
        "entry",
        {
            "symbol": "TEST",
            "exchange": "BSE",
            "action": "BUY",
            "qty": 1,
            "status": "complete",
            "pricetype": "MARKET",
            "position_ref": "held-position",
        },
    )
    env.store.update_order(order.id, status="complete", broker_order_id="held-entry", filled_qty=1)
    env.store.finish_run(run.id, "recovery_failed")

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert not result.ok and result.state == "close_failed" and result.close_pending
    assert _control_workflow(env).is_active is True


def test_control_recovery_finishes_closing_after_restart(control_env, monkeypatch):
    from services.strategy_module import recovery, state

    env = control_env
    rid = _armed_run(env, monkeypatch)
    env.store.set_automation_state(env.strategy_id, env.owner, "closing")
    state.clear_run_state(rid)

    results = recovery.recover_automation_controls(env.owner)

    assert len(results) == 1 and results[0].ok and results[0].state == "disabled"
    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is False


def test_control_recovery_pending_exits_keep_flow_and_entry_block(control_env, monkeypatch):
    from services.strategy_module import recovery

    env = control_env
    _armed_run(env, monkeypatch)
    env.store.set_automation_state(env.strategy_id, env.owner, "closing")

    results = recovery.recover_automation_controls(env.owner)

    assert len(results) == 1 and results[0].state == "closing" and results[0].close_pending
    assert _control_workflow(env).is_active is True
    assert env.calls.count("engine.stop_run") == 1


def test_control_recovery_repeated_failure_does_not_repeat_control_alert(control_env, monkeypatch):
    from services.strategy_module import recovery

    env = control_env
    _armed_run(
        env,
        monkeypatch,
        outcome={
            "ok": False,
            "stop_pending": True,
            "error": "broker refused exit",
            "exits": [],
        },
    )
    first = automation_control.disable_and_close(env.strategy_id, env.owner)
    alerts_before = env.store.list_critical_alerts(env.owner, strategy_id=env.strategy_id)

    recovered = recovery.recover_automation_controls(env.owner)

    assert recovered == [first]
    alerts_after = env.store.list_critical_alerts(env.owner, strategy_id=env.strategy_id)
    assert len(alerts_after) == len(alerts_before) == 1
    assert env.calls.count("engine.stop_run") == 2


def test_control_recovery_never_enables_disabled_or_foreign_strategy(control_env):
    from services.strategy_module import recovery

    env = control_env
    assert recovery.recover_automation_controls(env.owner) == []
    env.store.set_automation_state(env.strategy_id, env.owner, "closing")

    assert recovery.recover_automation_controls("somebody-else") == []
    assert _control_strategy(env).automation_state == "closing"
    assert _control_workflow(env).is_active is False


@pytest.mark.parametrize("new_state", ["armed", "closing"])
@pytest.mark.parametrize("lease_error", [False, True])
def test_delayed_control_recovery_cannot_close_a_new_automation_epoch(
    control_env, monkeypatch, new_state, lease_error
):
    """Recovery must recheck its exact durable snapshot after acquiring admission."""
    from services.strategy_module import engine, recovery, state

    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "closing")
    flow_db.activate_workflow(env.workflow_id, api_key="test-key")
    original_lease = automation_control._control_lease
    interleaved = []
    monkeypatch.setattr(engine, "_api_key_for", lambda owner: None)

    @contextmanager
    def complete_then_rearm_before_admission(owner):
        if not interleaved:
            interleaved.append(True)
            # This happens after recovery's enumeration, but before its lease
            # is acquired. Another worker finishes the old close; an operator
            # enables the next epoch and a signal starts its new run.
            closed = automation_control.disable_and_close(env.strategy_id, owner)
            assert closed.ok and closed.state == "disabled"
            assert automation_control.enable_sandbox(env.strategy_id, owner, "test-key").ok
            run_id = env.store.create_run(env.strategy_id, "sandbox", "sandbox").id
            env.store.set_strategy_status(env.strategy_id, "running", run_id)
            state.init_run_state(run_id, env.strategy_id, [])
            interleaved.append(run_id)
            if new_state == "closing":
                # Even the same state text is a different control request.
                env.store.set_automation_state(env.strategy_id, owner, "closing")
            if lease_error:
                raise RuntimeError("admission lease unavailable after the competing control")
        with original_lease(owner):
            yield

    monkeypatch.setattr(automation_control, "_control_lease", complete_then_rearm_before_admission)

    recovery.recover_automation_controls(env.owner)

    run_id = interleaved[1]
    assert _control_strategy(env).automation_state == new_state
    assert env.store.get_run(run_id).stopped_at is None
    assert env.store.get_run(run_id).stop_requested_reason is None
    assert _control_workflow(env).is_active is True

    # An explicit operator disable has no snapshot precondition.
    result = automation_control.disable_and_close(env.strategy_id, env.owner)
    assert result.ok and result.state == "disabled"
    assert env.store.get_run(run_id).stopped_at is not None


def test_boot_recovery_revisits_controls_even_without_open_runs(control_env):
    from services.strategy_module import recovery

    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "closing")
    flow_db.activate_workflow(env.workflow_id, api_key="test-key")

    recovery.recover_all()

    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is False


def test_shared_scheduler_reconciles_control_once_and_completes_after_flat(
    control_env, monkeypatch
):
    from services.strategy_module import scheduler

    env = control_env
    rid = _armed_run(env, monkeypatch, finalise=True)
    env.store.set_automation_state(env.strategy_id, env.owner, "closing")
    env.store.request_run_stop(rid, "manual")

    scheduler.reconcile_pending_stops()

    assert env.calls.count("engine.stop_run") == 1
    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is False


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_individual_control_refuses_shared_workflow(control_env, action):
    env = control_env
    wf = _control_workflow(env)
    extra = {
        "id": "other-run",
        "type": "strategyModuleRun",
        "data": {
            **next(node["data"] for node in wf.nodes if node["type"] == "strategyModuleRun"),
            "strategyId": env.strategy_id + 10000,
        },
    }
    flow_db.update_workflow(wf.id, nodes=[*wf.nodes, extra], is_active=True)
    env.store.set_automation_state(env.strategy_id, env.owner, "armed")

    result = (
        automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")
        if action == "enable"
        else automation_control.disable_and_close(env.strategy_id, env.owner)
    )

    assert not result.ok and "shared" in result.error.lower()
    assert _control_strategy(env).automation_state != "armed"
    assert _control_workflow(env).is_active is True
    assert env.calls == []


def test_disable_restores_inactive_flow_while_exit_is_pending(control_env, monkeypatch):
    from services.strategy_module import engine

    env = control_env
    _armed_run(env, monkeypatch)
    flow_db.deactivate_workflow(env.workflow_id)
    monkeypatch.setattr(engine, "_api_key_for", lambda owner: "test-key")

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert result.ok and result.state == "closing" and result.close_pending
    assert _control_workflow(env).is_active is True


def test_enable_does_not_rearm_stopped_run_with_residual_exposure(control_env):
    env = control_env
    run = env.store.create_run(env.strategy_id, "sandbox", "sandbox")
    order = env.store.record_order(
        run.id,
        1,
        "entry",
        {
            "symbol": "TEST",
            "exchange": "BSE",
            "action": "BUY",
            "qty": 1,
            "status": "complete",
            "pricetype": "MARKET",
            "position_ref": "orphaned-position",
        },
    )
    env.store.update_order(
        order.id, status="complete", broker_order_id="residual-entry", filled_qty=1
    )
    env.store.finish_run(run.id, "recovery_failed")

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert not result.ok and result.error
    assert _control_strategy(env).automation_state == "disabled"
    assert _control_workflow(env).is_active is False


def test_enable_failure_reports_actual_state_if_gate_write_fails(control_env, monkeypatch):
    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "armed")
    flow_db.delete_workflow(env.workflow_id)
    monkeypatch.setattr(
        env.store, "set_automation_state", lambda *args, **kwargs: (False, "gate unavailable")
    )

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert not result.ok and result.state == "armed"
    assert "gate unavailable" in result.error


def test_disable_does_not_activate_inactive_flow_after_run_finishes(control_env, monkeypatch):
    from services.strategy_module import engine

    env = control_env
    _armed_run(env, monkeypatch, finalise=True)
    flow_db.deactivate_workflow(env.workflow_id)
    monkeypatch.setattr(engine, "_api_key_for", lambda owner: None)

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert result.ok and result.state == "disabled"
    assert _control_workflow(env).is_active is False
    assert "flow:register" not in env.calls


def test_enable_blocks_entries_while_repairing_armed_but_inactive_flow(control_env):
    env = control_env
    env.store.set_automation_state(env.strategy_id, env.owner, "armed")
    original = env.scheduler.add_workflow_job

    def register(**kwargs):
        allowed, _ = automation_control.require_automation_entry(env.strategy_id, env.owner)
        assert allowed is False, "A trigger must not enter before activation verification"
        return original(**kwargs)

    env.scheduler.add_workflow_job = register

    result = automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")

    assert result.ok and result.state == "armed"
    assert _control_workflow(env).is_active is True


@pytest.fixture
def control_flow_app(monkeypatch):
    """Exercise the real Flow mutation routes with only session auth bypassed."""
    from flask import Flask

    import blueprints.flow as flow_routes
    import utils.session as session_utils

    monkeypatch.setattr(session_utils, "is_session_valid", lambda: True)
    monkeypatch.setattr(flow_routes, "get_current_api_key", lambda: "test-key")
    app = Flask(__name__)
    app.secret_key = "control-flow-tests"
    app.config["TESTING"] = True
    app.register_blueprint(flow_routes.flow_bp)
    app.teardown_appcontext(lambda error: flow_db.db_session.remove())
    return app


def _shared_control_graph(env):
    workflow = _control_workflow(env)
    nodes, edges = deepcopy(workflow.nodes), deepcopy(workflow.edges)
    run = next(node for node in nodes if node["type"] == "strategyModuleRun")
    extra = {**deepcopy(run), "id": "other-strategy-run"}
    extra["data"]["strategyId"] = env.strategy_id + 10000
    incoming = next(edge for edge in edges if edge["target"] == run["id"])
    return {
        "name": workflow.name,
        "nodes": [*nodes, extra],
        "edges": [*edges, {**incoming, "id": "other-strategy-edge", "target": extra["id"]}],
    }


def _edit_control_flow(app, env, graph, mutation):
    try:
        if mutation == "storage":
            workflow = flow_db.update_workflow(env.workflow_id, **graph)
            assert workflow is not None
            return {"is_active": workflow.is_active}
        with app.test_client() as client:
            response = (
                client.put(f"/flow/api/workflows/{env.workflow_id}", json=graph)
                if mutation == "put"
                else client.post(f"/flow/api/workflows/{env.workflow_id}/replace", json=graph)
            )
            assert response.status_code == 200, response.get_json()
            return response.get_json()
    finally:
        flow_db.db_session.remove()


@pytest.mark.parametrize("mutation", ["put", "replace"])
def test_flow_edit_during_stop_preserves_the_newly_shared_exit_path(
    control_env, control_flow_app, monkeypatch, mutation
):
    from services.strategy_module import engine

    env = control_env
    _armed_run(env, monkeypatch, finalise=True)
    graph = _shared_control_graph(env)
    original_stop = engine.stop_run

    def stop_then_edit(*args, **kwargs):
        outcome = original_stop(*args, **kwargs)
        _edit_control_flow(control_flow_app, env, graph, mutation)
        return outcome

    monkeypatch.setattr(engine, "stop_run", stop_then_edit)

    result = automation_control.disable_and_close(env.strategy_id, env.owner)

    assert not result.ok and "shared" in result.error.lower()
    assert result.state == "close_failed"
    assert _control_workflow(env).is_active is True
    assert "flow:unregister" not in env.calls


@pytest.mark.parametrize("action", ["enable", "disable", "flow_activate", "flow_deactivate"])
@pytest.mark.parametrize("mutation", ["put", "replace", "storage"])
def test_flow_edit_waits_for_lifecycle_finalization(
    control_env, control_flow_app, action, mutation
):
    """A graph cannot add an exit owner between exclusivity check and teardown."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from services import flow_lifecycle_service as lifecycle

    env = control_env
    activating = action in {"enable", "flow_activate"}
    if not activating:
        env.store.set_automation_state(env.strategy_id, env.owner, "armed")
        flow_db.activate_workflow(env.workflow_id, api_key="test-key")
    graph = _shared_control_graph(env)
    at_trigger_boundary, resume = Event(), Event()
    edit_started, edit_finished = Event(), Event()
    original_trigger = (
        env.scheduler.add_workflow_job if activating else env.scheduler.remove_workflow_job
    )

    def pause_trigger(*args, **kwargs):
        at_trigger_boundary.set()
        assert resume.wait(5), "test did not resume the lifecycle boundary"
        return original_trigger(*args, **kwargs)

    if activating:
        env.scheduler.add_workflow_job = pause_trigger
    else:
        env.scheduler.remove_workflow_job = pause_trigger

    def control():
        try:
            if action == "enable":
                return automation_control.enable_sandbox(env.strategy_id, env.owner, "test-key")
            if action == "disable":
                return automation_control.disable_and_close(env.strategy_id, env.owner)
            if action == "flow_activate":
                return lifecycle.activate_workflow(env.workflow_id, "test-key")
            return lifecycle.deactivate_workflow(env.workflow_id)
        finally:
            env.store.db_session.remove()
            flow_db.db_session.remove()

    def edit():
        edit_started.set()
        try:
            return _edit_control_flow(control_flow_app, env, graph, mutation)
        finally:
            edit_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        closing = pool.submit(control)
        assert at_trigger_boundary.wait(5)
        editing = pool.submit(edit)
        try:
            assert edit_started.wait(5)
            assert not edit_finished.wait(0.15), "Graph mutation overtook lifecycle finalization"
            assert all(node["id"] != "other-strategy-run" for node in _control_workflow(env).nodes)
        finally:
            resume.set()
        result = closing.result(timeout=5)
        edited = editing.result(timeout=5)

    if action.startswith("flow_"):
        assert result[1] == 200, result
    else:
        assert result.ok, result.error
    assert any(node["id"] == "other-strategy-run" for node in _control_workflow(env).nodes)
    assert _control_workflow(env).is_active is activating
    if mutation != "replace":
        assert edited["is_active"] is activating


def _edit_flow_in_another_process(connection, workflow_id):
    """Spawn target; no inherited thread lock or production scheduler is used."""
    from database import flow_db as child_store

    connection.send("attempting mutation")
    try:
        workflow = child_store.update_workflow(workflow_id, name="Cross-worker edit")
        connection.send(workflow.name if workflow is not None else None)
    finally:
        child_store.db_session.remove()
        connection.close()


def test_flow_mutation_lease_serializes_another_worker_process(control_env):
    import multiprocessing

    env = control_env
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_edit_flow_in_another_process, args=(child, env.workflow_id))
    try:
        with flow_db.workflow_mutation_lease(env.workflow_id):
            process.start()
            assert parent.poll(5)
            assert parent.recv() == "attempting mutation"
            assert not parent.poll(0.15), "A separate worker bypassed the workflow lease"
            assert _control_workflow(env).name == "Control test Workflow"
        assert parent.poll(5)
        assert parent.recv() == "Cross-worker edit"
        process.join(timeout=5)
        assert process.exitcode == 0
        assert _control_workflow(env).name == "Cross-worker edit"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent.close()
        child.close()
