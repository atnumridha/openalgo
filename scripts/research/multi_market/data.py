"""Read-only, bounded history snapshots for offline strategy research."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

IST = "Asia/Kolkata"
INDEX_DB = Path("/Users/nmandal/.codex/worktrees/neo-native/openalgo/db/openalgo.db")


def clean_minutes(raw, indian):
    d = raw.rename(columns={"timestamp": "time"}).copy()
    initial = len(d)
    d["time"] = pd.to_numeric(d.time, errors="coerce")
    for k in ["open", "high", "low", "close"]:
        d[k] = pd.to_numeric(d[k], errors="coerce")
    good = np.isfinite(d[["time", "open", "high", "low", "close"]]).all(axis=1)
    good &= (
        (d.low > 0)
        & (d.low <= d[["open", "close"]].min(axis=1))
        & (d.high >= d[["open", "close"]].max(axis=1))
    )
    good &= ~d.get("repaired", pd.Series(False, index=d.index)).fillna(False).astype(bool)
    good &= d.time.mod(60).eq(0)
    d = d[good].sort_values("time")
    duplicate = int(d.time.duplicated().sum())
    # Conflicting duplicate observations are unusable, not chosen by arrival order.
    d = d.drop_duplicates("time", keep=False)
    outside = 0
    if indian:
        t = pd.to_datetime(d.time, unit="s", utc=True).dt.tz_convert(IST)
        mins = t.dt.hour * 60 + t.dt.minute
        keep = (t.dt.dayofweek < 5) & (mins >= 555) & (mins < 930)
        outside = int((~keep).sum())
        d = d[keep]
    d["time"] = d.time.astype("int64")
    d["volume"] = (
        pd.to_numeric(d.get("volume", 0), errors="coerce").fillna(0).clip(lower=0)
        if "volume" in d
        else 0
    )
    d = d[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    return d, dict(
        raw_rows=initial,
        invalid_or_repaired=int((~good).sum()),
        duplicate_times=duplicate,
        out_of_session=outside,
        usable_rows=len(d),
    )


def resample_complete(d, minutes, indian):
    d = d.copy()
    # Midnight UTC for BTC; 09:15 IST is aligned for 5m/15m Indian bars.
    origin = 0 if not indian else 225 * 60
    d["bucket"] = (d.time - origin) // (minutes * 60) * (minutes * 60) + origin
    g = d.groupby("bucket", sort=True)
    b = g.agg(
        time=("time", "min"),
        last=("time", "max"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        count=("time", "size"),
    )
    b = b[
        (b["count"] == minutes) & (b.time == b.index) & (b["last"] == b.time + (minutes - 1) * 60)
    ].copy()
    b["end"] = b.time + minutes * 60
    return b.drop(columns=["last", "count"]).reset_index(drop=True)


def snapshot(root, out):
    out.mkdir(parents=True, exist_ok=True)
    datasets = {}
    coverage = {}
    start = int(pd.Timestamp("2026-04-20", tz=IST).timestamp())
    end = int(pd.Timestamp("2026-10-17", tz=IST).timestamp())
    raw = pd.read_parquet(root / "db/ml_signals/delta_btcusd.parquet")
    raw = raw[(raw.time >= start) & (raw.time < end)]
    datasets["BTCUSD"], coverage["BTCUSD"] = clean_minutes(raw, False)
    with closing(sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)) as con:
        for sym in ["NIFTY", "BANKNIFTY", "SENSEX"]:
            rows = [
                json.loads(r[0])
                for r in con.execute(
                    "SELECT payload FROM neo_chart_candle WHERE symbol=? AND interval='1m' AND timestamp>=? AND timestamp<? ORDER BY timestamp",
                    (sym, start, end),
                )
            ]
            datasets[sym], coverage[sym] = clean_minutes(pd.DataFrame(rows), True)
    for sym, d in datasets.items():
        days = pd.to_datetime(d.time, unit="s", utc=True).dt.tz_convert(IST).dt.strftime("%Y-%m-%d")
        daily = d.groupby(days).size()
        # Freeze everything, including incomplete sessions. Execution stops at gaps.
        dest = out / (sym + ".parquet")
        d.to_parquet(dest, index=False)
        coverage[sym].update(
            first_ist=pd.Timestamp(int(d.time.iloc[0]), unit="s", tz="UTC")
            .tz_convert(IST)
            .isoformat(),
            last_ist=pd.Timestamp(int(d.time.iloc[-1]), unit="s", tz="UTC")
            .tz_convert(IST)
            .isoformat(),
            sessions=len(daily),
            daily_minutes={str(k): int(v) for k, v in daily.items()},
            sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
            source="Delta BTCUSD stored historical API candles"
            if sym == "BTCUSD"
            else "Kotak Neo saved chart candles",
            missing_minutes_within_observed_sessions=int(
                sum(max(0, (1440 if sym == "BTCUSD" else 375) - n) for n in daily)
            ),
            zero_volume_rows=int((d.volume == 0).sum()),
        )
    (out / "coverage.json").write_text(json.dumps(coverage, indent=2))
    return datasets, coverage
