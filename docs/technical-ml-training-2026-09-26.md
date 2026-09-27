# Technical ML training — 26 September 2026

**Two models were trained on real historical observations, but neither demonstrated a reliable trading edge.** The selected model made money in its selection period and lost money in both later evaluation periods. It fails the research screen and is not eligible for live trading. This work adds an offline training and diagnostic pipeline; it does not install an ML strategy in the Flow or Research UI.

Follow-up requested by the user: [12 configurations with chronological retraining](ml-walkforward-search-2026-09-26.md), comprising 36 fits and 288 ML replays. The best development candidate improves the aggregate result but still fails consistency and trade-count checks. The original experiment below remains unchanged.

## What was trained

The experiment uses **9,240 available one-lot payoff labels across 116 represented training sessions**, drawn from 120 scheduled sessions. These are overlapping trading opportunities, not 9,240 independent executed trades. Labels estimate net profit divided by planned risk using actual option candles, next-minute entry, the shared exit rules and explicit costs. Examples whose one-lot planned risk exceeds ₹1,000 are excluded from fitting. Prediction opportunities remain observable without requiring future payoff availability.

There are **50 numerical features**, calculated from information available when each signal closes:

| Information | Examples |
|---|---|
| Trend and momentum | Returns, EMA distances and slopes, MACD, RSI, ADX, directional movement |
| Chart structure | Candle bodies and wicks, prior highs/lows, breakouts, session position |
| Volatility and range | ATR, Bollinger position/width, stochastic, realized volatility |
| Observed option activity | Premium returns, relative volume, session VWAP distance |
| Contract context | Call/put, premium, moneyness, days to expiry, historical lot size |

Chart structure is encoded from OHLC candles; no screenshot model was trained. NIFTY index volume is not invented. Option IV, historical order books and reliable bid/ask spreads are not available in these inputs.

The two fixed models are training-standardized **Ridge regression** and **histogram gradient-boosted trees**. Training targets are clipped to −3R…+3R, with equal total weight per session. Trees use a fixed seed and no random early-stopping split. Exactly three entry thresholds per model, 0.10R/0.20R/0.30R, were specified before fitting. See the unchanged [registered experiment plan](plans/2026-09-26-technical-ml-experiment.md).

## Separation of dates

| Purpose | Observed dates | Sessions |
|---|---|---:|
| Fit models and scaling | 1 January–27 June 2025, in two quarterly samples | 120 |
| Select model and threshold | 1 July–24 September 2025 | 60 |
| Later evaluation A | 1 October–29 December 2025 | 60 |
| Later evaluation B | 22 January–23 April 2026 | 60 |
| Reserved final evaluation, unused | 24 April–21 July 2026 | 60 |

The model and threshold are saved before either later evaluation is computed. Features use causal historical warm-up; whole-session boundaries separate training labels from later observations. The final reserved dates are removed before feature and label calculation.

The two later evaluation samples were previously seen in rule-based research. They are excluded from ML fitting and selection, but are **not a pristine final holdout for the overall research program**. This is one chronological experiment, not a completed multi-fold walk-forward study.

## Results after costs

Every independent portfolio starts with ₹10,000. The base scenario uses 10 basis points of adverse slippage and ₹0 brokerage per order; stress uses 30 basis points and ₹20 per order. Both include the recorded Kotak NFO tax/fee assumptions. These are **current rates applied hypothetically to historical prices**, not verified historical fee tables or actual broker fills.

All six selection results are retained:

| Model | Threshold | Base net P&L | Base trades | Stress net P&L | Stress trades |
|---|---:|---:|---:|---:|---:|
| Ridge | 0.10R | ₹567.11 | 6 | ₹297.16 | 6 |
| Ridge | 0.20R | ₹1,567.43 | 9 | ₹1,384.36 | 10 |
| Ridge | 0.30R | ₹1,074.50 | 4 | ₹432.64 | 5 |
| Boosted trees | 0.10R | −₹1,915.23 | 3 | −₹1,998.59 | 3 |
| Boosted trees | 0.20R | −₹1,914.56 | 4 | −₹1,933.46 | 7 |
| Boosted trees | 0.30R | −₹1,708.31 | 3 | −₹1,883.69 | 3 |

No candidate reaches the minimum 20 executed trades in each selection scenario. Ridge at 0.20R is selected **for diagnosis only**, using the registered fallback rule. Prediction error also fails to improve on a constant training-mean predictor: validation MSE is 1.5754 for Ridge and 1.5541 for trees versus **1.5382** for the constant baseline; lower is better.

| Later evaluation | ML base net / trades | ML stress net / trades | Existing filtered rule: base / stress net |
|---|---:|---:|---:|
| October–December 2025 | −₹1,764.16 / 4 | −₹1,784.20 / 3 | ₹817.61 / ₹397.20 |
| January–April 2026, fresh account | −₹1,915.59 / 3 | −₹1,387.95 / 4 | −₹1,097.03 / −₹1,504.75 |
| Both periods, continuous account | −₹1,764.16 / 4 | −₹1,784.20 / 3 | ₹817.61 / ₹397.20 |

The continuous account does not reset its equity or drawdown allowance between periods. After the early losses, remaining drawdown headroom cannot admit further eligible one-lot entries. Its result therefore differs from the sum of independently reset periods. Stress can change admission and subsequent trades, so stress P&L need not be lower on every path.

Only **seven base-scenario trades** execute across the two independent later samples, below the required 40. Maximum observed drawdown is 18.19% in evaluation A and 19.16% in B. Outcomes are complete and no ambiguous exits were counted, but positivity, trade-count and improvement-over-rules checks fail. Your risk limits were not loosened: first trade ₹1,000, all later trades sharing ₹1,000, ₹2,000 daily total, 20% persistent peak-equity drawdown protection and 20% cash buffer. These are planned limits; price gaps can exceed them.

## Useful learnings from Stefan Jansen's repository

The review covered the repository overview and relevant third-edition chapters, not every notebook or the entire stack. No third-party trading code was executed or copied.

| Learning | Application here |
|---|---|
| Define the target around an implementable decision, with point-in-time inputs | Next-minute option-payoff labels, chronological separation and training-only preprocessing. [Learning-task chapter](https://github.com/stefan-jansen/machine-learning-for-trading/tree/main/07_defining_the_learning_task) |
| Start with economically motivated feature families | Trend, volatility, candle structure and observed option activity; keep the indicator search bounded. [Financial-features chapter](https://github.com/stefan-jansen/machine-learning-for-trading/tree/main/08_financial_features) |
| Compare simple models before increasing complexity | Ridge, boosted trees and a constant-prediction benchmark, with saved validation results. [ML-pipeline chapter](https://github.com/stefan-jansen/machine-learning-for-trading/tree/main/11_ml_pipeline) |
| Judge the trading decision after execution costs | Whole-lot portfolio replay under base and stressed costs, not prediction accuracy alone. [Transaction-costs chapter](https://github.com/stefan-jansen/machine-learning-for-trading/tree/main/18_transaction_costs) |
| Track changing inputs and reproducible evidence | **New after this review:** training-reference feature drift diagnostics, plus retained model/data/decision hashes. [MLOps and governance chapter](https://github.com/stefan-jansen/machine-learning-for-trading/tree/main/26_mlops_governance) |

Most of these principles already informed the registered experiment; the concrete additional implementation from this review is `ml_diagnostics.py` and its command-line report. It computes population stability index (PSI) using training-derived bins, changes in feature means, and observations outside training ranges. It does not retrain, change thresholds or enable trading.

The largest changes include underlying volatility and moneyness in July–September, days to expiry and volatility in October–December, and lot size/days to expiry in 2026. For example, the 2026 lot-size PSI is 11.770. These are descriptive distribution differences, **not proof that a particular feature caused the losses**. Permutation importance highlights trend slope, EMA distance and breakout distance in selection data, but importance does not establish profitability or causality.

## Verification and corrections

Independent review found and corrected three issues before the canonical results above were produced:

1. Signals now bind the exact scored option contract. If it becomes unaffordable under stress, replay skips it instead of substituting an unscored option.
2. One-lot labels that exceed shared planned-risk limits are excluded: 110 training and 15 validation examples. Both models were refitted with the same settings.
3. Ambiguous validation exits now explicitly fail the selection and overall screening checks.

Verification: **388 focused tests passed**, including ML, minute execution, research, shared risk and automation-control regressions. The independent reviewer reran the 15 ML/diagnostic tests. Both models were independently refitted and produced exactly the saved validation predictions; reloaded checkpoints reproduced later predictions and exact contract schedules. All five prior rule reports (#3–#7) reproduced unchanged. Ruff passed. The full repository test suite was not run for this change.

The resource audit was static: explicit JSON/hash/model file handles use context managers; Parquet path I/O is library-managed; dataframes and bounded option-history buffers are local to finite research runs. No new network clients, DB sessions, subscriptions, executors or persistent process registries were introduced. This is not a measured long-running leak test.

No live entry was activated or deployed. The ML runner is offline and has no broker/order integration. Software tests verify implementation behavior; they do not prove future profitability.

## Reproduce and inspect

The canonical local output is [`technical-ml-2026-09-26-corrected`](../data/research/technical-ml-2026-09-26-corrected/). Read its [`results.json`](../data/research/technical-ml-2026-09-26-corrected/results.json), [`verification.json`](../data/research/technical-ml-2026-09-26-corrected/verification.json) and [`drift-diagnostics.json`](../data/research/technical-ml-2026-09-26-corrected/drift-diagnostics.json). Earlier output directories are preserved with `superseded.json` notices and must not be used as final evidence. Data and model outputs remain local and git-ignored.

From the project directory, use a **new** output directory; the trainer refuses to overwrite one:

```bash
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync --with scikit-learn==1.7.2 \
  python scripts/research_ml_train.py --output data/research/technical-ml-reproduction

UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync \
  python scripts/research_ml_diagnose.py --run-dir data/research/technical-ml-reproduction
```

These commands use the existing local source datasets. Scikit-learn is provided in a temporary dependency overlay; the platform's base dependencies were not changed.

Further research needs broader point-in-time option coverage and a separately registered, multi-period walk-forward evaluation. Current source coverage is limited, OHLC cannot reconstruct spreads/depth/partial fills, and data redistribution permissions have not been established. Repeatedly tuning on these same later losses would turn them into training feedback; it would not create independent proof of an edge. The reserved final period remains unused.
