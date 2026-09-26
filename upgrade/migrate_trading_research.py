#!/usr/bin/env python3
"""Add independent risk and research evidence tables; preserve existing data."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import inspect

from database.engine_factory import create_db_engine
from upgrade.migrate_strategy_module import get_database_url


def metadata():
    # Load configuration before importing modules which construct DB engines.
    os.environ.setdefault("DATABASE_URL", get_database_url())
    from database.strategy_qualification_db import Base as QualificationBase
    from database.trading_research_db import Base as ResearchBase
    from database.trading_risk_db import Base as RiskBase

    return ResearchBase.metadata, RiskBase.metadata, QualificationBase.metadata


def status(engine):
    existing = set(inspect(engine).get_table_names())
    return all(name in existing for meta in metadata() for name in meta.tables)


def apply(engine):
    for meta in metadata():
        meta.create_all(engine, checkfirst=True)
    return status(engine)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Inspect without writing")
    args = parser.parse_args()
    engine = create_db_engine(get_database_url())
    try:
        ready = status(engine) if args.status else apply(engine)
        print(
            "Research, risk and qualification tables ready"
            if ready
            else "Research/risk/qualification migration required"
        )
        return 0 if ready else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
