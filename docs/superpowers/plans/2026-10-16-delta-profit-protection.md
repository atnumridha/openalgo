# Delta position profit protection

User chose tighten-only trailing with a pullback gap and asked for profitable exits before the configured fee window closes.

- The Positions countdown has its own visible-page one-second clock. Row and total fee estimates use the same timestamp; missing entry time cannot manufacture a free-close window.
- Explicitly adopt an existing reduce-only broker stop for an identified open perpetual position. A preview explains entry, original stop, fixed 1:n target (default 1:3), adjustable trailing gap (default half the original risk), and deadline one minute before the configured free-close window ends. Enabling is a user-operated live control; tests never enable an actual account plan.
- A single server scheduler job samples enabled plans about once per second, including while the browser is closed. Persist plans and pending exit identities in the existing database through a dedicated table and idempotent migration.
- Use current bid for long liquidation and ask for short liquidation, costs including GST, a tick of exit slippage, and reported opening costs/funding. Protection starts only when there is enough positive net return to place a valid protective price; stop floors budget normal closing fees even after the offer ends.
- Tighten the existing stop in place; never cancel it to move it. Preserve the most protective observed/acknowledged stop. Original risk and 1:n target do not change as the stop tightens.
- At the fixed target, or inside the last minute of an eligible window while estimated net is positive, submit one durable reduce-only market exit. Keep the broker stop while the close reconciles. An acknowledgement is not a fill; unknown outcomes are reconciled by client ID and never blindly resubmitted.
- Stop automation on identity/side/average-entry changes, added entries, incompatible controllers, missing protection, or uncertain evidence. Partial reductions must not increase risk. Error/stale status is explicit; no claim that every intervening tick was observed.
- Verify with isolated stores and fake broker mutations, long/short and exact boundaries, costs, gaps, timed exits, unknown outcomes, restarts, and timer cleanup. Build and deploy without placing an order or changing a live protection setting.

## Verification and rollout

- Full frontend suite: 291 files, 3,790 tests passed before the final broker-display additions; final affected components: 54 tests passed. TypeScript and production build passed.
- Backend protection, shared fee and risk suites: 273 tests passed, including pure long/short ratchets, fee/deadline preflight, pending/unknown exits, pause/restart recovery, scoped access, product-specific broker leverage and native SL/TP filtering.
- Isolated SQLite migration status/create/repeat checks retained saved plans. A 200-cycle repository stress test showed no descriptor growth beyond the permitted two-descriptor tolerance.
- Runtime databases and previously served frontend backed up privately under log/mac/backups/delta-profit-20261016-1910. Applied the idempotent migration and restarted only the Delta uv launcher on port 5050. Kotak port 5001 was left running.
- Live UI verified the one-second server heartbeat, broker leverage of 5x versus the separate configured 2x app setting, and native broker SL/TP prices. Deployment created no enabled protection plans and submitted no broker mutation.
- External broker calls can fail or be delayed. The monitor uses REST snapshots and preserves native stops; a planned profitable exit cannot guarantee fill time or fee-waiver eligibility. Enablement remains an explicit user-operated live control.

## Shared currency display extension

One per-user INR/USD preference now notifies the navbar, Positions, chart axes/legend/position P&L, trading books, watchlist and account views immediately. Use Delta India's documented fixed ₹85 per USD. Underlying OHLC, order prices, triggers, quantities and fee calculations remain native USD; only output is formatted. Native order-input widgets identify their USD units. RSI, percentages, quantity and volume are not currency-scaled. Existing risk reads supply a bounded, scoped fee-profile snapshot for chart Net; missing/stale profiles show unavailable rather than assuming a fee offer.

Verification: 113 focused display/chart/order tests passed; 103 rechecks across initially failing or timed-out full-suite files passed; final axis-width adjustment passed 10 checks and the TypeScript/production build. Live UI showed INR in the desktop Net badge, price axes, OHLC and position Net/Gross. Chart axis width was increased for crypto prices. No broker mutations or server restart were performed for this display extension.

## 17 October 2026: total-position net-USD trailing

New protection previews default in the UI to `trailing_mode=net_usd`:
activation strictly above US$2, minimum US$1.50 net lock, US$0.50 behind the
highest estimated net profit. These are total-position dollars, not BTC quote
points. Arm, lock and gap are configurable and bound into the preview identity.
Existing records without this mode retain their original price-gap policy.
No existing closed record is rewritten or automatically enabled.

The cash inversion reserves opening cost, ordinary closing taker fees including
GST even during promotional fee windows, funding and one adverse price tick.
Closing fees are calculated at that adverse fill price, including the larger
short-side closing notional. Stop rounding favors the net floor. Accepted stops
only tighten; targets retain the original risk/reward template. If a ratchet was
not acknowledged before a pullback crosses the earned floor, a fresh verified
positive-net check may send an existing reduce-only exit intent; an already
crossed broker stop remains authoritative. Gaps and actual slippage can exceed
the modeled buffer, so the floor is an estimate, not a profit guarantee.

Peak, armed state and floor use the existing JSON protection record (no schema
change). They are committed before broker modification I/O, so a hard process
exit cannot lose an unacknowledged peak. Existing durable exit reconciliation,
ownership checks, partial-reduction protection, rate limiting and server1s
scheduler continue to apply independently of the browser.

Verification:287backend checks passed (64profit-protection,40crypto fee,
183risk-core), plus20focused frontend tests and a production build. Tests cover
strict activation equality, long/short cash inversion and actual adverse-fill
fees, monetary sizing, conservative promotion handling, pullbacks, invalid
settings, preview binding, restart and a hard process death during broker I/O.
Resource audit: no additional jobs, timers, connections or unbounded state;
existing context-managed DB sessions close the extra pre-I/O durability write.

The user corrected the API IP whitelist after an initial authenticated rejection.
A subsequent authenticated Delta BTCUSD snapshot reported quantity0. The app was
restarted through its existing uv launcher; authenticated Positions showed zero
positions, a fresh1smonitor heartbeat and the new default policy. No plan was
armed and no broker order was modified because there was no open position.
Existing/native broker stops were never canceled. Live execution with a real
position is not claimed verified.

Deployment backup: `log/mac/backups/delta-net-trail-20261017-071328` (database
snapshot and prior frontend entry files; old hashed assets retained).

## 17 October: native instrument prices, preference-based cash P&L

The user's later instruction supersedes the earlier request to convert chart
quotes everywhere. OHLC, price axes/data-window values, entry/fill prices,
SL/target, bid/ask, price changes and break-even levels now remain native USD
for Delta. Cash P&L and its fee/risk totals retain the saved INR/USD preference.
Trade cash notional stays native USD as a non-P&L field. Other brokers retain
their native formatting. Raw values, order requests, leverage and protection
calculations do not change.

Introduced a native `useBrokerPriceFormatter` alongside the existing cash
formatter, and separated mixed price/P&L components. Includes charting/dock,
Positions/protection, research, ML/scalping, Strategy Builder, books, Holdings
and sandbox quote fields. Price formatting adds no feed, timer or subscription;
no backend restart or database change was required. Existing preference
subscriptions still clean up through their hooks and terminal destroy path.

Focused validation runs passed:69display tests,85dock/fees/display checks,
and36Builder/display checks (overlapping suites; not summed). TypeScript and
production build passed. Read-only browser verification showed native USD
OHLC in the actual Data Window and legend `Prices USD · P&L INR`. The shared
INR preference and5xdefault were retained. Previous entry files backed up at
`log/mac/backups/delta-native-prices-20261017-090330`; old hashed assets retained.
