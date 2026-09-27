"""Evaluate the frozen EMA9/15 hypothesis offline; no order or broker access.

UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/research_ema_scalp.py \
    --output data/research/ema-scalp-2026-09-26
"""

import argparse
import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb
import numpy as np
import pandas as pd

from services.research.ema_scalp import (
    chart_outcome,
    indicators,
    option_outcome,
    select_itm,
    signals,
    summarize,
)

FIRST, LAST = "2025-01-01", "2026-04-23"
DATA = ROOT / "data/research/five-minute-2026-09-26"
SOURCE = ROOT / "data/research/ema-scalp-2026-09-26-source"
PLAN = ROOT / "docs/plans/2026-09-26-ema-scalping-evaluation.md"
MAIN = "slope0.1-confirm1-hold15"
SCENARIOS = {
    "base": {"slippage_bps": 10, "brokerage_per_order": 0},
    "stress": {"slippage_bps": 30, "brokerage_per_order": 20},
}


def read_json(path):
    with path.open() as stream:
        return json.load(stream)


def write_json(path, value):
    with path.open("w") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def screen_broker(paths, minutes):
    records = []
    for path in paths:
        for row in read_json(path)["raw_candles"]:
            if len(row) not in (6, 7):
                raise ValueError("Unknown broker candle schema")
            records.append(
                dict(zip(["start", "open", "high", "low", "close"], row[:5], strict=True))
            )
    f = pd.DataFrame(records)
    f["start"] = pd.to_datetime(f.start, utc=True).dt.tz_convert("Asia/Kolkata")
    # Cutoff before screening, features or outcomes; never load reserved data into a study table.
    f = f[f.start.dt.strftime("%Y-%m-%d") <= LAST].copy()
    for key in ("open", "high", "low", "close"):
        f[key] = pd.to_numeric(f[key], errors="coerce")
    count = len(f)
    f = f.drop_duplicates()
    duplicates = count - len(f)
    conflict = f.start.duplicated(keep=False)
    clock = f.start.dt.hour * 60 + f.start.dt.minute
    good = (
        np.isfinite(f[["open", "high", "low", "close"]]).all(axis=1)
        & (f.low > 0)
        & (f.low <= f[["open", "close"]].min(axis=1))
        & (f.high >= f[["open", "close"]].max(axis=1))
        & clock.between(555, 929)
        & (f.start.dt.minute % minutes == 0)
        & (f.start.dt.second == 0)
        & ~conflict
    )
    result = f[good].copy()
    result["bar_close"] = result.start + pd.Timedelta(minutes=minutes)
    result = result.set_index("bar_close").sort_index()[["open", "high", "low", "close"]]
    return result, {
        "raw_rows": count,
        "identical_duplicates_removed": duplicates,
        "rejected": int((~good).sum()),
        "valid_rows": len(result),
        "sessions": len(set(result.index.date)),
        "first": str(result.index.min()),
        "last": str(result.index.max()),
    }


def run_variant(signal_frame, minute_frame, hold):
    records, counts, last_exit = [], Counter(), None
    skipped = Counter()
    for at, row in signal_frame[signal_frame.direction != ""].iterrows():
        if not FIRST <= at.strftime("%Y-%m-%d") <= LAST:
            continue
        if (at + pd.Timedelta(minutes=hold)).strftime("%H:%M") > "15:25":
            skipped["late_signal"] += 1
            continue
        day = at.strftime("%Y-%m-%d")
        if last_exit is not None and at < last_exit:
            skipped["position_open"] += 1
            continue
        if counts[day] >= 3:
            skipped["daily_three_entry_cap"] += 1
            continue
        signal = {"timestamp": at.isoformat(), **row.to_dict()}
        outcome = chart_outcome(signal, minute_frame, hold)
        records.append(outcome)
        if outcome["entered"]:
            counts[day] += 1
            last_exit = pd.Timestamp(outcome.get("exit_at", at + pd.Timedelta(minutes=hold)))
    return records, dict(skipped)


def _option_stats(rows):
    priced = [r for r in rows if r["reason"] == "priced"]
    affordable = [r for r in priced if r["affordable"]]

    def stats(group):
        if not group:
            return {"count": 0, "win_rate": None, "mean_net_pnl": None, "sum_net_pnl": None}
        return {
            "count": len(group),
            "win_rate": sum(r["net_pnl"] > 0 for r in group) / len(group),
            "mean_net_pnl": float(np.mean([r["net_pnl"] for r in group])),
            "sum_net_pnl": round(sum(r["net_pnl"] for r in group), 2),
            "mean_funding": float(np.mean([r["premium_with_entry_fees"] for r in group])),
            "largest_loss": min(r["net_pnl"] for r in group),
        }

    return {
        "attempts": len(rows),
        "all_priced": stats(priced),
        "affordable_at_initial_capital": stats(affordable),
        "unavailable": dict(Counter(r["reason"] for r in rows if r["reason"] != "priced")),
        "not_a_portfolio_return": True,
    }


def audit_options(trades, out, manifest, costs, *, capital=10000):
    """Select using past listings and completed quotes, then query only selected contracts."""
    completed = [t | {"id": i} for i, t in enumerate(trades) if t["r"] is not None]
    exclusions = [
        {"id": i, "timestamp": t["timestamp"], "reason": "unresolved_index_exit"}
        for i, t in enumerate(trades)
        if t["r"] is None
    ]
    if not completed:
        return {name: _option_stats(exclusions) for name in SCENARIOS}
    by_trade_id = {t["id"]: t for t in completed}
    requests = pd.DataFrame(completed)
    requests["signal_time"] = pd.to_datetime(requests.timestamp, utc=True)
    requests["quote_time"] = requests.signal_time.dt.floor("5min")
    requests["exit_time"] = pd.to_datetime(requests.exit_at, utc=True)
    requests["month"] = requests.day.str[:7]
    daily_root = ROOT / "data/research/nse-daily/daily"
    daily_paths = {p.name[:10]: p for p in daily_root.glob("*.json.gz") if p.name[:10] <= LAST}
    quotes_by_id, selections = {}, []
    input_hashes = {}
    with duckdb.connect() as db:
        db.execute("SET memory_limit='512MB'")
        db.execute("SET threads=2")
        db.execute("SET TimeZone='Asia/Kolkata'")
        for month, group in requests.groupby("month"):
            path = DATA / "public-options/five-minute" / f"NIFTY-options-{month}-5m.parquet"
            input_hashes[str(path.relative_to(ROOT))] = file_hash(path)
            db.register("requests", group[["id", "quote_time", "direction"]])
            quotes = db.execute(
                """SELECT r.id,o.* FROM read_parquet(?) o JOIN requests r
                ON o.bar_close=r.quote_time AND o.option_type=r.direction""",
                [str(path)],
            ).df()
            for trade_id, part in quotes.groupby("id"):
                quotes_by_id[int(trade_id)] = part
        # One file/session at a time; no unbounded full-archive pandas table.
        for day, group in requests.groupby("day"):
            prior = max((d for d in daily_paths if d < day), default=None)
            listing = {}
            if prior and (pd.Timestamp(day) - pd.Timestamp(prior)).days <= 7:
                path = daily_paths[prior]
                input_hashes[str(path.relative_to(ROOT))] = file_hash(path)
                with gzip.open(path, "rt") as stream:
                    listing = {
                        (r["expiry"], float(r["strike"]), r["option_type"]): r
                        for r in json.load(stream)
                        if r["underlying"] == "NIFTY"
                    }
            for row in group.to_dict("records"):
                selected = select_itm(
                    quotes_by_id.get(row["id"], pd.DataFrame()),
                    listing,
                    spot=row["close"],
                    direction=row["direction"],
                    day=day,
                )
                if selected is None:
                    exclusions.append(
                        {
                            "id": row["id"],
                            "timestamp": row["timestamp"],
                            "reason": "no_observed_itm_with_prior_listing",
                        }
                    )
                else:
                    selections.append(
                        {
                            "id": row["id"],
                            "day": day,
                            "timestamp": row["timestamp"],
                            "signal_time": row["signal_time"],
                            "quote_time": row["quote_time"],
                            "exit_time": row["exit_time"],
                            "expiry": selected["expiry"],
                            "strike": selected["strike"],
                            "option_type": selected["option_type"],
                            "lot_size": selected["lot_size"],
                            "observed_premium": selected["close"],
                            "listing_day": prior,
                        }
                    )
        selection = pd.DataFrame(selections)
        selection.to_parquet(out / "option-selections.parquet", index=False)
        # Register every large file hash BEFORE reading outcome prices.
        for year in sorted({s["day"][:4] for s in selections}):
            path = DATA / "public-options/raw" / f"NIFTY_{year}.parquet"
            input_hashes[str(path.relative_to(ROOT))] = file_hash(path)
        write_json(
            out / "option-inputs.json", {"inputs": input_hashes, "manifest_sha256": manifest}
        )
        outcomes = {name: list(exclusions) for name in SCENARIOS}
        for year in sorted({s["day"][:4] for s in selections}):
            path = DATA / "public-options/raw" / f"NIFTY_{year}.parquet"
            selected = selection[selection.day.str[:4] == year]
            db.register("selected", selected)
            quotes = db.execute(
                """SELECT s.id,o.timestamp+INTERVAL 1 MINUTE AS bar_close,
                o.open,o.high,o.low,o.close,o.volume,o.source,o.granularity,o.underlying
                FROM read_parquet(?) o JOIN selected s ON o.date=s.day AND o.expiry=s.expiry
                AND o.strike=s.strike AND o.option_type=s.option_type
                AND o.timestamp>=s.signal_time AND o.timestamp<=s.exit_time
                ORDER BY s.id,o.timestamp""",
                [str(path)],
            ).df()
            by_id = {int(k): v for k, v in quotes.groupby("id")}
            for selected_row in selected.to_dict("records"):
                trade_id = selected_row["id"]
                q = by_id.get(trade_id, pd.DataFrame(columns=quotes.columns)).copy()
                q["bar_close"] = pd.to_datetime(q.bar_close, utc=True).dt.tz_convert("Asia/Kolkata")
                q = q.set_index("bar_close")
                # Source schema mismatches cannot silently become accepted bars.
                valid = (
                    (q.source == "upstox_expired")
                    & (q.granularity == "1min")
                    & (q.underlying == "NIFTY")
                )
                q = q[valid]
                trade = by_trade_id[trade_id]
                contract = {
                    "lot_size": selected_row["lot_size"],
                    "multiplier": 1,
                    "tick_size": 0.05,
                }
                for name, changes in SCENARIOS.items():
                    result = option_outcome(trade, q, contract, costs | changes, capital=capital)
                    outcomes[name].append(
                        {
                            "id": trade_id,
                            "timestamp": trade["timestamp"],
                            "direction": trade["direction"],
                            "index_reason": trade["reason"],
                            **result,
                        }
                    )
    for name, rows in outcomes.items():
        write_json(out / f"options-{name}.json", sorted(rows, key=lambda r: r["id"]))
    return {name: _option_stats(rows) for name, rows in outcomes.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capital", type=int, choices=(10000, 25000), default=10000)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bank_paths = sorted(SOURCE.glob("BANKNIFTY-5m-*.json"))
    minute_paths = sorted(SOURCE.glob("NIFTY-1m-*.json"))
    if not bank_paths or not minute_paths:
        raise ValueError("Read-only broker snapshots required before evaluation")
    spot_path = DATA / "NIFTY-spot-5m.parquet"
    source_paths = [
        Path(__file__),
        ROOT / "services/research/ema_scalp.py",
        ROOT / "services/research/replay.py",
        ROOT / "services/research/costs.py",
        ROOT / "services/risk/position.py",
        ROOT / "services/risk/models.py",
        PLAN,
    ]
    variants = [
        {
            "id": f"slope{slope}-confirm{int(confirm)}-hold{hold}",
            "slope": slope,
            "confirm": confirm,
            "hold": hold,
        }
        for slope in (0.1, 0.2)
        for confirm in (False, True)
        for hold in (5, 10, 15)
    ]
    costs_path = ROOT / "data/research/technical-ml-2026-09-26-corrected/registered-inputs.json"
    costs = read_json(costs_path)["costs"]
    amendment = ROOT / "docs/plans/2026-09-26-ema-scalping-capital-25000.md"
    manifest = {
        "plan_sha256": file_hash(PLAN),
        "source_hashes": {str(p.relative_to(ROOT)): file_hash(p) for p in source_paths},
        "input_hashes": {
            str(p.relative_to(ROOT)): file_hash(p)
            for p in [spot_path, costs_path, *bank_paths, *minute_paths]
        },
        "variants": variants,
        "main_variant": MAIN,
        "capital": args.capital,
        "available_premium": args.capital * 0.8,
        "capital_amendment_sha256": file_hash(amendment) if args.capital == 25000 else None,
        "first": FIRST,
        "last": LAST,
        "reserved_sessions_used": 0,
        "costs": costs,
        "scenarios": SCENARIOS,
        "versions": {
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "duckdb": duckdb.__version__,
        },
        "purpose": "Offline development test of supplied video summary, not live qualification",
    }
    write_json(out / "registered-experiment.json", manifest)
    bank, bank_audit = screen_broker(bank_paths, 5)
    minute, minute_audit = screen_broker(minute_paths, 1)
    spot = pd.read_parquet(spot_path)
    days = spot.bar_close.dt.strftime("%Y-%m-%d")
    spot = spot[days.between("2024-10-01", LAST)].set_index("bar_close")
    nifty_features, bank_features = indicators(spot), indicators(bank)
    write_json(
        out / "data-audit.json",
        {
            "bank": bank_audit,
            "minute": minute_audit,
            "nifty_5m_rows": len(spot),
            "reserved_sessions_used": 0,
        },
    )
    minute.to_parquet(out / "screened-nifty-1m.parquet")
    bank.to_parquet(out / "screened-banknifty-5m.parquet")
    all_results, main_trades = [], None
    for spec in variants:
        candidates = signals(
            nifty_features, bank_features, slope=spec["slope"], confirm=spec["confirm"]
        )
        records, skipped = run_variant(candidates, minute, spec["hold"])
        write_json(out / f"{spec['id']}-trades.json", records)
        selected_signals = candidates[
            (candidates.direction != "")
            & (candidates.index >= pd.Timestamp(FIRST, tz="Asia/Kolkata"))
        ]
        selected_signals.to_parquet(out / f"{spec['id']}-signals.parquet")
        result = {
            "spec": spec,
            "metrics": summarize(records),
            "skipped": skipped,
            "periods": {
                period: summarize(
                    [
                        r
                        for r in records
                        if (r["day"][:4] == "2026" and period == "2026")
                        or (
                            r["day"][:4] == "2025"
                            and period == f"2025Q{(int(r['day'][5:7]) - 1) // 3 + 1}"
                        )
                    ]
                )
                for period in ("2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026")
            },
        }
        all_results.append(result)
        if spec["id"] == MAIN:
            main_trades = records
        print(json.dumps({"variant": spec["id"], **result["metrics"]}), flush=True)
    write_json(out / "index-results.json", all_results)
    print("Auditing primary-variant ITM option selection and actual premium returns", flush=True)
    options = audit_options(
        main_trades, out, file_hash(out / "registered-experiment.json"), costs, capital=args.capital
    )
    result = {
        "main_variant": MAIN,
        "capital": args.capital,
        "available_premium": args.capital * 0.8,
        "index_variants": all_results,
        "options": options,
        "reserved_sessions_used": 0,
        "live_qualified": False,
        "limitations": [
            "Objective proxy for discretionary rules; not exact video replication",
            "Index 2R does not imply option net 2R",
            "One-lot counterfactual outcomes are not a portfolio",
            "Known development period; not independent final evidence",
        ],
    }
    write_json(out / "results.json", result)
    print(json.dumps({"options": options, "live_qualified": False}), flush=True)


if __name__ == "__main__":
    main()
