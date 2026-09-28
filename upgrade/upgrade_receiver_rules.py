"""Opt-in receiver upgrade: dry-run first; stop app/workers before --apply --offline.

Only recognized stock graphs and unedited long-option legs are eligible. All
rows are rechecked under one transaction after a private SQLite backup. Live
permissions, activation, pins, account limits and completed trades are preserved.
No broker calls are made. Restart the application to discard old cached graphs.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def inspect_installation(db):
    from services.strategy_module.receiver_rules import RECEIVER_NAMES
    from services.strategy_module.receiver_upgrade import UnsupportedReceiver, plan

    db.row_factory = sqlite3.Row
    strategies = [dict(r) for r in db.execute("SELECT * FROM sm_strategy ORDER BY id")]
    flows = [dict(r) for r in db.execute("SELECT * FROM flow_workflows ORDER BY id")]
    plans, skipped = [], []
    for row in strategies:
        if row["name"] not in RECEIVER_NAMES:
            continue
        try:
            strategy = row | {"legs": json.loads(row["legs"] or "[]")}
            # SQLite stores SQLAlchemy JSON values as text, including the JSON
            # literal "null". Match the ORM's decoded value before comparing
            # risk controls; preserve raw rows for the change-detection hash.
            if isinstance(strategy.get("lock_profit"), str):
                strategy["lock_profit"] = json.loads(strategy["lock_profit"])
            if db.execute(
                "SELECT 1 FROM sm_strategy_run WHERE strategy_id=? AND stopped_at IS NULL LIMIT 1",
                (row["id"],),
            ).fetchone():
                raise UnsupportedReceiver("Open managed run; reconcile exposure before upgrading")
            linked = []
            for flow in flows:
                nodes = json.loads(flow["nodes"] or "[]")
                if any(
                    n.get("type") in {"strategyModuleRun", "strategySignal"}
                    and n.get("data", {}).get("strategyId") == row["id"]
                    for n in nodes
                ):
                    linked.append(
                        flow | {"nodes": nodes, "edges": json.loads(flow["edges"] or "[]")}
                    )
            if len(linked) != 1:
                raise UnsupportedReceiver("Exactly one exclusive linked workflow is required")
            proposal = plan(strategy, linked[0])
            if proposal:
                snapshot = json.dumps(
                    {
                        "strategy": row,
                        "workflow": next(f for f in flows if f["id"] == linked[0]["id"]),
                    },
                    sort_keys=True,
                )
                proposal["before_hash"] = hashlib.sha256(snapshot.encode()).hexdigest()
                plans.append(proposal)
        except (UnsupportedReceiver, ValueError, TypeError, KeyError) as exc:
            skipped.append(f"strategy {row['id']}: {exc}")
    return plans, skipped


def apply(database, *, do_apply=False, offline=False):
    database = Path(database).resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if do_apply and not offline:
        raise ValueError(
            "Stop the application and workers, then explicitly request offline application"
        )
    uri = database.as_uri() + "?mode=" + ("rw" if do_apply else "ro")
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
        planned, skipped = inspect_installation(db)
        if not do_apply or skipped or not planned:
            return planned, skipped, None
        folder = database.parent / "backups"
        folder.mkdir(mode=0o700, exist_ok=True)
        backup = folder / f"receiver-rules-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.db"
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(backup)) as destination:
            db.backup(destination)
        db.execute("BEGIN IMMEDIATE")
        try:
            fresh, new_skipped = inspect_installation(db)
            if new_skipped or fresh != planned:
                raise RuntimeError(
                    "Receiver configuration changed after backup; no upgrade applied"
                )
            for item in planned:
                change = item["workflow_changes"]
                db.execute(
                    "UPDATE flow_workflows SET nodes=?,edges=?,description=? WHERE id=?",
                    (
                        json.dumps(change["nodes"]),
                        json.dumps(change["edges"]),
                        change["description"],
                        item["workflow_id"],
                    ),
                )
                db.execute(
                    "UPDATE sm_strategy SET scalp_profile=? WHERE id=?",
                    (item["strategy_changes"]["scalp_profile"], item["strategy_id"]),
                )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return planned, skipped, backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--offline", action="store_true", help="Confirm app and all workers are stopped"
    )
    args = parser.parse_args()
    changes, skipped, backup = apply(args.database, do_apply=args.apply, offline=args.offline)
    for change in changes:
        print(
            f"strategy {change['strategy_id']}, workflow {change['workflow_id']}: {change['strategy_changes']['scalp_profile']}; preserve mode={change['mode']}, active={change['active']}"
        )
    for reason in skipped:
        print(f"SKIPPED {reason}")
    print(
        f"{len(changes)} planned; {len(skipped)} skipped"
        + (f"; applied with backup {backup}" if backup else "; no changes applied")
    )
    if skipped:
        raise SystemExit(2)
