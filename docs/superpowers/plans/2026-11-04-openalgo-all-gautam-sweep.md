# OpenAlgoAll Gautam sweep implementation plan

> **For agentic workers:** Use superpowers:executing-plans for continuous inline execution. The user selected Gautam Jha only.

**Goal:** Add confirmed 1H previous-day sweep reversal observations, reference levels and guides to the existing TradingView indicator.

**Architecture:** A stateful Pine engine consumes chronological 1H OHLC and frozen prior UTC-day levels. A single source adapter handles confirmed higher-timeframe packets and all available lower-timeframe intrabars, then updates bounded price-chart drawings.

**Tech Stack:** Pine Script v6, existing PineTS validation runtime, Node tests, TradingView Pine Editor.

**Spec:** `docs/superpowers/specs/2026-11-04-openalgo-all-sweep-setups-design.md`

## Global constraints

- Gautam Jha only, default on. No PO3 code or new order execution.
- Fixed 12:30–21:30 IST window; completed 1H sweep and immediate next confirmation candle.
- UTC day boundaries and complete prior-day history. No EMA/trend gate.
- Confirmation-close entry reference, one-tick stop beyond sweep, opposite daily extreme target.
- Preserve existing studies, readable labels, dotted leaders and saved local source.

## Review focus

- A source interval gap or midnight must expire pending sweeps.
- Equal touches, doji and wrong-colour confirmation must not trigger.
- A confirmation that touches stop or target must not produce an actionable entry.
- Repeated higher-timeframe packets must not duplicate drawings or alerts.
- Missing previous-day hours and transformed candles must not produce valid signals.

## Task 1: Stateful source engine

Files: modify `scripts/tradingview/openalgo_combined_indicator.pine`; add `scripts/tradingview/tests/openalgo_gautam_sweep.test.cjs`.

Interface: `gj_step(o,h,l,c,opened,closed,day,pdh,pdl,tick,eligible,confirmed)` returns a `GJPacket` with time, references, phase, pending side, armed pulse, signal, sweep time/extreme, trigger, stop, target and entry reference. `gj_day_levels()` produces complete previous UTC-day H/L. `gj_hour()` combines them on 1H input.

- [x] Write behavioral tests that run the actual production Pine engine: Long and Short, pending state, frozen levels, expiry, limits, ambiguous ranges, invalid data and full UTC-day history.
- [x] Run the suite and observe missing-engine failure.
- [x] Implement the minimum production engine; rerun until all rule tests pass.

## Task 2: Chart integration and verification

Files: same indicator; update `scripts/tradingview/openalgo_combined_indicator_README.md`.

Interface: confirmed 1H packets use one timestamp key per source close. A drawing consumer renders pending/confirmed labels and latest guides. Lower chart intervals consume the previous completed 1H packet; higher chart intervals consume all closed source intrabars.

- [x] Add tests for packet deduplication, no forming-source event and bounded drawings, then implement the adapter and consumer.
- [x] Run this suite plus the existing TradingView test suite using the existing PineTS runtime. Record unrelated baseline failures separately.
- [x] Compile the full script in the user's existing TradingView Pine Editor, update its existing chart instance, and inspect BTC 5m and 1H displays.
- [x] Save local source, a chart screenshot and a brief validation record. Report any inaccessible runtime/history limitation explicitly.

## Execution notes

Ruling: work on the existing `codex/kotak-home-assistant` feature branch with exact-file backups; the current indicator is untracked session work and must be preserved. No branch reset, broad staging, broker interaction or unrelated app changes.

Task 1 and Task 2 are complete. A fresh review reproduced a failed-confirmation hour that could not arm its own independent sweep; Long/Short regression tests failed before the correction and passed afterward. Replayed 350 completed BTCUSD hours after that fix; eight confirmations independently reconciled.

The user then requested confirmed recent labels only in both TradingView and OpenAlgo. Added the last-ten-chart-candle display window, all-history option and pending/unconfirmed opt-in, both off by default. Actual Pine drawing tests cover expiry without a new signal and hidden pending state preserving confirmed guides. Final Pine suite: 210 passed, zero failed. The final 884-line source compiled in TradingView and both 5m/1H charts were checked. The account's Basic-plan script limit blocks a private save; the loaded indicator and complete local recovery source were retained.

OpenAlgo's active worktree is `/Users/nmandal/.codex/worktrees/neo-native/openalgo`. Exact original chart/layer files were backed up before the minimal display change. Display defaults and toggles were tested red → green, with 86 focused tests passing and the production frontend build passing. The live page visibly showed “Last 10 candles · Confirmed only”; both toggles were exercised and returned off. Calculation history, strategy settings and order actions were untouched.

Validation record: `docs/validation/2026-11-04-openalgo-all-gautam-sweep.md`. Screenshots, logs, source and exact-file backups are under `workspace/gautam-sweep-2026-11-04/`.
