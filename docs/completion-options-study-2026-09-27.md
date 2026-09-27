# ₹25,000 serial options replay — 2026-09-27

Forty-five fixed variants were tested with whole-lot option sizing, one serial portfolio, current Kotak charges applied retrospectively as an approved research assumption, and separate base/stress ledgers. These are historical simulations, not forward Sandbox results or live profit.

Capital is ₹25,000. Planned loss allowances are ₹1,000 for the first filled trade and a separate ₹1,000 shared by all later trades each day; profits do not restore them. The daily allowance is ₹2,000, with a 20% peak-equity drawdown pause and 20% cash buffer. Gaps and modeled costs can cause realized loss beyond planned limits.

Conlan rule adaptations use their underlying direction with a prebound option contract and the shared option replay engine, including a 2R target and 5/10/15-minute maximum holding times. They are different from the earlier one-lot opportunity study and from the book’s stock portfolios. ML uses chronological training and evaluation, with EMA 9/15 features; prediction accuracy is distinct from executed-trade win rate.

All global protected final dates were excluded from development. Rule portfolios cover each full development window; ML portfolios cover only its later evaluation slice. Do not sum across windows or compare them as identical samples. Stress raises estimated slippage from 10 to 30 basis points per side and multiplies brokerage by 1.5 (the supplied zero brokerage stays zero). Stress can admit a different number of trades because sizing and risk admission change with costs. A portfolio can stop admitting whole lots near its drawdown allowance without crossing the hard-pause threshold; “Paused: No” does not mean every later signal remained admissible.

## Data windows

| Dataset | Development starts | Development ends | Sessions |
|---|---|---|---:|
| dataset-3 | 2026-01-22 | 2026-04-23 | 60 |
| dataset-4 | 2025-01-01 | 2025-03-27 | 60 |
| dataset-5 | 2025-04-01 | 2025-06-27 | 60 |
| dataset-6 | 2025-07-01 | 2025-09-24 | 60 |
| dataset-7 | 2025-10-01 | 2025-12-29 | 60 |

## Results

| Dataset | Variant | Base trades | Stress trades | Win % | Base net ₹ | Stress net ₹ | Max drawdown % | Paused |
|---|---|---:|---:|---:|---:|---:|---:|---|
| dataset-3 | bollinger-10m | 115 | 112 | 49.57 | 1,129.27 | -2,059.56 | 15.32 | No |
| dataset-3 | bollinger-15m | 11 | 10 | 27.27 | -4,578.01 | -4,554.02 | 19.96 | No |
| dataset-3 | bollinger-5m | 84 | 41 | 47.62 | -4,531.40 | -4,511.96 | 19.78 | No |
| dataset-3 | ml-10m | 33 | 33 | 51.52 | 1,233.39 | 321.58 | 12.00 | No |
| dataset-3 | ml-15m | 35 | 34 | 45.71 | 5,460.31 | 3,606.64 | 7.85 | No |
| dataset-3 | ml-5m | 36 | 35 | 52.78 | 2,923.84 | 2,042.32 | 4.48 | No |
| dataset-3 | sma_macd-10m | 77 | 46 | 42.86 | 133.46 | -4,249.21 | 18.42 | No |
| dataset-3 | sma_macd-15m | 17 | 17 | 23.53 | -4,234.46 | -4,350.10 | 19.59 | No |
| dataset-3 | sma_macd-5m | 50 | 43 | 46.00 | -4,225.09 | -4,169.13 | 19.95 | No |
| dataset-4 | bollinger-10m | 90 | 88 | 44.44 | 1,650.59 | 668.30 | 19.95 | No |
| dataset-4 | bollinger-15m | 94 | 90 | 41.49 | -184.16 | -1,026.99 | 19.82 | No |
| dataset-4 | bollinger-5m | 124 | 112 | 42.74 | -2,963.48 | -3,743.50 | 19.86 | No |
| dataset-4 | ml-10m | 22 | 13 | 27.27 | -4,318.52 | -4,470.59 | 19.51 | No |
| dataset-4 | ml-15m | 18 | 19 | 33.33 | -4,910.83 | -4,921.77 | 19.64 | No |
| dataset-4 | ml-5m | 22 | 22 | 27.27 | -4,909.26 | -4,959.86 | 19.64 | No |
| dataset-4 | sma_macd-10m | 24 | 24 | 29.17 | -783.73 | -995.30 | 19.53 | No |
| dataset-4 | sma_macd-15m | 20 | 19 | 30.00 | -899.90 | -1,084.31 | 19.51 | No |
| dataset-4 | sma_macd-5m | 74 | 74 | 40.54 | -2,755.39 | -3,572.54 | 19.69 | No |
| dataset-5 | bollinger-10m | 89 | 75 | 48.31 | 2,106.88 | 588.38 | 19.91 | No |
| dataset-5 | bollinger-15m | 121 | 93 | 52.89 | 7,966.02 | 6,212.40 | 19.34 | No |
| dataset-5 | bollinger-5m | 96 | 86 | 54.17 | 1,307.27 | -135.95 | 19.43 | No |
| dataset-5 | ml-10m | 13 | 13 | 23.08 | -4,549.41 | -4,717.29 | 19.75 | No |
| dataset-5 | ml-15m | 22 | 18 | 36.36 | -3,974.81 | -4,060.80 | 19.24 | No |
| dataset-5 | ml-5m | 54 | 52 | 53.70 | 1,298.87 | -885.25 | 10.60 | No |
| dataset-5 | sma_macd-10m | 68 | 58 | 45.59 | -2,060.14 | -2,581.64 | 19.64 | No |
| dataset-5 | sma_macd-15m | 64 | 55 | 42.19 | -1,283.03 | -2,028.40 | 19.88 | No |
| dataset-5 | sma_macd-5m | 48 | 38 | 39.58 | -4,777.84 | -4,973.00 | 19.47 | No |
| dataset-6 | bollinger-10m | 63 | 42 | 44.44 | -4,502.49 | -4,656.99 | 19.49 | No |
| dataset-6 | bollinger-15m | 82 | 71 | 51.22 | -4,149.46 | -4,561.53 | 19.69 | No |
| dataset-6 | bollinger-5m | 40 | 27 | 45.00 | -4,513.42 | -4,602.95 | 19.73 | No |
| dataset-6 | ml-10m | 52 | 52 | 51.92 | 228.45 | 158.85 | 10.00 | No |
| dataset-6 | ml-15m | 30 | 32 | 40.00 | -3,701.27 | -3,807.12 | 19.63 | No |
| dataset-6 | ml-5m | 51 | 49 | 43.14 | -2,896.61 | -4,107.57 | 17.95 | No |
| dataset-6 | sma_macd-10m | 50 | 75 | 40.00 | -4,233.17 | -4,407.36 | 20.00 | No |
| dataset-6 | sma_macd-15m | 30 | 30 | 33.33 | -3,839.54 | -4,203.51 | 19.33 | No |
| dataset-6 | sma_macd-5m | 121 | 87 | 48.76 | 1,037.55 | -4,401.31 | 16.91 | No |
| dataset-7 | bollinger-10m | 96 | 46 | 46.88 | -3,450.75 | -3,797.75 | 19.84 | No |
| dataset-7 | bollinger-15m | 23 | 21 | 43.48 | -4,773.17 | -4,779.90 | 19.98 | No |
| dataset-7 | bollinger-5m | 46 | 45 | 45.65 | -3,897.54 | -4,208.11 | 19.68 | No |
| dataset-7 | ml-10m | 23 | 23 | 39.13 | -4,917.67 | -4,922.37 | 19.84 | No |
| dataset-7 | ml-15m | 48 | 43 | 45.83 | -2,808.27 | -3,321.14 | 19.30 | No |
| dataset-7 | ml-5m | 52 | 51 | 46.15 | -1,581.58 | -2,900.56 | 16.26 | No |
| dataset-7 | sma_macd-10m | 13 | 19 | 30.77 | -4,554.90 | -4,686.09 | 19.15 | No |
| dataset-7 | sma_macd-15m | 26 | 26 | 34.62 | -4,631.24 | -4,665.61 | 19.45 | No |
| dataset-7 | sma_macd-5m | 30 | 22 | 40.00 | -4,679.39 | -4,612.22 | 19.72 | No |

## Latest-window prediction diagnostic

| Holding limit | Prediction accuracy | Majority baseline | Labelled opportunities | Executed base trades | Trade win rate |
|---|---:|---:|---:|---:|---:|
| 5 minutes | 52.71% | 57.41% | 979 | 36 | 52.78% |
| 10 minutes | 52.71% | 57.71% | 979 | 33 | 51.52% |
| 15 minutes | 51.38% | 57.20% | 979 | 35 | 45.71% |

These classifiers scored below their majority-class baselines. Positive portfolio results therefore do not establish useful classification skill. Signals also pass liquidity, whole-lot affordability, pacing and shared risk limits before an executed trade. The selected model uses 42 development training sessions and an 18-session chronological evaluation; the other rule rows cover all 60 development sessions. The selection was exploratory. Its subsequent independent final test failed, as recorded below; no forward qualification is claimed.

## Frozen final selection

The predeclared screen selected ml-15m from dataset3, the most recent development window. It met the 20-trade minimum, complete outcomes, and positive base/stress net criteria. The exact artifact was reproduced through the actual UI, frozen as run 12, and evaluated once as final run 13. The final failed the profitability gate.

## One-shot final outcome — failed

Actual app run **12** reproduced the offline selected model exactly: identical artifact, model/prediction/signal hashes, base/stress trades, metrics and session analytics. The app configuration adds run-kind/dependency metadata and omits offline runner provenance; all shared economic and strategy settings match. The frozen model hash is `d6bd9f93723f647745e436343f726be8b9276fbf95acb1773c2c4a3fb21d60ac`.

Run **13** consumed the 60 sealed sessions from **2026-04-24 to 2026-07-21** once. It retained the same model/artifact hash and recorded `split.refitted=false`. No replacement candidate was evaluated on that holdout.

| Final scenario | Trades | Win rate | Net P&L | Profit factor | Max drawdown | Ending equity |
|---|---:|---:|---:|---:|---:|---:|
| Base costs | 47 | 38.30% | -₹4,442.45 | 0.7111 | 19.9782% | ₹20,557.55 |
| Higher costs | 45 | 37.78% | -₹3,948.62 | 0.7234 | 19.9050% | ₹21,051.38 |

Final prediction accuracy was **51.36%**, below the **57.79%** majority-class baseline, over 5,565 labelled opportunities; 33 had unavailable outcomes and remained in prediction/replay inputs. Both scenario ledgers reconcile trade count, net P&L and ending equity. Higher costs changed sizing and admission, so the stress scenario took a different path and happened to lose less; that is not evidence that higher costs improve the strategy.

The hard drawdown-pause flag stayed false because the measured threshold was not crossed, but fee-inclusive whole-lot admission rejected further opportunities near the remaining drawdown allowance. The base report records 1,531 budget/drawdown rejections. It is incorrect to read the false pause flag as unrestricted continued trading.

The actual UI rejected installation with: “Frozen ML final screen needs 20 resolved trades and positive net P&L.” It also disabled repeat final evaluation. No ML strategy or Flow was created. The selected model is **not suitable for promotion on this evidence**. Any future model development needs new evaluation data; this consumed window cannot be called untouched again.

Private app exports and equality checks are retained in `data/research/completion-2026-09-27-app-validation/`. Existing strategies, Flow activation, saved live fees and account allocations were preserved; the intended final-session ledger changed from zero to 60.

## Reproducibility

Private source inputs and detailed reports remain under `data/research/completion-2026-09-27-inputs/` and `data/research/completion-2026-09-27-options-final/`. Each result includes its configuration, source hashes and complete base/stress trade ledgers; rule reports also retain emitted contract-bound schedules. `summary.csv` is ledger-checked; `selection.json` records the frozen selection protocol outcome and source report hashes. Raw vendor prices are not published.

Run `scripts/research_conlan_portfolio.py` with all five dataset exports, the approved research costs, the mandatory global protected-date provenance, capital 25000, and a new output directory. Existing output directories are refused. Any subsequent change requires new development evidence and cannot reuse a consumed final split.

Forward qualification and reviewed live release remain separate. New strategies remain uninstalled and disabled; historical win rate does not establish live profitability.
