#!/usr/bin/env python3
"""
Migration: ML Signals settings and crypto fee profile

Adds the one-row table behind the ML Signals settings panel:
- ml_settings: the ML shortlist and retrain schedule, how an ML trade is sized
  and exited, and the fee profile every crypto net P&L is computed with
  (GST, Scalper Offer windows, the Diwali Scalper Offer voucher on BTCUSD and
  its monthly cap, the option premium cap)

A new table. init_db() in database/ml_settings_db.py creates it too, but that
only reaches an installation whose database is opened after this ships; this
script is what reaches the deployments that upgrade with `git pull`. A table
created by an earlier version of this feature is brought up to date column by
column, and no value already in it is changed. A table from the build that had
a flat opening-rebate percentage keeps that column, unused: SQLite cannot drop
a column in place on older versions, and an unread column costs nothing.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_ml_settings.py           # Apply migration
    uv run migrate_ml_settings.py --status  # Check status without changing anything
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, PROJECT_ROOT)
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

TABLE = "ml_settings"

DEFAULT_SYMBOLS = json.dumps(["BTCUSD", "ETHUSD", "SOLUSD"])

#: Every column after the key, with its SQLite and PostgreSQL definitions.
#: Defaults match database/ml_settings_db.py DEFAULTS.
COLUMNS = {
    "symbols": (f"TEXT NOT NULL DEFAULT '{DEFAULT_SYMBOLS}'",) * 2,
    "retrain_enabled": ("BOOLEAN NOT NULL DEFAULT 1", "BOOLEAN NOT NULL DEFAULT TRUE"),
    "retrain_hour_ist": ("INTEGER NOT NULL DEFAULT 3",) * 2,
    "retrain_minute_ist": ("INTEGER NOT NULL DEFAULT 30",) * 2,
    "risk_pct": ("FLOAT NOT NULL DEFAULT 1.0", "DOUBLE PRECISION NOT NULL DEFAULT 1.0"),
    "max_leverage": ("INTEGER NOT NULL DEFAULT 10",) * 2,
    "sandbox_balance_usd": (
        "FLOAT NOT NULL DEFAULT 1000.0",
        "DOUBLE PRECISION NOT NULL DEFAULT 1000.0",
    ),
    "smart_exit_enabled": ("BOOLEAN NOT NULL DEFAULT 1", "BOOLEAN NOT NULL DEFAULT TRUE"),
    "smart_exit_confirmations": ("INTEGER NOT NULL DEFAULT 2",) * 2,
    "max_hold_minutes": ("INTEGER NOT NULL DEFAULT 28",) * 2,
    "daily_loss_limit_pct": ("FLOAT NOT NULL DEFAULT 3.0", "DOUBLE PRECISION NOT NULL DEFAULT 3.0"),
    "breakeven_buffer_pct": (
        "FLOAT NOT NULL DEFAULT 0.05",
        "DOUBLE PRECISION NOT NULL DEFAULT 0.05",
    ),
    "fee_gst_pct": ("FLOAT NOT NULL DEFAULT 18.0", "DOUBLE PRECISION NOT NULL DEFAULT 18.0"),
    "fee_scalper_offer": ("BOOLEAN NOT NULL DEFAULT 1", "BOOLEAN NOT NULL DEFAULT TRUE"),
    "fee_scalper_minutes_major": (
        "FLOAT NOT NULL DEFAULT 30.0",
        "DOUBLE PRECISION NOT NULL DEFAULT 30.0",
    ),
    "fee_scalper_minutes_other": (
        "FLOAT NOT NULL DEFAULT 15.0",
        "DOUBLE PRECISION NOT NULL DEFAULT 15.0",
    ),
    "fee_diwali_offer": ("BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE"),
    "fee_voucher_earned_month": (
        "FLOAT NOT NULL DEFAULT 0.0",
        "DOUBLE PRECISION NOT NULL DEFAULT 0.0",
    ),
    "fee_premium_cap_pct": ("FLOAT NOT NULL DEFAULT 3.5", "DOUBLE PRECISION NOT NULL DEFAULT 3.5"),
    "live_strategy_id": ("INTEGER",) * 2,
    "sandbox_strategy_id": ("INTEGER",) * 2,
    "webhook_tokens": ("TEXT",) * 2,
    "last_retrain_status": ("VARCHAR(400)",) * 2,
    "updated_at": ("DATETIME DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
}


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    Run from upgrade/, a relative path would point at upgrade/db/openalgo.db,
    which SQLAlchemy creates empty on connect: the migration would succeed on
    a database the app never opens.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if not path or path == ":memory:" or os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path)


def get_database_url():
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


def table_exists(engine):
    return TABLE in inspect(engine).get_table_names()


def missing_columns(engine):
    if not table_exists(engine):
        return list(COLUMNS)
    present = {column["name"] for column in inspect(engine).get_columns(TABLE)}
    return [name for name in COLUMNS if name not in present]


def has_row(engine):
    if not table_exists(engine):
        return False
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {TABLE} WHERE id = 1")).scalar() > 0


def apply(engine):
    sqlite = "sqlite" in str(engine.url)
    pick = 0 if sqlite else 1
    with engine.connect() as conn:
        if not table_exists(engine):
            print(f"  [CREATE] Creating {TABLE} table...")
            columns = ",\n    ".join(f"{name} {spec[pick]}" for name, spec in COLUMNS.items())
            conn.execute(
                text(f"CREATE TABLE {TABLE} (\n    id INTEGER PRIMARY KEY,\n    {columns}\n)")
            )
            conn.commit()
            print(f"  [OK] {TABLE} table created")
        else:
            for name in missing_columns(engine):
                print(f"  [ADD] {TABLE}.{name}")
                spec = COLUMNS[name][pick]
                # SQLite refuses a non-constant default on ADD COLUMN; the ORM
                # sets updated_at on every write, so the column needs none.
                if sqlite and "CURRENT_TIMESTAMP" in spec:
                    spec = spec.split(" DEFAULT ")[0]
                conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {spec}"))
            conn.commit()
        if not has_row(engine):
            conn.execute(text(f"INSERT INTO {TABLE} (id) VALUES (1)"))
            conn.commit()
            print("  [OK] default settings row added")
        else:
            print("  [SKIP] settings row already present; values left as they are")
    return True


def status(engine):
    print()
    print("ML settings migration status")
    print("-" * 46)
    present = table_exists(engine)
    missing = missing_columns(engine)
    row = has_row(engine)
    print(f"  {TABLE:<34} {'present' if present else 'MISSING'}")
    if present:
        print(f"  {'columns':<34} {'complete' if not missing else 'MISSING ' + ', '.join(missing)}")
        print(f"  {'settings row':<34} {'present' if row else 'MISSING'}")
    print("-" * 46)
    applied = present and not missing and row
    print("All changes applied." if applied else "Migration needed.")
    return applied


def main():
    parser = argparse.ArgumentParser(description="ML settings table migration")
    parser.add_argument(
        "--status", action="store_true", help="Report status without changing anything"
    )
    args = parser.parse_args()

    print()
    print("ML Signals Settings Migration")
    print("-" * 46)
    try:
        db_url = get_database_url()
        print(f"Database: {db_url.split('://')[0]}://...")
        if "sqlite" in db_url:
            engine = create_engine(db_url, poolclass=NullPool)
        else:
            engine = create_engine(db_url)
        if args.status:
            status(engine)
            return 0
        apply(engine)
        status(engine)
        return 0
    except Exception as exc:
        print(f"  [X] Migration failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
