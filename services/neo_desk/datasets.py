"""Preserved real observations; no expired-option synthesis or forward fills."""

import csv
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path

from .types import IST, Candle, Contract

ROOT = Path("runtime/neo_desk/migration-20261013/backup/data")
ARCHIVE_ROOT = Path("runtime/neo_desk/datasets")


def _manifest_paths():
    """New broker pulls stay separate from the preserved migration snapshot."""
    paths = {}
    for root in (ROOT, ARCHIVE_ROOT):
        for path in sorted(root.glob("*/manifest.json")):
            paths.setdefault(path.parent.name, []).append(path)
    # An identity collision must not replace the observations of an existing replay.
    return {name: matches[0] for name, matches in paths.items() if len(matches) == 1}


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
    for path in _manifest_paths().values():
        try:
            m = json.loads(path.read_text())
            if m.get("source", {}).get("synthetic") is not False or m.get("kind") != "ohlc_1m":
                continue
            if not all(
                k in m
                for k in ("calendar_start", "calendar_end", "contracts", "files", "expiry_calendar")
            ):
                continue
            if any(
                not c.get("symbol", "").startswith("NIFTY")
                or c.get("exchange") not in ("nse_fo", "NFO")
                for c in m["contracts"]
            ):
                continue
            if not {"index_15m", "option_1m"}.issubset({f.get("kind") for f in m["files"]}):
                continue
            required_files = {"index_15m": "index.csv", "option_1m": "options.csv"}
            if not all(
                any(
                    f.get("kind") == kind
                    and f.get("path") == filename
                    and re.fullmatch(r"[0-9a-f]{64}", str(f.get("sha256", "")))
                    and (path.parent / filename).is_file()
                    and (path.parent / filename).stat().st_size > 0
                    for f in m["files"]
                )
                for kind, filename in required_files.items()
            ):
                continue
            if not m["contracts"] or any(
                not c.get("valid_from")
                or not c.get("valid_to")
                or c["valid_from"] > m["calendar_end"]
                or c["valid_to"] < m["calendar_start"]
                for c in m["contracts"]
            ):
                continue
            result.append(
                {
                    "id": path.parent.name,
                    "source": m["source"],
                    "start": m["calendar_start"],
                    "end": m["calendar_end"],
                    "expiries": m["expiry_calendar"],
                    "gaps": m.get("gaps", []),
                }
            )
        except (ValueError, KeyError, TypeError, OSError):
            continue
    from .chart_archive import get_archive
    saved = get_archive().datasets()
    return list({item["id"]: item for item in result + saved}.values())


def load_dataset(identity):
    if (
        not isinstance(identity, str)
        or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", identity)
        or identity not in {x["id"] for x in list_datasets()}
    ):
        raise ValueError("Choose a preserved real dataset.")
    from .chart_archive import get_archive
    saved = get_archive().load_dataset(identity)
    if saved is not None:
        return saved
    directory = _manifest_paths()[identity].parent
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
    bounds = {
        c["symbol"]: (date.fromisoformat(c["valid_from"]), date.fromisoformat(c["valid_to"]))
        for c in m["contracts"]
    }
    for symbol, minutes in options.items():
        lower, upper = bounds[symbol]
        options[symbol] = {
            time: bar
            for time, bar in minutes.items()
            if lower <= time.astimezone(IST).date() <= upper
            and time.astimezone(IST).date() <= contracts[symbol].expiry
        }
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
