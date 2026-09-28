#!/usr/bin/env python3
"""Backfill verified Kotak MCX quote units without changing order quantities.

Only Kotak's mcx_fo rows for the four verified mini contracts are eligible.
Missing values and the historical default 1 are repaired; changed lot sizes
or conflicting non-default values stop the migration before any writes.
Run with --status to inspect without changing rows.
"""

import argparse
import math
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy import bindparam, inspect, text

from database.engine_factory import create_db_engine
from services.risk.contract_units import SUPPORTED_MCX_ROOTS, mcx_contract_multiplier


def get_database_url():
    """Resolve the same database from the project or upgrade working directory."""
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
    prefix = "sqlite:///"
    if url.startswith(prefix):
        path = url[len(prefix) :]
        if path != ":memory:" and not os.path.isabs(path):
            return prefix + os.path.join(PROJECT_ROOT, path).replace("\\", "/")
    return url


def _pending(connection):
    inspector = inspect(connection)
    if not inspector.has_table("symtoken"):
        return []
    columns = {column["name"] for column in inspector.get_columns("symtoken")}
    if "contract_value" not in columns:
        raise ValueError("Run migrate_contract_value.py before the Kotak MCX migration")
    query = text(
        "SELECT id, name, lotsize, contract_value FROM symtoken "
        "WHERE exchange='MCX' AND brexchange='mcx_fo' AND name IN :roots"
    ).bindparams(bindparam("roots", expanding=True))
    pending = []
    for row in connection.execute(query, {"roots": sorted(SUPPORTED_MCX_ROOTS)}).mappings():
        factor = mcx_contract_multiplier(row["name"], row["lotsize"])
        value = row["contract_value"]
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Invalid MCX contract units on symbol row {row['id']}") from exc
            if not math.isfinite(value) or value not in (1.0, factor):
                raise ValueError(f"Conflicting MCX contract units on symbol row {row['id']}")
        if value != factor:
            pending.append({"id": row["id"], "factor": factor})
    return pending


def status(engine):
    """Return whether all eligible rows already carry verified quote units."""
    with engine.connect() as connection:
        return not _pending(connection)


def apply(engine):
    """Validate the entire eligible batch before updating it atomically."""
    with engine.begin() as connection:
        pending = _pending(connection)
        if pending:
            connection.execute(
                text("UPDATE symtoken SET contract_value=:factor WHERE id=:id"), pending
            )
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Inspect without writing")
    args = parser.parse_args()
    engine = create_db_engine(get_database_url())
    try:
        ready = status(engine) if args.status else apply(engine)
        print(
            "Kotak MCX contract units ready" if ready else "Kotak MCX contract units need migration"
        )
        return 0 if ready else 1
    except Exception as exc:
        print(f"Kotak MCX contract units migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
