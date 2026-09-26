#!/usr/bin/env python3
"""Add durable sandbox profit-comparison records without modifying run data."""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import _pragmas  # noqa: F401,E402
from sqlalchemy import inspect

from database.engine_factory import create_db_engine
from database.profit_comparison_db import Base, Comparison
from upgrade.migrate_strategy_module import get_database_url


def status(engine) -> bool:
    """Read-only preview of whether the comparison table is present."""
    present = Comparison.__tablename__ in inspect(engine).get_table_names()
    print(f"  {Comparison.__tablename__}: {'present' if present else 'MISSING'}")
    return present


def apply(engine) -> bool:
    """Create the table and unique index once; preserve any existing rows."""
    Base.metadata.create_all(bind=engine, checkfirst=True)
    return status(engine)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    engine = create_db_engine(get_database_url())
    try:
        ready = status(engine) if args.status else apply(engine)
        return 0 if ready else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
