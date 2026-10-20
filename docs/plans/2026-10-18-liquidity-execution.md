# Liquidity extra-confirmation execution

Implements the user's new transcript as an explicitly parameterized app strategy on Delta BTCUSD. The transcript is discretionary; this is not claimed as an exact mechanical transcription or an 80% system.

## Decisions

- Completed 1m candles, native confirmed 1H/4H/1D strict 2+2 swings; manual level override supported. References become usable only after confirmation. A touched level starts a single attempt.
- Skip the first directional candle after a level touch. Require an opposite candle closing beyond that first candle's open, body at least 0.5 ATR14. Then require a directional candle closing beyond the counterattack high/low. The final trigger is a subsequent observed executable-price crossing of its high/low. Short is explicitly an inferred mirror, disabled by default.
- Freeze pattern extreme plus one tick as stop. Opposing untouched HTF liquidity is the runner target; no invented target if none exists. Candidate expires after ten completed entry candles. Reconnect gaps abandon entry candidates rather than replay old crossings.
- Review-entry default, configurable automatic entries. Entry maker-only with attached broker stop, 15-second unfilled timeout; partial fills cancel the remainder. Real orders use the existing journaled Delta executor and exclusive account locks.
- Quantity cap 1, leverage 5, loss cap $1 including costs/slippage, margin cap $25, daily loss cap $3, three entries per IST day. These are editable app defaults, not video claims. Check actual product metadata and account collateral. Never change broker leverage or margin mode silently.
- If filled quantity >=2, book floor(quantity/2) at 1R only if estimated net partial proceeds are positive; otherwise use the runner target. After confirmed partial fills, protect fee-aware whole-trade breakeven. One contract uses a single target. At net peak >$2 lock max($1.50, peak-$0.50), tighten only. Native stop remains during network outages.
- Server process and SQLite state survive browser closure. Restart reconciles owned orders before entries; no duplicate intent retries. Paper and live ledgers separate. Mode changes stop entries and manage existing exposure in its original mode.
- New Trading page panel exposes configuration, status, review-entry, pause entries and close-owned-trade controls; existing Python host owns process lifecycle. Deployment never starts live execution or places a validation trade.

## Work and verification

1. Pure causal state machine and cost-aware sizing; tests for sequence, equality, weak counterattack, expiry, gap, restart and mirrored direction.
2. Adapter to existing durable executor; tests for partial sizing, restart, actual fills, tighten-only net floors and unknown submissions.
3. Hosted runner, account-bound API and compact existing-theme UI. Test ownership, paper/live separation, stale approvals, empty state and errors.
4. Display server-owned Entry / SL / Target overlays so chart execution levels match the durable trade rather than a second indicator calculation. Build frontend, run the resource audit and independent review. Verify deployed UI read-only; record exact remaining live qualification limitations.

Official API reference: https://docs.delta.exchange/ (entry brackets, client IDs, reduce-only exits and order status; reviewed 18 October 2026). No strategy profitability inferred from API documentation.
