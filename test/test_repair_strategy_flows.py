"""Installed Flow graph repairs preserve action, settings, and activation."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[1] / "upgrade" / "repair_strategy_flows.py"
_spec = importlib.util.spec_from_file_location("repair_strategy_flows", _path)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)


def _graph(kind="batch"):
    entry, exit_ = (("start", "stop") if kind == "batch" else ("long_entry", "long_exit"))
    nodes = [
        {"id": node_id, "type": "strategySignal", "data": {"strategyId": 4,
         "action": action, "mode": "sandbox", "operatorNote": "keep me"}}
        for node_id, action in (("entry-signal", entry), ("exit-signal-market", exit_),
                                ("exit-signal-1515", exit_))
    ]
    edges = [{"id": "gate", "source": "entry-all-rules", "target": "entry-signal",
              "sourceHandle": "true"}]
    return nodes, edges


@pytest.mark.parametrize("kind", ["batch", "signal"])
def test_repair_preserves_exit_actions_and_custom_settings(kind):
    nodes, edges = _graph(kind)
    repaired, routed = repair.repair_graph(
        nodes, edges, strategy_id=4, underlying="RELIANCE", exchange="NSE",
        owner="alice", strategy_kind=kind)
    assert nodes[0]["data"]["operatorNote"] == "keep me"
    assert repaired[0]["data"]["operatorNote"] == "keep me"
    assert [row["data"]["action"] for row in repaired[:3]] == [
        "start" if kind == "batch" else "long_entry",
        "stop" if kind == "batch" else "long_exit",
        "stop" if kind == "batch" else "long_exit",
    ]
    assert repaired[0]["data"]["barEvidence"] == repair.BAR_EVIDENCE
    assert len([row for row in repaired if row["type"] == "barOffset"]) == 4
    assert routed[0]["target"] == repair.BAR_IDS[0]
    again = repair.repair_graph(repaired, routed, strategy_id=4, underlying="RELIANCE",
                                exchange="NSE", owner="alice", strategy_kind=kind)
    assert again == (repaired, routed)


def test_unexpected_action_is_not_silently_rewritten():
    nodes, edges = _graph("signal")
    nodes[1]["data"]["action"] = "start"
    with pytest.raises(repair.UnknownGraph):
        repair.repair_graph(nodes, edges, strategy_id=4, underlying="RELIANCE",
                            exchange="NSE", owner="alice", strategy_kind="signal")


def test_known_legacy_opening_range_keeps_its_window():
    nodes, edges = _graph("signal")
    nodes.append({"id": "entry-opening-range", "type": "openingRange", "data": {
        "symbol": "ICICIBANK", "exchange": "NSE", "rangeStart": "09:15", "rangeEnd": "09:30",
        "outputVariable": "openingRange",
    }})
    repaired, _ = repair.repair_graph(nodes, edges, strategy_id=4, underlying="ICICIBANK",
                                      exchange="NSE", owner="alice", strategy_kind="signal")
    assert repaired[-5]["data"]["rangeMinutes"] == 15
    assert repaired[-5]["data"]["outputVariable"] == "openingRange"


def test_apply_backs_up_and_preserves_active_choice(tmp_path):
    db_path = tmp_path / "installed.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE broker_connections (id TEXT,user_id TEXT,broker TEXT,status TEXT,is_revoked INTEGER);
        CREATE TABLE sm_strategy (id INTEGER,user_id TEXT,underlying TEXT,underlying_exchange TEXT,
                                  strategy_kind TEXT,status TEXT,broker_connection_id TEXT);
        CREATE TABLE flow_workflows (id INTEGER,name TEXT,nodes TEXT,edges TEXT,is_active INTEGER,
                                     broker_connection_id TEXT);
    """)
    conn.execute("INSERT INTO broker_connections VALUES ('kotak-one','alice','kotak','expired',0)")
    conn.execute("INSERT INTO sm_strategy VALUES (4,'alice','RELIANCE','NSE','signal','stopped',NULL)")
    nodes, edges = _graph("signal")
    conn.execute("INSERT INTO flow_workflows VALUES (1,'cash',?,?,1,NULL)",
                 (json.dumps(nodes), json.dumps(edges)))
    conn.commit()
    conn.close()

    planned, skipped, backup = repair.apply(db_path)
    assert len(planned) == 1 and not skipped and backup is None
    changed, skipped, backup = repair.apply(db_path, do_apply=True)
    assert len(changed) == 1 and not skipped and backup.is_file()
    connection = sqlite3.connect(db_path)
    active, pin = connection.execute("SELECT is_active,broker_connection_id FROM flow_workflows").fetchone()
    assert (active, pin) == (1, "kotak-one")
    connection.close()
    assert repair.apply(db_path)[0] == []
