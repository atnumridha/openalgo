"""Independent, transactional SQL history; never cascades with a strategy/reset."""

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text


@dataclass(frozen=True)
class JournalSpec:
    table: str
    columns: tuple
    key: str
    owner: str
    mode: str
    time: str


def _spec(model, key, owner, mode, stamp, exclude=()):
    return JournalSpec(
        model.__tablename__,
        tuple(c.name for c in model.__table__.columns if c.name not in exclude),
        key,
        owner,
        mode,
        stamp,
    )


from database import neo_desk_db as desk
from database import neo_history_db as history
from database import sandbox_db as paper
from database import strategy_module_db as native

PAPER_SPECS = [
    _spec(
        paper.SandboxOrders,
        "{row}.orderid",
        "{row}.user_id",
        "'sandbox'",
        "replace({row}.order_timestamp,' ','T')||'+05:30'",
    ),
    _spec(
        paper.SandboxTrades,
        "{row}.tradeid",
        "{row}.user_id",
        "'sandbox'",
        "replace({row}.trade_timestamp,' ','T')||'+05:30'",
    ),
    _spec(
        paper.SandboxPositions,
        "{row}.id||':'||{row}.created_at",
        "{row}.user_id",
        "'sandbox'",
        "replace({row}.updated_at,' ','T')||'+05:30'",
    ),
    _spec(
        paper.SandboxDailyPnL,
        "{row}.user_id||':'||{row}.date",
        "{row}.user_id",
        "'sandbox'",
        "{row}.date||'T15:30:00+05:30'",
    ),
]
RUN_OWNER = "(SELECT s.user_id FROM sm_strategy s WHERE s.id={row}.strategy_id)"
ORDER_OWNER = "(SELECT s.user_id FROM sm_strategy s JOIN sm_strategy_run r ON r.strategy_id=s.id WHERE r.id={row}.run_id)"
RUN_MODE = "(SELECT r.mode FROM sm_strategy_run r WHERE r.id={row}.run_id)"
MAIN_SPECS = [
    _spec(
        native.SmStrategy,
        "{row}.id||':'||{row}.created_at",
        "{row}.user_id",
        "'configuration'",
        "replace({row}.updated_at,' ','T')||'+00:00'",
        exclude=("webhook_token_hash", "webhook_ip_allowlist"),
    ),
    _spec(
        native.SmStrategyRun,
        "{row}.id||':'||{row}.started_at",
        RUN_OWNER,
        "{row}.mode",
        "replace({row}.started_at,' ','T')||'+00:00'",
    ),
    _spec(
        native.SmStrategyOrder,
        "{row}.id||':'||{row}.placed_at",
        ORDER_OWNER,
        RUN_MODE,
        "replace(coalesce({row}.filled_at,{row}.placed_at),' ','T')||'+00:00'",
    ),
    _spec(
        native.SmStrategyCheckpoint,
        "{row}.id||':'||{row}.ts",
        ORDER_OWNER,
        RUN_MODE,
        "replace({row}.ts,' ','T')||'+00:00'",
    ),
    _spec(
        native.SmStrategyEvent,
        "{row}.id||':'||{row}.ts",
        "{row}.user_id",
        "coalesce(" + RUN_MODE + ",'configuration')",
        "replace({row}.ts,' ','T')||'+00:00'",
    ),
    _spec(
        desk.NeoDesk,
        "{row}.owner",
        "{row}.owner",
        "{row}.mode",
        "strftime('%Y-%m-%dT%H:%M:%f+00:00','now')",
        exclude=("settings",),
    ),
    _spec(
        desk.NeoClaim,
        "{row}.id",
        "{row}.owner",
        "coalesce((SELECT mode FROM neo_desk WHERE owner={row}.owner),'configuration')",
        "json_extract({row}.setup,'$.execute_at')",
    ),
    _spec(
        desk.NeoRunProtection,
        "{row}.run_id",
        "{row}.owner",
        "coalesce(json_extract({row}.protection,'$.mode'),'configuration')",
        "coalesce(json_extract({row}.protection,'$.observed_at'),json_extract({row}.protection,'$.execute_at'))",
    ),
    _spec(
        history.NeoFill,
        "{row}.identity",
        "{row}.owner",
        "'live'",
        "json_extract({row}.payload,'$.time')",
    ),
    _spec(
        history.NeoResearchJob,
        "{row}.id",
        "{row}.owner",
        "'research'",
        "strftime('%Y-%m-%dT%H:%M:%f+00:00','now')",
    ),
]


def install_journal(engine, specs):
    if engine.dialect.name != "sqlite":
        raise ValueError(
            "This terminal's independent retention journal requires its configured SQLite database."
        )
    with engine.begin() as connection:
        connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS neo_sql_journal (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner TEXT NOT NULL, mode TEXT NOT NULL, source_table TEXT NOT NULL,
          source_key TEXT NOT NULL, change_kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
          trading_date TEXT NOT NULL, recorded_at TEXT NOT NULL,
          payload TEXT NOT NULL,
          UNIQUE(owner,mode,source_table,source_key,change_kind,payload))""")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_neo_journal_owner_day ON neo_sql_journal(owner,mode,trading_date,id)"
        )
        for action in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(f"""CREATE TRIGGER IF NOT EXISTS neo_journal_no_{action.lower()}
              BEFORE {action} ON neo_sql_journal BEGIN SELECT RAISE(ABORT,'Trading history is append-only'); END""")
        for spec in specs:
            columns = {
                r[1] for r in connection.exec_driver_sql(f'PRAGMA table_info("{spec.table}")')
            }
            if not columns or not set(spec.columns).issubset(columns):
                raise ValueError(
                    "Trading retention cannot initialize: source schema is incomplete."
                )

            def payload(row, spec=spec):
                return "json_object(" + ",".join(f"'{c}',{row}.\"{c}\"" for c in spec.columns) + ")"

            def insert(row, kind, spec=spec, render_payload=payload):
                stamp = (
                    "coalesce("
                    + spec.time.format(row=row)
                    + ",strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))"
                )
                return f"""INSERT OR IGNORE INTO neo_sql_journal
                  (owner,mode,source_table,source_key,change_kind,occurred_at,trading_date,recorded_at,payload)
                  SELECT coalesce({spec.owner.format(row=row)},''),coalesce({spec.mode.format(row=row)},'configuration'),
                  '{spec.table}',cast({spec.key.format(row=row)} as text),'{kind}',{stamp},
                  date({stamp},'+5 hours','+30 minutes'),strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),{render_payload(row)}"""

            for action, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
                name = f"neo_archive_{spec.table}_{action.lower()}"
                when = f" WHEN {payload('NEW')} <> {payload('OLD')}" if action == "UPDATE" else ""
                connection.exec_driver_sql(
                    f'CREATE TRIGGER IF NOT EXISTS "{name}" AFTER {action} ON "{spec.table}"{when} BEGIN {insert(row, action.lower())}; END'
                )
            connection.exec_driver_sql(
                insert("source", "snapshot") + f' FROM "{spec.table}" source'
            )


def journal_rows(engine, owner, source=None, start=None, end=None, mode=None, limit=None):
    lower, upper = (date.fromisoformat(v).isoformat() if v else None for v in (start, end))
    if lower and upper and lower > upper:
        raise ValueError("From date must be before Through date.")
    where = ["owner=:owner"]
    params = {"owner": owner}
    for field, value in (("source_table", source), ("mode", mode)):
        if value:
            where.append(field + "=:" + field)
            params[field] = value
    # Fold changes by immutable entity key before date filtering; deleted records remain visible.
    query = (
        "SELECT * FROM neo_sql_journal WHERE id IN (SELECT max(id) FROM neo_sql_journal WHERE "
        + " AND ".join(where)
        + " GROUP BY owner,mode,source_table,source_key)"
    )
    if lower:
        query += " AND trading_date>=:start"
        params["start"] = lower
    if upper:
        query += " AND trading_date<=:end"
        params["end"] = upper
    query += " ORDER BY occurred_at,id"
    if limit is not None:
        if not 1 <= int(limit) <= 1000:
            raise ValueError("Choose a report page up to 1000 records.")
        query += " LIMIT :limit"
        params["limit"] = int(limit)
    with engine.connect() as connection:
        result = [dict(r) for r in connection.execute(text(query), params).mappings()]
    for row in result:
        row["payload"] = json.loads(row["payload"])
    return result


def online_backup(engine, target):
    if (
        engine.dialect.name != "sqlite"
        or not engine.url.database
        or engine.url.database == ":memory:"
    ):
        raise ValueError("An on-disk SQLite source is required for a verified backup.")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    pending = target.with_name(target.name + "." + uuid4().hex + ".tmp")
    # Never copy a live .db file: SQLite's backup API includes committed WAL pages.
    try:
        fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        with (
            sqlite3.connect(str(Path(engine.url.database).resolve())) as source,
            sqlite3.connect(str(pending)) as destination,
        ):
            source.backup(destination, pages=256, sleep=0.01)
            if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("SQL backup integrity verification failed.")
        with pending.open("rb") as f:
            os.fsync(f.fileno())
        os.replace(pending, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return target
    finally:
        if pending.exists():
            pending.unlink()
