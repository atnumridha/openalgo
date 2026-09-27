"""Predeclared IG-inspired scalping comparison; offline research only."""

import argparse
import os
import sys
from collections import Counter
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
    audit_options,
    file_hash,
    read_json,
    screen_broker,
    write_json,
)
from scripts.research_scalp_compare import PERIODS, option_diagnostics, period
from services.research.ema_scalp import chart_outcome, summarize
from services.research.ig_scalping import FAMILIES, bars_from_minutes, features, ig_signals

PLAN = ROOT / "docs/plans/2026-09-27-ig-scalping-evaluation.md"
ARTICLE = "https://www.ig.com/en/trading-strategies/four-simple-scalping-trading-strategies-190131"


def outcome(signal, minutes, hold, exits):
    result = chart_outcome(signal, minutes, hold)
    if not result["entered"]:
        return result
    at = pd.Timestamp(signal["timestamp"])
    end = at + pd.Timedelta(minutes=hold)
    flags = exits["exit_ce" if signal["direction"] == "CE" else "exit_pe"]
    candidates = flags.loc[(flags.index > at) & (flags.index <= end)]
    candidates = candidates[candidates]
    if candidates.empty:
        return result
    exit_at = candidates.index[0].tz_convert(at.tz)
    if result["r"] is not None and pd.Timestamp(result["exit_at"]) <= exit_at:
        return result
    expected = pd.date_range(at + pd.Timedelta(minutes=1), exit_at, freq="min")
    if not expected.isin(minutes.index).all():
        return result
    price = float(minutes.loc[exit_at, "close"])
    sign = 1 if signal["direction"] == "CE" else -1
    points = sign * (price - result["entry_price"])
    risk = sign * (result["entry_price"] - result["stop"])
    return result | {
        "reason": "indicator",
        "exit_at": exit_at.isoformat(),
        "exit_price": price,
        "points": points,
        "r": points / risk,
        "ambiguous": False,
    }


def run_variant(signals, minutes, hold):
    records, counts, skipped, last_exit = [], Counter(), Counter(), None
    for at, row in signals[signals.direction != ""].iterrows():
        day = at.strftime("%Y-%m-%d")
        if not FIRST <= day <= LAST:
            continue
        if (at + pd.Timedelta(minutes=hold)).strftime("%H:%M") > "15:25":
            skipped["late_signal"] += 1
            continue
        if last_exit is not None and at < last_exit:
            skipped["position_open"] += 1
            continue
        if counts[day] >= 3:
            skipped["daily_three_entry_cap"] += 1
            continue
        result = outcome({"timestamp": at.isoformat(), **row.to_dict()}, minutes, hold, signals)
        records.append(result)
        if result["entered"]:
            counts[day] += 1
            last_exit = pd.Timestamp(result.get("exit_at", at + pd.Timedelta(minutes=hold)))
    return records, dict(skipped)


def diagnostics(rows):
    result = option_diagnostics(rows)
    selected = [r for r in rows if r["reason"] == "priced" and r["affordable"]]
    result["wins"] = sum(r["net_pnl"] > 0 for r in selected)
    result["win_rate_day_block_95"] = None
    result["active_days"] = len({r["timestamp"][:10] for r in selected})
    result["excluded_initial_affordability"] = sum(
        r["reason"] == "priced" and not r["affordable"] for r in rows
    )
    if result["active_days"] >= 10:
        f = pd.DataFrame(selected)
        f["win"] = f.net_pnl > 0
        daily = f.groupby(f.timestamp.str[:10]).win.agg(["sum", "count"])
        n = len(daily)
        starts = np.random.default_rng(42).integers(0, n - 4, size=(2000, int(np.ceil(n / 5))))
        ix = (starts[..., None] + np.arange(5)).reshape(2000, -1)[:, :n]
        rates = daily["sum"].to_numpy()[ix].sum(axis=1) / daily["count"].to_numpy()[ix].sum(axis=1)
        result["win_rate_day_block_95"] = np.quantile(rates, [0.025, 0.975]).tolist()
    return result


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
            "primary": tf == 5 and hold == 15,
        }
        for family in FAMILIES
        for tf in ((5,) if family == "sar" else (5, 3))
        for hold in (5, 10, 15)
    ]
    manifest = {
        "registered_at": datetime.now(UTC).isoformat(),
        "first": FIRST,
        "last": LAST,
        "source": ARTICLE,
        "plan_sha256": file_hash(PLAN),
        "reserved_sessions_used": 0,
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
    frames = {tf: features(bars_from_minutes(minute, tf), tf) for tf in (3, 5)}
    write_json(
        out / "data-audit.json",
        {
            "minute": audit,
            "aggregate_counts": {tf: len(f) for tf, f in frames.items()},
            "reserved_sessions_used": 0,
        },
    )
    results = []
    for family in FAMILIES:
        for tf in (5,) if family == "sar" else (5, 3):
            group = out / f"{family}-{tf}m"
            group.mkdir()
            signal = ig_signals(frames[tf], family)
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
