# DPA Liquidity Sweep Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement and test the linked article as a separate TradingView strategy.
**Architecture:** Completed HTF structural context feeds a causal local swing → sweep → acceptance state machine. Native simulated orders use frozen stops and external targets.
**Tech Stack:** Pine v6; existing PineTS runtime and Node test runner; TradingView compiler/tester.
**Spec:** docs/superpowers/specs/2026-10-28-dpa-liquidity-sweep-design.md

## Global constraints
Preserve other strategies. Standard price charts only. Bull/Bear labels. No broker orders. No retrospective pivots or intraday forced exit. Disclose mechanical interpretations of discretionary source rules.

## Review focus
- New HTF context arriving after an older LTF swing must not retrospectively qualify it.
- Sweep-bar wick through the trigger must not enter before later confirmation.
- Pre-entry origin/target touch cancels; trade stops/targets stay frozen after entry.
- Costs, small ranges, mirrored long setups, overnight positions and native exit timing.
- Real HTF request must offset every tuple component with lookahead_on.

## Task 1: Strategy and executable rule tests
Files: scripts/tradingview/dpa_liquidity_sweep_strategy.pine; scripts/tradingview/tests/dpa_liquidity_sweep.test.cjs
Interfaces: f_context(); f_closed_context(); f_rules(direction, high, low, key, pivotHigh, pivotLow, pivotKey, initialPullLow, initialPullHigh, confirmed, eligible). Return signal, phase, swept level, trigger, stop, target, net R, formed, swept, rejected.
- [x] Write failing actual-Pine fixtures for sequence, mirrored entries, costs, invalidations and context chronology.
- [x] Run tests and observe failure before adding production Pine.
- [x] Implement context, sequence, native orders, table and chart plots.
- [x] Run the rule/order fixtures and existing Pine suites; expected all pass.

## Task 2: TradingView validation and documentation
Files: scripts/tradingview/dpa_liquidity_sweep_README.md; docs/validation/dpa-liquidity-sweep-2026-10-28.md; screenshot directory.
- [x] Compile as a separate TradingView strategy on standard NIFTY 15-minute chart.
- [x] Inspect Strategy Tester results and actual trade examples without optimizing for profits.
- [x] Request independent code review; fix important findings with regression tests.
- [x] Record exact settings, test coverage, actual available history, results and limitations.

## Execution ledger
User requested implementation and testing; continue directly in this session. Existing checkout has unrelated work: create separate files only and do not stage or commit unrelated changes. No new commit requested.

Task 1 complete: 25 new actual-Pine rule/context/order tests; 59/59 full suite passed, 0 failures (28 October2026). RED→GREEN observed before production source and for range retirement/table-state regressions.
Task 2 complete: TradingView compiler successful; NIFTY and SENSEX15m with1h context validated, Properties costs inspected. Independent review identified spent-range reuse and retired-state display; both fixed and regression-tested. Evidence and limits recorded in docs/validation/dpa-liquidity-sweep-2026-10-28.md.
Implementation decision: retire an impulse permanently on either external boundary touch, not only its pending local setup; reset only on context change. This prevents chasing spent liquidity.
Chart accommodation: account limit rejected another indicator; replaced only our existing PK draft instance for validation, preserving the separate PK source and all other user indicators. DPA restored to NIFTY15m at completion. No commit/push requested or performed.
