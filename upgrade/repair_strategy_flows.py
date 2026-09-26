"""Version-checked repair of the twelve installed intraday Flow graphs.

This migration is deliberately opt-in. ``plan`` changes only known node/edge
shapes and leaves all operator-tuned parameters and activation flags alone.
The CLI must back up the database and revalidate rows in one transaction before
applying any changes; an unfamiliar graph is reported, never overwritten.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class UnknownGraph(ValueError):
    """An installed graph has been customised beyond this migration's scope."""


BAR_IDS = ("repair-bar5-current", "repair-bar5-previous", "repair-bar15-current", "repair-bar15-previous")
BAR_VARIABLES = ("repairBar5Current", "repairBar5Previous", "repairBar15Current", "repairBar15Previous")
BAR_EVIDENCE = {"5m": list(BAR_VARIABLES[:2]), "15m": list(BAR_VARIABLES[2:])}
STARTER_EVIDENCE = {"5m": ["bar5Current", "bar5Previous"], "15m": ["bar15Current", "bar15Previous"]}


def _market_exchange(exchange: str) -> str:
    return {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange.upper(), exchange.upper())


def repair_graph(nodes: list[dict], edges: list[dict], *, strategy_id: int,
                 underlying: str, exchange: str, owner: str,
                 strategy_kind: str) -> tuple[list[dict], list[dict]]:
    """Return repaired copies; reject unexpected entry/exit graph versions."""
    nodes, edges = copy.deepcopy(nodes), copy.deepcopy(edges)
    by_id = {item.get("id"): item for item in nodes}
    if len(by_id) != len(nodes):
        raise UnknownGraph("duplicate node ID")
    signal = by_id.get("entry-signal")
    legacy = by_id.get("run")
    if signal is not None:
        if strategy_kind not in ("batch", "signal"):
            raise UnknownGraph("unknown strategy kind")
        entry_action, exit_action = ("start", "stop") if strategy_kind == "batch" else ("long_entry", "long_exit")
        expected = {
            "entry-signal": entry_action,
            "exit-signal-market": exit_action,
            "exit-signal-1515": exit_action,
        }
        for node_id, action in expected.items():
            node = by_id.get(node_id)
            if not node or node.get("type") != "strategySignal":
                raise UnknownGraph(f"missing expected {node_id}")
            data = node.get("data") or {}
            if data.get("strategyId") != strategy_id or data.get("action") != action or data.get("mode") != "sandbox":
                raise UnknownGraph(f"unexpected {node_id} owner, action or mode")
            if data.get("brokerOwner") not in (None, owner):
                raise UnknownGraph(f"{node_id} already has a different owner")
            data["brokerOwner"] = owner
        entry = by_id["entry-signal"]
        entry_data = entry["data"]
        calendar = _market_exchange(exchange)
        if entry_data.get("marketHoursExchange") not in (None, calendar):
            raise UnknownGraph("entry has a different market calendar")
        entry_data["marketHoursExchange"] = calendar
        if entry_data.get("barEvidence") not in (None, BAR_EVIDENCE):
            raise UnknownGraph("entry has different candle evidence")
        entry_data["barEvidence"] = copy.deepcopy(BAR_EVIDENCE)
        for node in nodes:
            if node.get("type") != "openingRange":
                continue
            data = node.get("data") or {}
            if data.get("rangeStart") != "09:15" or data.get("rangeEnd") != "09:30" or data.get("rangeMinutes") not in (None, 15):
                raise UnknownGraph("opening range differs from the known 09:15-09:30 starter window")
            data["rangeMinutes"] = 15

        present = [node_id in by_id for node_id in BAR_IDS]
        if any(present) and not all(present):
            raise UnknownGraph("partially installed evidence chain")
        if not all(present):
            inbound = [edge for edge in edges if edge.get("source") == "entry-all-rules" and edge.get("target") == "entry-signal" and edge.get("sourceHandle") == "true"]
            if len(inbound) != 1:
                raise UnknownGraph("entry gate edge differs from known graph")
            inbound[0]["target"] = BAR_IDS[0]
            for index, (node_id, variable) in enumerate(zip(BAR_IDS, BAR_VARIABLES, strict=True)):
                nodes.append({
                    "id": node_id, "type": "barOffset", "position": {"x": 1200 + 160 * index, "y": 200},
                    "data": {"symbol": underlying, "exchange": exchange, "interval": "5m" if index < 2 else "15m",
                             "source": "api", "offsetBars": index % 2, "outputVariable": variable},
                })
                edges.append({"id": f"repair-evidence-{index}", "source": node_id,
                              "target": BAR_IDS[index + 1] if index < 3 else "entry-signal"})
        else:
            for index, node_id in enumerate(BAR_IDS):
                data = by_id[node_id].get("data") or {}
                if by_id[node_id].get("type") != "barOffset" or data.get("outputVariable") != BAR_VARIABLES[index]:
                    raise UnknownGraph("existing evidence node differs from migration")
    elif legacy is not None:
        if legacy.get("type") != "strategyModuleRun" or legacy.get("data", {}).get("strategyId") != strategy_id or legacy.get("data", {}).get("mode") != "sandbox":
            raise UnknownGraph("legacy run node differs from starter graph")
        for node_id in ("bar5_current", "bar5_previous", "bar15_current", "bar15_previous"):
            if by_id.get(node_id, {}).get("type") != "barOffset":
                raise UnknownGraph("legacy graph lacks its expected candle nodes")
        data = legacy["data"]
        for field, value in (("marketHoursExchange", _market_exchange(exchange)), ("barEvidence", STARTER_EVIDENCE), ("brokerOwner", owner)):
            if data.get(field) not in (None, value):
                raise UnknownGraph(f"legacy {field} differs from starter graph")
            data[field] = copy.deepcopy(value)
    else:
        raise UnknownGraph("neither known signal nor known starter graph")
    return nodes, edges


def inspect_installation(connection: sqlite3.Connection) -> tuple[list[dict], list[str]]:
    """Build an idempotent patch set without changing a single installed row."""
    connection.row_factory = sqlite3.Row
    planned, skipped = [], []
    rows = connection.execute("SELECT id,name,nodes,edges,is_active,broker_connection_id FROM flow_workflows ORDER BY id").fetchall()
    for row in rows:
        try:
            nodes = json.loads(row["nodes"] or "[]")
            edges = json.loads(row["edges"] or "[]")
            references = {n.get("data", {}).get("strategyId") for n in nodes if n.get("type") in ("strategySignal", "strategyModuleRun")}
            if len(references) != 1 or not next(iter(references)):
                raise UnknownGraph("ambiguous strategy reference")
            strategy_id = next(iter(references))
            strategy = connection.execute("SELECT id,user_id,underlying,underlying_exchange,strategy_kind,status,broker_connection_id FROM sm_strategy WHERE id=?", (strategy_id,)).fetchone()
            if not strategy or strategy["status"] == "running":
                raise UnknownGraph("strategy missing or running")
            links = connection.execute("SELECT id,status FROM broker_connections WHERE user_id=? AND broker='kotak' AND is_revoked=0", (strategy["user_id"],)).fetchall()
            if len(links) != 1:
                raise UnknownGraph("Kotak broker ownership is ambiguous")
            broker_id = links[0]["id"]
            if row["broker_connection_id"] not in (None, broker_id) or strategy["broker_connection_id"] not in (None, broker_id):
                raise UnknownGraph("saved connection belongs to another broker")
            repaired_nodes, repaired_edges = repair_graph(
                nodes, edges, strategy_id=strategy_id, underlying=strategy["underlying"],
                exchange=strategy["underlying_exchange"], owner=strategy["user_id"],
                strategy_kind=strategy["strategy_kind"])
            if repaired_nodes != nodes or repaired_edges != edges or row["broker_connection_id"] is None or strategy["broker_connection_id"] is None:
                planned.append({"workflow_id": row["id"], "strategy_id": strategy_id,
                                "old_nodes": row["nodes"], "old_edges": row["edges"],
                                "old_workflow_connection": row["broker_connection_id"],
                                "old_strategy_connection": strategy["broker_connection_id"],
                                "new_nodes": json.dumps(repaired_nodes, separators=(",", ":")),
                                "new_edges": json.dumps(repaired_edges, separators=(",", ":")),
                                "broker_connection_id": broker_id, "active": bool(row["is_active"]),
                                "broker_status": links[0]["status"]})
        except (UnknownGraph, ValueError, TypeError) as exc:
            skipped.append(f"workflow {row['id']} ({row['name']}): {exc}")
    return planned, skipped


def apply(db_path: Path, *, do_apply: bool = False) -> tuple[list[dict], list[str], Path | None]:
    """Plan or apply after a private SQLite backup and in-transaction recheck."""
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    connection = sqlite3.connect(db_path, timeout=10)
    try:
        planned, skipped = inspect_installation(connection)
        if not do_apply or skipped or not planned:
            return planned, skipped, None
        backups = db_path.parent / "backups"
        backups.mkdir(mode=0o700, exist_ok=True)
        backup_path = backups / f"strategy-flow-repair-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.db"
        fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        destination = sqlite3.connect(backup_path)
        try:
            connection.backup(destination)
        finally:
            destination.close()
        connection.execute("BEGIN IMMEDIATE")
        try:
            current, newly_skipped = inspect_installation(connection)
            if newly_skipped or current != planned:
                raise RuntimeError("Installed workflows changed after backup; no migration was applied")
            for item in planned:
                connection.execute("UPDATE flow_workflows SET nodes=?,edges=?,broker_connection_id=? WHERE id=?",
                                   (item["new_nodes"], item["new_edges"], item["broker_connection_id"], item["workflow_id"]))
                connection.execute("UPDATE sm_strategy SET broker_connection_id=? WHERE id=?",
                                   (item["broker_connection_id"], item["strategy_id"]))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return planned, skipped, backup_path
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true", help="Back up and apply all recognised graphs atomically")
    args = parser.parse_args()
    changes, skipped, backup = apply(args.database, do_apply=args.apply)
    for item in changes:
        print(f"workflow {item['workflow_id']}: repair planned; active={item['active']}; broker={item['broker_status']}")
    for message in skipped:
        print(f"SKIPPED {message}")
    print(f"{len(changes)} planned, {len(skipped)} skipped" + (f", backup={backup}" if backup else ""))
