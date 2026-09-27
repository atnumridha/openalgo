"""Predeclared Tradetron-inspired scalping comparison; offline research only."""

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
from services.research.ig_scalping import bars_from_minutes
from services.research.tradetron_scalping import (
    EXCLUDED_SESSIONS,
    FAMILIES,
    TIMEFRAMES,
    features,
    regular_sessions,
    tradetron_signals,
)

PLAN = ROOT / "docs/plans/2026-09-27-tradetron-scalping-correctness-amendment.md"
ARTICLE = (
    "https://tradetron.tech/blog/scalping-trading-the-ultimate-guide-for-indian-traders-in-2025"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted(SOURCE.glob("NIFTY-1m-*.json"))
    assert paths
    cost_path = ROOT / "data/research/technical-ml-2026-09-26-corrected/registered-inputs.json"
    costs = read_json(cost_path)["costs"]
    names = (
        "scripts/research_tradetron_scalping.py",
        "services/research/tradetron_scalping.py",
        "scripts/research_ig_scalping.py",
        "services/research/ig_scalping.py",
        "scripts/research_ema_scalp.py",
        "scripts/research_scalp_compare.py",
        "services/research/ema_scalp.py",
        "services/research/costs.py",
        "services/research/replay.py",
        "services/risk/models.py",
        "services/risk/position.py",
    )
    specs = [
        {
            "id": f"{family}-{tf}m-r2-hold{hold}",
            "family": family,
            "timeframe": tf,
            "hold": hold,
            "reward": 2,
            "primary": hold == 15,
        }
        for family in FAMILIES
        for tf in (TIMEFRAMES[family],)
        for hold in (5, 10, 15)
    ]
    manifest = {
        "registered_at": datetime.now(UTC).isoformat(),
        "first": FIRST,
        "last": LAST,
        "source": ARTICLE,
        "plan_sha256": file_hash(PLAN),
        "plan_path": str(PLAN.relative_to(ROOT)),
        "reserved_sessions_used": 0,
        "excluded_sessions": list(EXCLUDED_SESSIONS),
        "source_hashes": {p: file_hash(ROOT / p) for p in names},
        "input_hashes": {str(p.relative_to(ROOT)): file_hash(p) for p in [*paths, cost_path]},
        "specs": specs,
        "capital": 25000,
        "premium_budget": 20000,
        "costs": costs,
        "scope": "NIFTY adaptations; exploratory independent opportunities, not portfolio returns",
    }
    write_json(out / "registered-experiment.json", manifest)
    minute, audit = screen_broker(paths, 1)
    minute = minute[
        (minute.index.strftime("%Y-%m-%d") >= FIRST) & (minute.index.strftime("%Y-%m-%d") <= LAST)
    ]
    before = len(minute)
    minute = regular_sessions(minute)
    frames = {1: features(minute, 1), 5: features(bars_from_minutes(minute, 5), 5)}
    write_json(
        out / "data-audit.json",
        {
            "minute": audit,
            "special_session_rows_excluded": before - len(minute),
            "study_minutes": len(minute),
            "study_observed_sessions": len(set(minute.index.date)),
            "aggregate_counts": {tf: len(f) for tf, f in frames.items()},
            "reserved_sessions_used": 0,
        },
    )
    results = []
    for family in FAMILIES:
        for tf in (TIMEFRAMES[family],):
            group = out / f"{family}-{tf}m"
            group.mkdir()
            signal = tradetron_signals(frames[tf], family)
            signal.to_parquet(group / "signals-and-exits.parquet")
            records, ids, group_results = [], {}, []
            for spec in [s for s in specs if s["family"] == family and s["timeframe"] == tf]:
                folder = out / spec["id"]
                folder.mkdir()
                trades, skipped = run_variant(signal, minute, spec["hold"])
                write_json(folder / "index-trades.json", trades)
                ids[spec["id"]] = list(range(len(records), len(records) + len(trades)))
                records.extend(trades)
                result = {
                    "spec": spec,
                    "index": summarize(trades),
                    "skipped": skipped,
                    "raw_signals": int((signal.direction != "").sum()),
                    "indicator_exits": sum(t["reason"] == "indicator" for t in trades),
                    "unresolved_reasons": dict(
                        Counter(t["reason"] for t in trades if t["r"] is None)
                    ),
                    "index_periods": {
                        p: summarize([t for t in trades if period(t["day"]) == p]) for p in PERIODS
                    },
                }
                group_results.append(result)
                print(spec["id"], result["index"]["completed"], "index outcomes", flush=True)
            write_json(group / "variant-option-ids.json", ids)
            option_dir = group / "option-audit"
            option_dir.mkdir()
            if records:
                audit_options(
                    records,
                    option_dir,
                    file_hash(out / "registered-experiment.json"),
                    costs,
                    capital=25000,
                )
            for scenario in ("base", "stress"):
                path = option_dir / f"options-{scenario}.json"
                if not path.exists():
                    write_json(
                        path,
                        [
                            {
                                "id": i,
                                "timestamp": t["timestamp"],
                                "reason": "unresolved_index_exit",
                            }
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
                b = result["options"]["base"]["affordable_at_initial_capital"]
                print(ident, "options", b, flush=True)
            results.extend(group_results)
            write_json(
                out / "results.json",
                {
                    "variants": results,
                    "reserved_sessions_used": 0,
                    "not_a_portfolio": True,
                    "live_qualified": False,
                    "capital": 25000,
                },
            )


if __name__ == "__main__":
    main()
