# 51 Trading Strategies OpenAlgo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Install a separate live51-strategy chart guide with causal confirmations, clear prerequisites, drawings and one risk plan, preserving all existing studies.

**Architecture:** Typed source catalog plus shared indicator series and chapter evaluators. A scoped deterministic lifecycle feeds a compact own React guide and an independent instance of the existing drawing utility. Three additive host hooks register, reconcile and display it.

**Tech Stack:** Existing React19/TypeScript/Vitest/Lightweight Charts5/Vite8; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-06-strategies51-openalgo-design.md`.

## Global Constraints

- Existing linked workspace `/Users/nmandal/.codex/worktrees/neo-native/openalgo`, branch `codex/neo-native-kotak`; source staging/evidence in the primary workspace. Preserve the dirty tree; no automatic commits, merge or cleanup.
- No changes to existing Book/Pine/indicator engines or order/broker/risk controls. New study `strategies-51-guide`; fixed-risk references only.
- All51 IDs are represented; missing data/manual/source rules cannot produce fabricated confirmation. Numerical defaults are local and disclosed.
- Closed-candle confirmation, actual UTC/as-of completion, latest10 labels, optional history/pending, dotted source links and one frozen plan.
- Build to isolated output. Copy bounded new/host source into served checkout with hash checks. Deploy index last and retain old assets; no service restart.

## Review Focus

- A wrong historical option identity/OI/VIX must not turn underlying OHLC into a premium signal.
- Future-confirmed pivots/clouds or wall-clock advancement must not backdate confirmations.
- Source stop/target/exit exceptions and one-sided strategies must survive the shared plan abstraction.
- Corrections, symbol/interval/replay changes and delayed history must clear mismatched current plans.
- The new51-row catalog must remain collapsed by default without hiding actual prerequisite failures.

### Task 1: Catalog, indicators and source evaluators

**Files:** Create `frontend/src/components/strategy51-guide/{types,catalog,indicators,chartRules,optionRules,priceActionRules}.ts` and focused tests; source audit metadata under the new directory.

**Interfaces:** `evaluateStrategy51(bars,context,settings,extras): Strategy51Result`;51 `StrategyDefinition` items; read-only UTC bar/context input. Later tasks consume typed events/rows, never duplicate strategy IDs.

- [x] Write catalog and formula tests, plus chapter-specific positive/negative and missing-prerequisite cases; run and observe failure.
- [x] Implement51 definitions, shared canonical series, per-strategy evidence/sequence evaluation and explicit manual/data/timeframe statuses.
- [x] Verify formulas, long-only branches,4L/4R, VWAP volume gates, MTF as-of RSI and actual-premium option rules; inspect all51 evaluated rows.

### Task 2: One-plan lifecycle, risk, preferences and drawings

**Files:** Create `engine.ts`, `preferences.ts`, `Strategy51Layer.ts` and tests in the new directory; reuse Book types/risk/drawing utility read-only.

**Interfaces:** `Strategy51Engine.reconcile(bars,context,settings,extras)` returns rows/events/plan/progress. Preferences are symbol-scoped and versioned. Layer `update(result,bars,settings)` owns its own instance and supports `destroy()`.

- [x] Write failing causal-prefix, history-correction, forming/stale, plan-freeze, stop/target ambiguity, timed exit, focus, sizing and geometry tests.
- [x] Implement deterministic bounded reconciliation and a single frozen plan; source conditional exits and local target labels remain explicit.
- [x] Implement new preferences and source-linked drawing adapter; test bounded/latest10 display, corrupted storage, identity resets and detach cleanup.

### Task 3: Compact guide, data and host integration

**Files:** New `Strategy51Guide.tsx`, read-only `useStrategy51Data.ts`, UI tests. Modify only `neo-desk/{NeoMarketChart.tsx,chartStudyChoices.ts,NeoTradingViewWorkspace.tsx}` plus narrowly scoped integration tests.

**Interfaces:** Host passes verified bars, matching source context, settings and read-only extras into own engine/layer; guide receives the resulting51 rows and callbacks. Enabled study controls all added reads/timers. Disabling clears only owned drawings.

- [x] Write failing registration, compact-summary,51-catalog/filter, settings, data-gate and enable/disable tests.
- [x] Add independent guide, own storage, optional auxiliary history/contract reads and minimal additive host integration.
- [x] Verify study activation, no initial account reads/orders, stale/failed data descriptions and no old preference mutation.

### Task 4: Review, deployment and native acceptance

**Files:** Evidence `workspace/strategies51-2026-11-06/`; validation note `docs/validation/2026-11-06-strategies51-openalgo.md`.

- [x] Run all new tests, relevant existing host/drawing tests, targeted lint and isolated production type/build; verify old hashes.
- [x] Obtain a fresh whole-change review per executing-plans; handle material findings with reproducing tests, record limits.
- [x] Deploy only verified static assets, retaining old chunks; enable study through native OpenAlgo UI.
- [ ] Final native appearance and post-reload persistence check: initial all51/data/geometry acceptance observed; simplified build is deployed but Computer Use ended on a denied URL before the final check. TradingView was not closed.

## Execution rulings

The prior Book acceptance gate is complete. The user's explicit continuation instruction and previous accepted one-plan/compact/no-old-changes choices govern this extension; do not ask the same approach/process questions again. Use inline execution and one fresh final reviewer. The source audit's old read-only boundary described that research task, not a prohibition on the user's now-authorized implementation or necessary read-only chart data.
