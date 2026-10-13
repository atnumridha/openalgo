"""Preserved real observations; no expired-option synthesis or forward fills."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
from hashlib import sha256
import csv, json, re
from .types import Candle, Contract

ROOT = Path("runtime/neo_desk/migration-20261013/backup/data")


@dataclass
class HistoricalDataset:
    identity: str
    index: list
    contracts: dict
    options: dict
    calendar: list
    source: dict
    gaps: list


def list_datasets():
    result = []
    for path in ROOT.glob("*/manifest.json"):
        try:
            m = json.loads(path.read_text())
            if m.get("source", {}).get("synthetic") is not False or m.get("kind") != "ohlc_1m":
                continue
            if not all(
                k in m
                for k in ("calendar_start", "calendar_end", "contracts", "files", "expiry_calendar")
            ):
                continue
            result.append(
                dict(
                    id=path.parent.name,
                    source=m["source"],
                    start=m["calendar_start"],
                    end=m["calendar_end"],
                    expiries=m["expiry_calendar"],
                    gaps=m.get("gaps", []),
                )
            )
        except (ValueError, KeyError):
            continue
    return result


def load_dataset(identity):
    if (
        not isinstance(identity, str)
        or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", identity)
        or identity not in {x["id"] for x in list_datasets()}
    ):
        raise ValueError("Choose a preserved real dataset.")
    directory = ROOT / identity
    m = json.loads((directory / "manifest.json").read_text())
    tables = {}
    for item in m["files"]:
        name = item["path"]
        if name not in ("index.csv", "options.csv"):
            continue
        p = directory / name
        if sha256(p.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Dataset checksum mismatch; replay refused.")
        tables[item["kind"]] = p
    if "index_15m" not in tables or "option_1m" not in tables:
        raise ValueError("Index 15-minute and option 1-minute observations are required.")
    contracts = {
        c["symbol"]: Contract(
            c["symbol"],
            "NFO",
            date.fromisoformat(c["expiry"]),
            D(c["strike"]),
            c["option_type"],
            int(c["lot_size"]),
            D(c["tick_size"]),
        )
        for c in m["contracts"]
    }
    ids = {c["id"]: c["symbol"] for c in m["contracts"]}
    index = []
    options = {symbol: {} for symbol in contracts}

    def bar(row):
        stamp = datetime.fromisoformat(row["time"])
        if stamp.tzinfo is None:
            raise ValueError("Dataset timestamp needs timezone.")
        values = [D(row[k]) for k in ("open", "high", "low", "close")]
        if (
            any(not v.is_finite() or v <= 0 for v in values)
            or values[2] > min(values[0], values[3])
            or values[1] < max(values[0], values[3])
        ):
            raise ValueError("Invalid observed OHLC.")
        return Candle(
            stamp,
            *values,
            D(row.get("volume") or 0),
            repaired=row.get("repaired", "false").lower() == "true",
        )

    with tables["index_15m"].open(newline="") as f:
        for row in csv.DictReader(f):
            index.append(bar(row))
    with tables["option_1m"].open(newline="") as f:
        for row in csv.DictReader(f):
            symbol = ids.get(row["instrument_id"])
            if symbol:
                b = bar(row)
                if b.time in options[symbol]:
                    raise ValueError("Duplicate option minute; replay refused.")
                options[symbol][b.time] = b
    index.sort(key=lambda b: b.time)
    if len({b.time for b in index}) != len(index):
        raise ValueError("Duplicate index bar; replay refused.")
    return HistoricalDataset(
        identity,
        index,
        contracts,
        options,
        [date.fromisoformat(day) for day in m["calendar"]],
        m["source"],
        m.get("gaps", []),
    )
