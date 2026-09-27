# Improving ML predictions — 26 September 2026

**Implemented and tested a prediction-focused upgrade. Improvement is partial, not consistent enough to replace the current model.** Prediction error improves by 1.64% in July–September 2025, worsens by 0.07% in October–December, and is unchanged in January–April 2026 because validation selects the original model. The prediction-quality screen fails. No model was promoted to live trading.

The user asked to focus on model predictions. Capital, costs, instrument selection and stop/target logic were therefore kept fixed. This work predicts **net option-trade payoff in planned-risk units (R)**. It does not predict a guaranteed winning trade or a stock's exact future price.

## Changes implemented

1. **Option-direction-aware features.** The original linear model has additive trend and call/put inputs. A call/put flag can shift its intercept, but cannot reverse the effect of a trend. The new feature transform aligns returns, trend, candle position, RSI, breakout distances and moneyness with the chosen option's direction. Volatility and option-price features retain their original meanings. This addresses a representation limitation; it is not proof that this limitation caused every loss.
2. **Stronger regularization and recent training windows.** Compare expanding history with the most recent 60 represented sessions, and reduce sensitivity to noisy feature coefficients. No future observations enter scaling or fitting.
3. **Less influence from overlapping labels.** One variant downweights candidate trades whose outcome intervals overlap many other examples. Each session still contributes equal total training weight. Thousands of closely related intraday examples are not counted as independent days of evidence.
4. **Separate calibration and selection.** The first 30 sessions of the intervening period fit a bounded affine adjustment to expected payoff. The last 30 select the model. Calibration cannot invert the forecast or amplify its slope beyond one; a zero slope is explicitly a constant forecast.
5. **Prediction-based acceptance checks.** Selection uses error on raw payoff labels, with equal weight per observed session. Every later evaluation compares against the original model, a past-training-mean forecast and an earlier-calibration-mean forecast. Paired daily errors and uncertainty intervals accompany the headline score.

The original feature/label code and existing trading runner were preserved. New code is in `services/research/ml_prediction.py` and `scripts/research_ml_predict.py`; it is an offline experiment, not a new live Flow or UI feature.

## Experiment

The [protocol](plans/2026-09-26-ml-prediction-improvement.md) was saved before fitting. Eight configurations, including the original control, were fitted across three chronological folds: **24 fits and 48 validation-variant evaluations**. Raw and calibrated predictions were considered for each fitted model. The recent-window variants coincide with expanding history when fewer than 60 training sessions exist; these are not independent pieces of evidence.

| Fold | Fit | Calibrate and select, in separate halves | Evaluate |
|---|---|---|---|
| 1 | Q1 2025 | Q2 2025 | Q3 2025 |
| 2 | Q1–Q2 2025 | Q3 2025 | Q4 2025 |
| 3 | Q1–Q3 2025 | Q4 2025 | January–April 2026 |

Whole-session label boundaries separate each stage. January–April payoff labels were constructed only after fold 3's choice was frozen; their observable features match the prior unlabeled table exactly. Missing outcomes remain missing and all controls use identical available labels.

These dates were already known from earlier research. Results are development evidence, not a fresh final test. The reserved **24 April–21 July 2026** remains excluded. Keeping model selection apart from evaluation follows [scikit-learn's evaluation guidance](https://scikit-learn.org/stable/modules/cross_validation.html); repeatedly selecting on known periods still limits generalization claims.

## Prediction results

Mean squared error (MSE) measures how far predicted net payoffs are from observed payoffs; lower is better. Values are in R² and average each session equally.

| Later period | Selected configuration | Original MSE | Selected MSE | Training-mean MSE | Change versus original |
|---|---|---:|---:|---:|---|
| July–September 2025 | Aligned Ridge 1,000, raw | 1.549793 | 1.524301 | **1.510604** | 1.64% improvement |
| October–December 2025 | Aligned Ridge 10,000, raw | **1.555616** | 1.556737 | 1.565602 | 0.07% worse |
| January–April 2026 | Original Ridge 10, raw | 1.679174 | 1.679174 | **1.545034** | Unchanged |

The earlier-calibration-mean control has MSE 1.539253, 1.564296 and 1.542262 respectively. In 2026, the selected model's error is **8.88% higher** than this simple recent-mean forecast. New calibration, recency and overlap-weighting variants did not provide a consistently superior selected forecast.

Evaluations contain 5,310 labels over 60 sessions, 4,872 over 58 sessions and 4,246 over 50 sessions. They are overlapping hypothetical opportunities, not executed independent portfolio trades. There are 30 unavailable January–April labels; they were not converted to zero.

The first period's paired daily MSE difference versus the original is −0.02549, with a five-session block-resampling interval of [−0.04006, −0.01214]. However, it does not beat the training-mean control. In the second period, the difference versus the original is +0.00112 with an interval spanning zero. The third period retains the original model. These descriptive development intervals are not adjusted for the repeated model search and do not establish future performance.

MSE, MAE and bias use equal-session weights. **Spearman rank correlation is ordinary unweighted correlation over the available rows**, used only as a diagnostic. The selected models score −0.0226, +0.0438 and −0.0306: there is little consistent positive ordering of better and worse outcomes in these samples. Five-bin forecast-versus-observed summaries are saved for each period; they describe expected-payoff calibration, not calibrated win probabilities.

## What this tells us

The current feature set has not demonstrated a stable predictive advantage over simple averages. Better representation improves one period, while a different period still chooses the old model and performs worse than an average-payoff forecast. More training runs alone would not address that evidence gap.

The next model-development priority is more informative point-in-time inputs and broader contract coverage. The raw archive already contains open interest, which the compact models do not use. OI changes, verified liquidity context, and higher-timeframe conditions are candidates for a separately specified feature experiment; none is claimed to improve accuracy without testing. Historical bid/ask depth and IV are not currently available in the model inputs and must not be fabricated. The tested daily option basket remains narrow.

The existing risk observations still matter for eventual trading: in the prior best strategy replay, its 2026 evaluation executed only three trades by 27 January, losing ₹1,915.59, of which ₹40.34 was explicit fees. Position risk averaged ₹638.53. That explains why prediction work here was separated from risk-rule changes; changing the loss limits would not demonstrate improved forecasts.

## Verification and reproduction

**404 focused tests passed**, including six new tests for direction symmetry, session weighting, label overlap, bounded calibration, recent-session boundaries and paired daily comparisons. Independent review found no blocking issue. All 24 models were independently refitted, all 48 validation evaluations were reproduced, and selected later predictions and daily MSE were checked. The complete experiment was also repeated after a lint-only change, with identical results. The full repository suite was not run.

The resource audit was static: explicit file/model handles are context-managed, Parquet file I/O is library-managed, and model/data state is local to a finite process. No new network clients, database sessions or persistent registries were introduced. There was no broker call, live activation, UI deployment or risk-setting change.

Canonical local evidence:

- [Results and all control comparisons](../data/research/ml-prediction-2026-09-26-verified/results.json)
- [Verification](../data/research/ml-prediction-2026-09-26-verified/verification.json)
- [Input, implementation and experiment fingerprints](../data/research/ml-prediction-2026-09-26-verified/registered-prediction-experiment.json)

Each fold directory retains models, all calibration/validation predictions, the frozen selection, later predictions, daily errors and reliability summaries. Earlier artifacts remain preserved. To reproduce with existing local datasets and a new output directory:

```bash
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync --with scikit-learn==1.7.2 \
  python scripts/research_ml_predict.py --output data/research/ml-prediction-reproduction
```

This adds a reproducible way to improve and reject predictors. It does not establish a consistently improved model or a profitable live strategy.
