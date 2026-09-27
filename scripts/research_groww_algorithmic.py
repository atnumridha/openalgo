"""Frozen Groww algorithmic family study, with observed ATM option outcomes."""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from scripts.research_ema_scalp import (
    FIRST,
    LAST,
    SOURCE,
    file_hash,
    read_json,
    run_variant,
    screen_broker,
    write_json,
)
from scripts.research_ig_scalping import diagnostics
from scripts.research_tradejini_scalping import SCENARIOS, prepare_options
from services.research.ema_scalp import option_outcome, summarize
from services.research.groww_algorithmic import FAMILIES, features, signals
from services.research.ig_scalping import bars_from_minutes
from services.research.tradetron_scalping import EXCLUDED_SESSIONS, regular_sessions

PLAN = ROOT / "docs/plans/2026-09-27-groww-algorithmic-ranking.md"
DAILY = ROOT / "data/research/yahoo/NIFTY-1d-full-history.csv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted(SOURCE.glob("NIFTY-1m-*.json"))
    cost_path = ROOT / "data/research/technical-ml-2026-09-26-corrected/registered-inputs.json"
    costs = read_json(cost_path)["costs"]
    prior = read_json(
        ROOT / "data/research/tradejini-scalping-2026-09-27/registered-experiment.json"
    )
    names = [
        *prior["source_hashes"],
        "scripts/research_groww_algorithmic.py",
        "services/research/groww_algorithmic.py",
    ]
    for n, sha in prior["source_hashes"].items():
        assert file_hash(ROOT / n) == sha, n
    specs = [
        {
            "id": f"{family}-hold{hold}",
            "family": family,
            "reward": 2,
            "hold": hold,
            "primary": hold == 15,
        }
        for family in FAMILIES
        for hold in (5, 10, 15)
    ]
    manifest = {
        "registered_at": datetime.now(UTC).isoformat(),
        "first": FIRST,
        "last": LAST,
        "article": "https://groww.in/blog/algorithmic-trading-strategies",
        "plan_path": str(PLAN.relative_to(ROOT)),
        "plan_sha256": file_hash(PLAN),
        "source_hashes": {n: file_hash(ROOT / n) for n in names},
        "input_hashes": {
            str(p.relative_to(ROOT)): file_hash(p) for p in [*paths, cost_path, DAILY]
        },
        "daily_path": str(DAILY.relative_to(ROOT)),
        "specs": specs,
        "excluded_sessions": list(EXCLUDED_SESSIONS),
        "capital": 25000,
        "premium_budget": 20000,
        "costs": costs,
        "scenarios": SCENARIOS,
        "protected_sessions_evaluated": 0,
        "not_a_portfolio": True,
        "live_qualified": False,
    }
    write_json(out / "registered-experiment.json", manifest)
    minute, audit = screen_broker(paths, 1)
    minute = minute[
        (minute.index.strftime("%Y-%m-%d") >= FIRST) & (minute.index.strftime("%Y-%m-%d") <= LAST)
    ]
    before = len(minute)
    minute = regular_sessions(minute)
    daily = pd.read_csv(DAILY)
    daily.index = pd.to_datetime(daily.timestamp, utc=True).dt.tz_convert("Asia/Kolkata")
    daily = daily.loc[daily.index.strftime("%Y-%m-%d") <= LAST].rename(columns={"Close": "close"})
    valid = np.isfinite(daily.close) & daily.close.gt(0)
    omitted_daily = list(daily.index[~valid].strftime("%Y-%m-%d"))
    daily = daily[valid]
    f = features(bars_from_minutes(minute, 5), daily)
    frames = {
        family: signals(f, family)[["open", "high", "low", "close", "direction", "stop_price"]]
        for family in FAMILIES
    }
    for family, frame in frames.items():
        frame.to_parquet(out / f"signals-{family}.parquet")
    write_json(
        out / "data-audit.json",
        {
            "minute": audit,
            "special_session_rows_excluded": before - len(minute),
            "study_minutes": len(minute),
            "five_minute_bars": len(f),
            "study_observed_sessions": len(set(minute.index.date)),
            "raw_signals": {k: int(v.direction.ne("").sum()) for k, v in frames.items()},
            "daily_last_used": daily.index.max().isoformat(),
            "invalid_daily_dates_excluded": omitted_daily,
        },
    )
    requests = []
    for family, frame in frames.items():
        for at, row in frame[frame.direction != ""].iterrows():
            requests.append(
                {
                    "id": len(requests),
                    "family": family,
                    "day": at.strftime("%Y-%m-%d"),
                    "timestamp": at.isoformat(),
                    "signal_time": at.tz_convert("UTC"),
                    "quote_time": at.floor("5min").tz_convert("UTC"),
                    "direction": row.direction,
                    "spot": float(row.close),
                }
            )
    requests = pd.DataFrame(requests)
    requests.to_parquet(out / "requests.parquet", index=False)
    print(
        f"{len(requests)} total signals: "
        + str({k: int(v.direction.ne("").sum()) for k, v in frames.items()}),
        flush=True,
    )
    if requests.empty:
        selections, prices, ids = {}, {}, {}
    else:
        selections, prices = prepare_options(
            requests, out, file_hash(out / "registered-experiment.json")
        )
        ids = {(r["family"], r["timestamp"]): r["id"] for r in requests.to_dict("records")}
    results = []
    for spec in specs:
        folder = out / spec["id"]
        folder.mkdir()
        frame = frames[spec["family"]].copy()
        frame["reward_multiple"] = spec["reward"]
        trades, skipped = run_variant(frame, minute, spec["hold"])
        for t in trades:
            t["id"] = ids[(spec["family"], t["timestamp"])]
        write_json(folder / "index-trades.json", trades)
        result = {"spec": spec, "index": summarize(trades), "skipped": skipped, "options": {}}
        for scenario, changes in SCENARIOS.items():
            rows = []
            for t in trades:
                base = {
                    "id": t["id"],
                    "timestamp": t["timestamp"],
                    "direction": t["direction"],
                    "index_reason": t["reason"],
                }
                if t["r"] is None:
                    row = {"reason": "unresolved_index_exit"}
                elif t["id"] not in selections:
                    row = {"reason": "no_observed_atm_with_prior_listing"}
                else:
                    q = prices.get(
                        t["id"], pd.DataFrame(index=pd.DatetimeIndex([], tz="Asia/Kolkata"))
                    ).copy()
                    q.index = q.index + pd.Timedelta(minutes=1)
                    contract = {
                        "lot_size": int(selections[t["id"]]["lot_size"]),
                        "multiplier": 1,
                        "tick_size": 0.05,
                    }
                    row = option_outcome(t, q, contract, costs | changes, capital=25000)
                rows.append(base | row)
            write_json(folder / f"options-{scenario}.json", rows)
            result["options"][scenario] = diagnostics(rows)
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
