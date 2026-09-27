# Twelve-configuration ML search — 26 September 2026

**Completed: 12 configurations, 36 chronological training runs and 288 ML trading replays.** The strongest development candidate is the compact 20-feature Ridge model. It makes money in two later periods and loses in the third. **No configuration passes the full development screen, and none is eligible for live trading.**

This is the user's requested expansion after the [earlier two-model experiment](technical-ml-training-2026-09-26.md). The new [protocol](plans/2026-09-26-ml-walkforward-search.md) was registered before fitting. Earlier results are preserved; this batch does not replace a failure with a selectively reported winner.

## What was tested

Four regressors were crossed with three feature sets:

- Ridge with regularization strength 10 or 100, with scaling fitted only on past training data.
- Gradient-boosted trees with shallow trees and fixed settings.
- Extra Trees with 120 shallow trees and a fixed seed.
- Feature sets: all 50 existing technical features; 46 excluding absolute premium, lot size, days to expiry and absolute log-volume; or a compact 20-feature set covering trends, momentum, volatility, candle position, option activity, direction and moneyness.

Each configuration was retrained three times:

| Fold | Training | Threshold selection | Later development evaluation |
|---|---|---|---|
| 1 | January–March 2025 | April–June 2025 | July–September 2025 |
| 2 | January–June 2025 | July–September 2025 | October–December 2025 |
| 3 | January–September 2025 | October–December 2025 | January–April 2026 |

These are the existing 60 observed sessions per period, not every calendar date. Training increases from 4,708 labels/58 represented sessions to 9,240/116 and then 14,550/176. Labels are overlapping opportunities, not independent executed trades. Three fixed thresholds, 0.10R/0.20R/0.30R, are evaluated only on the intervening selection period. Each chosen threshold and model are saved before evaluating the following period.

The count is **216 threshold-selection replays plus 72 later replays**, each including both cost scenarios. Six additional rule-baseline replays provide comparison. Reproduction runs are verification, not additional distinct configurations. The 288 replays share data and are not independent statistical tests.

Chronological separation and training-only preprocessing follow the [ML pipeline methodology](https://github.com/stefan-jansen/machine-learning-for-trading/tree/main/11_ml_pipeline) and [scikit-learn's evaluation guidance](https://scikit-learn.org/stable/modules/cross_validation.html). Because these dates have already informed research and now select a candidate, they are development evidence. The reserved **24 April–21 July 2026** final period remains unused.

## Best candidate: compact Ridge, alpha 10

Each row starts with a separate ₹10,000 account. Results include modeled fees and adverse slippage.

| Later period | Base net P&L | Stress net P&L | Base trades | Base maximum drawdown |
|---|---:|---:|---:|---:|
| July–September 2025 | ₹2,112.01 | ₹1,512.81 | 15 | 19.95% |
| October–December 2025 | ₹455.76 | ₹144.74 | 5 | 18.32% |
| January–April 2026 | −₹1,915.59 | −₹1,387.95 | 3 | 19.16% |
| Sum across the three independent accounts | **₹652.18** | **₹269.60** | **23** | Not additive |

**The sums are not a continuous return on one ₹10,000 investment.** Capital and drawdown state carry across days within each replay, but each period starts a fresh account. A small aggregate profit does not erase the losing 2026 period or near-limit drawdowns.

The model does not qualify because:

- None of its three threshold-selection periods satisfies all calibration requirements. The first loses money; the next two have fewer than 20 trades despite positive P&L.
- One of the three later periods loses money under both cost scenarios.
- There are only 23 base trades versus a minimum 20 per period and 60 combined.

Its aggregate result improves on the filtered-rule baseline, but that is only one of the required checks. Its prediction error beats the constant-mean benchmark in only one of the three threshold-selection periods. All later outcomes are complete and have zero ambiguous exits.

## All twelve results

Rank favors consistency: screen pass, number of periods positive under both costs, worst stressed period, then aggregate stressed P&L. This intentionally differs from choosing the largest aggregate base profit. Sums below are across the same three separately initialized accounts.

| Rank | Configuration | Positive periods / 3 | Base P&L sum | Stress P&L sum | Base trades | Screen |
|---|---|---:|---:|---:|---:|---|
| 1 | Compact Ridge 10 | 2 | ₹652.18 | ₹269.60 | 23 | Fail |
| 2 | All features, boosted trees | 1 | −₹1,790.24 | −₹2,653.68 | 20 | Fail |
| 3 | Portable features, boosted trees | 1 | ₹2,998.09 | −₹464.94 | 29 | Fail |
| 4 | Compact Ridge 100 | 1 | −₹1,177.28 | −₹2,150.49 | 23 | Fail |
| 5 | Portable Extra Trees | 0 | −₹1,403.45 | −₹1,692.50 | 5 | Fail |
| 6 | Portable Ridge 100 | 0 | −₹3,994.13 | −₹3,616.05 | 12 | Fail |
| 7 | All features, Ridge 100 | 0 | −₹3,581.69 | −₹2,867.28 | 9 | Fail |
| 8 | Portable Ridge 10 | 0 | −₹4,465.97 | −₹4,126.22 | 7 | Fail |
| 9 | All features, Extra Trees | 0 | −₹1,625.37 | −₹1,988.89 | 8 | Fail |
| 10 | All features, Ridge 10 | 0 | −₹4,829.74 | −₹4,385.62 | 9 | Fail |
| 11 | Compact Extra Trees | 0 | −₹1,838.19 | −₹1,992.27 | 3 | Fail |
| 12 | Compact boosted trees | 0 | −₹1,890.03 | −₹3,777.62 | 16 | Fail |

The smaller linear model is the best candidate in this batch; more complex trees did not deliver consistent improvement. The portable boosted model's ₹2,998.09 base sum becomes a ₹464.94 loss under stress, illustrating why base profit alone is insufficient. Some tree models make no trades in individual periods; abstention is recorded as zero, not a profitable period.

## Unchanged assumptions and limitations

Your capital and planned-risk limits remain ₹10,000; up to ₹1,000 for the first trade and another ₹1,000 shared by all later trades per day; ₹2,000 daily total; 20% persistent peak-equity drawdown protection; 20% cash buffer. The shared engine still requires affordable whole lots and exact scored option contracts, enters on the next minute, and applies its existing stop, target, cooldown and session-exit rules. No daily capital reset was used to bypass losses.

Base costs use 10 bps adverse slippage and zero brokerage per order; stress uses 30 bps and ₹20 per order. Both apply recorded current Kotak NFO fee assumptions hypothetically to historical candles. Historical bid/ask depth, partial fills and actual broker execution are unavailable. Sparse executions and limited contract coverage restrict conclusions. Planned loss caps can be exceeded by gaps.

Repeating selection on the same known periods cannot make them independent evidence. The fixed batch is complete; the search was not extended after seeing these outcomes. No guaranteed profit or live-readiness claim follows from its best score.

## Verification and saved evidence

**398 focused tests passed**, covering the new search, ML features/labels, replay, shared risk and automation controls. Independent review found no blocking correctness issue. All 36 models were independently refitted, reproducing saved predictions exactly; all 72 selected later replays were reproduced exactly. Threshold choices, contract schedules, model hashes, source hashes and chronology were checked.

Review prompted a rerun safeguard: cached labels are now rejected if the shared risk/cost/replay implementation changes. Its isolated regression test first failed, then passed. The entire fixed batch was repeated after this safeguard; all predictions and all 288 ML reports were identical. This is reproduction, not a further search. The full repository suite was not run; Ruff and whitespace checks passed.

Resource audit was static: explicit file/model handles use context managers, Parquet path I/O is library-managed, and data/model state is local to a finite CLI run. No new broker connections, database sessions, subscriptions, executors or long-running processes were introduced. No UI deployment or live activation occurred.

Canonical local artifacts:

- [Ranked results](../data/research/ml-walkforward-2026-09-26-verified/results.json)
- [Comparison CSV](../data/research/ml-walkforward-2026-09-26-verified/leaderboard.csv)
- [Verification record](../data/research/ml-walkforward-2026-09-26-verified/verification.json)
- [Registered configurations and source fingerprints](../data/research/ml-walkforward-2026-09-26-verified/registered-search.json)

Each configuration folder contains three saved models, calibration and later predictions, all threshold reports and exact trading signals. Earlier output is preserved with a pointer to the verified batch. Models and market data remain local and git-ignored.

To reproduce from the project directory, choose a new output directory; existing directories are refused:

```bash
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync --with scikit-learn==1.7.2 \
  python scripts/research_ml_search.py --output data/research/ml-walkforward-reproduction
```

The runner depends on the existing verified local datasets. It does not place Sandbox or live orders. A stronger claim requires new evidence from a separately specified experiment or forward Sandbox qualification, not additional selection on these same outcomes.
