# Bollinger Bands + Chikou Indicator Implementation Plan

**Goal:** Deliver a standalone Pine Script v6 indicator for Nifty and Sensex with confirmed buy/sell markers, alerts, and indicative risk levels.

**Design:** Use chart OHLC, SMA(20), population standard deviation times 2, and current close compared with the candle 26 bars back. The first upper/lower band touch starts a setup; only the immediately following candle can confirm, by closing beyond the setup high/low. Default Chikou clearance is above the historical high or below the historical low; offer close-only comparison. Signals require a closed candle and a positive distance to the middle-band stop. Entry is the confirmation close, initial stop is the confirmation SMA, and target is 1R by default. Levels stay fixed until the next signal or session reset; they are reference levels, not managed positions. No orders or performance claims.

**Approaches:** Intrabar breakout alerts offer earlier signals but can disappear; the user selected candle-close confirmation. Resolve the source's inconsistent stops using the most repeated SMA(20) rule. An optional squeeze filter uses a configurable relative band-width threshold; it is an explicit implementation choice, not a numeric rule from the source. Use literal 26-bar displacement and an optional first-touch filter to avoid repeated band-walk entries.

**Tech stack:** Pine Script v6. Standalone source and installation guide under scripts/tradingview; no application integration or dependency changes.

## Constraints and review focus

- Signals remain on the confirmation candle, never shifted into the past. Only the Chikou visualization is shifted.
- No future data, external symbol calls, orders, or volume requirements.
- Default Indian cash-session filter, 09:15–15:30 Asia/Kolkata, weekdays; do not carry setups across days or session gaps. Require confirmation candle to finish within session.
- Test next-candle expiry, wick-only rejection, Chikou obstruction, invalid risk, and warmup.
- Squeeze filter is off by default; when enabled require recent contraction and expansion at confirmation.

## Task 1: Indicator and user guide

- [x] Write behavior scenarios before implementation and run them against the missing source to observe failure.
- [x] Implement the standalone indicator with configurable bands, Chikou clearance, squeeze, session filter, markers, fixed latest-signal risk plots, and two alert conditions.
- [x] Run available local checks and behavior tests; explicitly distinguish any third-party runtime from TradingView's compiler.
- [x] Write installation and alert instructions, exact signal semantics, and limitations. No automatic commit, publish, or order placement.
- [x] Complete final independent source review.

## Execution record

- Initial nine behavior tests failed because the source did not exist; after implementation, those nine passed. Six additional checks cover close-only clearance, frozen levels, premarket blocking, squeeze rejection/acceptance, and time gaps; all 15 passed in PineTS 0.13.0.
- Test-runtime investigation: future synthetic candle timestamps were unconfirmed relative to the execution host clock; fixtures now use completed historical candles. Indicator confirmation logic was retained.
- Standalone artifact created directly alongside existing TradingView scripts; no application integration, application dependencies, commits, or trading actions.
- Implementation choices: full-candle clearance by default with close-only option; reject simultaneous upper/lower touches; expire setups across day boundaries and nonadjacent bars; latest reference levels freeze and reset daily. These choices favor unambiguous signals but may omit setups interpreted more loosely in the source video summary.
- TradingView compiler, Bar Replay, live alert delivery, and profitability remain unverified. Independent runtime checks do not establish those outcomes.
- Final independent review: no actionable findings; reviewer independently reran all 15 checks successfully.
