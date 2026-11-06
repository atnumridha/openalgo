# Continuous Delta trading with persistent market context

Status: proposed design; not a deployed execution engine.

## Requested outcome

Continuously scan BTCUSD in either direction using the existing 1-minute entry / 5-minute EMA9/15 filter, retain trend and candle context across reload/restart, and manage the complete entry-to-exit lifecycle. Reuse the existing Delta account and execution service. The Mac, server and network must remain available; this design is local, not cloud hosting.

## Current implementation

New automatic entries are triggered by DeltaTradePanel React effects while that chart is open and Auto is enabled. A Python protection worker already manages owned SL/target, profit peaks and reconciliation without the browser. The worker is currently started by the authenticated service factory on first use. Browser local storage currently owns Auto enablement and defaults. These facts prevent a truthful claim of unattended backend-owned 24/7 entry scanning today.

## Recommended approach: backend execution with durable context memory

- Move the entry scheduler and its enabled/default configuration into the existing local Python service, supervised with the existing chart server. The chart becomes the status/control surface. Preserve an explicit Off switch that stops new entries while protection continues.
- Exactly one executor per account, enforced by a process-safe lock and durable intents. Browser entry ownership must end before backend ownership is acknowledged. Never let both schedulers submit simultaneously.
- Load persisted configuration at startup. Resume only after verifying credentials/account binding, all account positions/orders, owned plans, last fills and unresolved intents. Unknown outcomes reconcile before another mutation. Existing acknowledged broker stops never loosen or disappear during recovery.
- Scan fresh completed 1m/5m candles. EMA9 above EMA15 on both intervals selects Long; below on both selects Short; mixed/unavailable/stale evidence waits. Candlestick patterns remain visible and supporting context, not a mandatory entry gate.
- Use the current entry strategy and conservative fee-aware sizing, fresh best bid for maker Long / best offer for maker Short, 2R reference target (not an executable TP in trend mode), required SL and ₹20 maximum planned scalp loss including standard fees. Risk and funds checks still apply even when fees are promotional.
- Block all new entries while any account order or position is active or an outcome is unresolved. A partially filled entry receives protection and its remaining entry quantity is reconciled/cancelled before another opportunity. Exits remain reduce-only market when needed; target remains maker.
- Latest user amendment: profit tracking qualifies at ₹15 verified net peak, but waits until a candle/ATR structural stop can cover ₹10 after fees. Long SL is below the last three completed lows with 0.25 ATR buffer, at least one ATR behind mark; Short mirrors it. Only tighten the acknowledged broker SL. No fixed ₹10 giveback exit. Trend reversal can exit; slippage can exceed planned protection.
- Persist current EMA regime, previous regime/change timestamp, fresh candle time, support/resistance, pattern observations, eligibility/rejection reasons, order/fill links and closed-trade cost/outcome. This is inspectable market-context memory. It does not silently rewrite risk or live strategy rules after a winning/losing trade.
- Show current status, data age, current 1m/5m direction, what is blocking entry, next evaluation, resting orders, acknowledged SL/TP, observed profit peak, planned floor and live net P&L/fees. Report rejected, accepted, filled and exited as separate events.
- Any adaptive model or automatic parameter training is a separate optional paper-tested extension. Persisted history alone does not establish predictive accuracy or profitability.

## Alternatives

1. Keep browser-owned Auto with chart kept open and Mac awake: least change, but browser closure/suspension ends scanning; unsuitable for the requested unattended continuity.
2. Recommended backend scheduler and durable market context: continuous while local infrastructure runs, preserving the existing strategy and controls.
3. Adaptive trained model: a separate research project requiring chronological evaluation, held-out evidence and explicit promotion to live use; it is not implied by adding memory.

## Verification before live enablement

- Strategy parity fixtures against the current frontend for long/short EMA, ATR/structure stop, anti-chase, 2R target, lot sizing and fees.
- Deterministic execution tests for no double entry across tabs/processes/symbols, partial fills, maker rejection, unknown responses, restart/reconciliation, Off during an in-flight decision and stale/network data.
- Historical replay and read-only live shadow evaluation. No real orders used as software tests.
- Existing SL/profit regression suite and browser status/control tests, bounded review and staged release.

Approval requested: implement approach 2 with context memory; keep future adaptive strategy changes separate from live execution until tested and approved.


## Later user amendments (authoritative)

The user requested additional source-inspired crypto strategies and then replaced mandatory 2R exits with trend management. EMA, liquidity sweep, FVG/MSS, breakout/retest, range RSI, double extrema and EMA/Fibonacci can propose entries under the same account/risk gates. Conflicting eligible directions wait. No fixed TP is created for new trend-mode plans; existing owned TP cancellation requires verified live SL and exact terminal TP proof. At 23:00 IST the latest request replaced a fixed ₹10 trailing gap with completed candle/volatility structure, delaying the ₹10 lock until feasible. These numeric source adaptations have mechanics tests, not established profitable performance.
