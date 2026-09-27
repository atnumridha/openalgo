"""Reconcile canonical research results and publish a descriptive, deduplicated ranking."""

import argparse
import csv
import hashlib
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/research"
STUDIES = [
    (
        "scalp-comparison-2026-09-26-verified",
        "Video comparison",
        "ITM; original calendar; index admission/stop",
    ),
    (
        "fourhour-range-2026-09-26",
        "Four-hour range",
        "ITM; original calendar; index admission/stop",
    ),
    (
        "ig-scalping-2026-09-27",
        "IG",
        "ITM; original calendar; index admission/stop and indicator exits",
    ),
    (
        "tradetron-scalping-2026-09-27-corrected",
        "Tradetron",
        "ITM; corrected calendar; index admission/stop",
    ),
    ("stockgro-timeframes-2026-09-27", "StockGro", "ITM; corrected calendar; index admission/stop"),
    (
        "tradejini-scalping-2026-09-27",
        "Tradejini",
        "ATM; corrected calendar; option admission and premium stop",
    ),
    (
        "groww-supertrend-2026-09-27",
        "Groww Supertrend",
        "ATM; corrected calendar; index admission/stop",
    ),
    (
        "groww-algorithmic-2026-09-27",
        "Groww algorithms",
        "ATM; corrected calendar; index admission/stop",
    ),
]
FAMILY_NAMES = {
    "ema915": "EMA 9/15 + Bank Nifty confirmation",
    "macd": "MACD crossover",
    "ema5": "EMA 5 reversal",
    "stochastic": "Stochastic pullback",
    "ma": "MA 5/20/200",
    "sar": "Parabolic SAR",
    "rsi": "RSI trend pullback",
    "ema": "EMA 5/10 crossovers/time windows",
    "divergence": "RSI divergence",
    "squeeze": "Bollinger squeeze",
    "pinbar": "Pin-bar rejection",
    "range": "Range bounce",
    "ema921": "EMA 9/21",
    "box": "Opening box breakout",
    "mean_z20": "Z-score mean reversion",
    "mean_daily10": "10% daily-mean reversion",
    "trend_50_200": "EMA 50/200 crossover",
    "timing_50_200": "EMA 50/200 + daily regime filter",
    "fourhour": "Four-hour range breakout",
    "supertrend": "Supertrend pullback",
}


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_cells(cells):
    ranked = [
        dict(r) for r in cells if not r["duplicate"] and r["base_count"] and r["stress_count"]
    ]
    ranked.sort(key=lambda r: (-r["stress_mean"], -r["base_mean"], -r["base_count"], r["id"]))
    others = [
        dict(r) for r in cells if r["duplicate"] or not r["base_count"] or not r["stress_count"]
    ]
    return [r | {"rank": i + 1} for i, r in enumerate(ranked)] + [
        r | {"rank": None} for r in others
    ]


def build_catalog():
    rows, fingerprints, verified_outcomes = [], {}, 0
    for name, study, protocol in STUDIES:
        folder = DATA / name
        path = folder / "results.json"
        result = load(path)
        assert result["capital"] == 25000 and result["live_qualified"] is False
        assert result.get("reserved_sessions_used", result.get("protected_sessions_evaluated")) == 0
        fingerprints[str(path.relative_to(ROOT))] = sha(path)
        for evidence in (
            "registered-experiment.json",
            "verification.json",
            "independent-chart-check.json",
            "independent-option-check.json",
        ):
            if (folder / evidence).exists():
                fingerprints[str((folder / evidence).relative_to(ROOT))] = sha(folder / evidence)
        for v in result["variants"]:
            spec = v["spec"]
            duplicate = bool(spec.get("reused", False))
            family = spec.get(
                "family",
                spec.get("strategy", "fourhour" if name.startswith("fourhour") else "supertrend"),
            )
            row = {
                "id": name + "/" + spec["id"],
                "study": study,
                "variant": spec["id"],
                "family": FAMILY_NAMES[family],
                "protocol": protocol,
                "spec": spec,
                "primary": spec.get("primary", spec["hold"] == 15 and spec.get("reward") == 2),
                "duplicate": duplicate,
                "live_qualified": False,
            }
            for scenario in ("base", "stress"):
                diagnostic = v["options"][scenario]
                stats = diagnostic["affordable_at_initial_capital"]
                raw = folder / spec["id"] / f"options-{scenario}.json"
                if duplicate:
                    raw = (
                        DATA
                        / "tradetron-scalping-2026-09-27-corrected"
                        / f"ema-1m-r2-hold15/options-{scenario}.json"
                    )
                outcomes = load(raw)
                fingerprints[str(raw.relative_to(ROOT))] = sha(raw)
                values = [
                    r["net_pnl"] for r in outcomes if r["reason"] == "priced" and r["affordable"]
                ]
                assert len(values) == stats["count"], (name, spec, scenario)
                if values:
                    assert abs(statistics.mean(values) - stats["mean_net_pnl"]) < 1e-8
                    assert abs(sum(values) - stats["sum_net_pnl"]) < 0.011
                    assert sum(x > 0 for x in values) / len(values) == stats["win_rate"]
                verified_outcomes += len(outcomes)
                row.update(
                    {
                        f"{scenario}_count": len(values),
                        f"{scenario}_mean": stats["mean_net_pnl"],
                        f"{scenario}_win_rate": stats["win_rate"],
                        f"{scenario}_ci95": diagnostic.get("mean_net_pnl_day_block_95"),
                        f"{scenario}_largest_loss": min(values) if values else None,
                        f"{scenario}_losses_over_1000": sum(x < -1000 for x in values),
                        f"{scenario}_mean_without_largest_win": (sum(values) - max(values))
                        / (len(values) - 1)
                        if len(values) > 1
                        else None,
                        f"{scenario}_positive_periods": sum(
                            s["mean_net_pnl"] is not None and s["mean_net_pnl"] > 0
                            for s in diagnostic.get("periods", {}).values()
                        ),
                        f"{scenario}_periods": diagnostic.get("periods", {}),
                        f"{scenario}_unavailable": diagnostic.get("unavailable", {}),
                    }
                )
            rows.append(row)
    # Verify that the earlier 25k EMA option audit duplicates the later comparison.
    p = DATA / "ema-scalp-25000-2026-09-26-verified/results.json"
    older = load(p)
    newer = load(DATA / "scalp-comparison-2026-09-26-verified/results.json")["variants"][2]
    for scenario in ("base", "stress"):
        assert (
            older["options"][scenario]["affordable_at_initial_capital"]
            == newer["options"][scenario]["affordable_at_initial_capital"]
        )
    fingerprints[str(p.relative_to(ROOT))] = sha(p)
    supplementary = {}
    other_files = {
        "ml_walkforward": "ml-walkforward-2026-09-26-verified/results.json",
        "ml_initial": "technical-ml-2026-09-26-corrected/results.json",
        "ml_prediction": "ml-prediction-2026-09-26-verified/results.json",
        "portfolio_filtered": "filtered-minute-2026-09-26/comparison.json",
        "portfolio_robustness": "robustness-2026-09-26/robustness-results.json",
        "archival_2019": "results/2026-09-26-run-1/run-1.json",
        "coarse_2026": "recent-ui-test-2026-09-26/run-2.json",
        "rebalance": "groww-rebalance-2026-09-27/results.json",
    }
    for label, filename in other_files.items():
        path = DATA / filename
        value = load(path)
        fingerprints[str(path.relative_to(ROOT))] = sha(path)
        supplementary[label] = {"evidence": str(path.relative_to(ROOT)), "sha256": sha(path)}
        if label == "ml_walkforward":
            supplementary[label]["ranked_candidates"] = [
                {k: v for k, v in c.items() if k != "folds"} for c in value["ranked_candidates"]
            ]
            assert all(not c["eligible_for_live"] for c in value["ranked_candidates"])
        if label == "rebalance":
            supplementary[label]["campaigns"] = value["campaigns"]
    supplementary["excluded_and_unranked"] = {
        "duplicate_ema": "Earlier 25k main option results equal EMA9/15 hold15 in the comparison; twelve earlier index-only sensitivity cells are not twelve option tests.",
        "superseded": "Use corrected Tradetron, corrected technical ML, verified comparison/walkforward/prediction; old originals and repeated verification runs are not new trials.",
        "capital": "Older 10k EMA and portfolio/ML studies are separate capital/equity/risk protocols, not entries in the 25k opportunity ranking.",
        "orderflow": "Fabio order-flow requires historical depth/prints; no reliable P&L/accuracy backtest available.",
        "arbitrage": "No synchronized executable two-leg bid/ask/size or fill/latency history; daily/minute last prices do not establish executable arbitrage.",
        "execution": "VWAP/TWAP are execution schedules, not entry alpha; current one-lot entries cannot be split into multiple whole-lot child orders. No execution-quality test claimed.",
        "hft_quantum": "No verified executable HFT or quantum edge experiment; conceptual articles are not ranked as tested trading strategies.",
    }
    ranked = rank_cells(rows)
    best_by_family = {}
    for row in ranked:
        if row["rank"] is not None:
            best_by_family.setdefault(row["family"], row)
    return {
        "cells": ranked,
        "supplementary": supplementary,
        "best_observed_by_family": list(best_by_family.values()),
        "primaries": [r for r in ranked if r["primary"] and not r["duplicate"]],
        "input_fingerprints": fingerprints,
        "outcome_records_reconciled": verified_outcomes,
        "unique_cells": sum(not r["duplicate"] for r in rows),
        "ranked_cells": sum(r["rank"] is not None for r in ranked),
        "duplicate_cells": sum(r["duplicate"] for r in rows),
        "zero_trade_cells": sum(not r["duplicate"] and not r["base_count"] for r in rows),
        "live_qualified": False,
        "protected_sessions_evaluated": 0,
    }


def table(rows, family=False):
    lines = [
        "| Rank | Strategy / variant | Base / stress trades | Net wins | Base mean ₹ | Stress mean ₹ | Stress-positive periods / 5 |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(rows, 1):
        win = f"{r['base_win_rate']:.1%}" if r["base_win_rate"] is not None else "N/A"

        def money(v):
            return f"{v:+.2f}" if v is not None else "N/A"

        label = (
            f"{r['family']} — `{r['variant']}`" if family else f"{r['study']} / `{r['variant']}`"
        )
        rank = i if family else r["rank"]
        lines.append(
            f"| {rank or '—'} | {label} | {r['base_count']} / {r['stress_count']} | {win} | {money(r['base_mean'])} | {money(r['stress_mean'])} | {r['stress_positive_periods']} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    catalog = build_catalog()
    catalog["ranking_script_sha256"] = sha(Path(__file__))
    (out / "ranking.json").write_text(json.dumps(catalog, indent=2, allow_nan=False))
    fields = [
        "rank",
        "study",
        "family",
        "variant",
        "primary",
        "duplicate",
        "base_count",
        "stress_count",
        "base_win_rate",
        "stress_win_rate",
        "base_mean",
        "stress_mean",
        "base_largest_loss",
        "stress_largest_loss",
        "base_losses_over_1000",
        "stress_losses_over_1000",
        "stress_positive_periods",
        "protocol",
    ]
    with (out / "ranking.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(catalog["cells"])
    text = "# Complete descriptive scalping ranking\n\n"
    text += "Mean net rupees per independent initial-affordability trade, not portfolio profit. Base net win rate shown. Ranked by stress mean, base mean, count; zero-trade and duplicate cells are unranked. Earlier ITM and newer ATM/stop/admission protocols differ. Development selection across many correlated trials does not establish statistical superiority or live qualification.\n\n"
    text += f"{catalog['unique_cells']} unique cells; {catalog['ranked_cells']} with trades, {catalog['zero_trade_cells']} without trades; {catalog['duplicate_cells']} reused cell excluded.\n\n"
    text += "## Best observed variant in each family (selected after outcomes)\n\n" + table(
        catalog["best_observed_by_family"], True
    )
    text += "\n\n## Original primary variants\n\n" + table(catalog["primaries"])
    text += (
        "\n\n## Every cell, including duplicates and no-trade outcomes\n\n"
        + table(catalog["cells"])
        + "\n"
    )
    (out / "ranking.md").write_text(text)
    print(
        json.dumps(
            {
                k: catalog[k]
                for k in (
                    "unique_cells",
                    "ranked_cells",
                    "zero_trade_cells",
                    "duplicate_cells",
                    "outcome_records_reconciled",
                )
            },
            indent=2,
        )
    )
    print(table(catalog["best_observed_by_family"], True))


if __name__ == "__main__":
    main()
