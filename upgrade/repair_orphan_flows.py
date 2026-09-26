"""Back up and disable active flows whose linked strategies were deleted.

Run with the app stopped: uv run python upgrade/repair_orphan_flows.py --apply
Without --apply (or with --status), inspect only. Graphs and history are retained.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def inspect_orphans():
    from database.flow_db import FlowWorkflow
    from database.strategy_module_db import SmStrategy
    from services.flow_readiness_service import strategy_nodes

    candidates = []
    # Query directly so an unreadable database cannot be mistaken for a missing
    # strategy by a convenience reader that catches errors and returns None.
    for workflow in FlowWorkflow.query.filter_by(is_active=True).order_by(FlowWorkflow.id).all():
        missing = sorted({node.get("data", {}).get("strategyId") for node in strategy_nodes(workflow)
                          if type(node.get("data", {}).get("strategyId")) is int
                          and SmStrategy.query.filter_by(id=node["data"]["strategyId"]).first() is None})
        if missing:
            candidates.append({"id": workflow.id, "name": workflow.name, "missing_strategy_ids": missing})
    return candidates


def backup_database(directory):
    from database.flow_db import engine

    if engine.dialect.name != "sqlite" or not engine.url.database:
        raise RuntimeError("This repair requires the installed SQLite database")
    path = Path(engine.url.database).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = directory / f"orphan-flow-repair-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.db"
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("The backup did not pass verification; no flows were changed")
    return backup


def repair_orphans(backup_dir):
    from database import flow_db, strategy_module_db
    from services.flow_lifecycle_service import deactivate_workflow

    if strategy_module_db.SmStrategyRun.query.filter_by(stopped_at=None).count():
        raise RuntimeError("Stop and review active strategy runs before applying this repair")
    planned = inspect_orphans()
    if not planned:
        return {"disabled": [], "backup": None}
    backup = backup_database(backup_dir)
    flow_db.db_session.expire_all()
    strategy_module_db.db_session.expire_all()
    if inspect_orphans() != planned:
        raise RuntimeError("Flows changed after backup; retry the repair")
    result = {"disabled": [], "backup": str(backup)}
    try:
        for item in planned:
            payload, status = deactivate_workflow(item["id"])
            if status != 200:
                raise RuntimeError(f"Could not disable workflow {item['id']}: {payload.get('error')}")
            result["disabled"].append(item["id"])
    finally:
        audit = backup.with_suffix(".json")
        with audit.open("x") as output:
            json.dump(result, output, indent=2)
        audit.chmod(0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--server-port", type=int, default=5001)
    parser.add_argument("--backup-dir", type=Path, default=Path("db/backups"))
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv()
    scheduler = None
    try:
        if not args.apply or args.status:
            print(json.dumps({"planned": inspect_orphans()}, indent=2))
            return 0
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(("127.0.0.1", args.server_port)) == 0:
                raise RuntimeError("Stop the app before applying the repair")
        from services.flow_scheduler_service import init_flow_scheduler

        # Remove persisted jobs through the real lifecycle without firing them.
        scheduler = init_flow_scheduler(paused=True)
        print(json.dumps(repair_orphans(args.backup_dir), indent=2))
        return 0
    finally:
        if scheduler:
            scheduler.shutdown()
        from utils.db_sessions import remove_all_scoped_sessions

        remove_all_scoped_sessions()


if __name__ == "__main__":
    raise SystemExit(main())
