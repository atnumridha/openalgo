"""Automatic account capture, verified backups and saved-chart status, without orders."""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from database import neo_desk_db as desk
from database import neo_history_db as history
from database import sandbox_db as paper
from utils.db_sessions import remove_all_scoped_sessions
from utils.logging import get_logger

from .chart_archive import get_archive
from .sql_retention import MAIN_SPECS, PAPER_SPECS, install_journal, online_backup
from .types import IST

logger = get_logger(__name__)
BACKUP_ROOT = Path("runtime/neo_desk/sql-backups")


def initialize_retention():
    desk.init_db()
    history.init_db()
    install_journal(history.engine, MAIN_SPECS)
    install_journal(paper.engine, PAPER_SPECS)
    get_archive()
    with history.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS neo_storage_status (owner TEXT PRIMARY KEY,payload TEXT NOT NULL)"
        )


def record_status(owner, **changes):
    with history.engine.begin() as connection:
        old = connection.execute(
            text("SELECT payload FROM neo_storage_status WHERE owner=:owner"), {"owner": owner}
        ).scalar()
        payload = {**(json.loads(old) if old else {}), **changes}
        connection.execute(
            text(
                "INSERT INTO neo_storage_status(owner,payload) VALUES(:owner,:payload) ON CONFLICT(owner) DO UPDATE SET payload=excluded.payload"
            ),
            {"owner": owner, "payload": json.dumps(payload)},
        )


def sync_pass():
    from database.auth_db import get_auth_token

    from .history import refresh_history

    try:
        owners = [row[0] for row in desk.db_session.query(desk.NeoDesk.owner).all()]
        for owner in owners:
            if not get_auth_token(owner):
                record_status(
                    owner,
                    sync_error="Broker session unavailable. Saved SQL history remains readable.",
                    checked_at=datetime.now(IST).isoformat(),
                )
                continue
            try:
                result = refresh_history(owner)
                record_status(
                    owner,
                    sync_error=None,
                    last_capture=datetime.now(IST).isoformat(),
                    last_capture_result=result,
                )
            except Exception:
                logger.warning(
                    "Automatic broker history capture did not complete; existing SQL archive retained."
                )
                record_status(
                    owner,
                    sync_error="Automatic broker history capture failed. Check the broker session; saved records are retained.",
                    checked_at=datetime.now(IST).isoformat(),
                )
    finally:
        remove_all_scoped_sessions()


def chart_capture_pass():
    from .trade_replay import capture_trade_charts

    try:
        owners = [r[0] for r in desk.db_session.query(desk.NeoDesk.owner).all()]
        for owner in owners:
            try:
                capture_trade_charts(owner)
                record_status(
                    owner,
                    trade_chart_error=None,
                    last_trade_chart_capture=datetime.now(IST).isoformat(),
                )
            except Exception:
                record_status(
                    owner,
                    trade_chart_error="Some traded instruments could not be captured. Saved charts remain readable.",
                )
    finally:
        remove_all_scoped_sessions()


def backup_pass():
    try:
        paths = []
        for label, engine in (("trading", history.engine), ("sandbox", paper.engine)):
            path = online_backup(engine, BACKUP_ROOT / "latest" / (label + ".db"))
            paths.append(path.name)
        record_status(
            "*", backup_error=None, last_backup=datetime.now(IST).isoformat(), backup_files=paths
        )
    except Exception:
        logger.exception("Verified SQL backup did not complete")
        record_status(
            "*",
            backup_error="SQL backup did not complete. Existing trading history is retained; retry backup.",
        )
    finally:
        remove_all_scoped_sessions()


def start_retention_jobs():
    from services.strategy_module.scheduler import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        raise RuntimeError("SQL history scheduler is unavailable.")
    scheduler.add_job(
        sync_pass,
        "interval",
        seconds=60,
        id="neo-history-capture",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(IST),
    )
    scheduler.add_job(
        chart_capture_pass,
        "interval",
        minutes=5,
        id="neo-trade-chart-capture",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(IST),
    )
    scheduler.add_job(
        backup_pass,
        "interval",
        minutes=60,
        id="neo-sql-backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(IST),
    )


def storage_status(owner):
    with history.engine.connect() as connection:
        statuses = {
            r[0]: json.loads(r[1])
            for r in connection.execute(
                text("SELECT owner,payload FROM neo_storage_status WHERE owner IN (:owner,'*')"),
                {"owner": owner},
            )
        }
        live_count = connection.execute(
            text("SELECT count(*) FROM neo_recorded_fill WHERE owner=:owner"), {"owner": owner}
        ).scalar()
        events = connection.execute(
            text("SELECT count(*) FROM neo_sql_journal WHERE owner=:owner"), {"owner": owner}
        ).scalar()
    with paper.engine.connect() as connection:
        paper_count = connection.execute(
            text(
                "SELECT count(DISTINCT source_key) FROM neo_sql_journal WHERE owner=:owner AND source_table='sandbox_trades'"
            ),
            {"owner": owner},
        ).scalar()
    return {
        "backend": "SQL · SQLite",
        "retention": "No automatic deletion of stored trade or candle history",
        "live_fills": live_count,
        "paper_fills": paper_count,
        "history_events": events,
        "charts": get_archive().coverage(),
        "datasets": get_archive().datasets(),
        **statuses.get("*", {}),
        **statuses.get(owner, {}),
    }


def saved_chart(symbol, exchange, interval, start, end):
    if interval == "1d":
        interval = "D"
    rows = get_archive().read(symbol, exchange, interval, start, end)
    return {
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "interval": "1d" if interval == "D" else interval,
        "source": "SQL saved history",
        "historical_only": True,
        "requested_start": start,
        "requested_end": end,
        "date": end if rows else None,
        "candles": [
            {
                "time": r["timestamp"] + 19800,
                **{k: r[k] for k in ("open", "high", "low", "close", "volume")},
            }
            for r in rows
        ],
    }
