"""Long-lived SQL candle archive and immutable, compressed replay source snapshots."""

import json
import zlib
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal as D
from functools import lru_cache
from hashlib import sha256

from sqlalchemy import text

from .types import IST, Candle, Contract


class ChartArchive:
    def __init__(self, engine=None):
        if engine is None:
            from database.neo_history_db import engine
        self.engine = engine
        with engine.begin() as connection:
            connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS neo_chart_candle (
              symbol TEXT NOT NULL, exchange TEXT NOT NULL, interval TEXT NOT NULL,
              timestamp INTEGER NOT NULL, trading_date TEXT NOT NULL, payload TEXT NOT NULL,
              captured_at TEXT NOT NULL, PRIMARY KEY(symbol,exchange,interval,timestamp))""")
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_neo_chart_dates ON neo_chart_candle(symbol,exchange,interval,trading_date)"
            )
            connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS neo_saved_dataset (
              id TEXT PRIMARY KEY, metadata TEXT NOT NULL, source TEXT NOT NULL,
              checksum TEXT NOT NULL, data BLOB NOT NULL, saved_at TEXT NOT NULL)""")
            for action in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS neo_dataset_no_{action.lower()} BEFORE {action} ON neo_saved_dataset BEGIN SELECT RAISE(ABORT,'Replay chart source is immutable'); END"
                )

    def save(self, symbol, exchange, interval, rows):
        if (
            not symbol
            or not exchange
            or interval not in ("1m", "3m", "5m", "10m", "15m", "30m", "1h", "D", "W")
        ):
            raise ValueError("Choose a supported candle identity and timeframe.")
        records = []
        for row in rows:
            timestamp = int(row["timestamp"])
            values = [D(str(row[k])) for k in ("open", "high", "low", "close")]
            if (
                any(not v.is_finite() or v <= 0 for v in values)
                or values[2] > min(values[0], values[3])
                or values[1] < max(values[0], values[3])
            ):
                raise ValueError("Invalid observed OHLC cannot be archived.")
            payload = {
                k: float(row.get(k) or 0) for k in ("open", "high", "low", "close", "volume", "oi")
            }
            payload.update(timestamp=timestamp, repaired=bool(row.get("repaired", False)))
            records.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "interval": interval,
                    "timestamp": timestamp,
                    "date": datetime.fromtimestamp(timestamp, IST).date().isoformat(),
                    "payload": json.dumps(payload, separators=(",", ":")),
                    "now": datetime.now(IST).isoformat(),
                }
            )
        if records:
            with self.engine.begin() as connection:
                connection.execute(
                    text("""INSERT INTO neo_chart_candle(symbol,exchange,interval,timestamp,trading_date,payload,captured_at)
                  VALUES(:symbol,:exchange,:interval,:timestamp,:date,:payload,:now)
                  ON CONFLICT(symbol,exchange,interval,timestamp) DO UPDATE SET payload=excluded.payload,captured_at=excluded.captured_at
                  WHERE neo_chart_candle.payload<>excluded.payload"""),
                    records,
                )
        return len(records)

    def read(self, symbol, exchange, interval, start, end):
        lower, upper = date.fromisoformat(start), date.fromisoformat(end)
        if lower > upper:
            raise ValueError("From date must be before Through date.")
        with self.engine.connect() as connection:
            return [
                json.loads(row[0])
                for row in connection.execute(
                    text(
                        "SELECT payload FROM neo_chart_candle WHERE symbol=:symbol AND exchange=:exchange AND interval=:interval AND trading_date BETWEEN :start AND :end ORDER BY timestamp"
                    ),
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "interval": interval,
                        "start": start,
                        "end": end,
                    },
                )
            ]

    def coverage(self):
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT symbol,exchange,interval,count(*) as count,min(trading_date) as start,max(trading_date) as end,max(captured_at) as last_saved FROM neo_chart_candle GROUP BY symbol,exchange,interval ORDER BY symbol,interval"
                    )
                ).mappings()
            ]

    def save_dataset(self, dataset, metadata):
        def candle(b):
            return {
                "time": b.time.isoformat(),
                **{k: str(getattr(b, k)) for k in ("open", "high", "low", "close", "volume")},
                "confirmed": b.confirmed,
                "repaired": b.repaired,
            }

        body = {
            "identity": dataset.identity,
            "index": [candle(b) for b in dataset.index],
            "contracts": {
                symbol: {
                    **asdict(c),
                    "expiry": c.expiry.isoformat(),
                    "strike": str(c.strike),
                    "tick_size": str(c.tick_size),
                }
                for symbol, c in dataset.contracts.items()
            },
            "options": {
                symbol: [candle(b) for b in sorted(minutes.values(), key=lambda b: b.time)]
                for symbol, minutes in dataset.options.items()
            },
            "calendar": [d.isoformat() for d in dataset.calendar],
            "source": dataset.source,
            "gaps": dataset.gaps,
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        checksum = sha256(raw).hexdigest()
        with self.engine.begin() as connection:
            old = connection.execute(
                text("SELECT checksum FROM neo_saved_dataset WHERE id=:id"),
                {"id": dataset.identity},
            ).scalar()
            if old:
                if old != checksum:
                    raise ValueError("Dataset identity conflicts with its immutable SQL snapshot.")
                return
            connection.execute(
                text(
                    "INSERT INTO neo_saved_dataset(id,metadata,source,checksum,data,saved_at) VALUES(:id,:metadata,:source,:checksum,:data,:saved_at)"
                ),
                {
                    "id": dataset.identity,
                    "metadata": json.dumps(metadata),
                    "source": json.dumps(dataset.source),
                    "checksum": checksum,
                    "data": zlib.compress(raw),
                    "saved_at": datetime.now(IST).isoformat(),
                },
            )

    def datasets(self):
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id,metadata,source FROM neo_saved_dataset ORDER BY id")
            ).all()
        return [
            {"id": r[0], **json.loads(r[1]), "source": json.loads(r[2]), "storage": "SQL"}
            for r in rows
            if json.loads(r[2]).get("synthetic") is False
        ]

    def load_dataset(self, identity):
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT checksum,data FROM neo_saved_dataset WHERE id=:id"), {"id": identity}
            ).first()
        if not row:
            return None
        raw = zlib.decompress(row[1])
        if sha256(raw).hexdigest() != row[0]:
            raise ValueError("SQL chart snapshot checksum mismatch; replay refused.")
        b = json.loads(raw)

        def candle(row):
            return Candle(
                datetime.fromisoformat(row["time"]),
                *[D(row[k]) for k in ("open", "high", "low", "close", "volume")],
                confirmed=row["confirmed"],
                repaired=row["repaired"],
            )

        from .datasets import HistoricalDataset

        return HistoricalDataset(
            b["identity"],
            [candle(row) for row in b["index"]],
            {
                s: Contract(
                    c["symbol"],
                    c["exchange"],
                    date.fromisoformat(c["expiry"]),
                    D(c["strike"]),
                    c["option_type"],
                    c["lot_size"],
                    D(c["tick_size"]),
                )
                for s, c in b["contracts"].items()
            },
            {
                s: {bar.time: bar for row in rows if (bar := candle(row))}
                for s, rows in b["options"].items()
            },
            [date.fromisoformat(d) for d in b["calendar"]],
            b["source"],
            b["gaps"],
        )


def save_observations(symbol, exchange, interval, rows):
    return get_archive().save(symbol, exchange, interval, rows)


@lru_cache(maxsize=1)
def get_archive():
    return ChartArchive()
