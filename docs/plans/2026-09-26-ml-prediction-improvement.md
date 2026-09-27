# Registered prediction-quality experiment

User steering: focus on improving ML predictions. Keep all capital, stop/target, contract selection and cost rules unchanged. This experiment evaluates predictions of costed one-lot option payoff in risk units (R), not raw stock-price accuracy or guaranteed profit. All dates are already-known development data; reserved 24 April–21 July 2026 remains excluded.

## Hypotheses and fixed variants

The existing compact linear model uses additive call/put and trend features. It cannot express opposite trend slopes for calls and puts without interactions. Test an option-direction-aligned version of the same 20 features: sign-align directional returns/trends/candle features/moneyness, center and sign-align RSI and close location, swap and negate high/low breakout distances for puts. Keep volatility, efficiency, option-price/activity features and call/put identity unchanged. No feature uses future information.

Eight fixed training configurations:

1. Original compact Ridge alpha 10, expanding history (control).
2. Aligned compact Ridge alpha 10, expanding history (feature ablation).
3. Aligned Ridge alpha 1,000, expanding history.
4. Aligned Ridge alpha 10,000, expanding history.
5. Aligned Ridge alpha 1,000, most recent 60 represented sessions.
6. Aligned Ridge alpha 10,000, most recent 60 represented sessions.
7. Aligned histogram boosting: 100 iterations, three leaves, minimum 200 samples per leaf, learning rate .03, L2 30, no random early stopping, seed 42.
8. Aligned Ridge alpha 1,000, expanding history, average inverse label-concurrency weights normalized to equal total weight per session. Other variants use equal total session weights.

Training payoff targets remain clipped to [-3,3] R. Evaluation always uses raw unclipped available labels. No unlabeled opportunity becomes a zero outcome.

## Chronology and calibration

Use the existing three folds: train Q1 / select Q2 / evaluate Q3; train Q1–Q2 / select Q3 / evaluate Q4; train Q1–Q3 / select Q4 / evaluate January–April 2026. Split each 60-session selection period into its first 30 observed sessions for calibration and last 30 for validation. Whole-session label exits must precede the following block. All transforms/scaling fit only on training.

Each trained model has two prediction variants: raw and affine-calibrated. Fit the calibrator only on available labels in the first selection half. Use equal-session weighted covariance/(variance + .05) for its slope, clipped to [0,1]; intercept matches the calibration block's weighted mean payoff. A slope of zero is explicitly reported as a constant forecast, not directional skill. No random calibration split.

Eight configurations × three folds = 24 fits, with 16 prediction variants per fold (48 validation evaluations). Select the minimum equal-session weighted raw-target MSE on the final selection half; tie-break MAE then stable candidate id. Freeze each winner and calibration parameters before predicting its later period. No grid expansion after results.

Compare with three controls on identical labeled rows and equal-session weights: the original compact Ridge; the clipped-target training mean from all available past training sessions; and the raw-target mean from the earlier calibration half. The calibration-mean control exposes improvements coming only from shifting the average, rather than learning technical signal relationships.

Evaluate MSE, MAE, mean prediction bias, Spearman rank correlation, and five prediction-bin reliability summaries. Use paired differences in daily MSE versus each control, with 2,000 fixed-seed resamples of contiguous five-session blocks within each period. These intervals describe dependent development observations and are not multiple-search-adjusted final proof.

Improvement screen: selected forecasts beat all three controls by at least 1% MSE in every later period, have lower MAE than the original Ridge in every period, and the 95% block-bootstrap upper bound on the mean daily MSE difference is below zero against every control in every period. Require complete metrics and at least 40 labeled sessions per later period. A failure stays failed. Live eligibility remains false regardless of this screen.

Q4 labels already exist. Compute January–April 2026 payoff labels only after fold 3's model selection is frozen, confirming all observable features exactly match the old unlabeled table. Preserve input/code/model hashes, all variant metrics, selection decisions and later predictions. No broker calls, UI changes, live settings, or profitability-based tuning.
