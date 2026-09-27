"""Registered three-family scalp comparison. Offline, no orders or activation."""

import argparse
import os
import sys
from pathlib import Path

os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from scripts.research_ema_scalp import (
    DATA,
    FIRST,
    LAST,
    SOURCE,
    _option_stats,
    audit_options,
    file_hash,
    read_json,
    run_variant,
    screen_broker,
    write_json,
)
from services.research.ema_scalp import indicators, signals, summarize
from services.research.scalp_strategies import ema_reversal_signals, macd_features, macd_signals

PLAN = ROOT / "docs/plans/2026-09-26-three-scalping-strategies.md"
TRANSCRIPTS = {
    "macd": Path(
        "/Users/atanumridha/.codex/attachments/ee45d521-294e-4406-b6fd-20ee8f958c5b/Pasted text.txt"
    ),
    "ema5": Path(
        "/Users/atanumridha/.codex/attachments/62dd34cc-4544-423c-b7bf-3cefe5f22db8/Pasted text.txt"
    ),
}
PERIODS = ("2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026")


def period(at):
    return "2026" if at[:4] == "2026" else f"2025Q{(int(at[5:7]) - 1) // 3 + 1}"


def option_diagnostics(rows):
    selected = [r for r in rows if r["reason"] == "priced" and r["affordable"]]
    result = _option_stats(rows)
    result["periods"] = {
        p: _option_stats([r for r in rows if period(r["timestamp"]) == p])[
            "affordable_at_initial_capital"
        ]
        for p in PERIODS
    }
    result["losses_exceeding_1000"] = sum(r["net_pnl"] < -1000 for r in selected)
    result["mean_net_pnl_day_block_95"] = None
    if selected:
        f = pd.DataFrame(selected)
        daily = f.groupby(f.timestamp.str[:10]).net_pnl.agg(["sum", "count"])
        n = len(daily)
        if n >= 10:
            rng = np.random.default_rng(42)
            starts = rng.integers(0, n - 4, size=(2000, int(np.ceil(n / 5))))
            ix = (starts[..., None] + np.arange(5)).reshape(2000, -1)[:, :n]
            means = daily["sum"].to_numpy()[ix].sum(axis=1) / daily["count"].to_numpy()[ix].sum(
                axis=1
            )
            result["mean_net_pnl_day_block_95"] = np.quantile(means, [0.025, 0.975]).tolist()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    specs = [
        {"id": f"{name}-r{reward:g}-hold{hold}", "strategy": name, "reward": reward, "hold": hold}
        for name, rewards in (("ema915", (2,)), ("macd", (1.5, 2)), ("ema5", (2, 3)))
        for reward in rewards
        for hold in (5, 10, 15)
    ]
    bank_paths = sorted(SOURCE.glob("BANKNIFTY-5m-*.json"))
    minute_paths = sorted(SOURCE.glob("NIFTY-1m-*.json"))
    spot_path = DATA / "NIFTY-spot-5m.parquet"
    costs_path = ROOT / "data/research/technical-ml-2026-09-26-corrected/registered-inputs.json"
    costs = read_json(costs_path)["costs"]
    source_names = (
        "scripts/research_scalp_compare.py",
        "scripts/research_ema_scalp.py",
        "services/research/scalp_strategies.py",
        "services/research/ema_scalp.py",
        "services/research/costs.py",
        "services/research/replay.py",
        "services/risk/models.py",
        "services/risk/position.py",
    )
    manifest = {
        "plan_sha256": file_hash(PLAN),
        "capital": 25000,
        "available_premium": 20000,
        "first": FIRST,
        "last": LAST,
        "reserved_sessions_used": 0,
        "variants": specs,
        "source_hashes": {p: file_hash(ROOT / p) for p in source_names},
        "input_hashes": {
            str(p.relative_to(ROOT)): file_hash(p)
            for p in [spot_path, costs_path, *bank_paths, *minute_paths]
        },
        "transcript_hashes": {k: file_hash(p) for k, p in TRANSCRIPTS.items()},
        "costs": costs,
        "ranking_scope": "Primary 2R/15min variants only; development comparison; not portfolio returns",
    }
    write_json(out / "registered-experiment.json", manifest)
    spot = pd.read_parquet(spot_path)
    spot = spot[spot.bar_close.dt.strftime("%Y-%m-%d").between("2024-10-01", LAST)].set_index(
        "bar_close"
    )
    bank, bank_audit = screen_broker(bank_paths, 5)
    minute, minute_audit = screen_broker(minute_paths, 1)
    write_json(
        out / "data-audit.json",
        {"bank": bank_audit, "minute": minute_audit, "reserved_sessions_used": 0},
    )
    print("Generating closed-bar signals for three independent strategy families", flush=True)
    candidates = {
        "ema915": signals(indicators(spot), indicators(bank), slope=0.1, confirm=True),
        "macd": macd_signals(macd_features(spot)),
        "ema5": ema_reversal_signals(spot, minute),
    }
    for name, f in candidates.items():
        f[f.direction != ""].to_parquet(out / f"signals-{name}.parquet")
    all_records, results, identities = [], [], {}
    for spec in specs:
        folder = out / spec["id"]
        folder.mkdir()
        f = candidates[spec["strategy"]].assign(reward_multiple=spec["reward"])
        records, skipped = run_variant(f, minute, spec["hold"])
        write_json(folder / "index-trades.json", records)
        identities[spec["id"]] = list(range(len(all_records), len(all_records) + len(records)))
        all_records.extend(records)
        summary = {
            "spec": spec,
            "index": summarize(records),
            "skipped": skipped,
            "index_periods": {
                p: summarize([r for r in records if period(r["day"]) == p]) for p in PERIODS
            },
        }
        results.append(summary)
        print(
            f"{spec['id']}: {summary['index']['completed']} completed, win rate {summary['index']['win_rate']}",
            flush=True,
        )
    write_json(out / "index-results.json", results)
    write_json(out / "variant-option-ids.json", identities)
    print(
        f"Pricing {len(all_records)} counterfactual opportunities in one bounded option-archive pass",
        flush=True,
    )
    audit = out / "option-audit"
    audit.mkdir()
    audit_options(
        all_records, audit, file_hash(out / "registered-experiment.json"), costs, capital=25000
    )
    option_rows = {
        name: {r["id"]: r for r in read_json(audit / f"options-{name}.json")}
        for name in ("base", "stress")
    }
    for result in results:
        name = result["spec"]["id"]
        result["options"] = {}
        for scenario, lookup in option_rows.items():
            rows = [lookup[i] for i in identities[name]]
            write_json(out / name / f"options-{scenario}.json", rows)
            result["options"][scenario] = option_diagnostics(rows)
        write_json(out / name / "results.json", result)
        a = result["options"]["base"]["affordable_at_initial_capital"]
        s = result["options"]["stress"]["affordable_at_initial_capital"]
        print(
            f"{name}: affordable={a['count']}; base mean={a['mean_net_pnl']}; stress mean={s['mean_net_pnl']}",
            flush=True,
        )
    write_json(
        out / "results.json",
        {
            "capital": 25000,
            "available_premium": 20000,
            "variants": results,
            "reserved_sessions_used": 0,
            "live_qualified": False,
            "not_a_portfolio": True,
        },
    )


if __name__ == "__main__":
    main()
