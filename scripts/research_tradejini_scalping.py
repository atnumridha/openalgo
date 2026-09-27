"""Run the frozen Tradejini adaptations offline; no live application state."""

import argparse
import gzip
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb
import pandas as pd

from scripts.research_ema_scalp import (
    DATA,
    FIRST,
    LAST,
    SOURCE,
    file_hash,
    read_json,
    screen_broker,
    write_json,
)
from scripts.research_ig_scalping import diagnostics
from services.research.tradejini_scalping import premium_outcome, select_atm, tradejini_signals
from services.research.tradetron_scalping import EXCLUDED_SESSIONS, regular_sessions

PLAN = ROOT / "docs/plans/2026-09-27-tradejini-scalping.md"
SCENARIOS = {
    "base": {"slippage_bps": 10, "brokerage_per_order": 0},
    "stress": {"slippage_bps": 30, "brokerage_per_order": 20},
}


def prepare_options(requests, out, manifest_hash):
    selections, quotes_by_id, hashes = [], {}, {}
    daily = {
        p.name[:10]: p
        for p in (ROOT / "data/research/nse-daily/daily").glob("*.json.gz")
        if p.name[:10] <= LAST
    }
    with duckdb.connect() as db:
        db.execute("SET memory_limit='512MB'")
        db.execute("SET threads=2")
        db.execute("SET TimeZone='Asia/Kolkata'")
        for month, group in requests.groupby(requests.day.str[:7]):
            path = DATA / "public-options/five-minute" / f"NIFTY-options-{month}-5m.parquet"
            hashes[str(path.relative_to(ROOT))] = file_hash(path)
            db.register("requests", group[["id", "quote_time", "direction"]])
            quotes = db.execute(
                """SELECT r.id,o.* FROM read_parquet(?) o JOIN requests r
                ON o.bar_close=r.quote_time AND o.option_type=r.direction""",
                [str(path)],
            ).df()
            quotes_by_id.update({int(i): q for i, q in quotes.groupby("id")})
        for day, group in requests.groupby("day"):
            prior = max((d for d in daily if d < day), default=None)
            listing = {}
            if prior and (pd.Timestamp(day) - pd.Timestamp(prior)).days <= 7:
                path = daily[prior]
                hashes[str(path.relative_to(ROOT))] = file_hash(path)
                with gzip.open(path, "rt") as stream:
                    listing = {
                        (r["expiry"], float(r["strike"]), r["option_type"]): r
                        for r in json.load(stream)
                        if r["underlying"] == "NIFTY"
                    }
            for row in group.to_dict("records"):
                selected = select_atm(
                    quotes_by_id.get(row["id"], pd.DataFrame()),
                    listing,
                    row["spot"],
                    row["direction"],
                    day,
                )
                if selected:
                    selections.append(
                        {
                            **row,
                            "listing_day": prior,
                            **{
                                k: selected[k]
                                for k in ("expiry", "strike", "option_type", "lot_size")
                            },
                            "observed_premium": selected["close"],
                        }
                    )
        selection = pd.DataFrame(selections)
        if selection.empty:
            raise ValueError("No options selected; inspect quote and listing coverage")
        selection.to_parquet(out / "option-selections.parquet", index=False)
        for year in sorted(set(selection.day.str[:4])):
            path = DATA / "public-options/raw" / f"NIFTY_{year}.parquet"
            hashes[str(path.relative_to(ROOT))] = file_hash(path)
        write_json(out / "option-inputs.json", {"inputs": hashes, "manifest_sha256": manifest_hash})
        pieces = []
        for year, group in selection.groupby(selection.day.str[:4]):
            db.register("selected", group)
            path = DATA / "public-options/raw" / f"NIFTY_{year}.parquet"
            q = db.execute(
                """SELECT s.id,o.timestamp AS bar_open,o.open,o.high,o.low,o.close,
                o.volume,o.source,o.granularity,o.underlying
                FROM read_parquet(?) o JOIN selected s ON o.date=s.day AND o.expiry=s.expiry
                AND o.strike=s.strike AND o.option_type=s.option_type
                AND o.timestamp>=s.signal_time AND o.timestamp<=s.signal_time+INTERVAL 15 MINUTE
                ORDER BY s.id,o.timestamp""",
                [str(path)],
            ).df()
            pieces.append(q)
        paths = pd.concat(pieces, ignore_index=True)
        paths["bar_open"] = pd.to_datetime(paths.bar_open, utc=True).dt.tz_convert("Asia/Kolkata")
        paths.to_parquet(out / "option-paths.parquet", index=False)
    valid = paths[
        (paths.source == "upstox_expired")
        & (paths.granularity == "1min")
        & (paths.underlying == "NIFTY")
    ]
    return {int(r["id"]): r for r in selections}, {
        int(i): p.set_index("bar_open") for i, p in valid.groupby("id")
    }


def simulate(requests, selections, paths, hold, costs):
    rows, counts, skipped, last_exit = [], Counter(), Counter(), None
    for signal in requests.to_dict("records"):
        ident, at, day = signal["id"], signal["signal_time"], signal["day"]
        at = at.tz_convert("Asia/Kolkata")
        end = at + pd.Timedelta(minutes=hold)
        if end.strftime("%H:%M") > "15:25":
            skipped["late_signal"] += 1
            continue
        if last_exit is not None and at < last_exit:
            skipped["position_open"] += 1
            continue
        if counts[day] >= 3:
            skipped["daily_three_entry_cap"] += 1
            continue
        base = {"id": ident, "timestamp": at.isoformat(), "direction": signal["direction"]}
        if ident not in selections:
            rows.append(base | {"reason": "no_observed_atm_with_prior_listing", "entered": False})
            continue
        q = paths.get(ident, pd.DataFrame(index=pd.DatetimeIndex([], tz="Asia/Kolkata")))
        result = premium_outcome(q, at, hold, int(selections[ident]["lot_size"]), costs)
        rows.append(base | result)
        if result["entered"]:
            counts[day] += 1
            last_exit = pd.Timestamp(result.get("exit_at", end))
    return rows, dict(skipped)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted(SOURCE.glob("NIFTY-1m-*.json"))
    cost_path = ROOT / "data/research/technical-ml-2026-09-26-corrected/registered-inputs.json"
    costs = read_json(cost_path)["costs"]
    names = [
        "scripts/research_tradejini_scalping.py",
        "services/research/tradejini_scalping.py",
        "scripts/research_ema_scalp.py",
        "scripts/research_ig_scalping.py",
        "scripts/research_scalp_compare.py",
        "services/research/ema_scalp.py",
        "services/research/ig_scalping.py",
        "services/research/tradetron_scalping.py",
        "services/research/replay.py",
        "services/research/costs.py",
        "services/risk/models.py",
        "services/risk/position.py",
    ]
    specs = [
        {
            "id": f"{family}-{tf}m-hold{hold}",
            "family": family,
            "timeframe": tf,
            "hold": hold,
            "primary": hold == 10,
        }
        for family in ("ema921", "box")
        for tf in (1, 3)
        for hold in (5, 10, 15)
    ]
    manifest = {
        "registered_at": datetime.now(UTC).isoformat(),
        "first": FIRST,
        "last": LAST,
        "article": "https://www.tradejini.com/blogs/introduction-to-scalping-in-nifty-options",
        "plan_path": str(PLAN.relative_to(ROOT)),
        "plan_sha256": file_hash(PLAN),
        "source_hashes": {n: file_hash(ROOT / n) for n in names},
        "input_hashes": {str(p.relative_to(ROOT)): file_hash(p) for p in [*paths, cost_path]},
        "specs": specs,
        "excluded_sessions": list(EXCLUDED_SESSIONS),
        "capital": 25000,
        "premium_budget": 20000,
        "planned_risk_budget": 1000,
        "costs": costs,
        "scenarios": SCENARIOS,
        "protected_sessions_evaluated": 0,
        "not_a_portfolio": True,
        "live_qualified": False,
    }
    write_json(out / "registered-experiment.json", manifest)
    minutes, audit = screen_broker(paths, 1)
    minutes = minutes[
        (minutes.index.strftime("%Y-%m-%d") >= FIRST) & (minutes.index.strftime("%Y-%m-%d") <= LAST)
    ]
    before = len(minutes)
    minutes = regular_sessions(minutes)
    write_json(
        out / "data-audit.json",
        {
            "minute": audit,
            "special_session_rows_excluded": before - len(minutes),
            "study_minutes": len(minutes),
            "study_observed_sessions": len(set(minutes.index.date)),
        },
    )
    requests = []
    for family in ("ema921", "box"):
        for tf in (1, 3):
            signal = tradejini_signals(minutes, tf, family)
            signal.to_parquet(out / f"{family}-{tf}m-signals.parquet")
            for at, row in signal[signal.direction != ""].iterrows():
                requests.append(
                    {
                        "id": len(requests),
                        "group": f"{family}-{tf}m",
                        "day": at.strftime("%Y-%m-%d"),
                        "timestamp": at.isoformat(),
                        "signal_time": at.tz_convert("UTC"),
                        "quote_time": at.floor("5min").tz_convert("UTC"),
                        "direction": row.direction,
                        "spot": float(row.close),
                    }
                )
            print(f"{family}-{tf}m signals={int(signal.direction.ne('').sum())}", flush=True)
    requests = pd.DataFrame(requests)
    requests.to_parquet(out / "requests.parquet", index=False)
    selections, option_paths = prepare_options(
        requests, out, file_hash(out / "registered-experiment.json")
    )
    results = []
    for spec in specs:
        folder = out / spec["id"]
        folder.mkdir()
        req = requests[requests.group == f"{spec['family']}-{spec['timeframe']}m"]
        result = {"spec": spec, "raw_signals": len(req), "options": {}, "skipped": {}, "exits": {}}
        for scenario, changes in SCENARIOS.items():
            rows, skipped = simulate(req, selections, option_paths, spec["hold"], costs | changes)
            write_json(folder / f"options-{scenario}.json", rows)
            result["options"][scenario] = diagnostics(rows)
            result["skipped"][scenario] = skipped
            result["exits"][scenario] = dict(
                Counter(r["exit_reason"] for r in rows if r["reason"] == "priced")
            )
            result["options"][scenario]["ambiguous_bars"] = sum(
                r.get("ambiguous", False) for r in rows
            )
            result["options"][scenario]["entered_unresolved"] = sum(
                r.get("entered", False) and r["reason"] != "priced" for r in rows
            )
        write_json(folder / "results.json", result)
        results.append(result)
        print(spec["id"], result["options"]["base"]["affordable_at_initial_capital"], flush=True)
    write_json(
        out / "results.json",
        {
            "variants": results,
            "capital": 25000,
            "not_a_portfolio": True,
            "live_qualified": False,
            "protected_sessions_evaluated": 0,
        },
    )


if __name__ == "__main__":
    main()
