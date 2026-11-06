# Delta scalping context implementation plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution and a fresh final review.

**Goal:** Fixed 1m/5m Delta scalping checks that do not change with the display chart.
**Architecture:** A pure history-to-risk adapter plus a public-data React Query hook feeds the existing trade panel. Recovery permissions include a strategy namespace; old trade management retains its chart context.
**Tech Stack:** TypeScript, React Query, Vitest, existing Delta public feed and Flask execution API.
**Spec:** docs/superpowers/specs/2026-11-02-delta-scalping-context-design.md

## Global constraints
- Only fresh closed 1m/5m data may authorize an entry; no replay/snapshot/non-Delta execution.
- Keep the current trend/protection algorithm and all broker/risk/ownership checks.
- No live order mutations or Auto activation in verification; no automatic conversion of legacy permissions.
- Preserve existing positions, unrelated dirty files and editable leverage/quantity defaults.

## Review focus
- Missing/error/stale 5m history must not silently drop the filter.
- Hiding patterns or changing chart interval must not change execution scope.
- Old symbol responses, forming bars and cached history must not authorize entries.
- Old recovery records must not activate the new mode; new scoped permission must revoke cross-tab.
- Small targets must cover fresh verified fees; unsupported fee metadata blocks new scalps.

### Task 1: Dedicated history adapter and hook
Files: create deltaScalpRisk.ts, useDeltaScalpRisk.ts, and their tests under frontend/src/components/neo-desk/.
- [x] Write failing cases for closed UTC normalization, 1m/5m alignment, missing/stale/mismatched/gapped data, and the fee floor.
- [x] Run RED; implement adapter using existing analyzeTrend/supportResistanceLevels and a verified fee calculation.
- [x] Test hook requesting only 1m/5m, refetch at minute close, periodic/error recovery, cleanup and disabled/replay gating.
- [x] Run GREEN.

### Task 2: Wire execution, recovery and visible status
Files: modify NeoMarketChart.tsx/tests, DeltaTradePanel.tsx/tests, deltaRecovery.ts/tests, deltaRisk.ts optional trend summary.
- [x] Write failing integration cases: 15m display still supplies 60-second risk, studies off still uses 5m, history/replay disables execution.
- [x] Write failing recovery/entry cases for legacy permission isolation, scoped resume/revocation, fresh fee preflight and exactly-once maker entry with SL/target.
- [x] Wire hook, compact execution status, scoped recovery and existing-plan management fallback.
- [x] Run focused regression tests, then frontend suite and build.

### Task 3: Verify and publish
- [x] Replay the saved public snapshot through the new adapter and pure backend candle guard; no simulated profitability claims.
- [x] Fresh review of touched files; address material findings with failing tests first.
- [x] Typecheck/build, publish assets/index atomically, and verify served files plus a read-only UI inspection. Do not reload an armed live tab.
- [x] Save evidence in docs/validation/delta-scalping-context-2026-11-02/ and report actual results/limitations.

Execution ruling: the user has approved the distinct 1m/5m approach. Preserve existing algorithm values and implement the bounded wiring directly. No commits: this existing managed worktree contains extensive unrelated work.
