"""Recorded executions and actual reported charges; no cancelled-order inference."""

import csv
import io
import json
from decimal import Decimal as D
from hashlib import sha256

from database import neo_history_db as db

from .fees import FeePlan, estimate_charges, fill_key
from .history_accounting import IMMUTABLE, MAX_BYTES, MAX_ROWS, TradeArchive, _normalized


def ingest_fills(owner, rows, source="broker_report"):
    if len(rows) > MAX_ROWS:
        raise ValueError("Import exceeds 10,000 executions.")
    db.init_db()
    summary = {"inserted": 0, "duplicates": 0, "updated": 0, "ignored": 0}
    try:
        for raw in rows:
            if str(raw.get("quantity")) == "0":
                summary["ignored"] += 1
                continue
            row = _normalized(raw, True)
            identity = sha256(
                json.dumps([row[k] for k in ("exchange", "trade_date", "fill_id")]).encode()
            ).hexdigest()
            previous = db.db_session.get(db.NeoFill, (owner, identity))
            row["provenance"] = raw.get("provenance") or [{"kind": source, "name": source}]
            if previous:
                old = previous.payload
                if any(old[k] != row[k] for k in IMMUTABLE) or (
                    old["fees"] is not None
                    and row["fees"] is not None
                    and old["fees"] != row["fees"]
                ):
                    raise ValueError("Execution identity conflict; import was rolled back.")
                if old["fees"] is None and row["fees"] is not None:
                    previous.payload = {**old, "fees": row["fees"], "provenance": row["provenance"]}
                    summary["updated"] += 1
                else:
                    summary["duplicates"] += 1
            else:
                db.db_session.add(db.NeoFill(owner=owner, identity=identity, payload=row))
                summary["inserted"] += 1
        db.db_session.commit()
    except Exception:
        db.db_session.rollback()
        raise
    return summary


class NativeAccounting(TradeArchive):
    def __init__(self, owner):
        self.owner = owner

    def fills(self):
        db.init_db()
        return sorted(
            [
                dict(r.payload)
                for r in db.db_session.query(db.NeoFill).filter_by(owner=self.owner).all()
            ],
            key=lambda f: (f["time"], f["exchange"], f["fill_id"]),
        )


def history_page(owner_id, symbol="", start=None, end=None, cursor=0, cost_plan="trade_free"):
    if cost_plan not in ("free_offer", "trade_free"):
        raise ValueError("Choose the free-offer or Trade Free fee plan estimate.")
    account = NativeAccounting(owner_id)
    result = account.page(offset=int(cursor), symbol=symbol, start=start, end=end)
    summary = result["summary"]
    n = summary["fill_count"]
    summary["actual_fees"] = (
        summary["fees"] if n and summary["fees_known_fill_count"] == n else None
    )
    fills = [
        f
        for f in account.fills()
        if (not symbol or f["symbol"] == symbol)
        and (not start or f["trade_date"] >= start)
        and (not end or f["trade_date"] <= end)
    ]
    plan = FeePlan(brokerage=D(0) if cost_plan == "free_offer" else D(10))
    # Pairing retains the full archive even when the exit-date filter excludes entry fills.
    all_fills = account.fills()
    estimate = estimate_charges(fills, None, plan)
    all_estimate = estimate_charges(all_fills, None, plan)
    by_id = {fill_key(f): f for f in all_fills}
    allocated = all_estimate.get("per_fill", {})
    for row in result["rows"]:
        portions = []
        for side in ("entry", "exit"):
            key = "|".join(str(row[k]) for k in (side + "_trade_date", "exchange", side + "_fill_id"))
            f = by_id.get(key)
            if f and key in allocated:
                portions.append(D(allocated[key]) * row["quantity"] / f["quantity"])
        charge = sum(portions) if len(portions) == 2 else None
        row["estimated_fees"] = str(charge) if charge is not None else None
        row["estimated_net_pnl"] = str(D(row["gross_pnl"]) - charge) if row["gross_pnl"] is not None and charge is not None else None
    estimate["cost_plan"] = cost_plan
    summary["estimated_fees"] = estimate["total"] if n else None
    result["fee_estimate"] = estimate
    if not n:
        summary["gross_pnl"] = None
        summary["net_pnl"] = None
    return result


def import_csv(owner, text):
    if len(text.encode()) > MAX_BYTES:
        raise ValueError("CSV exceeds 5 MiB.")
    rows = list(csv.DictReader(io.StringIO(text)))
    return ingest_fills(owner, rows, source="execution_csv")


def export_csv(owner, symbol="", start=None, end=None):
    return NativeAccounting(owner).export_csv(symbol, start, end)


def refresh_history(owner):
    from database.auth_db import get_auth_token

    auth = get_auth_token(owner)
    if not auth:
        raise ValueError("Reconnect Kotak to refresh recorded executions.")
    # Native normalized trade book may omit execution identities; use official raw fills only.
    from broker.kotak.api.order_api import get_trade_book

    raw = get_trade_book(auth)
    records = raw.get("data", []) if isinstance(raw, dict) else []
    if not isinstance(records, list):
        raise ValueError("Broker execution envelope is unavailable.")
    return ingest_fills(owner, broker_rows(records), source="kotak_daily_api")


def broker_rows(records):
    result = []
    for original in records:
        row = dict(original)
        if row.get("flDt") and row.get("flTm"):
            row["time"] = f"{row['flDt']} {row['flTm']}"
            row.pop("exTm", None)
        row.pop("fees", None)  # Daily trade API does not report paid charges.
        result.append(row)
    return result
