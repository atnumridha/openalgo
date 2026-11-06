# Video Master Candle Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a separate Pine v6 strategy from the disclosed video rules, install privately in TradingView, and test the selected NIFTY 27 October 2026 option.

**Architecture:** One strategy contains a reusable, causal signal function, chart plots, and simulated order handling. NIFTY generates Bull/Bear direction; option charts buy only the selected CE/PE using their own premium prices. Standard ATR trailing S/R replaces the undisclosed proprietary formula and is explicitly identified as an approximation.

**Tech Stack:** Pine Script v6, independent PineTS behavioral checks, TradingView Strategy Tester.

**Spec:** This document records the implementation decisions from the user's video, supplied summary and backtest request.

## Global Constraints

- Separate private script; preserve existing indicators and source.
- Confirm at candle close; use 5-minute standard candles.
- Setups trigger only on the next three bars; no future pivots or lookahead.
- Breakout, wick rejection and failed-breakout continuation are independent categories.
- Original PK/Early Master/Master and exact dynamic S/R formulas are undisclosed; do not claim a clone.
- Default ATR S/R length 10, multiplier 2: implementation assumptions, configurable.
- Option risk uses premium ATR(14) × 1 and 1R target by default: explicit backtest assumptions, configurable.
- Intraday 09:15–15:30 IST, expiry-day range 27 October 2026; flatten by session end.
- No real orders or public publishing. Never report index-point returns as option P&L.

## Review Focus

- Third bar valid, fourth bar expired; repeated setups cannot extend a pending window.
- Stop touched before confirmation invalidates pending entry; ambiguous stop/trigger candles rejected.
- No setup survives missing bars or a new IST session.
- Option modes only buy matching CE/PE premium; no index-to-premium stop substitution.
- Signal close, execution cost assumptions, limited expiry data and missing original formulas remain visible.

### Task 1: Signal engine and simulator

**Files:** Create `scripts/tradingview/video_master_candle_strategy.pine`, `scripts/tradingview/tests/video_master_candle.test.cjs`, `scripts/tradingview/video_master_candle_README.md`.

**Interfaces:** `f_model()` returns Bull/Bear pulses, signal stop, setup category, S/R and pending state; strategy consumes the pulses and uses chart premium for option orders.

- [x] Write/run failing source tests for delayed confirmation, third/fourth bar expiry, invalidation, rejection, continuation, gap/day reset and closed-bar gating.
- [x] Implement signal engine and risk/exit handling; 10 actual-source PineTS checks pass, including point value conversion.
- [x] Verify TradingView compilation and document assumptions; independent reviewer found no blocking issue.

### Task 2: TradingView expiry test

**Files:** Create `docs/validation/video-master-candle-2026-10-27.md` with verified results and settings.

**Interfaces:** Saved private strategy; user-selected option contract; Strategy Tester report.

- [x] Add separate draft to 5-minute chart. Private saving blocked by Basic plan's one-saved-script limit; source preserved locally, existing saved scripts unchanged.
- [x] Use both 22,700 CE/PE after user answered “both” to that example; verify chart contracts and 75 expiry-day bars.
- [x] Record actual test dates, six trades, net P&L, drawdown, costs and limitations in `docs/validation/video-master-candle-2026-10-27.md`.
