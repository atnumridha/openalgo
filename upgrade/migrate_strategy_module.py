#!/usr/bin/env python3
"""
Migration: Strategy Module (multi-leg options strategies with risk management)

Adds the seven tables backing /strategy:

- sm_strategy             strategy config: legs, risk parameters, scheduler, webhook token hash
- sm_strategy_run         one activation of a strategy, start to stop
- sm_strategy_order       every order the engine places, audit grade
- sm_strategy_checkpoint  periodic runtime snapshot, for crash recovery
- sm_webhook_event        every inbound webhook, accepted or rejected
- sm_strategy_event       risk-event audit trail
- sm_automation_event     user-scoped automation lifecycle audit trail
- sm_risk_reservation     committed entry risk that must survive a restart
- sm_risk_session_capital first observed cash for an account session

The automation admission upgrade also backfills legacy signal strategies once,
using only safe active sandbox links and preserving subsequent operator choices.
init_db() in database/strategy_module_db.py creates the tables too, but
that only helps an installation whose database is opened after this ships;
this script is what reaches the ~290k deployments that upgrade with `git pull`.

The DDL is taken from the ORM metadata rather than written out by hand. Six
tables with twenty indexes between them is a lot of surface for a transcription
error, and a hand-written CREATE TABLE that drifts from the model produces the
worst kind of bug: the app starts, the query compiles, and one column silently
holds the wrong thing. Reading the metadata means the migration cannot disagree
with the models it is creating.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_strategy_module.py           # Apply migration
    uv run migrate_strategy_module.py --status  # Check status without changing anything
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path for imports
sys.path.insert(0, PROJECT_ROOT)
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    cast,
    create_engine,
    inspect,
    select,
)
from sqlalchemy.pool import NullPool

#: Table names in dependency order: parents before the rows that reference them.
#: create_all sorts this itself, but --status reads better in this order and a
#: human comparing the two lists should not have to.
TABLES = (
    "sm_strategy",
    "sm_strategy_run",
    "sm_strategy_order",
    "sm_strategy_checkpoint",
    "sm_webhook_event",
    "sm_strategy_event",
    "sm_automation_event",
    "sm_broker_data_status",
    "sm_comparison_session_summary",
    "sm_risk_reservation",
    "sm_risk_session_capital",
)


#: Columns added after the tables first shipped. An installation that ran this
#: migration before they existed has the tables and not the columns, and
#: create_all(checkfirst=True) skips a table that is already there, so it would
#: never reach them. Each entry is (table, column, DDL type).
ADDED_COLUMNS = (
    (
        "sm_strategy",
        "automation_state",
        "VARCHAR(20) NOT NULL DEFAULT 'disabled'",
    ),
    (
        "sm_strategy",
        "automation_state_reason",
        "TEXT",
    ),
    (
        "sm_strategy",
        "automation_state_updated_at",
        "DATETIME",
    ),
    (
        "sm_strategy",
        "broker_connection_id",
        "VARCHAR(36)",
    ),
    (
        "sm_strategy_run",
        "broker_connection_id",
        "VARCHAR(36)",
    ),
    (
        "sm_strategy_order",
        "product",
        "VARCHAR(10)",
    ),
    (
        "sm_strategy_order",
        "position_ref",
        "VARCHAR(32)",
    ),
    (
        "sm_strategy_run",
        "stop_requested_at",
        "DATETIME",
    ),
    (
        "sm_strategy_run",
        "stop_requested_reason",
        "VARCHAR(30)",
    ),
    (
        "sm_risk_reservation",
        "scope",
        "VARCHAR(240) NOT NULL DEFAULT ''",
    ),
)


# Indexes added after the original tables shipped. An index must be applied
# separately because create_all() does not alter a table it finds already present.
ADDED_INDEXES = (
    (
        "sm_strategy_order",
        "ix_sm_order_run_leg_position",
        "CREATE INDEX ix_sm_order_run_leg_position "
        "ON sm_strategy_order (run_id, leg_id, position_ref)",
    ),
)


AUTOMATION_BACKFILL_VERSION = "sandbox_automation_admission_v1"
_migration_metadata = MetaData()
_migration_state = Table(
    "sm_schema_migration", _migration_metadata,
    Column("version", String(100), primary_key=True),
    Column("phase", String(30), nullable=False),
    Column("candidate_ids", JSON, nullable=False),
    Column("completed_at", DateTime),
)


def prepare_automation_backfill(engine):
    """Freeze creation identities before columns; SQLite row IDs can be reused."""
    _migration_state.create(engine, checkfirst=True)
    with engine.begin() as connection:
        if connection.execute(select(_migration_state).where(
            _migration_state.c.version == AUTOMATION_BACKFILL_VERSION
        )).first() is not None:
            return
        inspector = inspect(connection)
        candidate_ids = []
        if inspector.has_table("sm_strategy"):
            columns = {column["name"] for column in inspector.get_columns("sm_strategy")}
            if "automation_state" not in columns:
                strategy = Table("sm_strategy", MetaData(), autoload_with=connection)
                if "created_at" in columns:
                    candidate_ids = [
                        {"id": row.id, "created_at": row.creation_identity}
                        for row in connection.execute(select(
                            strategy.c.id,
                            cast(strategy.c.created_at, String).label("creation_identity"),
                        ))
                        if row.creation_identity is not None
                    ]
        connection.execute(_migration_state.insert().values(
            version=AUTOMATION_BACKFILL_VERSION, phase="candidates_snapshotted",
            candidate_ids=candidate_ids,
        ))


def backfill_automation_admission(engine):
    """Update admission and completion atomically, without any runtime actions.

    Reflect both tables on the supplied engine. Importing Flow's global session
    would otherwise read a different database in upgrades and isolated tests.
    """
    from services.strategy_module.workflow_link import (
        STRATEGY_EXECUTION_NODE_TYPES,
        validate_workflow_link,
    )

    with engine.begin() as connection:
        marker = connection.execute(select(_migration_state).where(
            _migration_state.c.version == AUTOMATION_BACKFILL_VERSION
        )).mappings().one()
        if marker["phase"] == "completed":
            return True
        metadata = MetaData()
        strategy_table = Table("sm_strategy", metadata, autoload_with=connection)
        workflows = []
        if marker["candidate_ids"] and inspect(connection).has_table("flow_workflows"):
            workflow_table = Table("flow_workflows", metadata, autoload_with=connection)
            workflows = [SimpleNamespace(**row) for row in
                         connection.execute(select(workflow_table)).mappings()]
        for candidate in marker["candidate_ids"]:
            # Earlier ID-only snapshots cannot prove which creation they
            # referred to; fail closed rather than enroll a replacement row.
            if not isinstance(candidate, dict) or not candidate.get("created_at"):
                continue
            strategy_id = candidate["id"]
            row = connection.execute(select(
                strategy_table,
                cast(strategy_table.c.created_at, String).label("creation_identity"),
            ).where(
                strategy_table.c.id == strategy_id
            )).mappings().first()
            if (row is None or row.get("created_at") is None
                    or row["creation_identity"] != candidate["created_at"]):
                continue
            # An operator may have changed admission after an interrupted DDL
            # phase. Never replace any state carrying such evidence.
            if (row["automation_state"] != "disabled"
                    or row["automation_state_reason"] is not None
                    or row["automation_state_updated_at"] is not None):
                continue
            state = "disabled"
            if row.get("strategy_kind") != "signal":
                reason = "Only signal strategies qualify for the sandbox admission backfill."
            elif row.get("live_enabled") is not False:
                reason = "Live-enabled or unknown live-mode strategy remains disabled."
            else:
                # Discover every execution link, including protective exits.
                # The shared validator requires one entry and owns all checks
                # on the same-strategy exit nodes; migration must not count
                # protective exits as additional admission nodes.
                linked = []
                for workflow in workflows:
                    nodes = getattr(workflow, "nodes", None)
                    if isinstance(nodes, list) and any(
                        isinstance(node, dict) and type(node.get("type")) is str
                        and node["type"] in STRATEGY_EXECUTION_NODE_TYPES
                        and isinstance(node.get("data"), dict)
                        and type(node["data"].get("strategyId")) is int
                        and node["data"]["strategyId"] == strategy_id
                        for node in nodes
                    ):
                        linked.append(workflow)
                link, reason = validate_workflow_link(SimpleNamespace(**row), linked)
                if link is not None:
                    if link.active:
                        state, reason = "armed", "Preserved active sandbox Flow admission."
                    else:
                        reason = "Linked Flow workflow is inactive."
            connection.execute(strategy_table.update().where(
                strategy_table.c.id == strategy_id,
                cast(strategy_table.c.created_at, String) == candidate["created_at"],
                strategy_table.c.automation_state == "disabled",
                strategy_table.c.automation_state_reason.is_(None),
                strategy_table.c.automation_state_updated_at.is_(None),
            ).values(automation_state=state, automation_state_reason=reason,
                     automation_state_updated_at=datetime.now(UTC).replace(tzinfo=None)))
        connection.execute(_migration_state.update().where(
            _migration_state.c.version == AUTOMATION_BACKFILL_VERSION
        ).values(phase="completed", completed_at=datetime.now(UTC).replace(tzinfo=None)))
    return True


def missing_columns(engine):
    """Which of ADDED_COLUMNS are not on their table yet.

    A table that does not exist at all is not reported here: create_all makes
    it with the column already on it.
    """
    inspector = inspect(engine)
    present_tables = set(inspector.get_table_names())
    missing = []
    for table, column, ddl in ADDED_COLUMNS:
        if table not in present_tables:
            continue
        names = {col["name"] for col in inspector.get_columns(table)}
        if column not in names:
            missing.append((table, column, ddl))
    return missing


def add_missing_columns(engine):
    """Add each missing column, leaving unknown historical facts nullable.

    Admission has its own versioned backfill. The product an old order was
    sent with is not recorded anywhere else, and inventing one would make the
    audit trail confidently wrong. NULL reads as "not recorded", which is true.
    """
    missing = missing_columns(engine)
    if not missing:
        return True
    for table, column, ddl in missing:
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            print(f"  [OK] Added {table}.{column}")
        except Exception as exc:
            print(f"  [FAIL] Could not add {table}.{column}: {exc}")
            return False
    return True


def missing_indexes(engine):
    """Which of ADDED_INDEXES are not on their table yet."""
    inspector = inspect(engine)
    present_tables = set(inspector.get_table_names())
    missing = []
    for table, index, ddl in ADDED_INDEXES:
        if table not in present_tables:
            continue
        names = {item["name"] for item in inspector.get_indexes(table)}
        if index not in names:
            missing.append((table, index, ddl))
    return missing


def add_missing_indexes(engine):
    """Create each missing index after its nullable columns exist."""
    missing = missing_indexes(engine)
    if not missing:
        return True
    for table, index, ddl in missing:
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(ddl)
            print(f"  [OK] Added {table}.{index}")
        except Exception as exc:
            print(f"  [FAIL] Could not add {table}.{index}: {exc}")
            return False
    return True


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run migrate_strategy_module.py`,
    and DATABASE_URL is relative by default ("sqlite:///db/openalgo.db"). Left
    relative it resolves against the current directory, so running from
    upgrade/ would point at upgrade/db/openalgo.db - which SQLAlchemy creates
    empty on connect. The migration would then report success having created
    its tables in a database the app never opens.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path).replace("\\", "/")


def get_database_url():
    """Read DATABASE_URL from the environment, with the project default."""
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


def load_metadata():
    """The strategy-module ORM metadata, which is the source of the DDL."""
    from database.strategy_module_db import Base

    return Base.metadata


def missing_tables(engine):
    """Which of our tables are not in the database yet."""
    present = set(inspect(engine).get_table_names())
    return [t for t in TABLES if t not in present]


def status(engine):
    """Report what would change, without changing anything."""
    inspector = inspect(engine)
    present = set(inspector.get_table_names())

    print("\nStrategy Module table status")
    print("-" * 46)
    for table in TABLES:
        if table in present:
            count = len(inspector.get_indexes(table))
            print(f"  {table:<26} present, {count} index(es)")
        else:
            print(f"  {table:<26} MISSING")
    print("-" * 46)

    absent = [t for t in TABLES if t not in present]
    columns = missing_columns(engine)
    indexes = missing_indexes(engine)
    backfill_pending = True
    if inspector.has_table(_migration_state.name):
        with engine.connect() as connection:
            phase = connection.execute(select(_migration_state.c.phase).where(
                _migration_state.c.version == AUTOMATION_BACKFILL_VERSION
            )).scalar_one_or_none()
        backfill_pending = phase != "completed"
    for table, column, _ddl in columns:
        print(f"  {table}.{column:<19} MISSING")
    for table, index, _ddl in indexes:
        print(f"  {table}.{index:<19} MISSING")

    if not absent and not columns and not indexes and not backfill_pending:
        print("Up to date. Nothing to do.")
        return True

    if absent:
        print(f"Migration needed. Would create {len(absent)} table(s):")
        for table in absent:
            print(f"  {table}")
    if columns:
        print(f"Migration needed. Would add {len(columns)} column(s):")
        for table, column, _ddl in columns:
            print(f"  {table}.{column}")
    if indexes:
        print(f"Migration needed. Would add {len(indexes)} index(es):")
        for table, index, _ddl in indexes:
            print(f"  {table}.{index}")
    if backfill_pending:
        print("Migration needed. Sandbox automation admission backfill is pending.")
    return False


def apply(engine):
    """Create whatever is missing. Existing tables keep their rows."""
    prepare_automation_backfill(engine)
    absent = missing_tables(engine)
    if not absent:
        print("  All strategy-module tables already present.")
        # Not "nothing to do": a table that exists is skipped by create_all,
        # so a column added after the table first shipped only ever arrives
        # through this path.
        return (add_missing_columns(engine) and add_missing_indexes(engine)
                and backfill_automation_admission(engine))

    metadata = load_metadata()
    # checkfirst=True is what makes this safe to re-run: a table that already
    # exists is skipped rather than raising, so a partially-applied migration
    # (interrupted midway) completes cleanly on the next run.
    metadata.create_all(bind=engine, checkfirst=True)

    still_missing = missing_tables(engine)
    if still_missing:
        print(f"  [FAIL] These tables were not created: {', '.join(still_missing)}")
        return False

    for table in absent:
        print(f"  [OK] Created {table}")

    # A partially applied migration can leave some tables present and some
    # absent, so the columns still have to be checked on the ones that were
    # already there.
    return (add_missing_columns(engine) and add_missing_indexes(engine)
            and backfill_automation_admission(engine))


def main():
    parser = argparse.ArgumentParser(description="Strategy Module schema migration")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Report what would change without changing anything",
    )
    args = parser.parse_args()

    db_url = get_database_url()
    shown = db_url if not db_url.startswith("sqlite") else "sqlite://..."
    print("\nStrategy Module Migration")
    print("-" * 46)
    print(f"Database: {shown}")

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        if args.status:
            status(engine)
            return 0

        print("\nApplying migration...")
        ok = apply(engine)
        print("-" * 46)
        if ok:
            print("Migration complete.")
            return 0
        print("Migration failed. See the messages above.")
        return 1
    finally:
        # A migration is a short-lived process, but disposing is what keeps
        # the SQLite file unlocked for the app that may be waiting on it.
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
