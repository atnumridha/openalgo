"""Fresh identities for prospective paper evidence and live-release checks."""

import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.research.dataset import digest
from services.risk.budget import BudgetPolicy

_RUNTIME = frozenset(
    {
        "name",
        "status",
        "current_run_id",
        "created_at",
        "updated_at",
        "live_enabled",
        "automation_state",
        "automation_state_reason",
        "automation_state_updated_at",
        "user_id",
    }
)


def strategy_digest(strategy):
    return digest({key: value for key, value in strategy.items() if key not in _RUNTIME})


def workflow_digest(workflows):
    graphs = []
    for workflow in workflows:
        nodes = []
        for node in workflow.nodes:
            data = deepcopy(node.get("data", {}))
            if node["type"] in {"strategyModuleRun", "strategySignal"}:
                # This operational switch is separately authorized at dispatch.
                data.pop("mode", None)
            nodes.append({"id": node.get("id"), "type": node["type"], "data": data})
        edges = [
            {
                key: value
                for key, value in edge.items()
                if key not in {"selected", "style", "animated", "label"}
            }
            for edge in workflow.edges
        ]
        graphs.append(
            {
                "id": workflow.id,
                "broker_connection_id": workflow.broker_connection_id,
                "nodes": sorted(nodes, key=lambda n: str(n["id"])),
                "edges": sorted(edges, key=lambda e: str(e.get("id", ""))),
            }
        )
    return digest(sorted(graphs, key=lambda graph: graph["id"]))


def _read_strategy(owner, strategy_id):
    from database import strategy_module_db as store

    with Session(store.engine) as db:
        row = db.scalar(
            select(store.SmStrategy).where(
                store.SmStrategy.id == strategy_id, store.SmStrategy.user_id == owner
            )
        )
        if row is None:
            raise LookupError("Strategy not found")
        return store.strategy_to_dict(row)


def _read_workflows(owner, strategy):
    from database import flow_db
    from services.strategy_module.workflow_link import validate_workflow_link

    with Session(flow_db.engine) as db:
        rows = list(db.scalars(select(flow_db.FlowWorkflow).limit(10001)))
        if len(rows) > 10000:
            raise ValueError("Workflow inventory exceeds the qualification bound")
        linked = [
            row
            for row in rows
            if any(
                isinstance(node, dict)
                and node.get("type") in {"strategyModuleRun", "strategySignal"}
                and isinstance(node.get("data"), dict)
                and node["data"].get("strategyId") == strategy["id"]
                for node in row.nodes or []
            )
        ]
        link, error = validate_workflow_link(
            SimpleNamespace(**strategy, user_id=owner), linked, require_sandbox=False
        )
        if error:
            raise ValueError(error)
        return [
            SimpleNamespace(
                id=row.id,
                nodes=deepcopy(row.nodes),
                edges=deepcopy(row.edges),
                broker_connection_id=row.broker_connection_id,
                is_active=row.is_active,
            )
            for row in linked
        ]


def _broker_identity(owner, connection_id):
    from database import auth_db

    if not connection_id:
        raise ValueError("Qualification requires a pinned broker connection")
    with auth_db.engine.connect() as db:
        pin = (
            db.execute(
                text(
                    "SELECT bc.id,bc.broker FROM broker_connections bc JOIN api_keys ak "
                    "ON ak.broker_connection_id=bc.id AND ak.user_id=bc.user_id "
                    "WHERE bc.id=:pin AND bc.user_id=:owner AND bc.is_revoked=0 "
                    "AND bc.status IN ('connected','authenticated')"
                ),
                {"pin": connection_id, "owner": owner},
            )
            .mappings()
            .first()
        )
    with Session(auth_db.engine) as db:
        auth = db.scalar(select(auth_db.Auth).where(auth_db.Auth.name == owner))
        if (
            not pin
            or auth is None
            or auth.is_revoked
            or auth.broker.lower() != pin["broker"].lower()
        ):
            raise ValueError("The active authenticated broker does not match the pinned account")
        # Ciphertext changes on an unchanged login; hash the material token,
        # never store/return it. Broker user identity prevents account swapping.
        token = auth_db.decrypt_token(auth.auth)
        if not token:
            raise ValueError("An authenticated broker session is required")
        account = auth.user_id
        if not isinstance(account, str) or not account.strip():
            raise ValueError("The saved broker session has no account identity; authenticate again")
        if auth.broker.lower() == "kotak":
            # The login callback persists the UCC alongside its token. A later
            # config edit must not relabel old quotes as another account.
            from utils.config import get_broker_api_key

            if account != get_broker_api_key():
                raise ValueError("The configured Kotak account changed; authenticate again")
        account_hash = digest(
            {"connection": connection_id, "broker": auth.broker.lower(), "account": account.strip()}
        )
        epoch = digest({"account": account_hash, "token": token})
    return {
        "broker_connection_id": str(connection_id),
        "broker": pin["broker"].lower(),
        "broker_account_hash": account_hash,
        "broker_epoch": epoch,
    }


def _risk_context(owner):
    from database import trading_risk_db as ledger
    from services.research.costs import validate_cost_dates, validate_cost_schedule
    from services.strategy_module.trading_budget import trading_day

    if not ledger.policy_enabled(owner):
        raise ValueError("Enable the capital profile with a verified cost schedule first")
    costs = validate_cost_schedule(ledger.get_costs(owner))
    validate_cost_dates(costs, [trading_day()])
    paused = any(
        ledger.status(owner, mode, trading_day())["paused"] for mode in ("sandbox", "live")
    )
    return {"costs": costs, "paused": paused}


def _source_hash():
    root = Path(__file__).resolve().parents[2]
    paths = [
        *sorted((root / "services/research").glob("*.py")),
        *sorted((root / "services/risk").glob("*.py")),
        *sorted((root / "services/strategy_module").glob("*.py")),
        root / "services/flow_executor_service.py",
        root / "database/strategy_qualification_db.py",
        root / "database/trading_risk_db.py",
        root / "blueprints/brlogin.py",
        root / "database/auth_db.py",
    ]
    h = hashlib.sha256()
    for path in paths:
        h.update(str(path.relative_to(root)).encode())
        with path.open("rb") as source:
            h.update(source.read())
    return h.hexdigest()


def current_binding(owner, strategy_id, strategy_config=None, costs=None):
    if type(strategy_id) is not int or strategy_id <= 0 or not owner:
        raise ValueError("A strategy owned by the current user is required")
    strategy = _read_strategy(owner, strategy_id)
    if strategy_config is not None:
        from dataclasses import asdict, is_dataclass
        from datetime import time
        from decimal import Decimal

        proposed = (
            strategy_config
            if isinstance(strategy_config, dict)
            else asdict(strategy_config)
            if is_dataclass(strategy_config)
            else vars(strategy_config)
        )

        def normal(value):
            if isinstance(value, Decimal):
                return float(value)
            if isinstance(value, time):
                return value.strftime("%H:%M")
            if isinstance(value, dict):
                return {k: normal(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [normal(v) for v in value]
            return value

        for key, value in proposed.items():
            if key not in _RUNTIME and key in strategy and normal(value) != normal(strategy[key]):
                raise ValueError("Strategy configuration changed after admission")
    workflows = _read_workflows(owner, strategy)
    broker = _broker_identity(owner, strategy.get("broker_connection_id"))
    risk = _risk_context(owner)
    if costs is not None and digest(costs) != digest(risk["costs"]):
        raise ValueError("Cost schedule changed after admission")
    binding = {
        "strategy_id": strategy_id,
        "strategy_hash": strategy_digest(strategy),
        "workflow_hash": workflow_digest(workflows),
        "source_hash": _source_hash(),
        "cost_hash": digest(risk["costs"]),
        "risk_policy_version": BudgetPolicy().version,
        **{key: value for key, value in broker.items() if key != "broker_epoch"},
    }
    from services.research.qualification_execution import current_flow_origin

    origin = current_flow_origin()
    if origin and (
        origin["workflow_hash"] != binding["workflow_hash"]
        or origin["workflow_id"] != workflows[0].id
    ):
        raise ValueError("The running Flow graph differs from the enrolled graph")
    return {
        **binding,
        "workflow_id": workflows[0].id,
        "entry_origin": origin,
        "binding_hash": digest(binding),
        "broker_epoch": broker["broker_epoch"],
        "costs": risk["costs"],
        "risk_paused": risk["paused"],
    }
