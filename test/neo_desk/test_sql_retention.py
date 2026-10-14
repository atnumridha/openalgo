from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from database import sandbox_db as paper
from services.neo_desk.sql_retention import (
    PAPER_SPECS,
    install_journal,
    journal_rows,
    online_backup,
)


@pytest.fixture
def database(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "paper.db"))
    paper.Base.metadata.create_all(engine)
    install_journal(engine, PAPER_SPECS)
    return engine


def add_fill(connection, trade="t1", owner="owner", day="2026-10-09", side="BUY", price=50):
    connection.execute(
        text("""INSERT INTO sandbox_trades
      (tradeid,orderid,user_id,symbol,exchange,action,quantity,price,product,trade_timestamp)
      VALUES (:trade,:trade,:owner,'NIFTY13OCT2622500CE','NFO',:side,65,:price,'NRML',:stamp)"""),
        {"trade": trade, "owner": owner, "side": side, "price": price, "stamp": day + " 10:00:00"},
    )


def test_transaction_rollback_cannot_leave_a_fictional_fill(database):
    with database.connect() as connection:
        transaction = connection.begin()
        add_fill(connection)
        transaction.rollback()
    assert journal_rows(database, "owner", source="sandbox_trades") == []


def test_history_survives_deleted_source_and_new_connection(database):
    with database.begin() as connection:
        add_fill(connection)
        connection.execute(text("DELETE FROM sandbox_trades"))
    database.dispose()
    rows = journal_rows(database, "owner", source="sandbox_trades")
    assert len(rows) == 1 and rows[0]["payload"]["tradeid"] == "t1"
    assert rows[0]["trading_date"] == "2026-10-09"


def test_any_date_filter_and_owner_partition_are_enforced(database):
    with database.begin() as connection:
        add_fill(connection, "a", day="2025-10-09")
        add_fill(connection, "b", day="2026-10-09")
        add_fill(connection, "foreign", owner="someone-else")
    assert [
        r["payload"]["tradeid"]
        for r in journal_rows(
            database, "owner", source="sandbox_trades", start="2025-10-09", end="2025-10-09"
        )
    ] == ["a"]
    with pytest.raises(ValueError):
        journal_rows(database, "owner", start="2026-10-09", end="2025-10-09")


def test_duplicate_updates_do_not_double_count_and_journal_is_append_only(database):
    with database.begin() as connection:
        add_fill(connection)
        connection.execute(text("UPDATE sandbox_trades SET price=50 WHERE tradeid='t1'"))
    assert len(journal_rows(database, "owner", source="sandbox_trades")) == 1
    with pytest.raises(Exception, match="append.only"):
        with database.begin() as connection:
            connection.execute(text("DELETE FROM neo_sql_journal"))


def test_verified_online_backup_includes_wal_commits(database, tmp_path):
    with database.begin() as connection:
        connection.execute(text("PRAGMA wal_autocheckpoint=0"))
        add_fill(connection)
    target = online_backup(database, tmp_path / "backup.db")
    restored = create_engine("sqlite:///" + str(target))
    assert len(journal_rows(restored, "owner", source="sandbox_trades")) == 1
    assert target.stat().st_mode & 0o777 == 0o600


def test_sql_chart_candles_survive_restart_and_have_no_one_year_purge(tmp_path):
    from services.neo_desk.chart_archive import ChartArchive

    engine = create_engine("sqlite:///" + str(tmp_path / "charts.db"))
    archive = ChartArchive(engine)
    rows = [
        {"timestamp": 1728452700, "open": 50, "high": 51, "low": 49, "close": 50, "volume": 100}
    ]
    archive.save("NIFTY", "NSE_INDEX", "15m", rows)
    engine.dispose()
    reopened = ChartArchive(engine)
    result = reopened.read("NIFTY", "NSE_INDEX", "15m", "2024-10-09", "2024-10-09")
    assert len(result) == 1 and result[0]["close"] == 50
    assert reopened.coverage()[0]["count"] == 1


def test_saved_dataset_reproduces_chart_after_csv_source_disappears(tmp_path):
    from test_replay import fixture

    from services.neo_desk.chart_archive import ChartArchive

    engine = create_engine("sqlite:///" + str(tmp_path / "charts.db"))
    archive = ChartArchive(engine)
    data = fixture()
    archive.save_dataset(
        data, {"start": "2026-10-13", "end": "2026-10-13", "expiries": ["2026-10-13"]}
    )
    engine.dispose()
    saved = ChartArchive(engine).load_dataset(data.identity)
    assert (
        saved.index == data.index
        and saved.options == data.options
        and saved.contracts == data.contracts
    )


def test_paper_report_matches_full_inventory_then_filters_exit_date(database, monkeypatch):
    from services.neo_desk.history import history_page

    monkeypatch.setattr(paper, "engine", database)
    with database.begin() as connection:
        add_fill(connection, "entry", day="2026-10-08")
        add_fill(connection, "exit", day="2026-10-09", side="SELL", price=60)
        connection.execute(text("DELETE FROM sandbox_trades"))
    result = history_page("owner", start="2026-10-09", end="2026-10-09", mode="sandbox")
    assert result["mode"] == "sandbox"
    assert D(result["summary"]["gross_pnl"]) == 650
    assert result["summary"]["fill_count"] == 1
    assert result["coverage"]["recorded_dates"] == ["2026-10-08", "2026-10-09"]
    assert history_page("someone-else", mode="sandbox")["coverage"]["fill_count"] == 0


def test_durable_engine_fsyncs_committed_trading_records(tmp_path):
    from database.engine_factory import create_db_engine, enable_durable_writes

    engine = create_db_engine("sqlite:///" + str(tmp_path / "durable.db"))
    enable_durable_writes(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA synchronous").scalar() == 2


def test_dataset_registry_can_reopen_a_sql_snapshot_without_its_files(tmp_path, monkeypatch):
    from test_replay import fixture

    import services.neo_desk.datasets as registry
    from services.neo_desk.chart_archive import ChartArchive

    archive = ChartArchive(create_engine("sqlite:///" + str(tmp_path / "charts.db")))
    data = fixture()
    from dataclasses import replace

    data = replace(data, source={"synthetic": False, "name": "unit market snapshot"})
    archive.save_dataset(
        data, {"start": "2026-10-13", "end": "2026-10-13", "expiries": ["2026-10-13"], "gaps": []}
    )
    monkeypatch.setattr(registry, "ROOT", tmp_path / "missing-backup")
    monkeypatch.setattr(registry, "ARCHIVE_ROOT", tmp_path / "missing-download")
    monkeypatch.setattr("services.neo_desk.chart_archive.get_archive", lambda: archive)
    assert registry.list_datasets()[0]["storage"] == "SQL"
    assert registry.load_dataset(data.identity).options == data.options


def test_native_execution_history_survives_strategy_deletion(tmp_path):
    from sqlalchemy.orm import Session

    from database import neo_desk_db, neo_history_db
    from database import strategy_module_db as native
    from services.neo_desk.sql_retention import MAIN_SPECS

    engine = create_engine("sqlite:///" + str(tmp_path / "native.db"))
    for base in (native.Base, neo_desk_db.Base, neo_history_db.Base):
        base.metadata.create_all(engine)
    install_journal(engine, MAIN_SPECS)
    with Session(engine) as session:
        strategy = native.SmStrategy(
            user_id="owner",
            name="retention",
            universe_tab="fno",
            underlying="NIFTY",
            underlying_exchange="NSE_INDEX",
            webhook_token_hash="test-only-hash",
        )
        session.add(strategy)
        session.flush()
        run = native.SmStrategyRun(strategy_id=strategy.id, mode="sandbox")
        session.add(run)
        session.flush()
        session.add(
            native.SmStrategyOrder(
                run_id=run.id,
                leg_id=1,
                kind="entry",
                symbol="NIFTY13OCT2622500CE",
                exchange="NFO",
                action="BUY",
                qty=65,
                filled_qty=65,
                avg_fill_price=50,
                status="complete",
            )
        )
        session.commit()
        session.query(native.SmStrategyOrder).delete()
        session.query(native.SmStrategyRun).delete()
        session.query(native.SmStrategy).delete()
        session.commit()
    rows = journal_rows(engine, "owner", source="sm_strategy_order", mode="sandbox")
    assert len(rows) == 1 and rows[0]["payload"]["filled_qty"] == 65
