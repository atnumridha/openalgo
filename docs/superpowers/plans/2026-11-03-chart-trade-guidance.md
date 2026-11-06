# Chart Trade Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add the approved collapsible, advisory Trade guide to the active Trading chart.

**Architecture:** A pure guidance model and a small React card consume existing chart plans and explicit selected-broker display snapshots. Extend the existing read-only option preview with an explicit fee profile and optional target; preserve its default Kotak behavior and all execution controls.

**Tech Stack:** Existing React/TypeScript, TanStack Query, Flask/Python Decimal, Vitest and pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-chart-trade-guidance-design.md` (approved 3 November).

## Global Constraints

- Guidance only: no order mutations, new entry blocks or changes to trading rules.
- Existing active source: `/Users/nmandal/.codex/worktrees/neo-native/openalgo`. Preserve unrelated uncommitted work; do not stage/commit it or change worktree ownership.
- One compact collapsible card in the existing side panel; no table over the candles.
- Explicit broker fee profile, real contract metadata, fixed Delta USD/INR conversion 85, estimated outcomes labelled.
- Do not substitute available margin for account balance or fabricate live trade history.
- Keep frozen plans fixed, separate chart timeframes from backend Auto, and label replay/stale/missing evidence.

## Review Focus

- A bought PE uses a stop below its premium entry even with a falling underlying.
- Switching symbol, broker, quantity or fee day must discard previous estimates.
- A profitable trailing stop can be beyond entry; do not display it as a loss or reject it as a new-entry stop.
- A live Delta Auto context must not be confused with the displayed chart timeframe.
- Missing/old account data and incomplete recent fills must not become zero risk or zero losses.

### Task 1: Explicit option fee profiles

**Files:** `services/neo_desk/option_risk_preview.py`, new `services/neo_desk/flattrade_fees.py`, `test/neo_desk/test_option_risk_preview.py`.

**Interfaces:** Extend `option_risk_preview(body, contract, day=None)` with optional `broker: 'kotak' | 'flattrade'` and `target`, retaining the old defaults. Return explicit `broker` and fee source. Flattrade components follow its dated published calculator.

- [x] Add tests for Flattrade's ₹103.01 NSE example, BSE profile, CE/PE, explicit target, invalid broker/target and unchanged Kotak defaults; observe RED.
- [x] Implement Decimal fee estimates and validated optional fields; observe GREEN with the existing option preview tests.

### Task 2: Pure guidance and card

**Files:** new `frontend/src/components/neo-desk/tradeGuidance.ts`, `tradeGuidance.test.ts`, `TradeGuide.tsx`, `TradeGuide.test.tsx`; extend `optionRiskApi.ts` types.

**Interfaces:** Export `GuidePlan`, `GuideBrokerContext`, `readTradeGuidance`, and Delta display adapter. The card consumes chart trend readings, interval, live/replay state, current quote, contract metadata, optional frozen plan and optional selected-broker context. It uses only the existing GET risk-preview endpoint.

- [x] Test fresh/mixed/stale trend, crossed long/short plans, CE/PE premium direction, Delta maker/taker costs and profitable stops, quantity changes and missing balance/history; observe RED.
- [x] Implement the model and collapsible card with explicit fee/quantity controls for unconnected planning, no trade buttons, timestamps and journal reminders; observe GREEN.

### Task 3: Connect existing display contexts

**Files:** `NeoMarketChart.tsx`, `DeltaTradePanel.tsx`, `CombinedChartPanel.tsx`, relevant tests.

**Interfaces:** Optional `onGuidance(context: GuideBrokerContext | null)` callbacks pass selected quantities, current plans, quotes and existing account data. Use existing `planningBars`, `calculateEntryPlan` and preview lines for a clearly labelled planning fallback; no additional signal engine or account reads.

- [x] Add tests for guide integration and callback updates without order mutations; observe RED.
- [x] Mount card in existing side panel, wire read-only contexts and preserve replay isolation and current execution behavior; observe GREEN.

### Task 4: Verify and show

- [x] Run affected backend/frontend suites, production build and inspect any failures against baseline.
- [x] Run a fresh review of this change, resolve important findings and rerun affected tests.
- [x] Show the served guide in Chrome, verify expanded/collapsed views and quantity/profile controls using reads only. Test narrow layout with a disposable clearly identified fixture if native window resizing is unavailable.
- [x] Update the design status and report verification and remaining data limits.

## Execution notes

The user approved implementation in this session. Execute inline without another approval round. The app worktree is owned by another task, so it cannot be attached here; ownership remains unchanged. Apply only scoped file patches with original-content checks and retain a before/after patch for review. No automatic commit of the serving checkout's existing uncommitted files.


### User-requested extension: Kotak Neo orders

- [x] Add regressions for external pending orders, SL trigger prices, remaining quantities, terminal removal, account/mode/symbol scoping, equity read-only view and unavailable orderbook state.
- [x] Reuse existing one-second snapshots and chart price-line overlay, with no new trading actions.
- [x] Review cancellation/controller races and explicitly unverified averages; add failing regressions and fix them.
- [x] Publish the read-only order view and record verification. Pending Kotak order detection is fixture-verified; a real pending Kotak order was not observed on a matching chart during this check.


## Final verification, 3 November 2026

- Backend: 236 tests passed in the isolated neo_desk suite.
- Frontend affected integration run: 301 passed; one pre-existing Delta trade-alert test failed. The same alert failure was reproduced with the saved pre-change Delta panel. After the final quantity-label-only correction, all 47 focused guide/order tests passed again.
- TypeScript and production build passed after the final correction. Existing oversized-chunk warning remains.
- Fresh review findings addressed: partial Delta SL coverage, unconfirmed/cancelled Indian broker stops, explicitly unverified position cost basis, stale snapshot churn and manual/Auto plan labels.
- Served read-only Flattrade fee endpoint returns the explicit dated zero-brokerage profile. Live BTCUSD guide, collapse/expand and live position observation verified. Small-layout fixture verified at 360px.
- No execution strategy, Auto setting or financial order was changed/submitted for testing. The user's already-running Auto continued independently.
- Limitation: no real pending Kotak order was observed on its matching chart during browser verification; terminal removal, partial fills, trigger versus limit prices and read-only equity overlay are covered by normalized-data fixtures.
