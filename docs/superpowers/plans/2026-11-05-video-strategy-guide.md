# Video Strategy Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put every video strategy name into both chart guides with source-faithful detections where rules are shown, explicit incomplete-source states otherwise, and clear next-condition guidance.

**Architecture:** A pure completed-candle engine produces immutable observations and one selected display plan. OpenAlgo renders those through a compact guide and a dedicated chart layer; the combined Pine indicator mirrors the engine and catalogue, validated using shared OHLC fixtures. Neither renderer changes broker or Auto decisions.

**Tech Stack:** Existing React/TypeScript/lightweight-charts, Pine Script v6, Vitest and existing PineTS runtime. No new installed dependencies.

**Spec:** `docs/superpowers/specs/2026-11-04-video-strategy-guide-design.md`, with 5 November source-only scope ruling below.

## Global Constraints

- User response on 5 November: “all from the video”. Include all fifteen names. Do not silently enable the six proposed local variants as if they came from the video. Implement the eight illustrated concepts; named-only concepts and incomplete KRM remain visible as source-incomplete unless the original creator's complete rules can be verified.
- Existing compact guide, confirmed observations, last ten chart candles, older-history and pending opt-ins remain. One selected new guide plan at a time.
- Preserve existing studies, live broker position overlays, GJ and A-01…A-07 configuration work. No order actions or changes to eligibility.
- Current live OpenAlgo checkout: `/Users/nmandal/.codex/worktrees/neo-native/openalgo`. Pine source: primary checkout. Back up exact current files and use minimal integrations; never overwrite concurrent work from an old copy.
- Source discretion such as strict 2-left/2-right pivots and ATR thresholds must be visible as implementation settings, not claimed author rules. All eight engines use the reviewed deterministic choices in the spec.

## Review Focus

- A zone is known before its next-bar retest; a creation bar cannot fill its own plan or invalidate its own OTE extreme.
- Missing/forming/invalid bars must never become fresh actions merely through a browser clock advancing.
- Old terminal observations must not become the next automatic fresh selection.
- A failed FVG/OB can create one distinct conversion record without resurrecting its original plan.
- Index, futures and option-premium price units must not become interchangeable buy/sell instructions.

### Task 1: Source catalogue, causal engine and fixtures

**Files:** Create in live frontend `src/components/chart-toolkit/videoStrategyGuide.ts`, `videoStrategyTypes.ts`, `videoStrategyCatalog.ts`, `videoStrategyGuide.test.ts`; shared fixtures in primary `scripts/tradingview/validation/video-strategy-fixtures.json`.

**Interfaces:** `videoStrategyGuide(bars, {seconds, asOf, tickSize, session?, indian?, standard?}) -> VideoGuideResult`. Result includes fifteen catalogue readings, causal events/history, latest completed time and chosen id; event fields: id, strategy, side, status, createdAt, confirmedAt, entryAt, watch, entry, stop, target, zoneLow, zoneHigh, reason, evidence. `chooseVideoSetup(result, selectedId?)` selects current records and reports mixed current directions.

- [x] Write red tests for fifteen-name coverage, incomplete source methods, mirrored FVG/OB/sweep/BOS/CHoCH/IFVG/breaker/OTE, strict close breaks, known pivots, terminal lifecycle, no own-bar fills, frozen OTE, gaps and future/forming inputs.
- [x] Observe missing-module failures; implement bounded causal state, source catalogue and eight recipes with exact reviewed rules, source status and numeric settings labelled.
- [x] Run engine tests plus shared fixture generation/independent assertions; retain actual OHLC fixture cases for Pine comparisons.

### Task 2: OpenAlgo guide and one-plan chart display

**Files:** Create live `src/components/neo-desk/VideoStrategyGuide.tsx`, its tests, `src/components/chart-toolkit/VideoStrategyLayer.ts`, its tests. Minimal integration in `NeoMarketChart.tsx` and its tests.

**Interfaces:** Component consumes result/selection, controlled `onSelect(id)` and current symbol/interval/option side; layer `update(result, selectedId, {first,last,showPending,showAll})`, `destroy()`.

- [x] Red tests: all source names, wait vs current review, explicit missing rules, mixed signals, selected plan, scope reset, option bearish guidance, ten-candle filtering, missing-data clearing and no broker calls.
- [x] Add collapsible source guide, worded direction/action/conditions, available prices and evidence, source-incomplete messages, source numeric settings. Draw one selected zone/watch/entry/SL/target and recent confirmation labels using existing canvas/line patterns.
- [ ] Run engine/layer/component and existing chart integration tests. Build live frontend. Check real chart controls/drawings without trading actions.

### Task 3: Pine port and cross-runtime verification

**Files:** Modify primary `scripts/tradingview/openalgo_combined_indicator.pine`; create `tests/openalgo_video_strategy.test.cjs`; update README and validation record.

**Interfaces:** Delimited production engine `// VIDEO GUIDE ENGINE START/END`, bounded `VGState`/`VGEvent` UDTs, one completed-bar step. Same recipe IDs, statuses, prices and source-completeness catalogue as Task 1. Rendering uses one compact table and one selected plan.

- [x] Write actual-Pine runtime tests red using shared OHLC fixtures, comparing event direction, knowledge time, status, watch/entry/stop/target with production JS/TS output; additional incomplete-source catalogue tests.
- [x] Port the causal state and render new guide without altering existing studies. Reuse ten-candle/history/pending controls; add strategy selection and catalogue expansion.
- [x] Run full Pine suite and focused OpenAlgo regressions.
- [x] Compile/update in TradingView and inspect standard intraday views, controls and rendered drawings; evidence saved for 1m/1H and catalogue. Preserve full local source because Basic plan prevents private save.
- [ ] Verify live OpenAlgo browser visuals and durable TradingView layout persistence.

### Task 4: Fresh review and final validation

- [x] Run a fresh final code review required by executing-plans, focused on causality, stale actions, price units, source claims and broker isolation. Resolve important findings with regressions.
- [ ] Rerun impacted checks, build if code changed, save real UI screenshots and validation evidence. Report exactly which detectors have complete source and which names still require rules.

## Execution ruling

Continue inline under the user's implementation instruction and existing approved compact-guide approach. Do not add another procedural approval question. Source-only scope is a conservative interpretation of the latest reply, clearly communicated before work. Exact-file backups and no broad staging/commits preserve the extensive uncommitted session work.

## Final status

Code/review fixes and scoped verification are done. Build passed, frontend157focusedchecks and Pine234checks passed. Fullfrontend19pre-existingfailures were reproduced against old chart files. TradingView update/compile and native visual checks succeeded after resuming; source recovery and screenshots are recorded in the validation report. Private cloud Save is blocked by the Basic account limit. Live OpenAlgo browser visuals and durable TradingView layout persistence remain unverified. Full validation: `docs/validation/2026-11-05-video-strategy-guide.md`. No merge/push/cleanup performed.
