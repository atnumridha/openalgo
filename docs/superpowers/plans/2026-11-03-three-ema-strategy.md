# Three EMA Strategy Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement bounded tasks with failing tests and independent review.

**Goal:** Add the approved independent EMA9/15/21 crypto strategy and EMA21 chart overlay.
**Architecture:** Extend the local EMA arithmetic with period21; a pure new detector feeds the existing ensemble action/risk/dedup machinery. Existing completed opposite EMA9/15 crossover management exits its owned position. Shared exposure and protection authorities remain unchanged.
**Tech Stack:** Python, Decimal strategy money, React/TypeScript, Lightweight Charts.
**Spec:** docs/superpowers/specs/2026-11-03-three-ema-strategy-design.md (user approved adaptation).

## Global Constraints
- Completed 1m signals with existing 5m direction filter; no named candle-pattern gate.
- Strict 9/15/21 ordering, each adjacent gap >=0.1ATR14, all slopes over3bars agree; candle closes above/below all EMAs.
- First qualifying alignment after a transition only; durable setup ID anchored to alignment regime, not each signal bar.
- SL beyond farther EMA21/signal wick plus0.25ATR and existing minimum noise distance; never clip for affordability.
- Preserve INR20 full-fee planned loss, maker entries, market exits, exposure lock and structural trailing. No auto-arming by agent.

## Review Focus
- Alignment becoming eligible after slopes/gaps improve must not repeat during unchanged regime.
- A forming candle cannot authorize entry or exit.
- Existing EMA9/15 calculations and cross icons must remain unchanged.
- Additional EMA period must not break older response fixtures or stale async chart work.
- Persisted new strategy ID must route through reviewed exit/recovery and risk checks.

## Tasks
- [x] Add red tests for 21-period SMA seed, recursion, independent copy and previous9/15 behavior; implement backend EMA21 and chart line/legend with frontend tests and TypeScript check.
- [x] Add red mirrored detector tests: transition, slopes, gaps, close location, 5m filter, repeated regime, malformed/stale and forming history; implement `ema_three` in ensemble with stable setup metadata and standard action conversion.
- [x] Verify shared owner persists strategy metadata and exits opposite completed9/15 cross; add regression test if existing coverage does not establish it.
- [x] Run targeted backend/frontend suites, independent spec/safety review and build. Record exact validation outcomes and limitations.
- [x] Hash-check source publication and assets, inspect current exposure before any restart, retain protections. Verify live read-only diagnostics and chart; final financial UI activation stays user-owned.

## Execution ledger
- Approved source adaptation received3November2026. Work staged in existing isolated /private/tmp/delta-loss-fixes; production checkout is neo-native. Do not touch unrelated nominal checkout changes.

- Completed: backend579tests+24subtests,frontend712tests,tsc/build,independentreview;source/assets hashverified,healthpass,liveversion3. BrowserEMA21overlay awaits user refresh; existingOn/fixed4lots100x preserved. No liveorder was created as a test.
