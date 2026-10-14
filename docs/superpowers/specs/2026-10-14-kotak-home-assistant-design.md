# Kotak Neo trading assistant on the OpenAlgo home page

Date: 14 October 2026. Status: specification ready for user review; implementation has not started.

## Requested outcome

Add a live trading assistant to the authenticated OpenAlgo home/dashboard page for a connected Kotak Neo account. The user selects NIFTY or SENSEX, an expiry listed in descending date order, and strikes. Show strike prices, explain whether a call, put, or WAIT is appropriate, and provide an entry plan, SL, target, risk, and liquidity context. Add user-operated one-click live entry, direct exits, index and option charts, live P&L and ongoing HOLD / TIGHTEN SL / EXIT guidance. Refresh the display every second. Include the lessons from the user's 14 October trade review: repeated entries after losses, profit giveback, missing or incorrectly directed stops, cancelled protection, and rejected exits.

The user chose integration into OpenAlgo itself instead of a standalone Python or Streamlit application. Python implements analysis, authenticated data aggregation and durable trade management; the existing React dashboard displays it. The user clicks to enter and can exit directly from this screen. An entry ticket includes its protective stop and the selected automatic exit rules. Entries are never autonomous. Continuous monitoring runs in the OpenAlgo server, independently of this chat and the dashboard tab. Building these controls does not authorize placing real orders during development or testing.

## Placement and controls

- Add a Kotak Trading Assistant component to `frontend/src/pages/Dashboard.tsx`, below the existing account summary and before resource links. Preserve the existing page and design system.
- Render only for the current authenticated broker `kotak`. Never expose account information on the public landing page.
- Index selector: NIFTY maps to NSE_INDEX/NFO; SENSEX maps to BSE_INDEX/BFO.
- Expiries come from the master-contract/expiry service. Parse dates, remove expired entries using IST, and sort latest first. Show an explicit selection prompt rather than automatically treating the farthest expiry as recommended.
- Show available strikes for the selected expiry, ascending by strike, with CE and PE quotes side by side. Start with an ATM-centred window and allow expanding it. Only recommend among the loaded window and clearly describe that coverage.
- Permit choosing a strike for inspection. Changing the selection invalidates the old recommendation immediately and clears old subscriptions and pending results. Ignore responses for an earlier selection.
- Show price, bid, ask, percentage spread, lot size, and available volume/OI. Missing fields are unavailable, never zero by default.
- User settings: maximum risk per trade in INR, daily loss limit, maximum profit giveback in INR, permitted premium allocation, spread ceiling, and cooldown. Monetary settings start unset; quantity guidance is unavailable until the required budgets are supplied. An educational setup can still be shown as unconfigured.
- Keep an open-trades panel visible even when the index, expiry or strike selection changes. Each row shows actual filled quantity/average entry, current bid and LTP with ages, gross and estimated net P&L, original/current SL, target, protection status, and a short HOLD / TIGHTEN SL / EXIT / DATA UNAVAILABLE explanation.
- Reuse the existing chart component for separate index and selected-option charts with 1m/5m/15m views, entry/exit markers, premium SL/target lines on the option chart, and liquidity zones/invalidation on the index chart. Keep index and premium price scales separate; display IST without changing the underlying UTC timestamps. Forming candles may update visually but cannot confirm a setup.

## Data connection and refresh

Reuse session-authenticated OpenAlgo services and the existing Kotak adapter. No new broker credentials or browser scraping. Use the existing market-data manager/subscriptions for the index and displayed option legs. Reuse scalping expiry, strike, history and book interfaces where their semantics fit.

A one-second UI clock recomputes quote ages, live risk and guidance from the latest snapshot. This is not a promise of a new exchange trade each second. Market ticks arrive through the existing feed. REST fallback quote reads are batched, single-flight and rate-limited. Display the source and timestamp of the last successful update.

Refresh completed history on minute boundaries; obtain sufficient 1m and 5m warm-up history at startup. Use actual Unix timestamps and request the existing history endpoint's UTC time basis instead of its chart-display offset. Exclude forming candles and reject gaps affecting the setup. Fetch account books on order events with a five-second fallback; display their separate ages. Disable new recommendations if account books are older than 15 seconds or required quotes older than five seconds during the trading session.

Use server IST session timing for cash index options. Outside the session, show Market closed with historical analysis and no actionable entry. Authentication errors, market-data disconnects, incomplete master contracts, malformed data and stale candles produce WAIT with a reason. Preserve last valid values for context with a stale label, never imply a failed account read means flat.

Caches and journal records are scoped to authenticated user, broker account identity, live/analyzer mode and IST date. Multiple tabs must not start duplicate unrestricted broker loops. The server manages only explicitly authorized open trades and their exit policies; it does not open new trades on a signal. A database-backed ownership lease and operation generation prevent simultaneous workers or restarted processes from submitting the same managed action.

## Live entry and direct exit controls

### One-click entry

- Start with live entry disarmed. The user deliberately enables Live trading for this authenticated session, with a prominent live/analyzer badge. Do not persist a live-armed state across logout, account change or browser restart. Disarming stops new entries and preserves active protection and exits.
- Show the complete ticket beside the Buy button: account/mode, NIFTY or SENSEX, expiry, strike, CE/PE, exchange, product, whole lots/units, entry price cap, premium SL and target, estimated charges, estimated loss at SL, premium at risk, and selected automatic exits. Use labels such as Buy 1 lot · 65 units only when the current contract metadata actually supplies that lot size. A bought put also uses BUY entry and SELL protection.
- Require configured risk limits, valid session hours, fresh books/quotes, available funds, valid contract metadata and an eligible setup. The server recomputes eligibility and validates a single-use ticket that expires within five seconds, bound to user/account/mode, selection, quantity and plan version. A selector or risk-setting change invalidates the ticket. Never silently switch contract, increase quantity or chase a moved price when clicked.
- Use a tick-aligned limit entry within the user-selected slippage/price cap and premium budget. Allow IOC only where the adapter supports it; otherwise use a bounded resting limit with a five-second cancel deadline. A partial fill is a real position and needs protection. No automatic repricing beyond the displayed cap or automatic repeat entry.
- Persist an idempotent order intent before broker submission. Repeated clicks, multiple tabs, request retries and timeouts reuse/reconcile that intent. An unknown submission remains Order status unknown, blocks another entry, and is not blindly resubmitted. A tag is a correlation aid, not evidence that Kotak guarantees exactly-once submission.
- V1 opens long calls/puts only, one managed position at a time. Do not average down, pyramid, reverse, sell uncovered options, or open against an existing position/pending order in the same contract/product. Positions opened elsewhere remain visible but need an explicit Manage this position action with a reviewed quantity and exit plan before automated management.

### Protection and automatic exits

An entry click authorizes submitting its disclosed protective SELL stop for actual fills, cancelling any unfilled entry remainder when necessary, and reducing the filled position if protection fails. The ticket clearly shows automatic target exit, index invalidation and account-risk exit choices; those optional automated rules start off until selected. Broker SL protection is required for this feature's live entries. Guidance without a selected automatic rule remains an alert with a manual Exit button. Optional trailing/profit-floor management also starts off and requires selection before it can modify a stop. No language-model call may directly decide or submit a live order.

Kotak's current trading API documentation states that bracket/cover orders were discontinued on Trade APIs on 1 April 2026. V1 therefore uses an ordinary entry plus a separately acknowledged broker stop; it must not claim atomic entry-and-stop attachment or native OCO. Place protection promptly as fills are confirmed, keep remaining entry quantity bounded, and show the temporary Unprotected / protection pending state. Never call a configured local SL a broker-accepted order. The existing adapter converts SL-M to a stop-limit; display the actual trigger and limit, including the possibility of a gap leaving it unfilled.

Maintain a single coordinated exit path per managed position. Default to one broker-resting stop and a server-observed target, avoiding independent full-size resting SL and target sells. On a target, manual exit or authorized invalidation, first reconcile pending entry fills and stop status. Modify the owned stop into a permitted immediately executable exit when supported and verified; otherwise confirm its cancellation before submitting the remaining sell. A cancellation response alone cannot erase a concurrent fill. If cancellation/fill state is unknown, reconcile and surface the uncertainty instead of adding a second full-size sell.

If protection is definitively rejected or missing after a confirmed cancellation, cancel any outstanding entry remainder, halt new entries, and attempt to flatten only the confirmed residual position. If protection submission has an unknown outcome, reconcile it before sending a potentially overlapping exit. If exit is rejected, show the broker's actual reason and outstanding exposure. Retry only after an authoritative terminal rejection/cancellation and refreshed remaining quantity, with bounded backoff; unknown outcomes never trigger blind retries. Protection, target and position state remain active until fills and fresh positions confirm the result, not merely until the broker returns an order ID.

### Exit controls and position ownership

- Provide Exit full, Exit selected lots, Tighten SL, and Exit all managed trades. Partial exit requires at least two lots and shows both exit and remaining quantities. Exit all names and scopes the managed trades; it does not silently close unrelated holdings or positions.
- New-entry arming, daily entry halts and cooldown do not disable exits. Manual exit does not depend on an eligible recommendation or fresh index candles. The server must still establish the signed residual position and competing pending orders before choosing an exit quantity; show unavailable account state clearly rather than fabricate a flat position or safe quantity.
- Derive SELL direction and maximum remaining quantity on the server from fresh account books and the managed fill ledger. Coordinate stop changes, targets, manual exits and account-risk exits under the same durable operation lock. Reconcile fills during modify/cancel races, split orders at exchange freeze limits, and attach protection to the remaining position after a partial exit.
- Do not cancel or modify unowned orders automatically. Detect external trades/order changes, pause conflicting automation and show the exact conflict. Account-wide execution outside this assistant can race it; local locks cannot guarantee broker-level reduce-only semantics. An accidental reversal must be detected and prominently reported rather than concealed as a successful exit.
- Persist the entry plan, broker IDs, remaining fills, protection state and exit intent across reloads/restarts. On restart, reconcile broker books before resuming action. Trade monitoring is bound to its original account and mode; switching the UI to analyzer does not reroute live management into paper orders or discard a live trade. A daily journal/risk rollover must not delete an unresolved position or order intent.
- Closing the browser does not end server monitoring while the server and broker session are healthy. Show server heartbeat, broker connection and accepted-stop status separately. Server/network/auth failure can stop target/trailing actions; an accepted DAY stop can remain at the broker for its validity but cannot guarantee a fill. V1 is intraday: require a displayed square-off cutoff before the applicable broker/session deadline, include it in the accepted ticket, and never assume a DAY stop protects an overnight position.

### Execution reuse boundaries

Reuse shared Kotak order, modification, cancellation, book and market-data services behind a new account-scoped coordinator. Do not route this feature directly through the existing generic `close_leg` handler: it accepts client-supplied direction/quantity. Do not register the same managed trade in the existing scalping stop engine: its generic Kotak path clears state after order acceptance and its SL key has no account identity. A single controller must own each position; reject adoption if another controller still owns it. Preserve unrelated scalping/Delta behavior and limit any shared changes to the contract required by this coordinator.

Sources checked 14 October 2026: [Kotak trading API documentation](https://github.com/Kotak-Neo/Kotak-Neo/blob/main/docs/trading-apis.md) for order operations and BO/CO withdrawal; [Kotak stop-order support](https://www.kotakneo.com/support/how-do-i-place-sl-m-or-sl-l-orders/) for the separate entry/stop model and stop-limit price direction. Actual supported adapter behavior must also be tested without live orders.

## Liquidity and participant interpretation

Describe observable liquidity proxies, not a claim to identify institutional participants or predict stop locations with certainty:

- Previous trading day's index high and low from actual available history.
- Confirmed 5m swing highs/lows: two completed bars on each side; a pivot becomes usable only after both right-hand bars close.
- Repeated highs/lows: two or more confirmed pivots within 0.1 of the current 5m ATR(14), grouped into a zone.
- Index liquidity sweep: a completed 1m bar trades beyond a known zone and closes back inside. Label it Sweep observed; require subsequent confirmation before a directional setup.
- Option execution liquidity: valid two-sided bid/ask, non-crossed spread, positive quoted quantities where available, volume and OI if provided. Show availability and age for each evidence source. Missing depth does not become an inferred order imbalance.

Index spot volume may be absent or synthetic. Never use it as traded volume. OI and option volume are context rather than proof that large traders are buying or selling. Do not add a fabricated smart-money score or institutional label.

## Deterministic entry setups

V1 provides two explicitly experimental, paper-testable setup types, evaluated only on completed candles:

1. Break and retest: close beyond a previously confirmed index zone, then within the next five completed 1m bars retest the zone and close on the breakout side. The retest bar must show directional confirmation. A close back through the invalidation boundary resets the setup.
2. Sweep and reclaim/rejection: sweep a known low and reclaim it for a bullish candidate, or sweep a known high and reject it for a bearish candidate. A following completed 1m candle must close beyond the sweep candle's high for bullish confirmation or below its low for bearish confirmation, within five bars.

For bullish confirmation, require the latest completed 5m close above EMA20 with EMA20 rising; bearish requires the reverse. If that trend filter opposes the candidate, show WAIT. Conflicting simultaneous setups show WAIT rather than selecting arbitrarily. Do not repeatedly emit the same setup on every one-second redraw: identify it by selection, zone, direction and confirmation timestamp. Expire an unentered signal after the next completed 1m bar or if its invalidation level is crossed.

The index stop is beyond the confirming retest or sweep extreme with a buffer of 0.1 index 1m ATR(14). The index target is the next opposing confirmed liquidity zone. If none exists, target guidance is unavailable. Require index reward/risk of at least 2 before calling a setup eligible. This threshold is a research rule, not a demonstrated edge.

## Contract selection, option SL and target

Choose CE for a bullish setup and PE for a bearish setup in the user's selected expiry. Rank only contracts that exist and have valid, fresh two-sided quotes and correct lot/tick metadata. Prefer candidates within two available strike intervals of ATM, lower percentage spread, then stronger available depth/volume. Explain the selected strike and the alternatives. Do not recommend a cheap distant OTM option solely on premium price.

For the selected candidate, load its completed 1m candles. Option SL distance is 1.5 option ATR(14), rounded outwards to its actual tick size. Indicated entry is current ask; protective SL is below entry for both bought calls and bought puts. Set the premium target at twice that distance above entry, rounded to the tick size. An index invalidation alert can occur before this independent premium stop. Do not translate an index move into a guaranteed option price using a fixed delta.

Require positive SL and valid ATR, and enough confirmed index room to the next opposing zone. Calculate whole-lot quantity against both maximum per-trade loss including estimated costs/slippage and the user's premium-allocation cap. If a single lot does not fit, show WAIT / one lot exceeds budget. No fractional lots or hardcoded lot sizes.

Validate live quantity and net reward/risk at the maximum permitted entry price, including estimated exit slippage and fees, rather than only at the current ask. Freeze the disclosed absolute SL/target when accepting the ticket; actual fills update entry and P&L without widening SL or extending target. If fills or market movement invalidate that protection, use the protection-failure path. Estimated loss at SL is a planning amount, not a maximum guaranteed loss through gaps or failed execution.

Show the index entry confirmation, index invalidation and liquidity target separately from option ask, premium SL and premium target. Label prices Indicative until filled; once a position is observed, use its actual entry and observed acknowledged protection. A suggested SL is never displayed as a broker-accepted stop.

Display estimated net loss at SL, net profit at target and net reward/risk. If costs erase the minimum net reward/risk of 1.5, suppress the recommendation. Use exchange-specific date-stamped rates for NFO and BFO, configurable brokerage and slippage; default brokerage to zero per the user's stated offer and label it as assumed. Verify applicable rates during implementation. If a fee schedule is unavailable or invalid, cost-qualified quantity and eligibility are unavailable instead of reusing NFO rates for SENSEX.

## Account risk and order alerts

Reconstruct day fills with partial-fill support and documented stable identifiers. Reconcile quantities to the successful position book before publishing day statistics. Keep gross realised, estimated charges, estimated net realised and open P&L distinct. Unsupported timestamps, missing fill IDs or inconsistent quantities expose incomplete reconciliation rather than an invented total.

Persist the observed day P&L peak and halt reasons per user/account/mode/date. If the tool starts midway through the day, mark earlier open-position peaks unavailable; do not claim the observed peak is the true full-day peak. Configured daily loss and profit-giveback breaches suppress recommendations and new entries through this assistant and trigger alerts. They execute exits only for managed positions whose accepted policy enables that action. They do not prevent manual trades elsewhere in OpenAlgo.

After three consecutive reconciled net losing position cycles, suppress entries for the configured cooldown (initial non-monetary default: five minutes). A fresh setup must occur after cooldown. Avoid treating every fill as a separate loss. Unsupported carry-in positions make streak analysis incomplete.

For each observed open long option position, inspect active order protection by symbol, exchange, product and side. Alert on absent acknowledged sell protection, wrong-side BUY stops, protective quantity mismatches, multiple active exits whose combined quantity exceeds exposure, cancelled protection without a replacement and rejected exits. A pending profit limit alone is not protective SL coverage. State observed facts; do not invent the broker's margin-rejection cause. Reconcile stop modifications and partial fills before declaring a coverage problem. Alerts disappear only after a fresh successful book confirms resolution.

For observed long options, surface Exit alert on index invalidation, premium SL, target, or configured risk-limit breach. Execute only the selected automatic exit rules for managed positions through the coordinator above. Surface a tighter suggested stop only after favourable movement and never loosen an acknowledged stop. Show proposed, submitted, broker-acknowledged and filled actions as separate states. HOLD means the selected rules have not called for an exit; stale or contradictory evidence produces DATA UNAVAILABLE rather than reassurance to hold.

## Prevent repeated mistakes while managing winning trades

The user's additional requirement is to reduce the behaviours that damaged the 14 October session while preserving valid winning opportunities. Optimise for net expectancy and controlled drawdown rather than a higher trade count or win rate alone. No profit guarantee or claim that today's profitable contracts will remain profitable is permitted.

### Lessons grounded in the review

- The realised curve reached approximately +INR 4,213 at 13:06 before subsequent cycles lost approximately INR 12,142. Maintain a persistent observed peak and a separate entry-halt state; restarting the UI or changing strikes must not clear a breached daily limit.
- NIFTY 22600 put cycles produced the largest cumulative loss. Block reuse of a consumed or stopped setup ID and require a new completed-candle confirmation after a cooldown. Switching strikes or switching between CE and PE must not bypass account-level cooldown or daily limits.
- The largest cycle lost INR 4,296.50 after cancelled sell-stop orders at progressively lower levels. Freeze the initial plan at observed entry, show the change from its original risk, and flag any observed loosening or cancellation of acknowledged protection. Recomputing ATR must never silently widen an existing position's suggested stop.
- A BUY stop increased an existing long position. Validate every observed protection order against the current signed position and remaining quantity. An unresolved wrong-side order, rejected protective exit, or missing coverage blocks new entry recommendations across the assistant until fresh books confirm resolution.
- Some profitable cycles had too little gross profit to cover reliable execution costs. Evaluate entries and exits after estimated round-trip fees and slippage; a positive option-price move is not itself a net win.

### Managing a valid winner

- Display the frozen initial entry/SL/target, current executable bid, net open P&L estimate, observed net peak, and the reason to HOLD or EXIT. Do not recalculate a moving target on every quote or automatically extend a target after it is reached.
- A flat-entry WAIT condition such as no new setup or cooldown does not itself produce an exit from an already-open valid position. Existing-position decisions use the frozen plan, current invalidation, protection state, target and configured account risk limits. A genuine daily risk breach remains an exit alert as specified above.
- Let the position follow its original target while the setup remains valid. A completed-bar adverse structure change, the protective stop, target, or account risk breach produces an exit alert; a forming-candle wiggle alone does not constitute a confirmed structure change. Price-based stop breaches still alert immediately from fresh quotes.
- Add an optional profit-protection rule with explicit configuration. It starts disabled until chosen by the user. At the configured net-profit activation threshold, propose a net-profit floor calculated from the observed peak and the configured retention fraction. The floor calculation includes estimated liquidation costs and slippage. The proposed stop can only tighten; store proposed and acknowledged stops separately. A proposed floor is not realised profit or guaranteed execution.
- For a partial-exit suggestion or user-requested partial exit, require at least two valid whole lots and show the exact exit and remaining quantities. Reconcile and resize protection through the coordinator as fills arrive; do not leave a full-quantity stop alongside a partial sell. V1 defaults to a full-position target; it does not invent fractional-lot partial exits.
- After a profitable exit, require a new setup confirmation. A win must not automatically increase risk budget, lot size, daily limits or override a poor spread.

### Evidence and journal evaluation

Tag observed cycles by the actual setup evidence available at entry (break/retest, sweep confirmation, or unclassified), index, expiry, strike, time window and costs. Today's order export contains no historical entry-signal evidence; its profitable trades must remain unclassified unless contemporaneous market data supports attribution. Do not label all today's winners as successful examples of the newly proposed rules.

Record net expectancy, median win/loss, profit factor, maximum observed drawdown, profit giveback, stop changes, rejection events and re-entry delay. Compare rules on chronological paper/replay samples using only information available at each decision, with costs and adverse fills. Preserve losing examples and no-trade intervals. The goal is evidence that the controls reduce harmful behaviour without routinely cutting valid winners; no performance qualification is inferred from the single reviewed day.

## Components and storage

- Python pure analysis module for zones, setups, fee-aware plans and risk checks; a separate durable execution coordinator; and session-authenticated snapshot/config/ticket/entry/exit/protection/journal endpoints. Resolve account identity and broker credentials on the server, never from client-supplied authority.
- React home-page component, small API/type modules and hooks reusing the market-data manager, query cache, chart component and order refresh events. Entry/exit request state must survive selection changes and be reconciled on page reload.
- User/account-scoped durable settings, order intents, managed positions, operation leases and alert/journal state using existing database conventions. Preserve analyzer/live separation and apply normal session/CSRF protection to every mutation. Existing unscoped SL tables cannot establish account ownership.
- Journal stores selection, completed-candle evidence, chosen contract, frozen/indicative plans, authorized exit rules, operation IDs, broker order IDs, fill transitions, alerts, and data freshness. Export only the current user's records as CSV. Do not store keys or authentication headers.
- Follow existing OpenAlgo UI components, themes and responsive layout. Clearly show blocked reasons, unavailable data and acknowledged versus suggested stops in text, not colour alone.

## Verification and delivery

Python tests cover causal pivots, repeated-high grouping, completed-candle exclusion, break/retest and sweep confirmation, contradictory/stale setups, partial fills, quantity reconciliation, account-read failure, incorrect stop direction, overlapping exits, cancelled coverage, whole-lot sizing, invalid metadata, tick rounding, missing fee schedules and date/mode scoping.

Add regression scenarios for the 14 October failure modes: changing strikes cannot evade a halt; restarting cannot clear the observed peak or daily breach; rising ATR cannot widen an open trade's stop; wrong-side protection blocks new recommendations; duplicated fills cannot increase the loss streak; entry cooldown alone cannot exit a valid winner; the proposed net floor never loosens; one-lot positions cannot receive partial-exit suggestions; and a winning exit cannot increase the user's risk budget. Treat these as behaviour checks, not a claim that historical losses would have been prevented at particular counterfactual prices.

Frontend tests cover Kotak-only rendering, descending expiry dates across month/year boundaries, NIFTY/SENSEX exchange mapping, selector invalidation, full strike-price display, one-second age updates, stale WAIT, unavailable fields, risk settings and disconnect/unmount cleanup. Run the existing dashboard-related tests and production type/build checks. Inspect the rendered home-page integration at desktop and narrow widths. Use fixtures to verify fault behaviour without placing orders. State clearly if an authenticated live Kotak/OpenAlgo session is unavailable for final integration verification.

Execution tests must cover duplicate/multi-tab clicks, stale/altered tickets, cross-user/account access, forged action/quantity, submit timeouts after broker acceptance, partial entry/protection failures, late fills after cancel, SL/target/manual-exit races, partial exit resizing, freeze splitting, rejected exits, external order conflicts, lease loss, restart recovery and analyzer/live changes. Verify that accepted-but-unfilled exits never produce Closed, unknown submissions never produce a duplicate order, and no entry halt blocks a reconciled reducing exit. Verify that unselected automatic rules cannot send broker writes and that chart/guidance updates cannot directly submit orders. Use injected broker fixtures and analyzer mode; no real trade is a development test.

Implement additively and preserve the repository's existing uncommitted work. The scope authorizes building user-operated live controls and explicitly selected protective automation. It does not authorize changing production credentials, enabling live trading for the user, submitting real orders, changing unrelated account settings/trade limits, or sending external notifications during development.

## Review checkpoint

User review of this specification is the next step. After approval, create a written implementation plan and obtain the execution-method choice required by the brainstorming workflow. No product code, dependencies or trading behaviour have been changed at this specification stage.
