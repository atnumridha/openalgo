"""Explicit installation of a passing frozen ML model as a stopped Flow strategy."""

from types import SimpleNamespace

from database import flow_db
from database import strategy_module_db as strategies
from database.trading_research_db import get_store
from services.flow_workflow_validator import validate_workflow
from services.research.jobs import historical_ml_reason
from services.strategy_module.scalping_pack import _connection_for_owner, workflow_definition
from services.strategy_module.starter_pack import _option_definition
from services.strategy_module.workflow_link import validate_workflow_link


def install(owner, final_run_id):
    from blueprints.strategy_module import validate_strategy_config
    from services.strategy_module.automation_control import _control_lease

    if type(final_run_id) is not int or final_run_id <= 0:
        raise ValueError("Choose a completed frozen ML final run")
    store = get_store()
    final = store.get_run(owner, final_run_id)
    if final is None or final.get("parent_run_id") is None:
        raise ValueError("Frozen ML final run is unavailable")
    parent = store.get_run(owner, final["parent_run_id"])
    reason = historical_ml_reason(final, parent or {})
    if reason:
        raise ValueError(reason)
    source = store.get_dataset(owner, final["dataset_id"])
    if not source:
        raise ValueError("Frozen ML session rules are unavailable")
    metadata = source["metadata"]
    session_open, session_close = metadata["session_open"], metadata["session_close"]
    model_hash = final["report"]["ml"]["model_hash"]
    name = f"NIFTY Frozen ML Run {final_run_id}"
    with _control_lease(owner), flow_db.flow_link_mutation_lease():
        rows = strategies.list_strategies(owner)
        current = next((row for row in rows if row["name"] == name), None)
        created = False
        if current is None:
            definition = _option_definition(
                name, "CE", entry_time=session_open, exit_time=session_close
            )
            definition["broker_connection_id"] = _connection_for_owner(owner, rows)
            definition.update(overall_target_mtm=None, daily_loss_limit_inr=2000)
            base, error = validate_strategy_config(definition)
            if error:
                raise ValueError(error)
            base.update(
                scalp_profile="ml_forest", ml_final_run_id=final_run_id, ml_model_hash=model_hash
            )
            current, error = strategies.create_strategy(owner, base)
            if current is None:
                raise RuntimeError(error or "Could not save frozen ML strategy")
            current.pop("webhook_token", None)
            created = True
        if (
            current.get("ml_final_run_id") != final_run_id
            or current.get("ml_model_hash") != model_hash
            or current.get("scalp_profile") != "ml_forest"
        ):
            raise ValueError("Existing strategy name belongs to different ML rules")
        if current.get("entry_time") != session_open or current.get("exit_time") != session_close:
            raise ValueError(
                "Installed ML entry or square-off window differs from the evaluated session"
            )
        linked = flow_db.get_workflows_for_strategy(current["id"], strict=True)
        if linked:
            link, error = validate_workflow_link(
                SimpleNamespace(**current, user_id=owner), linked, require_sandbox=False
            )
            if error:
                raise ValueError(error)
            return {
                "created": created,
                "strategy_id": current["id"],
                "workflow_id": link.workflow_id,
                "model_hash": model_hash,
            }
        if (
            current["status"] != "stopped"
            or current["automation_state"] != "disabled"
            or current["live_enabled"]
        ):
            raise ValueError("Stop and disable this ML strategy before adding its Flow")
        graph = workflow_definition(current, current["id"], owner, current["broker_connection_id"])
        graph["description"] = (
            "Frozen model scores server-observed completed bars. Starts disabled for explicit Sandbox review."
        )
        errors = validate_workflow(graph, strict=True)
        if errors:
            raise ValueError(f"ML Flow is invalid: {errors}")
        flow = flow_db.create_workflow(
            name=graph["name"],
            description=graph["description"],
            nodes=graph["nodes"],
            edges=graph["edges"],
            broker_connection_id=current["broker_connection_id"],
        )
        if flow is None:
            raise RuntimeError(
                "ML strategy saved but Flow could not be created; retry installation"
            )
        return {
            "created": created,
            "strategy_id": current["id"],
            "workflow_id": flow.id,
            "model_hash": model_hash,
        }
