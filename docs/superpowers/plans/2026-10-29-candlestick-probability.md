# Candlestick Probability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a generic candle-pattern study with honest causal outcome estimates and clear chart levels.

**Architecture:** A pure TypeScript engine powers dashboard, chart and offline evaluation. Per-market seed evidence is optional. UI consumes one shared study contract; independent UI work can proceed against that contract while the engine is tested.

**Tech Stack:** Existing React, TypeScript, Vitest, lightweight-charts; no new dependency.

**Spec:** docs/superpowers/specs/2026-10-29-candlestick-probability-design.md

## Global Constraints

- Work in workspace/candlestick-probability/frontend, a guarded snapshot of the active neo-native frontend.
- Preserve existing votes, source edits and orders; do not commit/push without a current request.
- 2R within ten completed candles; minimum 50 observations and default 80% estimated-event threshold.
- Same rules on all symbols; evidence isolated by symbol/exchange/timeframe and version.

## Review Focus

- Historical replay before a seed cutoff must never see that future evidence.
- Gaps, duplicate invalid OHLC, late-session candidates and both-level bars must fail conservatively.
- A forming/live bar and stale history must never create an actionable confirmed entry.
- Scope changes must clear prior symbol evidence and chart levels.
- Pattern success rates must not be called option returns or future guaranteed win rates.

### Task 1: Causal engine and evidence evaluation

Files: chart-toolkit/candleProbabilityTypes.ts; candleProbability.ts; candleProbability.test.ts; research/evaluate.ts; candleProbabilitySeeds.json.

Interfaces: analyzeCandles(bars, CandleOptions, seed?) -> CandleStudy; detectPattern(history) -> CandleGeometry|null; evidenceEstimate(counts) -> CandleEstimate. The shared types file fixes exact fields before UI work.

- [x] Write fixtures for symmetric geometry, stop/target levels, prefix invariance, ten-bar expiry, gaps and same-bar ambiguity, seed mismatch/future cutoff and minimum samples.
- [x] Run them failing, implement the smallest engine that passes, then rerun.
- [x] Run the engine on audited NIFTY candles at 1/5/15m and preserve chronological predictions/outcomes, per-bucket counts and validation metrics. Report actual observations and qualified cases separately.

### Task 2: Generic chart and dashboard presentation

Files: CandlestickProbabilityPanel.tsx/test; CandleProbabilityLayer.ts/test; DashboardIndicatorSignals.tsx; NeoMarketChart.tsx; NeoTradingViewWorkspace.tsx and affected tests.

Interfaces: consume CandleStudy and CandleOptions; make no broker/order calls. Analysis adapter receives verified bars/asOf and exact market scope. Use existing chart history and study selection.

- [x] Write UI tests for insufficient samples, qualified decision, historical-only/stale status, option/crypto direction wording and level visibility.
- [x] Implement accessible separate card and optional existing-chart layer, with current and last setup explicitly distinguished.
- [x] Verify controls persist, scope changes clear old study, existing nine vote remains independent.

### Task 3: Verification and guarded installation

- [x] Run focused tests, full frontend suite, typecheck, build; report unrelated baseline failures by name.
- [x] Obtain independent code review, fix material findings with regressions.
- [x] Check active frontend baseline, back up replacements, install source/build with index last and retain hashed old assets.
- [x] Reload dashboard and verify actual card, chart selection and levels. Save concise evidence/results report.
