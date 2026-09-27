"""Render the recorded local algorithm study without re-fitting or selecting new rules."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render(study, output):
    data = json.loads((study / "results.json").read_text())
    manifest = json.loads((study / "manifest.json").read_text())
    variants, models = data["option_variants"], data["ml"]
    chart = output.parent / "assets" / (output.stem + ".png")
    chart.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or chart.exists():
        raise ValueError("Choose a new report destination; existing reports are immutable")
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), layout="constrained")
    labels = [f"{r['family'].replace('_', ' ').upper()}\n{r['hold_minutes']} min" for r in variants]
    x = np.arange(len(labels))
    for offset, scenario, color in [(-0.18, "base", "#186c8b"), (0.18, "stress", "#bd5b42")]:
        axes[0].bar(
            x + offset,
            [
                r["options"][scenario]["affordable_at_initial_capital"]["sum_net_pnl"] / 1000
                for r in variants
            ],
            width=0.36,
            label=scenario.title(),
            color=color,
        )
    axes[0].set_xticks(x, labels, fontsize=8)
    axes[0].axhline(0, color="#555", linewidth=0.8)
    axes[0].set_ylabel("Summed option outcomes, INR thousands")
    axes[0].set_title(
        "Rule adaptations: 25,000 INR affordability\nNot a continuous risk-limited portfolio",
        fontsize=11,
    )
    axes[0].legend()
    matrix = np.array(
        [
            [r["metrics"]["net_pnl"] for r in models if r["id"].startswith(f"ml-dataset{i}-")]
            for i in (4, 5, 6, 7, 3)
        ]
    )
    im = axes[1].imshow(matrix, cmap="RdYlGn", vmin=-5000, vmax=5000, aspect="auto")
    for (row, col), value in np.ndenumerate(matrix):
        axes[1].text(col, row, f"{value:+,.0f}", ha="center", va="center", fontsize=9)
    axes[1].set_xticks(range(3), ["5 min", "10 min", "15 min"])
    axes[1].set_yticks(range(5), ["2025 Q1", "2025 Q2", "2025 Q3", "2025 Q4", "2026 Jan-Apr"])
    axes[1].set_title(
        "ML: later evaluation slice in each window\nNet INR; separate 10,000 INR replay accounts",
        fontsize=11,
    )
    fig.colorbar(im, ax=axes[1], label="Net INR")
    fig.savefig(chart, dpi=150)
    plt.close(fig)
    lines = [
        "# Algorithm study: real-data results and implementation coverage",
        "",
        "The missing mathematical components are implemented. **Keep the new strategies disabled: none of these results establishes reliable live profitability.** The SMA-MACD option adaptation has a small positive base-case average, but loses under execution stress; Bollinger loses in every tested holding period. Twelve of fifteen ML evaluations lose money in the base case.",
        "",
        f"Evaluated {manifest['data_audit']['evaluated_sessions']} observed NIFTY sessions, {manifest['first']} through {manifest['last']}. These are previously studied development data, not a fresh blind holdout. All final evaluation dates remain excluded. No strategy was installed or activated and no order was submitted.",
        "",
        f"![Study results](assets/{chart.name})",
        "",
        "## Option-rule adaptations",
        "",
        "Exact signal equations: SMA(5) minus SMA(34) sign changes (including the first available sign), and Bollinger(20, 2 sample standard deviations) outside-band reversal. Their **option adaptation** buys CE for positive signals and PE for negative signals, uses the signal-candle index stop, a 2R index target, and a 5/10/15-minute deadline. This differs from the book's long-stock buy/sell interpretation. Entries use the next minute open; index-driven exits use the next observed option minute open. Stops win intrabar ties.",
        "",
        "Each row is a one-lot opportunity study with a ₹25,000 initial-capital affordability check and ₹20,000 premium ceiling, at most three index entries per day, with overlapping positions skipped. It **does not** compound equity or enforce the live ₹1,000 first-trade / ₹1,000 later-trades pool and portfolio drawdown pause. The saved live template adds those admission rules and a separate protective premium stop, so this table is not a live-template portfolio forecast.",
        "",
        "| Rule | Hold | Affordable priced trades | Win rate after costs | Net sum, base | Net sum, stress | Largest base loss |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in variants:
        a = r["options"]["base"]["affordable_at_initial_capital"]
        s = r["options"]["stress"]["affordable_at_initial_capital"]
        lines.append(
            f"| {r['family']} | {r['hold_minutes']}m | {a['count']} | {100 * a['win_rate']:.2f}% | ₹{a['sum_net_pnl']:+,.2f} | ₹{s['sum_net_pnl']:+,.2f} | ₹{a['largest_loss']:,.2f} |"
        )
    lines += [
        "",
        "Base costs apply your current saved Kotak NFO charges retrospectively **as your approved research assumption**, with 10 bps adverse slippage per side and ₹0 brokerage. Stress uses 30 bps and ₹20 per order. The saved September–October 2026 cost schedule is unchanged. Some stress affordability exclusions differ because costs are higher.",
        "",
        "| Rule / hold | Unresolved attempts | Affordability exclusions | Base mean P&L 95% day-block interval | Losses greater than ₹1,000 |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in variants:
        b = r["options"]["base"]
        lo, hi = b["mean_net_pnl_day_block_95"]
        lines.append(
            f"| {r['id']} | {sum(b['unavailable'].values())} | {b['excluded_initial_affordability']} | ₹{lo:,.2f} to ₹{hi:,.2f} | {b['losses_exceeding_1000']} |"
        )
    lines += [
        "",
        "## Chronological ML tests",
        "",
        "Each imported 120-session dataset contributes only its first 60 development sessions. The first 42 train the model with three expanding chronological folds; the final 18 are evaluated. The separate final 60 remain sealed. Five distinct data windows × three horizons = fifteen evaluations. Features and training weights cannot use evaluation outcomes. All models use seed 42, 100 trees and probability threshold 0.5; no result-driven retuning occurred.",
        "",
        "The canonical ML replay retains the existing **₹10,000 research policy**, ₹1,000 first-trade budget, ₹1,000 shared later-trade budget, ₹2,000 daily loss allowance and 20% drawdown pause. It is distinct from the ₹25,000 option opportunity study above. Each window starts its own account; sums across these runs would not represent one continuous portfolio.",
        "",
        "| Data window | Hold | Prediction accuracy | Majority reference | Executed trades | Trade win rate | Net base | Net stress | Max observed drawdown |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(
        models,
        key=lambda r: (
            (int(r["id"].split("dataset")[1].split("-")[0]) - 4) % 5,
            int(r["id"].split("hold")[1]),
        ),
    ):
        ident = int(r["id"].split("dataset")[1].split("-")[0])
        window = {3: "2026 Jan–Apr", 4: "2025 Q1", 5: "2025 Q2", 6: "2025 Q3", 7: "2025 Q4"}[ident]
        m = r["metrics"]
        a = r["accuracy"]
        lines.append(
            f"| {window} | {r['id'].split('hold')[1]}m | {a['accuracy_pct']:.2f}% | {a['majority_baseline_pct']:.2f}% | {m['trade_count']} | {m['win_rate']:.2f}% | ₹{m['net_pnl']:+,.2f} | ₹{r['stress']['net_pnl']:+,.2f} | {m['max_drawdown_pct']:.2f}% |"
        )
    lines += [
        "",
        "Prediction accuracy counts both profitable and unprofitable opportunity labels, including predictions to skip. Trade win rate counts executed trades only. The majority reference is the larger class in the evaluation slice, not an investable strategy. JSON reports also compare Brier loss against a probability estimated from training data only, with reliability bins, feature importance, and session-block uncertainty where at least ten evaluation sessions exist.",
        "",
        "## Portfolio ranking and randomized controls",
        "",
    ]
    c = data["components"]
    ref = c["preference_reference"]
    lines += [
        f"Bollinger signals with rolling-Sharpe(100) ranking returned **{ref['return_pct']:.2f}% gross**, with **{ref['max_drawdown_pct']:.2f}%** maximum drawdown. This is a two-index daily proxy experiment (NIFTY / BANKNIFTY), fractional exposure and at most one holding to create meaningful ranking competition. It is not the source repository's five-stock universe and not executable option P&L.",
        "",
        "| Control | Repeats | Median gross return | Fraction matching/beating the reference |",
        "|---|---:|---:|---:|",
    ]
    for name in ("white_noise", "bootstrap_preference"):
        s = c["preference_controls"][name]
        lines.append(
            f"| {name} | {s['repeats']} | {s['median_return_pct']:.2f}% | {100 * s['upper_tail_fraction']:.1f}% |"
        )
    lines += [
        "",
        "These are seeded descriptive null comparisons, not proof of statistical significance. Bootstrapping uses only trailing observable returns at each decision. The nine-setting Bollinger-window / Sharpe-window grid is exploratory and is not used to promote a strategy.",
        "",
        "## Coverage and remaining data requirements",
        "",
        "| Source component | Implementation and evidence |",
        "|---|---|",
        "| SMA-MACD / Bollinger signals | Independent equations, future-mutation tests, six real-data option variants; two optional disabled templates |",
        "| Rolling Sharpe / portfolio replacement | Next-observed-close fractional-asset engine; real two-index proxy study; source five-stock universe unavailable |",
        "| Grid search / charts | Existing Research optimizer retained; nine proxy combinations tested; every grid ledger and equity curve saved in the supplement |",
        "| White-noise / bootstrapped preference | 100 seeded comparisons each; full return distributions saved |",
        "| CUSUM / nonuniform lag | Causal event selection and as-of calendar lags; fixed and volatility-scaled 5/10/15-minute barriers tested on actual prices |",
        "| Triple barriers | Missing horizons/gaps remain unavailable; close-based event labels separate from conservative intrabar option execution |",
        "| Event uniqueness / RF | Session-balanced overlapping-event weights integrated into the existing technical RF; 15 real evaluations |",
        "| Money flow / CMF | Observed option volumes only; zero-range/warmup values remain unavailable; no standalone trading rule invented |",
        "| Return / volatility / Sharpe / Sortino / Calmar / pure-profit / alpha / drawdown | Implemented in offline analytics; observed aligned NIFTY benchmark, no synthetic SPY benchmark |",
        "| Alternative revenue ML + portfolio | Release-aware adapter, features, purged classifier and event-signal portfolio implemented; **not empirically testable without company revenue releases and publication timestamps** |",
        "| ML live inference | Remains research-only and cannot be promoted; the reference repository is offline and supplies no verified OpenAlgo live adapter |",
        "",
        "The upstream source has a restrictive freeware license. The additions implement mathematical ideas independently; upstream code is not bundled. Exact signal equations are preserved, while portfolio fills, bootstrap windows, alternative-data vintages and chronological validation deliberately avoid hindsight. This is coverage of algorithms and research components, not a byte-for-byte port or a claim that every book example is a deployable strategy.",
        "",
        "## Using the changes",
        "",
        "After restarting OpenAlgo, open **Strategies → Available templates**. The two new entries are **NIFTY SMA 5/34 Zero-Cross (Research)** and **NIFTY Bollinger 20/2 Reversal (Research)**. They remain uninstalled until you choose Install; installation is tested to create a stopped sandbox strategy, no scheduler, and an inactive Flow. Existing strategies are preserved.",
        "",
        "In **Research → Historical test → Train a RandomForest model**, choose a maximum holding time of 5, 10 or 15 minutes. Results now include prediction quality, calibration, feature importance and recorded ML inputs. A test does not enable live trading.",
        "",
        "## Evidence",
        "",
        f"- Main run and raw trade/model evidence: `{study}`.",
        f"- Manifest: `{study / 'manifest.json'}`; source snapshots and input hashes retained.",
        f"- Grid ledger supplement: `{study / 'portfolio-ledgers'}`; recomputed component results match the original study.",
        "- Backend: 3,993 passed, 13 skipped, 1 expected failure. Frontend: 2,786 passed; build passed. Focused post-report/UI checks recorded separately.",
        "- Independent code review completed; signal warmup, missing-bar labels, revenue revisions and short-sample confidence intervals corrected and regression tested.",
        "- Browser: isolated host with real Research API/worker and synthetic UI fixture; five-minute ML run completed and diagnostics displayed. Fixture profit/accuracy is **not** included in this report. Production broker and live settings were untouched.",
        "",
        "Reproduce with the optional research environment:",
        "",
        "```sh",
        ".venv/bin/python scripts/research_conlan_algorithms.py \\",
        "  --output data/research/conlan-new-run --current-kotak-assumption",
        "```",
        "",
        "This explicitly chooses the current-fee research assumption. It does not edit saved costs. Choose a new output directory each time.",
    ]
    output.write_text("\n".join(lines) + "\n")
    return chart


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(render(args.study.resolve(), args.output.resolve()))
