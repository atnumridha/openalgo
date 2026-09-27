"""Frozen Groww Supertrend pullback study, with observed ATM option outcomes."""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
from services.research.groww_supertrend import pullback_signals, supertrend_features
from services.research.tradetron_scalping import EXCLUDED_SESSIONS, regular_sessions

PLAN = ROOT / "docs/plans/2026-09-27-groww-supertrend.md"
TRANSCRIPT = Path(
    "/Users/atanumridha/.codex/attachments/c4c74202-03d4-484b-88e2-28891c0fd66b/Pasted text.txt"
)


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
        "scripts/research_groww_supertrend.py",
        "services/research/groww_supertrend.py",
    ]
    for n, sha in prior["source_hashes"].items():
        assert file_hash(ROOT / n) == sha, n
    specs = [
        {
            "id": f"supertrend-r{r}-hold{hold}",
            "reward": r,
            "hold": hold,
            "primary": r == 2 and hold == 10,
        }
        for r in (2, 3)
        for hold in (5, 10)
    ]
    manifest = {
        "registered_at": datetime.now(UTC).isoformat(),
        "first": FIRST,
        "last": LAST,
        "article": "https://groww.in/p/scalping-strategy",
        "video": "https://www.youtube.com/watch?v=ip_vWNyLj5w",
        "plan_path": str(PLAN.relative_to(ROOT)),
        "plan_sha256": file_hash(PLAN),
        "source_hashes": {n: file_hash(ROOT / n) for n in names},
        "input_hashes": {str(p.relative_to(ROOT)): file_hash(p) for p in [*paths, cost_path]},
        "transcript_path": str(TRANSCRIPT),
        "transcript_sha256": file_hash(TRANSCRIPT),
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
    signal = pullback_signals(supertrend_features(minute))
    signal.to_parquet(out / "signals.parquet")
    write_json(
        out / "data-audit.json",
        {
            "minute": audit,
            "special_session_rows_excluded": before - len(minute),
            "study_minutes": len(minute),
            "study_observed_sessions": len(set(minute.index.date)),
            "raw_signals": int(signal.direction.ne("").sum()),
        },
    )
    requests = []
    for at, row in signal[signal.direction != ""].iterrows():
        requests.append(
            {
                "id": len(requests),
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
    print(f"{len(requests)} closed Supertrend pullback signals", flush=True)
    if requests.empty:
        raise ValueError("No registered signals; no historical option test was run")
    selections, prices = prepare_options(
        requests, out, file_hash(out / "registered-experiment.json")
    )
    ids = {r["timestamp"]: r["id"] for r in requests.to_dict("records")}
    results = []
    for spec in specs:
        folder = out / spec["id"]
        folder.mkdir()
        frame = signal.copy()
        frame["reward_multiple"] = spec["reward"]
        trades, skipped = run_variant(frame, minute, spec["hold"])
        for t in trades:
            t["id"] = ids[t["timestamp"]]
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
