"""Read-only replay of owner-bound executed fills and their recorded protection."""

import json
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import inspect, text

from database import neo_history_db as db

from .chart_archive import get_archive
from .history import NativeAccounting, PaperAccounting
from .types import IST


def chart_identity(symbol, exchange):
    """Translate broker identities for chart lookup without rewriting execution facts."""
    native = {"nse_fo": "NFO", "bse_fo": "BFO", "nse_cm": "NSE", "bse_cm": "BSE"}.get(
        exchange.lower()
    )
    if native:
        from database.token_db import get_oa_symbol

        return get_oa_symbol(symbol, native) or symbol, native
    return symbol, exchange


def _table():
    with db.engine.begin() as c:
        c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS neo_trade_replay_chart (
            owner TEXT NOT NULL, identity TEXT NOT NULL, payload TEXT NOT NULL,
            saved_at TEXT NOT NULL, PRIMARY KEY(owner,identity))""")


def _bars(owner, symbol, exchange, start, end, fetch=True):
    symbol, exchange = chart_identity(symbol, exchange)
    archive = get_archive()
    rows = archive.read(symbol, exchange, "1m", start, end)
    # Existing SQL observations remain usable when the broker session or contract expires.
    if (
        fetch
        and not rows
        and (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days <= 29
    ):
        from database.auth_db import get_auth_token
        from services.history_service import get_history

        auth = get_auth_token(owner)
        if auth:
            try:
                ok, result, _ = get_history(
                    symbol,
                    exchange,
                    "1m",
                    start,
                    end,
                    auth_token=auth,
                    broker="kotak",
                    background=True,
                )
                if ok:
                    archive.save(symbol, exchange, "1m", result.get("data", []))
                    rows = archive.read(symbol, exchange, "1m", start, end)
            except Exception:
                # No raw broker response or credential is returned to the UI.
                pass
    return [
        {"time": r["timestamp"], **{k: r[k] for k in ("open", "high", "low", "close", "volume")}}
        for r in rows
    ]


def _protection(owner, mode, row, fills):
    """Never attach the current preset/position or another account's risk to a past fill."""
    if not inspect(db.engine).has_table("neo_sql_journal"):
        return [], None
    entry = next(
        (
            f
            for f in fills
            if f["fill_id"] == row["entry_fill_id"]
            and f["trade_date"] == row["entry_trade_date"]
            and f["exchange"] == row["exchange"]
        ),
        None,
    )
    if not entry:
        return [], None
    symbol, exchange = chart_identity(row["symbol"], row["exchange"])
    with db.engine.connect() as c:
        orders = c.execute(
            text("""SELECT payload FROM neo_sql_journal
            WHERE owner=:owner AND mode=:mode AND source_table='sm_strategy_order'
            AND json_extract(payload,'$.broker_order_id')=:order_id
            AND json_extract(payload,'$.symbol')=:symbol
            AND json_extract(payload,'$.exchange')=:exchange"""),
            {
                "owner": owner,
                "mode": mode,
                "order_id": entry["order_id"],
                "symbol": symbol,
                "exchange": exchange,
            },
        ).all()
        run_ids = {json.loads(o[0])["run_id"] for o in orders}
        if len(run_ids) != 1:
            return [], None
        run_id = next(iter(run_ids))
        records = c.execute(
            text("""SELECT recorded_at,payload,change_kind FROM neo_sql_journal
            WHERE owner=:owner AND source_table='neo_run_protection'
            AND json_extract(payload,'$.run_id')=:run ORDER BY id"""),
            {"owner": owner, "run": run_id},
        ).all()
    trail, profile = [], None
    end = datetime.fromisoformat(row["exit_time"])
    start = datetime.fromisoformat(row["entry_time"])
    for stamp, raw, kind in records:
        p = json.loads(raw)["protection"]
        p = json.loads(p) if isinstance(p, str) else p
        profile = p.get("profile") or profile
        # A startup snapshot has no reliable historical change time. Do not backdate it.
        if kind not in ("insert", "update"):
            continue
        at = datetime.fromisoformat(stamp).astimezone(IST)
        if start - timedelta(minutes=1) <= at <= end:
            trail.append(
                {
                    "time": int(at.timestamp()),
                    "option_stop": p.get("option_stop"),
                    "option_target": p.get("option_target"),
                    "index_stop": p.get("index_stop"),
                    "index_target": p.get("target"),
                    "index_reference": p.get("index_reference"),
                    "net_floor": p.get("net_floor"),
                }
            )
    return trail, profile


def trade_replay(owner, trade_id, mode="live", fetch=True):
    if mode not in ("live", "sandbox") or not isinstance(trade_id, str) or len(trade_id) > 1000:
        raise ValueError("Choose an exact recorded Live or Sandbox trade.")
    account = NativeAccounting(owner) if mode == "live" else PaperAccounting(owner)
    fills = account.fills()
    rows, _ = account._match(fills)
    row = next((r for r in rows if r["trade_id"] == trade_id), None)
    if row is None:
        raise ValueError("Recorded trade was not found for this account and mode.")
    start, end = row["entry_trade_date"], row["exit_trade_date"]
    _table()
    identity = sha256((mode + "\0" + trade_id).encode()).hexdigest()
    with db.engine.connect() as c:
        old = c.execute(
            text("SELECT payload FROM neo_trade_replay_chart WHERE owner=:owner AND identity=:id"),
            {"owner": owner, "id": identity},
        ).scalar()
    saved = json.loads(old) if old else None
    if saved and saved["coverage"]["complete"]:
        return saved
    option = _bars(owner, row["symbol"], row["exchange"], start, end, fetch)
    underlying = (
        "SENSEX"
        if row["symbol"].startswith("SENSEX")
        else "NIFTY"
        if row["symbol"].startswith("NIFTY")
        else None
    )
    index = (
        _bars(
            owner,
            underlying,
            "BSE_INDEX" if underlying == "SENSEX" else "NSE_INDEX",
            start,
            end,
            fetch,
        )
        if underlying
        else []
    )
    trail, profile = _protection(owner, mode, row, fills)
    stamps = {b["time"] for b in option}
    first = int(datetime.fromisoformat(row["entry_time"]).timestamp()) // 60 * 60
    last = int(datetime.fromisoformat(row["exit_time"]).timestamp()) // 60 * 60
    missing = [
        t
        for t in range(first, last + 1, 60)
        if t not in stamps
        and 555
        <= (datetime.fromtimestamp(t, IST).hour * 60 + datetime.fromtimestamp(t, IST).minute)
        < 930
        and datetime.fromtimestamp(t, IST).weekday() < 5
    ]
    notes = []
    if not option:
        notes.append(
            "No saved option candles for this trade. Kotak may not return expired contracts; fill prices remain recorded."
        )
    elif missing:
        notes.append(
            f"{len(missing)} option minutes are missing between the recorded entry and exit. Gaps are not filled or interpolated."
        )
    if not trail:
        notes.append(
            "SL, target and trailing changes were not recorded for this trade. Current strategy settings are not applied retrospectively."
        )
    if row["status"] not in ("closed", "partial_close"):
        notes.append(
            "Execution sequence or opening inventory is unresolved. Markers show reported fills, not a verified P&L match."
        )
    result = {
        "source": "Recorded "
        + ("Kotak Live" if mode == "live" else "Sandbox")
        + " fills · SQL saved chart",
        "mode": mode,
        "trade_id": trade_id,
        "saved_at": datetime.now(IST).isoformat(),
        "coverage": {"complete": bool(option) and not missing, "gaps": notes},
        "trade": {
            "symbol": row["symbol"],
            "direction": "PE"
            if row["symbol"].endswith("PE")
            else "CE"
            if row["symbol"].endswith("CE")
            else "",
            "profile": profile,
            "entry_side": row["entry_side"],
            "entry_time": row["entry_time"],
            "exit_time": row["exit_time"],
            "entry_price": row["entry_price"],
            "exit_price": row["exit_price"],
            "quantity": row["quantity"],
            "status": row["status"],
            "net": row["net_pnl"],
            "reason": "Recorded execution",
            "initial_index_stop": None,
            "index_target": None,
            "index_reference": None,
            "initial_option_stop": None,
            "option_target": None,
            "option_bars": option,
            "index_bars": index,
            "trail": trail,
            "underlying": underlying,
            "recorded": True,
        },
    }
    # Closed replay snapshots survive contract expiry and application restart. A later
    # successful capture may enrich a previously incomplete snapshot.
    if option:
        with db.engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO neo_trade_replay_chart(owner,identity,payload,saved_at) VALUES(:owner,:id,:payload,:stamp) ON CONFLICT(owner,identity) DO UPDATE SET payload=excluded.payload,saved_at=excluded.saved_at"
                ),
                {
                    "owner": owner,
                    "id": identity,
                    "payload": json.dumps(result),
                    "stamp": result["saved_at"],
                },
            )
    return result


def capture_trade_charts(owner):
    """Capture all today's filled instruments before they expire; never sends orders."""
    from database.auth_db import get_auth_token
    from services.history_service import get_history

    auth = get_auth_token(owner)
    if not auth:
        return
    today = datetime.now(IST).date().isoformat()
    symbols = {
        (f["symbol"], f["exchange"])
        for account in (NativeAccounting(owner), PaperAccounting(owner))
        for f in account.fills()
        if f["trade_date"] == today
    }
    failed = False
    for symbol, exchange in sorted(symbols):
        symbol, exchange = chart_identity(symbol, exchange)
        ok, result, _ = get_history(
            symbol, exchange, "1m", today, today, auth_token=auth, broker="kotak", background=True
        )
        if ok:
            get_archive().save(symbol, exchange, "1m", result.get("data", []))
        else:
            failed = True
    if failed:
        raise ValueError(
            "Some traded instruments could not be captured. Previously saved charts remain readable."
        )
