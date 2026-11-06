# Book Patterns & Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new independent book-pattern/trend indicator with one confirmed reference plan, drawings, explanations and monetary risk sizing to OpenAlgo and TradingView.

**Architecture:** A pure typed engine owns reference-specific recognition, closed-candle confirmation, deterministic plan selection and sizing. A separate OpenAlgo layer/guide consumes it through bounded chart-host integration. A new Pine script implements the same contracts and is tested against the TypeScript engine on identical candle prefixes.

**Tech Stack:** TypeScript, React, lightweight-charts 5.2.1, Vitest, Pine Script v6, existing PineTS/Node test tooling. No new dependency.

**Spec:** `/Users/nmandal/Documents/AlgoTrading/openalgo/docs/superpowers/specs/2026-11-05-book-pattern-risk-guide-design.md`

## Global Constraints

- User selected “One plan: pattern + trend confirmation (Recommended)”.
- Preserve OpenAlgoAll and all protected old indicator files byte-for-byte. See preservation hashes under `workspace/book-pattern-risk-guide-2026-11-05/` in the primary workspace.
- Default annotations: latest ten chart candles, confirmed only; pending/neutral/history options are independent new-study settings.
- Permitted additive host edits: `frontend/src/components/neo-desk/{NeoMarketChart.tsx,chartStudyChoices.ts,NeoTradingViewWorkspace.tsx}` and relevant tests. No protected ToolkitLayer/ToolkitPanel edits.
- Reference-specific stops and the executable appendix are binding. Default risk 0.25%, entered equity zero/unset, default fallback/minimum reward-risk 3R; no invented account balance, fill or profitability.
- No broker, execution, bot, account-risk or existing preference migrations. No automatic order actions.
- Serving frontend source is `/Users/nmandal/.codex/worktrees/neo-native/openalgo/frontend`; primary Pine destination is `/Users/nmandal/Documents/AlgoTrading/openalgo/scripts/tradingview/`. Existing linked checkout isolation was verified. The static bundle stays unchanged until final build/deployment.
- Shared checkout has unrelated dirty work. Do not stage/reset/commit it. Record bounded before/after artifacts instead of whole-file commits when a file already contains unrelated work.
- Node path: `/Users/nmandal/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin`. All product edits outside the primary writable root use the normal escalated file-writing tool; do not bypass permissions.

## Review Focus

- A corrected/invalid candle or unverified cached forming candle cannot silently create a closed signal; test in Task 1 and host readiness in Task 2.
- Large symbols, tiny ticks, missing volume/currency/lot metadata cannot fabricate a size or passing filter; test Task 1 and inputs Task 2.
- Multiple detectors qualifying on one candle cannot choose by incidental iteration order or replace an older active plan; test Task 1 and Pine parity Task 3.
- Long retained history, symbol/interval switches and hover during refresh must not delete old indicator objects or reintroduce null renderer crashes; test Task 2 and native Task 4.
- Pine realtime rollback, confirmed-pivot delays and reference-specific body/gap rules must match historical prefix behavior; test Task 3.

---

### Task 1: Pure detector, plan and risk engine

**Files:** Create `frontend/src/components/book-pattern-guide/{types.ts,settings.ts,math.ts,candles.ts,shapes.ts,levels.ts,risk.ts,engine.ts,engine.test.ts,fixtures.ts}` in the serving checkout. Split tests by responsibility if useful. Do not import or edit old detector logic.

**Interfaces:**
- Export `BookBar` with UTC-second `time`, OHLC, `volume`, optional `repaired` provenance.
- Export `BookSettings`, `DEFAULT_BOOK_SETTINGS`, `BookContext`, `BookEvent`, `BookPlan`, `BookGuideResult`, `BookAlert` from this folder. Settings include all documented configurable defaults; context includes identity, interval seconds, current/observed UTC time, source/live readiness, tick and validated linear instrument units.
- Export `BookPatternEngine.reconcile(bars: BookBar[], context: BookContext, settings?: Partial<BookSettings>): BookGuideResult`. Result supplies confirmed/pending events, context observations, active/last terminal plan, alternate matches, explanation/next condition and fresh deduplicated alerts.
- Event fields must expose stable ID, pattern ID/name, side, source photo IDs, formation/recognition/confirmation timestamps, trigger/stop/target method, geometry points/segments and status. Plan exposes ID/side/name, creation time, entry/SL/target, RR, terminal state and optional sizing with unavailable reasons.
- Export `calculateBookRisk(...)` as a pure public function and a deterministic batch-analysis entry point for Pine parity, e.g. `analyzeBookGuide(bars, context, settings)` using the same engine.
- Task 1's report documents exact final interfaces; Tasks 2–3 consume the actual types and report, not a guessed parallel shape.

- [ ] Write failing fixtures before implementation: every named shape/candle in the reference coverage table, positive and nearby invalid cases, mirrored directions, source-specific stop asymmetries and inverted-hammer body confirmation.
- [ ] Run Vitest on the new tests and capture expected missing-engine failures.
- [ ] Implement numerical primitives and detectors from the executable appendix, preserving source evidence versus local rules. No future pivot use, retrospectively recognized breakout, or same-candle later confirmation.
- [ ] Add failing lifecycle/risk fixtures: conflicting sides -> WAIT, same-side deterministic priority, frozen plan, alternative opposite signal, inclusive SL/TP ambiguity, expiry at 50 later closed candles, next-candle-only SR trigger, failed candidate can re-arm on same bar, quantity-step rounding, FX/point-value applied once, missing capital and nonlinear product refusal.
- [ ] Implement buffered stops, price-reference targets, minimum RR filter, risk sizing and one-plan lifecycle. Initial historical reconciliation emits no live alert replay. Repeated forming updates do not advance confirmed state or emit duplicate alerts. Feed correction invalidates affected cached state and recomputes without historical alert replay.
- [ ] Run every-prefix fixtures and settings/identity reset tests. Check invalid/repaired/nonfinite data, missing volume/warm-up and equality boundaries. Capture green results and coverage ledger mapping all 55 photos to detector/context support.
- [ ] Save Task 1 report plus bounded files/diff; obtain task-scoped spec and quality review before Task 2.

### Task 2: Independent OpenAlgo drawing and guide

**Files:** Create `frontend/src/components/book-pattern-guide/{BookPatternLayer.ts,BookPatternGuide.tsx,preferences.ts,BookPatternLayer.test.ts,BookPatternGuide.test.tsx,preferences.test.ts}`. Additive edits only to the three permitted chart hosts and their relevant tests.

**Interfaces:**
- Consume the exported engine/result/types from Task 1.
- `BookPatternLayer` owns only its new series primitives/price lines and offers `update(result, bars, displayOptions)` and `destroy()`; draw complete geometry, labels and the selected Entry/SL/Target. Its cleanup never removes foreign chart objects.
- `BookPatternGuide` consumes result/settings/context and `onSettingsChange`; offers clear pattern, expected/next/invalidation, trend/filter state and risk inputs, with independent storage key `neo.book-pattern-risk-guide.v1`.
- Use study ID `book-pattern-risk-guide`, label `Book patterns & risk · single plan`. Add this ID to the current chart without removing existing selections; retain detailed settings independently.
- Host chart times from `chartBars()` are UTC already. API raw plot times have +19800 shift; never subtract twice. Feed engine verified observation time from the existing host readiness path; do not promote cached bars by clock alone.

- [ ] Write failing UI/layer tests for last-ten retention, hidden pending/neutral, optional history, missing risk inputs, stable single plan, foreign object preservation and cleanup on disable/identity changes.
- [ ] Implement bounded geometry rendering (40 shapes/80 polylines/160 labels/120 lines), entry white/SL red/target green, matching existing chart conventions. Draw on price coordinates; no source-code details in the trading flow.
- [ ] Add accessible settings and compact explanation/risk panel using existing UI components. No new visual design system or browser tab required.
- [ ] Integrate engine updates into chart history/received-candle/quote refresh using the existing chart lifecycle and null-crash guard. Never fetch additional broker data or restart backend workers for this study.
- [ ] Test identity/interval changes, readiness loss/recovery, stale/no-volume after market close and repeated hover/history replacements. Verify prior enabled study IDs/settings stay unchanged.
- [ ] Run affected component tests and production TypeScript/build checks with a dedicated temporary output directory; do not overwrite served frontend/dist before Task 4. Save bounded integration diff and report; obtain task review.

### Task 3: Separate Pine indicator and parity

**Files:** Create `scripts/tradingview/openalgo_book_patterns_risk.pine`, `scripts/tradingview/openalgo_book_patterns_risk_README.md`, `scripts/tradingview/tests/book_patterns_risk.test.cjs` in primary workspace. Do not modify `openalgo_combined_indicator.pine` or old Pine tests.

**Interfaces:**
- Port Task 1's actual settings, detector semantics, event IDs and plan lifecycle. Use a standalone core between `// BOOK ENGINE START` and `// BOOK ENGINE END`, with its own settings/state/event types and deterministic step function. Test wrapper extracts the actual production core; never test only a JS reimplementation.
- Use Node and the existing frontend bundler (Rolldown in this checkout) to load the actual TS engine for parity fixtures. Existing PineTS is available from the current established test runtime; resolve it explicitly without adding dependencies or modifying package files.
- Display new script title `OpenAlgo Book Patterns & Risk`, own price overlays and guide table, source-context/target-method labels and independent risk/display inputs. No `strategy.*` orders.

- [ ] Write a failing actual-Pine-core test from a hand-derived candle confirmation fixture before the Pine implementation.
- [ ] Implement the engine core using confirmed bars and confirmed pivots. Keep forming progress separate; no retrospective entry alert or object creation using future geometry.
- [ ] Extend parity tests to every reference family, source exceptions, strict/local gap settings, prefix timing, side conflicts, plan retention/expiry, risk units and target/stop ambiguity. Negative fixtures must prove detectors do not pass on merely similar shapes.
- [ ] Add drawing retention and budget stress tests, alert deduplication and rollback-safe latest-ten cleanup. Never delete objects belonging to another script.
- [ ] Run new Pine tests plus relevant existing Pine baseline tests as preservation verification. Document incomplete platform emulation explicitly; PineTS success alone is not native acceptance.
- [ ] Save report/diff and obtain task-scoped review.

### Task 4: Native acceptance and bounded delivery

**Files:** New evidence under `workspace/book-pattern-risk-guide-2026-11-05/`, validation report under `docs/validation/2026-11-05-book-pattern-risk-guide.md`. No unrelated product edits.

- [ ] Run complete affected frontend/Pine suites and production build; compare failures with recorded baseline. Do not call a red suite green.
- [ ] Recheck all protected hashes and compare host diffs with before snapshots. Record only this feature's changes, including source hashes and all source coverage rows.
- [ ] Deploy only the frontend static build after checks. Do not restart trading services, change broker state or operate any order control.
- [ ] In TradingView create a **new** Pine indicator, paste/save the new script, compile and add it to the chart. Verify the old saved OpenAlgoAll indicator remains present and unmodified. Use only CUA for browser/native actions and protect against unexpected tab switches.
- [ ] On OpenAlgo enable the new study on the existing chart, verify drawings/guide/settings and repeated candle refreshes. Verify one plan at a time, no pending clutter and no null-renderer crash. Keep TradingView tab open for the user's check.
- [ ] Obtain broad final independent review, address material defects, preserve unresolved external limitations honestly and deliver file links plus validation evidence. No merge, public publication or unrelated commit is required.

## Execution rulings

- Use the existing linked chart checkout and scoped subagent implementation/review tasks. No new checkout is necessary; current compiled static assets are unchanged during source implementation.
- The user has selected the reviewed single-plan approach. Continue implementation without another process-choice question; delegation and test sequencing are routine execution choices.
- Dirty shared source makes whole-branch commits unsafe for unrelated work. Review new files and captured bounded host diffs rather than committing unrelated edits. Each task must still leave a concrete testable artifact and report.

- Runtime check: PineTS 0.13.1 is available at `/private/tmp/tv-combined-validation/node_modules/pinets`; Vite 8 provides Rolldown rather than esbuild. Use this existing bundler for the TS parity oracle; add no dependency.

- Build-output ruling: `frontend/dist` is served directly. Task2 validation must target an owned temporary output directory; default build output is final deployment and belongs only to Task4 after gates. No backend restart is needed.

- Deployment ruling: build the final frontend into owned temporary output, copy new hashed assets alongside retained old assets, then replace served index.html last. Keep earlier hashed files so already-open chart tabs can still load their existing chunks; no backend restart.

### User-directed visual refinement in the final bounded fix wave

Apply the spec's chart clarity refinement before beginning any 51-strategy product implementation. Verify same-price-scale candle outlines, source-role anchors, dotted leaders, outside-body caption placement, compact default guide and independent causal context trend lines. Include exact context geometry and toggle/budget tests in both platforms; perform native visual checks on the final frozen source, including pan/zoom and setting persistence. Keep source audits for51 read-only until this gate is complete.
