"""Run only missing timeframe/session cells; reuse the verified EMA1m baseline."""

import argparse
import os
import sys
from collections import Counter
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
    audit_options,
    file_hash,
    read_json,
    run_variant,
    screen_broker,
    write_json,
)
from scripts.research_ig_scalping import diagnostics
from scripts.research_scalp_compare import PERIODS, period
from services.research.ema_scalp import summarize
from services.research.stockgro_timeframes import WINDOWS, entry_window, timeframe_signals
from services.research.tradetron_scalping import EXCLUDED_SESSIONS, regular_sessions

PLAN = ROOT / "docs/plans/2026-09-27-stockgro-timeframes.md"
BASELINE = ROOT / "data/research/tradetron-scalping-2026-09-27-corrected"
ARTICLE = "https://www.stockgro.club/blogs/trading/best-time-frame-for-scalping/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    prior = read_json(BASELINE / "registered-experiment.json")
    assert prior["first"] == FIRST and prior["last"] == LAST
    assert prior["capital"] == 25000 and prior["premium_budget"] == 20000
    for name, value in prior["source_hashes"].items():
        assert file_hash(ROOT / name) == value, name
    assert file_hash(ROOT / prior["plan_path"]) == prior["plan_sha256"]
    old_verification = read_json(BASELINE / "verification.json")
    assert (
        old_verification["hashes_match"] and old_verification["protected_sessions_evaluated"] == 0
    )
    paths = sorted(SOURCE.glob("NIFTY-1m-*.json"))
    cost_path = ROOT / "data/research/technical-ml-2026-09-26-corrected/registered-inputs.json"
    inputs = {str(p.relative_to(ROOT)): file_hash(p) for p in [*paths, cost_path]}
    assert inputs == prior["input_hashes"]
    costs = read_json(cost_path)["costs"]
    assert costs == prior["costs"]
    baseline_folder = BASELINE / "ema-1m-r2-hold15"
    reused_paths = [
        BASELINE / "registered-experiment.json",
        BASELINE / "verification.json",
        BASELINE / "ema-1m/signals-and-exits.parquet",
        baseline_folder / "results.json",
        baseline_folder / "index-trades.json",
        baseline_folder / "options-base.json",
        baseline_folder / "options-stress.json",
    ]
    names = [
        "scripts/research_stockgro_timeframes.py",
        "services/research/stockgro_timeframes.py",
        *prior["source_hashes"],
    ]
    specs = [
        {
            "id": f"ema-{tf}m-{window}-r2-hold15",
            "family": "ema",
            "timeframe": tf,
            "window": window,
            "hold": 15,
            "reward": 2,
            "primary": window == "all",
            "reused": tf == 1 and window == "all",
        }
        for tf in (1, 3, 5)
        for window in WINDOWS
    ]
    manifest = {
        "registered_at": datetime.now(UTC).isoformat(),
        "first": FIRST,
        "last": LAST,
        "source": ARTICLE,
        "plan_path": str(PLAN.relative_to(ROOT)),
        "plan_sha256": file_hash(PLAN),
        "source_hashes": {n: file_hash(ROOT / n) for n in names},
        "input_hashes": inputs,
        "reused_hashes": {str(p.relative_to(ROOT)): file_hash(p) for p in reused_paths},
        "baseline_root": str(BASELINE.relative_to(ROOT)),
        "specs": specs,
        "reserved_sessions_used": 0,
        "excluded_sessions": list(EXCLUDED_SESSIONS),
        "capital": 25000,
        "premium_budget": 20000,
        "costs": costs,
        "scope": "Timeframe/session comparison of EMA5/10; eight new cells and one reused baseline",
    }
    write_json(out / "registered-experiment.json", manifest)
    minute, audit = screen_broker(paths, 1)
    minute = minute[
        (minute.index.strftime("%Y-%m-%d") >= FIRST) & (minute.index.strftime("%Y-%m-%d") <= LAST)
    ]
    before = len(minute)
    minute = regular_sessions(minute)
    signals = {tf: timeframe_signals(minute, tf) for tf in (1, 3, 5)}
    pd.testing.assert_frame_equal(
        signals[1], pd.read_parquet(BASELINE / "ema-1m/signals-and-exits.parquet")
    )
    baseline = read_json(baseline_folder / "results.json")
    baseline["spec"] = next(s for s in specs if s["reused"])
    baseline["reused_from"] = str((baseline_folder / "results.json").relative_to(ROOT))
    results = [baseline]
    write_json(out / "reused-baseline.json", baseline)
    write_json(
        out / "data-audit.json",
        {
            "minute": audit,
            "special_session_rows_excluded": before - len(minute),
            "study_minutes": len(minute),
            "study_observed_sessions": len(set(minute.index.date)),
            "aggregate_counts": {tf: len(f) for tf, f in signals.items()},
            "reused_baseline_signal_equality": True,
            "reserved_sessions_used": 0,
        },
    )
    for tf, full in signals.items():
        group = out / f"ema-{tf}m"
        group.mkdir()
        full.to_parquet(group / "signals-and-exits.parquet")
        records, ids, group_results = [], {}, []
        for spec in [s for s in specs if s["timeframe"] == tf and not s["reused"]]:
            folder = out / spec["id"]
            folder.mkdir()
            signal = entry_window(full, spec["window"])
            trades, skipped = run_variant(signal, minute, 15)
            write_json(folder / "index-trades.json", trades)
            ids[spec["id"]] = list(range(len(records), len(records) + len(trades)))
            records.extend(trades)
            result = {
                "spec": spec,
                "index": summarize(trades),
                "skipped": skipped,
                "raw_signals": int(signal.direction.ne("").sum()),
                "outside_entry_window": int(
                    full.direction.ne("").sum() - signal.direction.ne("").sum()
                ),
                "unresolved_reasons": dict(Counter(t["reason"] for t in trades if t["r"] is None)),
                "index_periods": {
                    p: summarize([t for t in trades if period(t["day"]) == p]) for p in PERIODS
                },
            }
            group_results.append(result)
            print(spec["id"], result["index"]["completed"], "index outcomes", flush=True)
        write_json(group / "variant-option-ids.json", ids)
        option_dir = group / "option-audit"
        option_dir.mkdir()
        audit_options(
            records, option_dir, file_hash(out / "registered-experiment.json"), costs, capital=25000
        )
        for scenario in ("base", "stress"):
            path = option_dir / f"options-{scenario}.json"
            if not path.exists():
                write_json(
                    path,
                    [
                        {"id": i, "timestamp": t["timestamp"], "reason": "unresolved_index_exit"}
                        for i, t in enumerate(records)
                    ],
                )
        lookups = {
            s: {r["id"]: r for r in read_json(option_dir / f"options-{s}.json")}
            for s in ("base", "stress")
        }
        for result in group_results:
            ident = result["spec"]["id"]
            result["options"] = {}
            for scenario, lookup in lookups.items():
                rows = [lookup[i] for i in ids[ident]]
                write_json(out / ident / f"options-{scenario}.json", rows)
                result["options"][scenario] = diagnostics(rows)
            write_json(out / ident / "results.json", result)
            print(
                ident,
                "options",
                result["options"]["base"]["affordable_at_initial_capital"],
                flush=True,
            )
        results.extend(group_results)
        write_json(
            out / "results.json",
            {
                "variants": results,
                "reserved_sessions_used": 0,
                "not_a_portfolio": True,
                "live_qualified": False,
                "capital": 25000,
                "new_cells": 8,
                "reused_cells": 1,
            },
        )


if __name__ == "__main__":
    main()
