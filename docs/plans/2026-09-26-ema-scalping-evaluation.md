# EMA 9/15 scalping evaluation implementation plan

> **For agentic workers:** Execute inline with superpowers:executing-plans, tests first, then independent code review. This frozen registration must not be edited after seeing results.

**Goal:** Test the user's supplied video summary empirically, including the claimed 90% win rate, without claiming chart accuracy equals option profitability.

**Architecture:** A pure offline signal/outcome module and a reproducible research CLI. Reuse shared position risk decisions; keep the app, live strategies, portfolio limits and previously frozen ML work unchanged.

**Tech Stack:** Python, pandas, NumPy, DuckDB, pytest, existing research costs/risk core.

**Spec:** User-supplied summary of https://www.youtube.com/watch?v=RMwUsnJB40c and the requested 5–15 minute holding window, EMA 9/15 and 1:2 reward/risk. The full video transcript could not be retrieved; the supplied summary is the specification. This is an objective approximation of discretionary rules, not a certified exact reproduction.

## Frozen research rules

- Closed NIFTY 5-minute candles; EMA 9 and 15 use close, adjust=False and at least 75 warmup bars. Historical overnight continuity is retained, but signals require four contiguous same-session candles. No future prices in signals.
- Bullish: EMA9 > EMA15; both rise over three candles by at least 0.10 ATR14 per candle (ATR uses Wilder-style EWM). Bearish is symmetric. A 0.20 threshold is the single registered slope sensitivity. These normalized thresholds replace visual angles, which depend on chart zoom; neither is asserted to equal 30 degrees.
- Signal candle intersects the EMA zone, closes beyond both EMAs in trend direction, and is either a pin bar (rejection wick >= 2 bodies, close in trend-side quarter), full body (body >= 60% range), or big body (range >= 1.5 prior ATR and body >= 50% range). Positive body in trend direction is required.
- Confirmation variant: exact same-time closed Bank Nifty candle agrees in EMA order and slope. Reject when its previous 20-candle high (bullish) or low (bearish) lies ahead within 0.5 ATR. No filling stale/missing confirmation bars. This is an explicit proxy for discretionary resistance/support.
- NIFTY index entry at the next observed one-minute candle's OPEN, after the signal closes. Stop at signal candle low for bullish/high for bearish; target at two times the actual entry-to-stop distance. Reject entry already through stop. Shared risk core decides stop/target; gap fills use observed open. Both boundaries in one minute are stop-first and counted as ambiguous.
- Exit at stop, target or 5/10/15 minutes, whichever first; time is measured from actual entry open (signal close), not the end timestamp of the entry candle. No new signal whose full holding period exceeds 15:25. Missing execution minutes yield unresolved outcomes, never wins or zero P&L. No overnight trades.
- One index position at a time, maximum 3 entries per day. No retroactive trade removal. Report positive-return fraction and full 2R target-hit fraction separately, all time exits and ambiguity, raw counts, mean R, gross point P&L and day-block bootstrap intervals for positive-return fraction. Index P&L is diagnostic, not money earned from a tradable instrument.
- Twelve predeclared variants: 2 slope thresholds x confirmation off/on x 3 holding limits. Main variant is slope 0.10 + confirmation + 15 minutes, fixed before results. All variants retained; do not select the best retrospectively and call it validated.
- Dates: 2025-01-01 through 2026-04-23; report quarters and Jan–Apr 2026. Warmup starts October 2024. Exclude 2026-04-24 onward before features, labels or fitting. These dates were used in earlier development; no independent final qualification.
- Main-variant NIFTY ITM option feasibility/return audit: use nearest observed expiry 1–7 days away and closest strictly ITM strike known from previous-session NSE listings; positive-volume complete signal candle, at least 10 lots of observed volume. Do not substitute OTM or pick a strike using future returns. Read historical lot sizes from previous-session NSE files. Missing metadata is unavailable.
- Price one long option lot at the next one-minute OPEN, and sell at the next one-minute OPEN after the index exit candle closes. This deliberately includes up to one minute of exit-detection latency; premium exit timing is not guessed within an OHLC candle. A 15-minute index time exit sells at its deadline open. Require continuous, positive-volume, valid option minutes while exposed. Unsupported fills remain unavailable. Base costs = 10 bps each side, zero brokerage; stress = 30 bps and INR20/order plus existing explicit taxes/fees. Current assumed fees applied to old prices are hypothetical.
- Report full available one-lot option outcomes and subset affordable with INR10,000 and 20% cash buffer. These are counterfactual observations, not a deployable portfolio: index-based stops do not establish an option-premium loss ceiling or guarantee net 2R. Do not claim they enforce the user's INR1,000/INR1,000 buckets or live drawdown. Those existing controls stay unchanged and live activation is outside this study.
- No ML fitting in this study: first test the user's concrete rules without another learned filter changing the specification. Signal fields are reusable for subsequent ML features.

## Review focus

1. Bar-start/bar-close confusion and future confirmation/option selection.
2. Short direction stop/target semantics, gap fills and ambiguous intraminute order.
3. Missing/duplicate minutes, zero volume and stale dual-index history.
4. ITM affordability, point-in-time lots and option returns incorrectly called net 2R.
5. Denominator/sample selection, overlapping trades and reserved-period leakage.

## Tasks

### 1. Pure signals and minute outcomes

- [ ] Add failing tests in `test/test_research_ema_scalp.py` for causal features, mirrored signals, confirmation, exact holding deadline, missing bars, short/long stops, gap/ambiguous outcomes and statistics denominators.
- [ ] Implement `services/research/ema_scalp.py` and run the focused tests.

### 2. Reproducible data and evaluation CLI

- [ ] Add `scripts/research_ema_scalp.py`, hash the plan/code/input files before tests, screen broker candles without price repair and register all 12 variants.
- [ ] Save per-trade records, signals, source audits and all variant results under a new gitignored research directory. Query large option archives through bounded context-managed DuckDB connections.
- [ ] Test ITM selection and price/cost calculation on controlled fixtures. Run all variants and the main option audit; retain failures and missing evidence.

### 3. Verification and report

- [ ] Independently review code/evidence and fix implementation defects without changing the frozen hypothesis.
- [ ] Reproduce outputs, run related risk/research tests, lint and diff checks; statically audit files, database and network resource closure.
- [ ] Document actual results and limitations in `docs/ema-scalping-evaluation-2026-09-26.md` and link from docs index. No commit/push or live configuration mutation.
