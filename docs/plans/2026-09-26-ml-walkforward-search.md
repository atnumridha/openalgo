# Registered follow-up: 12 configurations with chronological retraining

The user requested more than ten tests and repeated training to find better results. This is a new, explicitly authorized development search following the failed two-model experiment; it does not rewrite that experiment or its results. Register this protocol before running the new fits. All previously observed dates remain development evidence. Do not use the reserved 24 April–21 July 2026 period or activate orders.

## Fixed search

Twelve configurations: four regressors crossed with three feature sets. Models use scikit-learn 1.7.2 in a temporary dependency overlay; no change to the app environment.

- Ridge alpha 10 and Ridge alpha 100, each with training-fitted standardization.
- Histogram gradient boosting: 120 iterations, 7 leaves, minimum 100 examples per leaf, learning rate 0.05, L2 10, early stopping disabled, seed 42.
- Extra Trees: 120 trees, maximum depth 4, minimum 100 examples per leaf, maximum feature fraction 0.7, one worker, seed 42.
- Feature sets: all existing 50; portable (exclude absolute premium, lot size, days to expiry and absolute log-volume); compact (20 specified trend, return, volatility, candle, option and contract-direction features). No feature selection using new results.
- Training target and labels unchanged: eligible one-lot net payoff / planned risk, targets clipped to [-3,3] only during fitting; equal total training weight per session. Exclude unavailable labels. No random row splits.

Each configuration is retrained for three folds (36 fits):

| Fold | Fit | Choose threshold | Later development evaluation |
|---|---|---|---|
| 1 | Q1 2025 | Q2 2025 | Q3 2025 |
| 2 | Q1–Q2 2025 | Q3 2025 | Q4 2025 |
| 3 | Q1–Q3 2025 | Q4 2025 | January–April 2026 |

Use the same existing 60 observed sessions per quarter/period. Training label exits must precede calibration, and calibration label exits must precede evaluation. Reuse verified earlier feature tables; construct Q4 payoff labels from original observed candles for threshold selection only. Keep later evaluation prediction separate from calibration selection. Save each checkpoint, predictions, chosen threshold and hashes before evaluating that fold.

Exactly three thresholds per fit: 0.10R, 0.20R and 0.30R. Prefer thresholds satisfying positive base/stress net P&L, at least 20 trades in each, and zero ambiguous exits; then complete candidates with at least 20 trades; then diagnostic candidates. Within each tier, rank stressed net P&L, base net P&L, then smaller threshold. An incomplete result never outranks a complete one. Every calibration outcome remains saved.

## Trading assumptions and comparison

No change to position sizing, stops, eligible contract universe or capital limits. Use exact scored option symbols, next-minute execution, current shared risk engine, existing hypothetical Kotak fees, 10 bps/zero brokerage base and 30 bps/₹20-per-order stress. Maximum first-trade planned risk ₹1,000, all later trades share ₹1,000 per day, ₹10,000 starting equity, 20% persistent peak drawdown and 20% cash buffer. Replays cannot circumvent a stop by resetting capital daily.

Compare every later fold with the unchanged filtered-rule baseline and no-trade (zero return). Three thresholds × 36 fits × two cost scenarios = 216 calibration replays. One selected threshold × 36 fits × two scenarios = 72 later development replays. This is **12 distinct configurations, 36 fits and 288 ML replays**, not 288 independent strategies or statistically independent tests.

Each period evaluation starts with ₹10,000 so periods can be compared. Their P&L sum is a sum across separate accounts, not a continuous investment return. Rank the configurations by: passes the full development screen, number of later periods positive in both cost scenarios, worst later stressed P&L, sum of later stressed P&L, then stable configuration id. Report all twelve, not just the best.

The development screen requires all three threshold-calibration screens to pass, complete and unambiguous outcomes, positive base/stress P&L in every later period, at least 20 base trades per later period and 60 combined, and positive aggregate improvement over the rule baseline in both cost scenarios. Ranking does not imply this screen passed. Regardless of outcome, live eligibility remains false because repeated model selection on these known dates is not prospective qualification.

## Stop and preserve evidence

Complete this fixed batch even if early candidates win or lose. Do not expand the grid or tune after seeing this batch's outcomes. Record the best development candidate, the failed checks, and all losses. Preserve original artifacts. A new experiment or independent forward Sandbox evidence is required for any further claim; no amount of refitting establishes guaranteed profit.

Implementation scope: an offline search runner and pure selection/split helpers, regression tests for chronology, excluded dates and truthful ranking. Reuse the existing feature, label and risk logic. Hash inputs/code/configuration; refuse output-directory overwrite. No UI, broker connection, credential, saved live configuration or deployed process changes.
