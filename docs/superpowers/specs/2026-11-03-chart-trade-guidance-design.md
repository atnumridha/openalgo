# Trading chart guidance

## Purpose and chosen approach

Add simple, advisory guidance to the existing Trading chart using the findings from the 2–3 November Flattrade journal. The user selected **Guidance only** on 3 November. Guidance must explain the current evidence and planned cash outcomes without placing orders or adding order blocks.

Two approaches were considered: guidance alone, or guidance plus optional entry limits. Guidance alone was chosen because the user wants usable explanations without another filter disabling entries. Existing execution safeguards and broker controls are outside this change.

## What the user sees

One compact, collapsible **Trade guide** inside the existing side panel. Do not add a table over the candles or another full-width sidebar. Reuse existing entry, SL and target lines.

1. **Direction and reason:** show upward bias, downward bias or mixed direction, with the timeframes and one plain-English explanation. Keep chart timeframe evidence separate from the Delta backend's independent 1m/5m execution setup. A direction reading is not a promise or an order approval.
2. **Trade plan:** show entry, SL and target, the plan's timestamp, and estimated rupee loss at SL and profit at target after the appropriate broker's fees. Warn when the current price has passed a frozen entry, SL or target; do not move a frozen plan to make it appear current.
3. **Risk and costs:** show selected lots/quantity, estimated round-trip charges and net reward compared with net risk. Where a fresh, verified account balance exists, show planned loss as a percentage of that balance and name the balance used. Do not silently substitute available margin, yesterday's balance or another broker's balance.
4. **Journal reminders:** explain that another entry needs a fresh trigger and that repeated losses deserve a pause. Show event-specific re-entry/loss messages only when verified, complete records for the selected account and trading day support them. Otherwise say that recent trade history is unavailable. Do not display invented zero counts or treat the historical journal as a live account feed.

The collapsed card retains one short status and the principal reason. Details, fee assumptions and data timestamps stay behind expansion. Use the existing theme and readable text; leave the user's small candle labels unchanged.

## Data and calculation rules

- Reuse existing chart plans, closed-candle trend readings and broker snapshots instead of adding an independent signal engine.
- Distinguish underlying index direction from the selected option's premium direction. A bought PE is still a long-premium position, with SL below premium entry.
- Keep Flattrade's verified zero-brokerage estimate separate from the existing Kotak account fee schedule. The current general option preview calls the Kotak brokerage helper, so it cannot be labelled a Flattrade estimate without explicit broker scoping and verification.
- Delta uses its own contract size, fees and account information. Its USD-to-INR display retains the user's fixed conversion of 85. Do not apply option fees or lot rules to crypto.
- Missing, stale, mismatched or expired data produces a specific explanation, not a green trade approval. Show observed timestamps; do not promise millisecond exchange updates.
- Any planning budget is advisory. No new numeric risk limit, cooldown, trading-hour exclusion or loss cap is activated by this change.
- Guidance remains separate from order review, placement, cancellation, protection and Auto trading. It cannot enable an unsafe order or disable an existing exit.

## Implementation and verification

The app listening on port 5001 currently serves `/Users/nmandal/.codex/worktrees/neo-native/openalgo`; inspect and preserve its existing uncommitted work. Use its existing React/TypeScript components and read-only API services. Keep calculation helpers pure and testable.

Verify long and short crypto, bought CE and PE, fees by broker, quantity changes, flat and open positions, crossed/frozen plans, mixed timeframes, stale data, missing account history and replay. Confirm that guidance adds no calls to order mutation endpoints. Check a narrow screen and both expanded/collapsed states in the browser, using live reads or clearly identified fixtures; never submit a real order to test the guide.

The journal supports the priority of risk, fees and repeated-entry explanations. It does not validate a new trading strategy or prove that these messages prevent losses.

Status: approved by the user on 3 November 2026; implemented and published. Guide verified on the live BTCUSD chart and a 360px layout fixture; Kotak order detection verified with normalized broker-order fixtures, without placing a real test order.


## User-requested extension: live Kotak order detection

The user additionally requested automatic detection of live Kotak Neo orders on the chart. Reuse the current combined broker orderbook, refreshing about once per second, with no order mutations or additional entry rules. Draw exact-symbol/exchange/account-mode pending limit orders and SL triggers, remaining quantities and verified position averages. Show broker labels independently of the broker selected for a new order. Remove terminal and stale orders. Never recreate a cancelled broker stop from saved controller status. Crypto retains its existing separate Delta integration. Other Indian instruments get a read-only view, with no option order ticket enabled for unsupported instruments.
