"""Completed-candle Flow graphs for sandbox batch and signal starters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowInstallResult:
    created: tuple[dict, ...]
    existing: tuple[dict, ...]


WORKFLOW_SPECS = (
    ("NIFTY 5/15-Minute Trend Signal Receiver", "NIFTY", "NSE_INDEX", "standard"),
    ("NIFTY Breakout and Retest Signal Receiver", "NIFTY", "NSE_INDEX", "standard"),
    ("NIFTY Long-Option Momentum Signal Receiver", "NIFTY", "NSE_INDEX", "standard"),
    ("SENSEX 5/15-Minute Trend Signal Receiver", "SENSEX", "BSE_INDEX", "standard"),
    ("SENSEX Breakout and Retest Signal Receiver", "SENSEX", "BSE_INDEX", "standard"),
    ("GOLDM Momentum and Breakout Signal Receiver", "GOLDM", "MCX", "standard"),
    ("CRUDEOILM Momentum and Breakout Signal Receiver", "CRUDEOILM", "MCX", "standard"),
    ("SILVERM Momentum and Breakout Signal Receiver", "SILVERM", "MCX", "high_volatility"),
    (
        "NATGASMINI Momentum and Breakout Signal Receiver",
        "NATGASMINI",
        "MCX",
        "high_volatility",
    ),
    ("NIFTY 50 Cash Momentum Signal Receiver", "RELIANCE", "NSE", "standard"),
    ("Cash Support Mean-Reversion Signal Receiver", "HDFCBANK", "NSE", "standard"),
    ("Opening-Range Breakout Signal Receiver", "ICICIBANK", "NSE", "standard"),
)

SIGNAL_WORKFLOW_NAMES = frozenset({
    "NIFTY 50 Cash Momentum Signal Receiver",
    "Cash Support Mean-Reversion Signal Receiver",
    "Opening-Range Breakout Signal Receiver",
})


def _node(node_id: str, node_type: str, x: int, y: int, **data) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": x, "y": y},
        "data": data,
    }


def _edge(edge_id: str, source: str, target: str, **fields) -> dict:
    return {"id": edge_id, "source": source, "target": target, **fields}


def _definition(
    strategy_name: str,
    strategy_id: int,
    underlying: str,
    exchange: str,
    risk_profile: str,
    broker_owner: str,
) -> dict:
    market_hours_exchange = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange, exchange)
    signal = strategy_name in SIGNAL_WORKFLOW_NAMES
    nodes = [
        _node(
            "start",
            "start",
            280,
            20,
            label="Every completed 5-minute candle",
            scheduleType="interval",
            intervalValue=5,
            intervalUnit="minutes",
            marketHoursOnly=True,
            marketHoursExchange=market_hours_exchange,
        ),
        _node(
            "bar5_current",
            "barOffset",
            40,
            150,
            symbol=underlying,
            exchange=exchange,
            interval="5m",
            source="api",
            offsetBars=0,
            outputVariable="bar5Current",
        ),
        _node(
            "bar5_previous",
            "barOffset",
            40,
            270,
            symbol=underlying,
            exchange=exchange,
            interval="5m",
            source="api",
            offsetBars=1,
            outputVariable="bar5Previous",
        ),
        _node(
            "trend5",
            "varCondition",
            40,
            390,
            leftValue="{{bar5Current.close}}",
            operator=">",
            rightValue="{{bar5Previous.high}}",
        ),
        _node(
            "bar15_current",
            "barOffset",
            500,
            150,
            symbol=underlying,
            exchange=exchange,
            interval="15m",
            source="api",
            offsetBars=0,
            outputVariable="bar15Current",
        ),
        _node(
            "bar15_previous",
            "barOffset",
            500,
            270,
            symbol=underlying,
            exchange=exchange,
            interval="15m",
            source="api",
            offsetBars=1,
            outputVariable="bar15Previous",
        ),
        _node(
            "trend15",
            "varCondition",
            500,
            390,
            leftValue="{{bar15Current.close}}",
            operator=">",
            rightValue="{{bar15Previous.close}}",
        ),
        _node("confirm", "andGate", 280, 520, inputCount=2),
        _node(
            "run",
            "strategySignal" if signal else "strategyModuleRun",
            280,
            650,
            strategyId=int(strategy_id),
            brokerOwner=broker_owner,
            mode="sandbox",
            outputVariable="strategyRun",
            marketHoursExchange=market_hours_exchange,
            barEvidence={
                "5m": ["bar5Current", "bar5Previous"],
                "15m": ["bar15Current", "bar15Previous"],
            },
            **({"action": "long_entry", "symbol": underlying, "exchange": exchange} if signal else {}),
        ),
    ]
    edges = [
        _edge("e1", "start", "bar5_current"),
        _edge("e2", "bar5_current", "bar5_previous"),
        _edge("e3", "bar5_previous", "trend5"),
        _edge("e4", "start", "bar15_current"),
        _edge("e5", "bar15_current", "bar15_previous"),
        _edge("e6", "bar15_previous", "trend15"),
        _edge("e7", "trend5", "confirm", sourceHandle="true", targetHandle="input-0"),
        _edge("e8", "trend15", "confirm", sourceHandle="true", targetHandle="input-1"),
        _edge("e9", "confirm", "run", sourceHandle="true"),
    ]
    return {
        "name": f"{strategy_name} Workflow",
        "description": (
            f"Sandbox-only intraday {underlying} workflow. Uses completed 5-minute and "
            "15-minute confirmation and delegates execution to Strategy Module controls."
        ),
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "starter_pack": "sensex_mcx_intraday_v1",
            "strategy_name": strategy_name,
            "strategy_id": int(strategy_id),
            "underlying": underlying,
            "exchange": exchange,
            "risk_profile": risk_profile,
            "mode": "sandbox",
        },
    }


def workflow_definitions(strategy_ids: Mapping[str, int], broker_owner: str) -> tuple[dict, ...]:
    """Build graphs only for strategies whose durable ids are known."""
    return tuple(
        _definition(name, strategy_ids[name], underlying, exchange, risk_profile, broker_owner)
        for name, underlying, exchange, risk_profile in WORKFLOW_SPECS
        if name in strategy_ids
    )


def _matches_starter_graph(current: object, definition: dict) -> bool:
    """Only upgrade bar guards on known graphs, preserving customized ones."""
    nodes = getattr(current, "nodes", None) or []
    if getattr(current, "edges", None) != definition["edges"]:
        return False
    expected = {node["id"]: node for node in definition["nodes"]}
    if len(nodes) != len(expected) or {node.get("id") for node in nodes} != set(expected):
        return False
    for node in nodes:
        wanted = expected[node["id"]]
        if node.get("type") != wanted["type"]:
            return False
        actual_data = dict(node.get("data") or {})
        wanted_data = dict(wanted["data"])
        if node["id"] == "start":
            if (
                "marketHoursExchange" in actual_data
                and actual_data["marketHoursExchange"] != wanted_data["marketHoursExchange"]
            ):
                return False
            actual_data.pop("marketHoursExchange", None)
            wanted_data.pop("marketHoursExchange", None)
        if node["id"] == "run":
            if "barEvidence" in actual_data and actual_data["barEvidence"] != wanted_data["barEvidence"]:
                return False
            if (
                "marketHoursExchange" in actual_data
                and actual_data["marketHoursExchange"] != wanted_data["marketHoursExchange"]
            ):
                return False
            actual_data.pop("barEvidence", None)
            wanted_data.pop("barEvidence", None)
            actual_data.pop("marketHoursExchange", None)
            wanted_data.pop("marketHoursExchange", None)
        if actual_data != wanted_data:
            return False
    return True


def install(
    strategy_ids: Mapping[str, int],
    broker_owner: str,
    broker_connection_ids: Mapping[str, str | None] | None = None,
) -> WorkflowInstallResult:
    """Create only missing Flow rows; activation remains an explicit step."""
    from database.flow_db import create_workflow, get_all_workflows, update_workflow
    from services.flow_workflow_validator import validate_workflow

    existing_by_name = {row.name: row for row in get_all_workflows()}
    created: list[dict] = []
    existing: list[dict] = []
    connection_ids = broker_connection_ids or {}
    for definition in workflow_definitions(strategy_ids, broker_owner):
        strategy_name = definition["metadata"]["strategy_name"]
        connection_id = connection_ids.get(strategy_name)
        current = existing_by_name.get(definition["name"])
        if current is not None:
            nodes = [dict(node, data=dict(node.get("data") or {})) for node in current.nodes]
            changed = False
            if _matches_starter_graph(current, definition):
                start = next((node for node in nodes if node.get("type") == "start"), None)
                expected_calendar = next(
                    node["data"]["marketHoursExchange"]
                    for node in definition["nodes"]
                    if node.get("type") == "start"
                )
                if start is not None and start["data"].get("marketHoursExchange") != expected_calendar:
                    start["data"]["marketHoursExchange"] = expected_calendar
                    changed = True
                run = next((node for node in nodes if node.get("id") == "run"), None)
                if run is not None:
                    expected_run = next(node for node in definition["nodes"] if node["id"] == "run")
                    for field in ("barEvidence", "marketHoursExchange"):
                        if run["data"].get(field) != expected_run["data"][field]:
                            run["data"][field] = expected_run["data"][field]
                            changed = True
            updates = {}
            if changed:
                updates["nodes"] = nodes
            if (
                connection_id is not None
                and getattr(current, "broker_connection_id", None) is None
                and _matches_starter_graph(current, definition)
            ):
                updates["broker_connection_id"] = connection_id
            if updates:
                update_workflow(int(current.id), **updates)
            existing.append(
                {"id": int(current.id), "name": current.name, "is_active": bool(current.is_active)}
            )
            continue
        errors = validate_workflow(definition, strict=True)
        if errors:
            raise RuntimeError(
                f"Starter workflow {definition['name']!r} is invalid: {errors[0]['message']}"
            )
        row = create_workflow(
            name=definition["name"],
            description=definition["description"],
            nodes=definition["nodes"],
            edges=definition["edges"],
            broker_connection_id=connection_id,
        )
        if row is None:
            raise RuntimeError(f"Could not install starter workflow {definition['name']!r}")
        created.append({"id": int(row.id), "name": row.name, "is_active": False})
        existing_by_name[row.name] = row
    return WorkflowInstallResult(tuple(created), tuple(existing))
