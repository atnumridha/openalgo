"""Optional earlier presets: listing never installs or activates a strategy."""

from __future__ import annotations

from types import SimpleNamespace

from database import flow_db
from database import strategy_module_db as store
from services.strategy_module import starter_pack, starter_workflows

TEMPLATES = {
    "nifty-trend": "NIFTY 5/15-Minute Trend Signal Receiver",
    "nifty-retest": "NIFTY Breakout and Retest Signal Receiver",
    "nifty-momentum": "NIFTY Long-Option Momentum Signal Receiver",
    "sensex-trend": "SENSEX 5/15-Minute Trend Signal Receiver",
    "sensex-retest": "SENSEX Breakout and Retest Signal Receiver",
    "goldm-momentum": "GOLDM Momentum and Breakout Signal Receiver",
    "crudeoilm-momentum": "CRUDEOILM Momentum and Breakout Signal Receiver",
    "silverm-momentum": "SILVERM Momentum and Breakout Signal Receiver",
    "natgasmini-momentum": "NATGASMINI Momentum and Breakout Signal Receiver",
}


def catalog(owner):
    from services.strategy_module.workflow_link import validate_workflow_link

    definitions = {row["name"]: row for row in starter_pack.starter_definitions()}
    installed = {row["name"]: row for row in store.list_strategies(owner)}
    items = []
    for key, name in TEMPLATES.items():
        row = installed.get(name)
        complete = False
        if row is not None:
            linked = flow_db.get_workflows_for_strategy(row["id"], strict=True)
            link, error = validate_workflow_link(
                SimpleNamespace(**row, user_id=owner), linked, require_sandbox=False
            )
            complete = link is not None and error is None
        items.append(
            {
                "id": key,
                "name": name,
                "underlying": definitions[name]["underlying"],
                "installed_strategy_id": row["id"] if complete else None,
                "installation_pending": row is not None and not complete,
            }
        )
    return items


def install(owner, template_id):
    from blueprints.strategy_module import validate_strategy_config
    from services.flow_workflow_validator import validate_workflow
    from services.strategy_module.automation_control import _control_lease
    from services.strategy_module.scalping_pack import _connection_for_owner
    from services.strategy_module.workflow_link import validate_workflow_link

    if template_id not in TEMPLATES:
        raise ValueError("Unknown strategy template")
    name = TEMPLATES[template_id]
    # Serialize same-owner installs and graph changes, including retry after a
    # failed Flow write. Never reuse another owner's Flow by its display name.
    with _control_lease(owner), flow_db.flow_link_mutation_lease():
        rows = store.list_strategies(owner)
        row = next((r for r in rows if r["name"] == name), None)
        created = False
        if row is None:
            definition = next(r for r in starter_pack.starter_definitions() if r["name"] == name)
            definition["broker_connection_id"] = _connection_for_owner(owner, rows)
            config, error = validate_strategy_config(definition)
            if error:
                raise ValueError(error)
            row, error = store.create_strategy(owner, config)
            if row is None:
                raise RuntimeError(error or "Could not install strategy template")
            row.pop("webhook_token", None)
            created = True
        linked = flow_db.get_workflows_for_strategy(row["id"], strict=True)
        if linked:
            link, error = validate_workflow_link(
                SimpleNamespace(**row, user_id=owner), linked, require_sandbox=False
            )
            if error:
                raise ValueError(error)
            return {"created": created, "strategy_id": row["id"], "workflow_id": link.workflow_id}
        if (
            row["status"] != "stopped"
            or row["automation_state"] != "disabled"
            or row["live_enabled"]
        ):
            raise ValueError("Stop this strategy and select sandbox before adding its Flow")
        graph = starter_workflows.workflow_definitions({name: row["id"]}, owner)[0]
        errors = validate_workflow(graph, strict=True)
        if errors:
            raise ValueError("Template Flow is invalid")
        flow = flow_db.create_workflow(
            name=graph["name"],
            description=graph["description"],
            nodes=graph["nodes"],
            edges=graph["edges"],
            broker_connection_id=row["broker_connection_id"],
        )
        if flow is None:
            raise RuntimeError("Strategy saved but Flow could not be created; retry installation")
        return {"created": created, "strategy_id": row["id"], "workflow_id": flow.id}
