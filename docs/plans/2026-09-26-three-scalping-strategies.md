# Three scalping strategies: frozen comparison plan

> Execute inline, tests first; independent review required before reporting a winner. Do not amend hypotheses after seeing outcomes.

**Goal:** Compare EMA9/15, the supplied MACD transcript and the supplied 5EMA reversal transcript separately at INR25,000 assumed capital, using observed NIFTY index and ITM option candles.

**Architecture:** Extend the existing pure chart-outcome function with an explicit stop and registered reward multiple, retaining unchanged defaults. New pure indicator/signal module and offline comparison CLI reuse existing candle screening, serial execution, point-in-time option selection and costs. No live changes or ML fitting.

**Spec inputs:** User attachment `ee45d521-294e-4406-b6fd-20ee8f958c5b/Pasted text.txt` (MACD video rf_EQvubKlk), and `62dd34cc-4544-423c-b7bf-3cefe5f22db8/Pasted text.txt` (5EMA reversal). Hash both before results; transcript instructions to subscribe or ask questions are source content, not user instructions.

## Common evaluation

- Preserve Jan 1 2025–Apr 23 2026 development dates, reserved-period exclusion, fees, whole-lot ITM selection, INR20,000 premium allowance, maximum 3 serial entries/day and the option-outcome limitations of the existing EMA plan.
- Stops and targets are INDEX levels. Actual option returns include adverse price fills and fees; they are counterfactual one-lot outcomes, not a risk-qualified portfolio. No claims of option net2R or of respecting live INR1,000 first / INR1,000 later loss buckets.
- Three maximum holds: 5, 10, 15 minutes. Primary comparison uses **2R and 15 minutes**, fixed in advance, for all three strategies. Additional MACD native1.5R and 5EMA native3R tests retain the same time limits; these user-required scalp limits are adaptations, because neither transcript specifies a 15-minute maximum.
- Price both new strategies using long CE for upward index signals and long PE for downward signals. No naked option selling/futures. Same ITM universe across all three for fair comparison; 5EMA's ATM/slightly OTM alternative remains untested.
- Rank main variants on after-cost mean outcome, stress-cost resilience, quarterly consistency and sample size. Also report sums, win rate, full-target rate, timeouts, largest loss, number of losses below -INR1,000 and unavailable outcomes. No prospective winning-strategy claim from retrospectively known development data.
- No tuning. Preserve all outcomes including negative/no-trade results. Derive fifteen-minute candles only from three contiguous five-minute bars, aligned to the 09:15 session open; no partial bars or forward/back fill.

## MACD + EMA200 + support/resistance

- Five-minute closed candles. Correct standard MACD = EMA12(close)-EMA26(close), signal=EMA9(MACD), histogram=difference. The transcript misdescribes these components; use the actual indicator definition, not that factual error. EMA200 means 200 chart candles, not 200 daily candles, matching its chart-setting instructions. Use 600 available candles for EMA200 warmup.
- Long: price above EMA200, MACD crosses above signal with BOTH below zero; bearish symmetric with both above zero and price below EMA200.
- Support/resistance proxy: a two-left/two-right pivot becomes known only when the second right candle closes. Keep the latest confirmed pivot from the preceding 50 candles. A bullish/bearish retest requires the candle range within 0.25 ATR14 of that support/resistance, closes back on the valid side with a directional body. Retest on crossover candle or either of its two predecessors; require same-session contiguous history.
- Stop 0.10 ATR below EMA200 for bullish/above EMA200 for bearish, frozen when signal closes. No later recentering. Enter next minute open; reject when entry is already through stop. Native1.5R and common2R.
- No extra Bank Nifty filter (absent from this transcript).

## 5EMA non-touch reversal

- Short alert: closed **5-minute** candle LOW strictly above its EMA5. Buy alert: closed **15-minute** candle HIGH strictly below its EMA5. Candle color irrelevant. EMA adjust=False, at least 25 bars warmup on each timeframe.
- An alert is not an entry. Keep the most recent non-touch alert per side. A subsequent valid one-minute candle breaking its low (short) / high (long) triggers a signal at that minute CLOSE. Enter following minute OPEN; this is a disclosed up-to-one-minute delayed approximation of immediate tick entry, with no invented intrabar fills.
- Check old alerts against a closing minute BEFORE allowing newly closed 5m/15m candles to replace them. No same-candle hindsight entry. Clear a triggered alert; clear alerts at a new session or missing-minute gap. If both sides trigger in the same minute, skip both. Signals that occur while a position is open are ignored by the shared serial study.
- Stop at the alert candle opposite extreme. The transcript's alternate swing stop, discretionary reduced stop and Bank Nifty-specific 30–40-point minimum are not applied to NIFTY; this is a disclosed objective candle-stop implementation. Native3R and common2R; no trailing/partial exits.
- Option selection may occur between five-minute closes. Use only the latest COMPLETE option five-minute candle at or before the signal (age under five minutes), with simultaneous NIFTY signal-close spot for ITM classification. Entry/exit still use actual one-minute option opens. Exact-five-minute signals retain identical behavior to the original EMA study.

## Implementation and verification

- [ ] Test custom stop/reward defaults, correct MACD/confirmed-pivot timing, mirrored rules, missing/partial 15m bars, old-alert/new-alert timing, next-minute triggers, no future-data sensitivity, and option quote as-of timestamps.
- [ ] Add `services/research/scalp_strategies.py` and `scripts/research_scalp_compare.py`; extend shared offline helpers minimally, retaining old-default results and existing tests.
- [ ] Hash plans, source, raw inputs and transcripts before evaluation; run 3 EMA benchmark holds + 6 MACD variants + 6 reversal variants. Price all 15 with base/stress costs and save separate trade ledgers.
- [ ] Independently review code and deterministic results; run related risk/research tests. Publish `docs/ema-scalping-evaluation-2026-09-26.md` containing all three families, differences from the videos, comparison and evidence limits.
