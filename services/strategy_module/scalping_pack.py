"""Idempotent installation of three stopped, broker-pinned scalping strategies."""

from services.strategy_module.scalping import PROFILES, TOP_PROFILES
from services.strategy_module.starter_pack import _option_definition


def definitions():
    rows = []
    for profile in TOP_PROFILES:
        name = PROFILES[profile]
        row = _option_definition(
            name, "CE", entry_time="09:30" if profile == "box15" else "09:35", exit_time="15:20"
        )
        row.update(scalp_profile=profile, overall_target_mtm=None, daily_loss_limit_inr=2000)
        row["legs"][0].update(
            atm_offset="ITM1" if profile == "ema915" else "ATM",
            sl_pts=10 if profile == "box15" else 20,
            target_pts=20 if profile == "box15" else None,
        )
        rows.append(row)
    return rows


def workflow_definition(strategy, strategy_id, owner, connection_id):
    return {
        "name": f"{strategy['name']} Workflow",
        "description": "Evaluate saved signals on completed candles with one-lot stops up to ₹300, a rising profit stop aiming for ₹900–₹1,500+, 5-minute cooldown and a 15-minute deadline. Start disabled; choose sandbox or live in Strategies.",
        "broker_connection_id": connection_id,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "position": {"x": 200, "y": 50},
                "data": {
                    "label": "Check completed candles every minute",
                    "scheduleType": "interval",
                    "intervalValue": 1,
                    "intervalUnit": "minutes",
                    "marketHoursOnly": True,
                    "marketHoursExchange": "NSE",
                },
            },
            {
                "id": "run",
                "type": "strategyModuleRun",
                "position": {"x": 200, "y": 230},
                "data": {
                    "strategyId": strategy_id,
                    "brokerOwner": owner,
                    "mode": "sandbox",
                    "marketHoursExchange": "NSE",
                    "outputVariable": "scalpResult",
                    "barEvidence": {"scalpProfile": strategy["scalp_profile"]},
                },
            },
        ],
        "edges": [{"id": "start-run", "source": "start", "target": "run"}],
    }


def _connection_for_owner(owner, rows):
    from sqlalchemy import text

    from database import auth_db

    pins = {r["broker_connection_id"] for r in rows if r.get("broker_connection_id")}
    with auth_db.engine.connect() as db:
        owned = {
            r[0]
            for r in db.execute(
                text("SELECT id FROM broker_connections WHERE user_id=:owner AND is_revoked=0"),
                {"owner": owner},
            )
        }
    pins &= owned
    if len(pins) != 1:
        pins = owned
    if len(pins) != 1:
        raise ValueError(
            "Exactly one saved broker connection is needed to install the scalping pack"
        )
    return next(iter(pins))


def install(owner):
    from services.strategy_module.automation_control import _control_lease

    with _control_lease(owner):
        return _install(owner)


def _install(owner):
    from blueprints.strategy_module import validate_strategy_config
    from database import flow_db
    from database import strategy_module_db as store
    from services.flow_workflow_validator import validate_workflow

    rows = store.list_strategies(owner)
    connection_id = _connection_for_owner(owner, rows)
    existing = {r["name"]: r for r in rows}
    created, retained, workflows = [], [], []
    for definition in definitions():
        definition["broker_connection_id"] = connection_id
        row = existing.get(definition["name"])
        if row is None:
            config, error = validate_strategy_config(definition)
            if error:
                raise ValueError(error)
            row, error = store.create_strategy(owner, config)
            if row is None:
                row = next(
                    (r for r in store.list_strategies(owner) if r["name"] == definition["name"]),
                    None,
                )
                if row is None:
                    raise ValueError(error or "Could not save scalping strategy")
                retained.append(row["id"])
            else:
                row.pop("webhook_token", None)
                created.append(row["id"])
        else:
            retained.append(row["id"])
        if (
            row.get("scalp_profile") != definition["scalp_profile"]
            or row.get("broker_connection_id") != connection_id
        ):
            raise ValueError(
                f"{definition['name']} already exists with different rules or broker; review it first"
            )
        linked = flow_db.get_workflows_for_strategy(row["id"])
        if linked:
            from types import SimpleNamespace

            from services.strategy_module.workflow_link import validate_workflow_link

            link, error = validate_workflow_link(
                SimpleNamespace(**row, user_id=owner), linked, require_sandbox=False
            )
            if error:
                raise ValueError(error)
            workflows.append(link.workflow_id)
            continue
        graph = workflow_definition(definition, row["id"], owner, connection_id)
        errors = validate_workflow(graph, strict=True)
        if errors:
            raise ValueError(f"Invalid scalping workflow: {errors}")
        workflow = flow_db.create_workflow(**graph)
        if workflow is None:
            raise ValueError("Could not create scalping workflow")
        workflows.append(workflow.id)
    return {"created": created, "existing": retained, "workflows": workflows}
