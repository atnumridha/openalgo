# Multi-market strategy research implementation plan

**Goal:** Build and run an offline, reproducible search for chart-rule combinations targeting at least 80% winning trades, while requiring positive expectancy after costs and reporting unsuccessful results honestly.

**Scope:** BTCUSD futures execution simulation; NIFTY, BANKNIFTY and SENSEX underlying-direction studies; actual long-option simulation only where dated contract metadata and premium candles are available. No live order connections or deployment changes.

**Design:** A bounded Python research package separates data validation, causal signals, OHLC execution and chronological selection. Existing pure position-risk decisions supply stop/target checks. Source data is read only and frozen into a dated research folder. Outputs include the full development leaderboard, selection rationale, validation and final test, individual trades, coverage, and a human-readable HTML report.

## Fixed protocol before search

- Use up to the last 180 calendar days ending 16 October 2026; explicitly identify shorter data histories. Ignore invalid, repaired, out-of-session and incomplete candles; do not fill missing bars or fabricate index volume.
- Use 5-minute and 15-minute entries. Entry families: trend pullback, breakout/retest, Bollinger reclaim, prior-range sweep/reclaim, and regime combination. Base and selective confirmation variants.
- Candidate exits: 1, 1.5 or 2.5 ATR stops; 0.5, 1, 1.5, 2 or 3R targets; maximum holding 30 or 120 minutes. Exactly 600 configurations per market. Smaller rewards are explicitly reported, not concealed to improve win rate.
- Signals use completed candles only; entry is next minute open. Minute candles resolve exits; adverse stop wins if both touched. No overlap, martingale, averaging down, future pivots, or automatic re-entry within the same signal bar. Maximum three entries per exchange day.
- Split observed dates chronologically 60% development / 20% validation / 20% final test. Rank only development candidates with at least 30 trades and positive expectancy; validate at most the top ten, then freeze one before opening the final period. If none qualifies, select an explicitly failed diagnostic candidate. Never retune from final results.
- A candidate meets the research screen only with final net win rate >=80%, >=100 final trades, positive expectancy, profit factor >=1.2, positive stress-cost result and sufficient history (>=60 sessions). Even then it is not proof of future profitability. Report Wilson intervals as descriptive, with dependence caveat.
- BTC costs: fixed 0.001 BTC, taker 0.05% per side plus 18% GST, 0.01% adverse slippage per side; funding reserve disclosed separately. Stress doubles slippage and fees. Indian index study uses points and assumed slippage, not INR option P&L or a broker win rate.
- Indian option diagnostic uses only contracts with dated validity metadata, closest eligible expiry and ATM strike determined at the signal, next-open entry, actual premium candles, zero brokerage plus existing dated fee estimator. Report missing coverage and small samples.
- Historical periods may overlap earlier research. Label this chronological validation, not a pristine prospective experiment. Forward observation is required before a profitability claim.

## Tasks

- [x] Freeze and audit data, record unavailable retrievals and provenance.
- [x] Add causal feature/signal engine and tests for future-data invariance and session/gap boundaries.
- [x] Add shared-risk OHLC execution, costs and selection tests (same-bar ambiguity, gaps, invalid data, short symmetry, holdout exclusion).
- [x] Run the fixed search, freeze selections, evaluate final and stress periods, and run covered option diagnostics.
- [x] Review causality, resource ownership and evidence; deliver a concise result plus a full report and reproducible scripts.

## Outcome

The final stable run completed all 2,400 development configurations and separate
validation/final/stress evaluations. No candidate qualified. No configuration
reached 80% net wins with at least 30 development trades. The Indian option
diagnostic could not resolve any selected entry from the available dated data;
underlying points must not be presented as option profitability.

All 18 focused tests passed, static checks and formatting passed, source/data
checksums matched the completed run, and final trade exports reconciled to the
reported totals. Independent review findings were corrected and covered by
regressions before the final run. See
[research documentation](../../research/multi-market-chart-research.md).

No app restart, live order submission, risk-setting mutation or chart deployment
was performed. The report is a local artifact. Browser visual preview of its
file URL was blocked by browser policy; it was queued in the native file panel
instead, and its generated content and links were checked directly.

## Research basis

- CME support/resistance: https://www.cmegroup.com/education/courses/technical-analysis/support-and-resistance
- Fidelity ATR: https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr
- Fidelity ADX: https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX
- Fidelity RSI: https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/rsi
- John Bollinger's rules: https://www.bollingerbands.com/bollinger-band-rules
- VWAP requires traded volume: https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/
- Multiple-testing risk: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- Backtest assumptions: https://www.freqtrade.io/en/stable/backtesting/

Thresholds, family combinations and exits are app research choices, not validated claims made by these sources. FVG/order-flow and assertions about smart money are not inferred from OHLC alone.
