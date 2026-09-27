"""Frozen NIFTY four-hour-range adaptation; offline, no broker or live changes."""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
from scripts.research_scalp_compare import PERIODS, option_diagnostics, period
from services.research.ema_scalp import summarize
from services.research.fourhour_range import range_signals

PLAN = ROOT / "docs/plans/2026-09-26-fourhour-range-evaluation.md"
TRANSCRIPT = Path(
    "/Users/atanumridha/.codex/attachments/6c57eb9a-a226-4896-8ad3-6de95fdd3d67/Pasted text.txt"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted(SOURCE.glob("NIFTY-1m-*.json"))
    if not paths:
        raise ValueError("Saved minute snapshots required")
    cost_path = ROOT / "data/research/technical-ml-2026-09-26-corrected/registered-inputs.json"
    costs = read_json(cost_path)["costs"]
    sources = (
        "scripts/research_fourhour_range.py",
        "services/research/fourhour_range.py",
        "scripts/research_ema_scalp.py",
        "scripts/research_scalp_compare.py",
        "services/research/ema_scalp.py",
        "services/research/costs.py",
        "services/research/replay.py",
        "services/risk/models.py",
        "services/risk/position.py",
    )
    specs = [{"id": f"fourhour-r2-hold{hold}", "reward": 2, "hold": hold} for hold in (5, 10, 15)]
    manifest = {
        "first": FIRST,
        "last": LAST,
        "reserved_sessions_used": 0,
        "plan_sha256": file_hash(PLAN),
        "transcript_sha256": file_hash(TRANSCRIPT),
        "source_hashes": {name: file_hash(ROOT / name) for name in sources},
        "input_hashes": {str(p.relative_to(ROOT)): file_hash(p) for p in [*paths, cost_path]},
        "variants": specs,
        "primary": "fourhour-r2-hold15",
        "capital": 25000,
        "available_premium": 20000,
        "costs": costs,
        "adaptation": "NIFTY first session four hours 09:15–13:15 IST; 5-minute re-entry triggers",
        "scope": "Exploratory independent one-lot opportunities; no portfolio replay or tuning",
    }
    write_json(out / "registered-experiment.json", manifest)
    minute, source_audit = screen_broker(paths, 1)
    minute = minute[minute.index.strftime("%Y-%m-%d").to_series(index=minute.index).between(FIRST, LAST)]
    assert minute.index.max().strftime("%Y-%m-%d") <= LAST
    signal_frame, signal_audit = range_signals(minute)
    signal_frame[signal_frame.direction != ""].to_parquet(out / "signals.parquet")
    write_json(out / "data-audit.json", {
        "minute": source_audit,
        "signal_generation": signal_audit,
        "reserved_sessions_used": 0,
    })
    print(
        f"Frozen rules: {signal_audit['valid_range_sessions']} complete ranges; "
        f"{signal_audit['excluded_range_sessions']} excluded ranges; {signal_audit['signals']} signals",
        flush=True,
    )
    all_records, identities, results = [], {}, []
    for spec in specs:
        folder = out / spec["id"]
        folder.mkdir()
        records, skipped = run_variant(signal_frame, minute, spec["hold"])
        write_json(folder / "index-trades.json", records)
        identities[spec["id"]] = list(range(len(all_records), len(all_records) + len(records)))
        all_records.extend(records)
        result = {
            "spec": spec,
            "index": summarize(records),
            "skipped": skipped,
            "unresolved_reasons": dict(Counter(r["reason"] for r in records if r["r"] is None)),
            "index_periods": {p: summarize([r for r in records if period(r["day"]) == p]) for p in PERIODS},
        }
        results.append(result)
        print(f"{spec['id']}: {result['index']['completed']} index outcomes", flush=True)
    write_json(out / "index-results.json", results)
    write_json(out / "variant-option-ids.json", identities)
    audit = out / "option-audit"
    audit.mkdir()
    print(f"Pricing {len(all_records)} outcomes from saved option minutes", flush=True)
    audit_options(all_records, audit, file_hash(out / "registered-experiment.json"), costs, capital=25000)
    lookups = {
        name: {r["id"]: r for r in read_json(audit / f"options-{name}.json")}
        for name in ("base", "stress")
    }
    for result in results:
        name = result["spec"]["id"]
        result["options"] = {}
        for scenario, lookup in lookups.items():
            rows = [lookup[i] for i in identities[name]]
            write_json(out / name / f"options-{scenario}.json", rows)
            result["options"][scenario] = option_diagnostics(rows)
        write_json(out / name / "results.json", result)
        base = result["options"]["base"]["affordable_at_initial_capital"]
        stress = result["options"]["stress"]["affordable_at_initial_capital"]
        print(
            f"{name}: n={base['count']}; base mean={base['mean_net_pnl']}; "
            f"stress mean={stress['mean_net_pnl']}", flush=True,
        )
    write_json(out / "results.json", {
        "primary": manifest["primary"],
        "capital": 25000,
        "available_premium": 20000,
        "variants": results,
        "reserved_sessions_used": 0,
        "live_qualified": False,
        "not_a_portfolio": True,
        "exact_video_markets_tested": False,
    })


if __name__ == "__main__":
    main()
