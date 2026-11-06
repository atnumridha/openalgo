# Automatic Chart Entry and Risk Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** Plot automatic or user-provided entry with structure/ATR SL and an exact 2R target on the selected chart.
**Architecture:** Pure causal math and setup detection; a memoized planner panel; existing option cash-estimate API reused; chart lines scoped to the active instrument/timeframe.
**Tech Stack:** React 19, TypeScript, TanStack Query, lightweight-charts, Vitest; existing Python fee API.
**Spec:** docs/superpowers/specs/2026-10-30-automatic-chart-entry-risk-design.md

## Global Constraints
- No order endpoints or brokerage-account changes; preserve existing user work.
- Actual running checkout /Users/nmandal/.codex/worktrees/neo-native/openalgo; reuse it.
- No new dependencies. Keep the existing theme, compact dock and fitted plot.
- User-supplied external entry is authoritative; target distance exactly twice SL distance.
- Browser access was explicitly blocked; no browser/CDP/Playwright workaround.

## Review Focus
- CE/PE both long premium; BTC shorts reverse signs, never use option rupee fees.
- A forming/cached candle cannot become confirmed just because time passed.
- Off-tick average fills cannot be labelled exact executable 2R; reject with a clear explanation.
- Entry editing, symbol/timeframe/user changes, replay and delayed history clear or freeze the correct plan.
- UI defaults and loading states must never plot a fabricated trade or rerun heavy calculations per quote.

### Task 1: Local plan mathematics and confirmed setup
Files: new chartTradePlan.ts and chartTradePlan.test.ts in frontend/src/components/neo-desk.
- [x] Test ATR warmup, causal pivots, long/short SL geometry, exact tick arithmetic, invalid inputs, prefix consistency, retest expiry and gaps; watch RED.
- [x] Implement immutable plan data and O(N) causal calculations, consuming verified UTC bars and known trend bars only.
- [x] Run focused math tests; record evidence.

### Task 2: Planner panel and chart integration
Files: new ChartEntryPlan.tsx/test.tsx; modify PremiumRiskPreview.tsx and NeoMarketChart.tsx/test.tsx.
- [x] Test authoritative external entry, edit/apply/recalculate/freeze, direction, clearing on unavailable scope, and reuse of option fee estimates; watch RED.
- [x] Add Automatic / Outside entry modes, existing style controls, exact 2R labels and reasons when unavailable.
- [x] Plot scoped levels immediately from local math; keep option estimates in the expanded dock and index/BTC values in their own price units.
- [x] Run appropriate tests, typecheck and production build; obtain independent source review; fix important findings and verify.
- [x] Deploy local frontend build and verify served assets. Report browser visual-QA limitation.

## Ledger
Initial decision: user action authorizes implementing the already-described design plus the outside-entry override; no additional design approval is needed. Existing linked running worktree is reused. No commits or changes to unrelated work are requested.


### Scope extension: all chart signals and research setups
- User explicitly limited the scope to chart signals/research; automated order-placing strategies are unchanged.
- Added broker master search, per-contract tick/session metadata, shared Indicators controls, and independent one-minute research sources on every display timeframe.
- Price-based studies use the selected instrument. Bought CE/PE remain long premiums; unknown commodity/currency cash underlyings are not guessed. Their automatic mode explicitly uses bullish own-premium 15m structure.
- Archived index-only research defaults remain available to historical callers; the active chart opts into own-price research and exact2R.
- Missing preceding-session data stays unavailable and retries; an older weekday never silently substitutes. Weekday Daily and partial final intraday session ATR regressions are covered.

### Scope extension: crypto verification
- User explicitly requested 24/7 crypto support/resistance, entry/SL/target and LONG/SHORT signals across indicators/setups.
- BB/Chikou now supports continuous sessions, confirmed source timing, tick-rounded stops and exact2R chart references. Toolkit/Nine rebuild timing/numerics/structure after missing continuous-market bars.
- Delta chart and hourly reference studies use each source's own fixed request observation time. Cached partial candles cannot become confirmed by the clock alone.
- Display labels for perpetuals use LONG/SHORT throughout price indicators, candle evidence, BB and research. Genuine Delta OI history pairs exact completed price/OI timestamps; failed refreshes immediately return WAIT. Perpetual IV/PCR are explicitly inapplicable.
- Public Delta BTC/ETH live-data smoke: 500 bars each at5m/1h/1d, all six price studies, support/resistance and both risk-plan directions passed95 arithmetic/data checks. Sample math4–13ms, excluding network/UI.
- Public BTC/ETH one-minute samples across three dates exercised all five research setups with exact2R trades, including UTC previous-day/opening range. This is functional verification, not performance or profitability evidence.

## Review and verification evidence
Independent source review caught and led to regression fixes for automatic-plan freezing, Daily/session ATR continuity, prior-session coverage/substitution, non-equity sessions, crypto partial-candle confirmation, cross-gap signals, separately cached reference candles and failed OI refreshes. Typecheck and36 backend checks passed. Final frontend suite/build and deployment results are recorded below after completion.


### Expanded compatibility audit requested by the user
The 17 representative profiles cover NIFTY, BANKNIFTY, SENSEX, NSE equities, stock futures, index/stock CE and PE, MCX futures/options, CDS futures, BTCUSD and ETHUSD. All seven chart timeframes (1m,3m,5m,15m,30m,1h,1d) exercise numeric readiness, no future-data leakage, chart structure and both tick-aligned 2R plan geometries. Separate cases exercise both directions of every price-indicator rule, combined RSI/MACD, BB, and every research mode on each profile. This validates generic symbol behavior; it does not claim a live quote/history test for every listed broker contract.

Additional audit fixes: FVG crypto continuity over the display-date boundary, confirmed BB Daily setups with real session-close handling, per-contract session close in Toolkit/Nine, and no short-premium BB risk reference on bought CE/PE charts. Bearish option observations display AVOID; crypto observations display SHORT. Focused compatibility matrix plus BB tests:250 passing. Source review is rechecking these final changes.


### Final release verification
- 794 frontend tests passed across 55 files in34.35s; full type check passed.
- 36 backend contract/risk/fee tests passed. The production frontend build passed in1.77s (existing large-chunk advisory remains).
- The compatibility matrix now has255 cases. Candlestick evidence uses contract session/tick rules; old incompatible probability seeds are rejected. Both directions and exact2R tick-aligned geometry are checked. Broker midnight-UTC Daily stamps are covered.
- Independent source review identified the candlestick metadata/seed, failed-history overlay and separately successful range-history boundaries; all were corrected and regression tested. Verified selected-date history remains usable when the separate recent-history request fails.
- Real BTC/ETH history:1,531 arithmetic/data assertions passed over2,994 completed observations, including715 candlestick patterns. Sample combined calculations5.28–15.27ms, excluding network/UI. The earlier all-five-mode crypto research checks also passed.
- The local service was restarted. Health returned200; both new authenticated routes correctly returned401 anonymously. All index-referenced production assets returned200 and matched the built files byte-for-byte.
- Browser interaction remains unverified because access was blocked by environment URL policy. No alternate browser workaround, order placement or automated strategy changes were made.
- Detailed scope and limitations: docs/validation/2026-10-30-chart-symbol-compatibility.md.
