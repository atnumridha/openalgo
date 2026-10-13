import sqlite3

from test_history import OWNER, fill, isolated

from services.neo_desk.history import history_page
from services.neo_desk.migration import migrate_archive


def test_migration_dry_run_then_idempotent_import(tmp_path):
    p = tmp_path / "fills.sqlite"
    with sqlite3.connect(p) as c:
        c.execute(
            "CREATE TABLE fills (fill_id TEXT,order_id TEXT,symbol TEXT,exchange TEXT,product TEXT,side TEXT,quantity INTEGER,price TEXT,fees TEXT,time TEXT)"
        )
        f = fill("a")
        c.execute(
            "INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?)",
            tuple(
                f[k]
                for k in (
                    "fill_id",
                    "order_id",
                    "symbol",
                    "exchange",
                    "product",
                    "side",
                    "quantity",
                    "price",
                    "fees",
                    "time",
                )
            ),
        )
    preview = migrate_archive(p, OWNER, dry_run=True)
    assert preview["source_fills"] == 1 and history_page(OWNER)["coverage"]["fill_count"] == 0
    assert migrate_archive(p, OWNER)["inserted"] == 1
    assert migrate_archive(p, OWNER)["inserted"] == 0
