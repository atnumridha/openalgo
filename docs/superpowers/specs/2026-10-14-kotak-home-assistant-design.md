# Kotak Neo trading assistant on the OpenAlgo home page

Date: 14 October 2026. Status: specification ready for user review; implementation has not started.

## Requested outcome

Add a live trading assistant to the authenticated OpenAlgo home/dashboard page for a connected Kotak Neo account. The user selects NIFTY or SENSEX, an expiry listed in descending date order, and strikes. Show strike prices, explain whether a call, put, or WAIT is appropriate, and provide an entry plan, SL, target, risk, and liquidity context. Refresh the display every second. Include the lessons from the user's 14 October trade review: repeated entries after losses, profit giveback, missing or incorrectly directed stops, cancelled protection, and rejected exits.

The user chose integration into OpenAlgo itself instead of a standalone Python or Streamlit application. Python implements analysis and authenticated data aggregation; the existing React dashboard displays it. Guidance and alerts do not submit, cancel, modify, or close orders.

## Placement and controls

- Add a Kotak Trading Assistant component to `frontend/src/pages/Dashboard.tsx`, below the existing account summary and before resource links. Preserve the existing page and design system.
- Render only for the current authenticated broker `kotak`. Never expose account information on the public landing page.
- Index selector: NIFTY maps to NSE_INDEX/NFO; SENSEX maps to BSE_INDEX/BFO.
- Expiries come from the master-contract/expiry service. Parse dates, remove expired entries using IST, and sort latest first. Show an explicit selection prompt rather than automatically treating the farthest expiry as recommended.
- Show available strikes for the selected expiry, ascending by strike, with CE and PE quotes side by side. Start with an ATM-centred window and allow expanding it. Only recommend among the loaded window and clearly describe that coverage.
- Permit choosing a strike for inspection. Changing the selection invalidates the old recommendation immediately and clears old subscriptions and pending results. Ignore responses for an earlier selection.
- Show price, bid, ask, percentage spread, lot size, and available volume/OI. Missing fields are unavailable, never zero by default.
- User settings: maximum risk per trade in INR, daily loss limit, maximum profit giveback in INR, permitted premium allocation, spread ceiling, and cooldown. Monetary settings start unset; quantity guidance is unavailable until the required budgets are supplied. An educational setup can still be shown as unconfigured.

## Data connection and refresh

Reuse session-authenticated OpenAlgo services and the existing Kotak adapter. No new broker credentials or browser scraping. Use the existing market-data manager/subscriptions for the index and displayed option legs. Reuse scalping expiry, strike, history and book interfaces where their semantics fit.

A one-second UI clock recomputes quote ages, live risk and guidance from the latest snapshot. This is not a promise of a new exchange trade each second. Market ticks arrive through the existing feed. REST fallback quote reads are batched, single-flight and rate-limited. Display the source and timestamp of the last successful update.

Refresh completed history on minute boundaries; obtain sufficient 1m and 5m warm-up history at startup. Use actual Unix timestamps and request the existing history endpoint's UTC time basis instead of its chart-display offset. Exclude forming candles and reject gaps affecting the setup. Fetch account books on order events with a five-second fallback; display their separate ages. Disable new recommendations if account books are older than 15 seconds or required quotes older than five seconds during the trading session.

Use server IST session timing for cash index options. Outside the session, show Market closed with historical analysis and no actionable entry. Authentication errors, market-data disconnects, incomplete master contracts, malformed data and stale candles produce WAIT with a reason. Preserve last valid values for context with a stale label, never imply a failed account read means flat.

Caches and journal records are scoped to authenticated user, broker, live/analyzer mode and IST date. Multiple tabs must not start duplicate unrestricted broker loops. No autonomous background trading process is added.

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

Show the index entry confirmation, index invalidation and liquidity target separately from option ask, premium SL and premium target. Label prices Indicative until filled; once a position is observed, use its actual entry and observed acknowledged protection. A suggested SL is never displayed as a broker-accepted stop.

Display estimated net loss at SL, net profit at target and net reward/risk. If costs erase the minimum net reward/risk of 1.5, suppress the recommendation. Use exchange-specific date-stamped rates for NFO and BFO, configurable brokerage and slippage; default brokerage to zero per the user's stated offer and label it as assumed. Verify applicable rates during implementation. If a fee schedule is unavailable or invalid, cost-qualified quantity and eligibility are unavailable instead of reusing NFO rates for SENSEX.

## Account risk and order alerts

Reconstruct day fills with partial-fill support and documented stable identifiers. Reconcile quantities to the successful position book before publishing day statistics. Keep gross realised, estimated charges, estimated net realised and open P&L distinct. Unsupported timestamps, missing fill IDs or inconsistent quantities expose incomplete reconciliation rather than an invented total.

Persist the observed day P&L peak and halt reasons per user/mode/date. If the tool starts midway through the day, mark earlier open-position peaks unavailable; do not claim the observed peak is the true full-day peak. Configured daily loss and profit-giveback breaches suppress entry recommendations and trigger alerts; this assistant does not prevent manual trades elsewhere in OpenAlgo.

After three consecutive reconciled net losing position cycles, suppress entries for the configured cooldown (initial non-monetary default: five minutes). A fresh setup must occur after cooldown. Avoid treating every fill as a separate loss. Unsupported carry-in positions make streak analysis incomplete.

For each observed open long option position, inspect active order protection by symbol, exchange, product and side. Alert on absent acknowledged sell protection, wrong-side BUY stops, protective quantity mismatches, multiple active exits whose combined quantity exceeds exposure, cancelled protection without a replacement and rejected exits. A pending profit limit alone is not protective SL coverage. State observed facts; do not invent the broker's margin-rejection cause. Reconcile stop modifications and partial fills before declaring a coverage problem. Alerts disappear only after a fresh successful book confirms resolution.

For observed long options, surface Exit alert on index invalidation, premium SL, target, or configured risk-limit breach. Surface a tighter suggested stop only after favourable movement and never loosen an acknowledged stop. The user remains responsible for execution; no broker write function is called by this feature.

## Components and storage

- Python pure analysis module for zones, setups, fee-aware plans and risk checks, plus a session-authenticated snapshot/config/journal API. Reuse broker read services rather than import execution functions.
- React home-page component, small API/type modules and a hook reusing the market-data manager, query cache and order refresh events.
- User-scoped durable settings and alert/journal state using existing database conventions; preserve analyzer/live separation and apply normal session/CSRF protection to local settings writes.
- Journal stores selection, completed-candle evidence, chosen contract, indicative plan, observed fills, alerts, and data freshness. Export only the current user's records as CSV. Do not store keys or authentication headers.
- Follow existing OpenAlgo UI components, themes and responsive layout. Clearly show blocked reasons, unavailable data and acknowledged versus suggested stops in text, not colour alone.

## Verification and delivery

Python tests cover causal pivots, repeated-high grouping, completed-candle exclusion, break/retest and sweep confirmation, contradictory/stale setups, partial fills, quantity reconciliation, account-read failure, incorrect stop direction, overlapping exits, cancelled coverage, whole-lot sizing, invalid metadata, tick rounding, missing fee schedules and date/mode scoping.

Frontend tests cover Kotak-only rendering, descending expiry dates across month/year boundaries, NIFTY/SENSEX exchange mapping, selector invalidation, full strike-price display, one-second age updates, stale WAIT, unavailable fields, risk settings and disconnect/unmount cleanup. Run the existing dashboard-related tests and production type/build checks. Inspect the rendered home-page integration at desktop and narrow widths. Use fixtures to verify fault behaviour without placing orders. State clearly if an authenticated live Kotak/OpenAlgo session is unavailable for final integration verification.

Implement additively and preserve the repository's existing uncommitted work. No changes to production credentials, account settings, broker execution policy, external notifications or trade limits are authorized by this feature.

## Review checkpoint

User review of this specification is the next step. After approval, create a written implementation plan and obtain the execution-method choice required by the brainstorming workflow. No product code, dependencies or trading behaviour have been changed at this specification stage.
