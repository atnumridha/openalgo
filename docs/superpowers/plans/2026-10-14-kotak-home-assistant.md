# Kotak home assistant implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the approved Kotak home trading desk with manual one-click orders, durable protection, live monitoring and journal.

**Architecture:** Add a pure analysis module, account-scoped durable coordinator, authenticated Flask blueprint and dashboard component. Reuse existing broker services, market data and charts. Each mutation persists its intent before broker I/O and reconciles fills before reporting completion.

**Tech Stack:** Python, SQLAlchemy, Flask, React, TypeScript, existing chart and UI components.

**Spec:** `docs/superpowers/specs/2026-10-14-kotak-home-assistant-design.md`

## Global constraints

- No separate arming or confirmation dialog for manual Buy/Exit in Live mode.
- User clicks entry; automated exits require the disclosed accepted policy.
- No real orders during implementation or tests; preserve pre-existing working changes.
- Quotes older than five seconds and account data older than 15 seconds cannot qualify entry.
- Separate broker acknowledgement from fill, suggested SL from accepted protection, and analyzer from live.
- User approved implementation and requested no further approval prompts: execute natively in this session.

## Review focus

- Unknown broker submissions remain unresolved and never cause blind resubmission.
- A stop filling during cancellation cannot create an overlapping sell.
- Changing account/mode cannot route an existing live exit into the analyzer.
- Daily rollover cannot discard unresolved trades or let selection changes clear halts.
- A failed account read cannot imply flat or a completed exit.

### Task 1: Analysis and fee-aware plans

**Files:** `services/kotak_assistant/analysis.py`, `test/test_kotak_assistant_analysis.py`.
**Interfaces:** `analyse(one, five, now) -> dict`; `plan(entry, sl, target, qty, exchange, settings, tick, lot) -> dict`; `journal(fills, positions) -> dict`.
- [x] Write failing tests for causal zones, unfinished candles, missing/crossed quotes, fees, lot sizing, tick/risk validation and duplicate fills.
- [x] Run `.venv/bin/python -m pytest test/test_kotak_assistant_analysis.py -q`; expect failure until implementation exists.
- [x] Implement deterministic analysis, separate exchange fee schedules, complete-fill reconciliation and entry risk checks.
- [x] Run the same tests; expect all pass.

### Task 2: Durable execution coordinator

**Files:** `services/kotak_assistant/store.py`, `execution.py`, `broker.py`, `test/test_kotak_assistant_execution.py`.
**Interfaces:** `Coordinator(store, gateway, clock)` with `preview`, `enter`, `exit`, `tighten`, `reconcile`; store persists account state and serializes operations. Gateway supplies fresh books, quotes and broker order mutations.
- [x] Write failing fixture tests for duplicate requests, partial fills, accepted-but-unfilled exits, rejection, stale data, partial exit races, unknown submission, account separation and restart recovery.
- [x] Run execution tests and observe failures.
- [x] Implement durable intents/leases, required protection, owned-order cancellation, bounded reducing exits and optional deterministic automatic policies.
- [x] Run analysis and execution tests; expect all pass.

### Task 3: Authenticated API and server monitoring

**Files:** `blueprints/kotak_assistant.py`, `services/kotak_assistant/runtime.py`, `app.py`, `test/test_kotak_assistant_routes.py`.
**Interfaces:** `/kotak-assistant/api/{snapshot,config,preview,entry,exit,stop,journal}`; server monitor processes unresolved trade states independently of UI lifetime.
- [x] Write failing route tests for missing session, wrong broker, authority isolation and mutations.
- [x] Implement session/CSRF protected routes, shared cached data reads, broker-account identity, IST calendar handling and CSV export.
- [x] Register blueprint and idle monitor during existing startup lifecycle.
- [x] Run all assistant tests; expect all pass.

### Task 4: Dashboard trading desk

**Files:** `frontend/src/components/kotak-assistant/{KotakAssistant,TradingTicket,ManagedTrades}.tsx`, `frontend/src/api/kotakAssistant.ts`, tests and `frontend/src/pages/Dashboard.tsx`.
**Interfaces:** Typed API matches Task 3; scoped queries, selection generation and a one-second clock; existing charts and market feed.
- [x] Write failing tests for Kotak-only display, expiry date sorting, no arming, selection invalidation and direct exit availability.
- [x] Implement responsive chain/ticket/risk settings, charts, live price/P&L, guidance, direct controls and journal link.
- [x] Run targeted frontend tests and TypeScript build; expect pass.

### Task 5: Integration verification and review

- [x] Run assistant backend tests, relevant existing tests, frontend suite and production build. Document unrelated baseline failures accurately.
- [x] Inspect responsive rendered fixture UI and verify server route registration without a live order.
- [x] Obtain fresh code review; correct important execution or isolation defects, then rerun affected checks.
- [x] Record delivery and limits; install into the existing local OpenAlgo app. No real trade, merge or push is part of this request.


## Delivery evidence — 15 October 2026

Implemented in the existing checkout on `codex/kotak-home-assistant`, preserving unrelated working changes. The local app uses `/Users/nmandal/.codex/worktrees/neo-native/openalgo`; only assistant-owned modules and minimal app/dashboard/tag integrations were installed there. Existing native desk and chart components were preserved. Original integration files were backed up under `/tmp/kotak-active-before`.

- Final backend: 81 tests passed across all assistant modules and the existing scalping risk/futures suites.
- Final frontend: 252 files, 3,508 tests passed. Source and running-checkout production builds passed. Ruff passed for new Python modules/tests.
- Browser fixture: one manual Buy and one direct Exit, desktop and 390px mobile, no horizontal overflow or page errors. All broker/account endpoints were mocked; no real orders were submitted.
- Independent reviews corrected protection on stale optional data, delayed fills, residual cost basis, cancellation/exit retry, setup reuse, session cutoff and direct external-position close. Final targeted review found no additional blocker.
- Full project Python collection remains blocked by four existing `test` package import errors; the targeted suites above passed.

The active app was cold-restarted after checking for active live strategies or assistant intents. A historical paper BTC stop record was retained. macOS hot reload caused a fork failure earlier, so subsequent activation used a fresh process. Protected assistant routes return HTTP 401 without authentication. Existing Kotak order-update websocket reports an invalid session token; the assistant has REST fallback and displays unavailable/stale states. Authenticated live broker execution was not tested.

Configure the four monetary risk limits before entry. Live mode is the sole execution-mode gate; there is no arming dialog. Liquidity levels are candle/depth proxies, not proof of institutional activity. Fees and net results are estimates, to be reconciled with the broker contract note. Historical journals require archived or broker-supplied fills; absent data is unavailable rather than zero.


## Clarity follow-up — 15 October 2026

The home desk now separates nearest confirmed index support/resistance (index points) from option entry/SL/target (rupees per unit). Ticket and managed-position summaries use explicit text plus coloured borders; unconfirmed protection remains labelled unconfirmed. Draft chart lines follow edited inputs, while fill markers read BUY/EXIT fill. Chart headings, full stop-loss labels and a persistent legend distinguish suggested draft prices from actual filled entries and accepted protection. Target copy states whether automatic target exit is enabled. Missing/stale levels stay explicit.

Verified the focused component suite (11 tests), source and active-checkout builds, and the rendered active dashboard. Changes are frontend only; no server restart or real order. Screenshot: `/tmp/kotak-clarity.jpg`.


## Visual review follow-up — 15 October 2026

Inspected the real authenticated dashboard at the user's 994px browser width. The old page stacked market overview, execution readiness, five account cards, a tall assistant header, repeated explanations and charts far below the fold. Reordered the Kotak home page so the trading desk appears first; retained account balances, native market overview and native execution feedback in an expandable section. Other broker dashboards retain their existing account view.

Reduced default card padding, condensed daily P&L into a strip, made support/resistance compact, placed a switchable chart beside the order ticket at this window width, and removed duplicate draft price summaries. Entry/SL/target inputs retain clear labels and coloured borders. Optional extra exit rules are expandable; automatic target stays visible. Live/manual order permissions and risk validation remain unchanged.

Checked the populated real strike list and selected an option without submitting an order. Simplified rows; showed only nearest support/resistance chart lines. Scoped placeholder snapshots keep the chain/positions visible during contract changes and discard the previous selected plan, never carrying data across account/mode/index/expiry. The focused frontend suite passed 13 tests; source and running-checkout production builds passed. No real orders or backend restart.


## Risk/reward presets — 15 October 2026

Added visible 1:1.5, 1:2 (default), and 1:5 presets beneath the stop-loss/target fields. Target = entry + (entry − SL) × selected multiple, rounded upward to the contract tick. Changing entry or SL recomputes target and draft chart; editing target manually enters custom mode. Gross rupee risk and potential profit use selected lots/contract units. The UI distinguishes these gross ratios from the fee/slippage-aware backend preview and explicitly requires a valid stop below entry; absent fresh candles do not cause an invented SL. Optional automatic target behavior remains user-controlled.

Verified 17 focused frontend tests and production builds in source and active checkout. No broker order or backend restart.


## Automatic SL and target — 15 October 2026

Selecting a priced option now derives a draft stop immediately: use the existing option-volatility distance when its selected plan is available, otherwise show a labelled 10% premium-buffer fallback. Stops round down to the contract tick and must remain strictly between zero and entry. The selected reward multiple computes the target and updates the chart. Entry edits recalculate automatic levels. Explicit manual stop and custom target edits survive late plan arrival; a Use automatic SL control restores derived behavior. No price/tick means no invented numeric level. This is draft planning only: account risk limits, fresh-data validation and explicit user order submission are retained.

Twenty focused tests passed, including fallback fill, ratio/entry changes, volatility priority and preservation of manual edits. Source and running-checkout production builds passed. No real orders or backend restart.


## Chart fixes and recommendation placement — 15 October 2026

Inspected the actual selected 15m option chart. Drag/wheel navigation was disabled, history refresh and live ticks forced latest view, dense initial bars and EMA/volume axis tags crowded the chart, and a static caption labelled historical candles as live. In Paper mode, the app forces a dark theme while the saved light-mode preference caused dark OHLC text on the dark chart.

Enabled chart drag/zoom and added Latest (reset horizontal view and price autoscale). User-panned ranges persist through history refresh; latest-follow preserves the user's zoom width. Initial spacing uses chart width. Removed EMA/volume axis tags, shortened entry/SL/target labels, displayed candle date/IST time, corrected Paper theme contrast, and labelled historical versus recent-tick data. Missing/stale exchange timestamps cannot create wall-clock candles. Initial history errors can recover on the next successful reconcile.

Moved the recommendation panel above support/resistance and the chart/ticket workspace, with an Inspect control only. Missing qualified setups remain WAIT; a displayed candidate under WAIT is explicitly watchlist only. Twenty-five focused frontend tests and source/active production builds passed. No broker order or backend restart.


## Readable on-chart line text — 15 October 2026

Added contrasting labels directly on the plot for SUPPORT, RESISTANCE, DRAFT ENTRY/STOP LOSS/TARGET and verified filled-position levels. Labels include exact formatted prices, follow chart coordinates during pan/zoom/resize, and separate nearby labels while retaining a connector to each original line. Price-axis numeric values remain; the small duplicate axis titles are removed. Unconfirmed protection does not receive an accepted-stop label. Out-of-view/invalid levels are not labelled.

Twenty-eight focused tests passed, including collision spacing, line-anchor preservation, invalid/out-of-view filtering and chart-boundary placement. Source and running-checkout production builds passed. No order or backend restart.


## Visible strike selection — 15 October 2026

Actual UI inspection showed the full strike list below the chart with an inconspicuous internal scroller, starting far below ATM. Added an actual-contract Strike selector beside Expiry and explicit CE/PE selection buttons with prices in the top controls. The initial displayed strike is ATM when available; missing data is loading/choose-expiry, not invented contracts. Selecting a strike invalidates the previous contract selection. The detailed list now highlights and centres the selected/ATM row, preserves scroll on quote refresh, and keeps column headings visible. These controls only select a contract; Buy remains a separate explicit user action.

Twenty-nine focused tests and source/active production builds passed, including top strike/CE/PE presence. No order or backend restart.


## CE/PE premium support and resistance — 15 October 2026

Selected option charts now calculate their own support/resistance from the current contract and timeframe's completed candles. Confirmed pivots require two completed candles on each side; the nearest low below and high above the latest option premium become CE/PE SUPPORT/RESISTANCE. Forming candles cannot confirm pivots; absent levels remain unavailable. State is scoped to contract/exchange/timeframe to prevent carrying CE levels into PE or between strikes.

Cyan/orange premium lines and explicit CE/PE labels coexist with distinct draft/actual entry, SL and target lines. The index chart retains index-derived levels. No execution or automatic stop behavior changes. Thirty-two focused tests and source/active builds passed. No order or backend restart.


## Strike-to-ticket automatic population — 15 October 2026

Strike selection now picks that row's contract on the retained CE/PE side and fills the ticket; initial loaded ATM uses CE by default. One lot is the default for a new contract. CE/PE buttons, the detailed chain and recommendation inspection share the same side-selection handler. Selected reward ratio persists across strike/side changes; a custom absolute target does not carry to another contract.

Draft entry uses a positive ask first, otherwise a tick-aligned last traded price labelled indicative. This addresses the observed broker response with LTP but zero bid/ask; fresh executable bid/ask validation is still mandatory before actual entry. Existing volatility/labelled percentage fallback generates SL and the selected multiple generates profit target. No contract price/tick means no invented numbers. Selecting never submits an order.

Thirty-three focused tests and source/active builds passed, including zero-ask LTP fill, one-lot default and PE/1:5 preference retention across strikes. No real order or backend restart.


## Continuous refresh — 15 October 2026

Changed desk polling from five seconds to a one-second schedule, including background refresh where the browser permits it. Existing in-flight deduplication, broker caches and quote/order rate limits remain. Prices/charts continue to consume streaming ticks; no one-millisecond REST polling was introduced (that would request 1,000 polls/second and exceed practical broker/browser limits). Data age and stale/WAIT states remain visible; a refresh schedule does not claim a fresh broker timestamp. Ticket previews remain three-second renewals and historical candle reconciliation retains its cache.

Thirty-three focused tests and source/active builds passed. Verified the preceding strike-to-ticket request in the actual UI: one lot, LTP-based indicative entry 144.20, draft SL 129.75 and 1:2 target 173.10; Buy remained disabled outside market hours. No trade or backend restart.

### 15 October — live feed and automatic exit audit

- Corrected internal WebSocket client defaults to use configured WEBSOCKET_HOST/WEBSOCKET_PORT. Active native desk proxy uses 8767; hardcoded 8765 caused repeated connect delays and stale snapshot displays.
- New order tickets enable automatic target exit by default. Existing trade policies remain stored per trade; no live order was submitted during validation.
- Replaced unconditional “Streaming prices” caption with Live feed / Broker snapshots / Waiting for fresh prices according to observed quote source and age.
- Added regression coverage for configured endpoint, target exit across controller restart, confirmed stop cancellation before target SELL, stale target quote rejection, and broker SL fill recovery without duplicate SELL.
- Verification: 62 backend tests passed, one skipped (assistant + WebSocket lifecycle); 34 frontend tests passed; primary and deployed builds passed. Existing post-pytest logger shutdown warnings persist.
- Deployed only relevant files with backup under /tmp/kotak-live-audit-backup; cold-restarted server after confirming no active assistant trades, native strategy runs, or scalp states. Server PID90271; dashboard200. Broker feed and order-update connections authenticated. UI shows automatic target checked, account age3s, market-closed entry block, and Paper mode. Live broker fills were not tested outside market hours.
- Broker SL is a stop-limit order attached after actual entry fills. Target exit is server-side and depends on server availability, fresh executable bid, broker cancellation confirmation and execution; chart levels are not fill guarantees.

### 15 October — chart entry guard and daily discipline

- Added a compact guard inside the chart card: entry/loss counts, data freshness, selected CE/PE alignment with confirmed index signal, fee-aware reward/risk from the current broker preview, and explicit WAIT / SETUP CHECKED / NEW ENTRIES BLOCKED status.
- New assistant entries are blocked after 3 distinct broker-confirmed BUY order IDs or 2 completed net-losing cycles in that account/mode/IST day. Split fills count once. Day-local high-water counts persist through restart/book omissions and reset next IST day. Ticket validation checks limits again at entry click.
- Entry caps remain separate from monetary risk halts: they cannot trigger optional account-risk exits or prevent stop management/manual exits. Added regression coverage for this distinction.
- Corrected 5m freshness to measure age from candle completion, allowing normal completed candles throughout the next five-minute cycle; missing/late history still blocks signals.
- Ticket clears previews/disables new Buy on a server entry block. Chart preview is scoped to symbol, account username, mode and expiry time. Setup checks are guidance for manual entries; no autonomous entries or untested stronger filters were introduced.
- Verification: 92 backend checks passed (assistant plus shared scalping regression tests), 39 UI tests passed, Ruff and production builds passed. Visual verification performed on Paper dashboard with 0/3 entries, 0/2 losses and market-closed WAIT. No broker orders were placed.
- Deployed relevant files only, backup /tmp/kotak-chart-entry-guard-backup; cold restart PID93705 after confirming no active assistant trades, native runs or scalp states. Dashboard200; market/order streams authenticated.

### 15 October — larger scalping terminal, from user reference

- Kotak dashboard alone now uses the available viewport width, including fluid navigation; other routes/brokers retain the standard container.
- Replaced the single chart/sidebar arrangement with a full-width CE / Index / PE terminal and a CE / PE toggle for two wider option charts. One timeframe control applies to all visible panes. Each chart is at least 560px tall, with larger responsive desktop height.
- Added RSI14 in a separate 0–100 pane with 30/70 reference lines, using the existing Wilder RSI calculation. EMA and volume remain. Indicators are display-only and do not change entry/exit rules.
- Each option pane has its own contract, premium support/resistance, fill markers and actual position data. Active ticket levels appear only on that contract. Select CE/PE loads the existing ticket without placing an order.
- Compacted the top header; kept recommendations above the charts, with index levels in an expandable summary. Entry guard and durable execution remain intact; ticket/chain/managed exits follow below the charts.
- Verification: 49 frontend tests passed (terminal contract isolation, selection, layout toggle, shared timeframe, RSI warmup/flat/decline cases, existing assistant and navbar checks); production build passed. Browser verified three panes, separate RSI displays, two-pane expansion and PE ticket auto-population; no broker order submitted. UI-only deployment; no server restart needed. Backup /tmp/kotak-scalping-terminal-backup.

### 15 October — Buy and lots directly on each option chart

- Added CE and PE chart controls with independent lot inputs, broker lot-size unit totals, entry/SL/target prices, auto-target status and mode-labelled Buy buttons.
- Extracted existing ticket state/submission flow into useTradingTicket; chart controls and detailed ticket render the same controller for the selected side. Manual entry/SL/target, lot and exit-policy edits remain synchronized. Each side keeps its own controller; prices/levels are scoped to its own contract.
- Reused preview/entry endpoints, CSRF, server risk/cap/quote validation, durable idempotent ticket submission and existing stop/target management. No arming or extra confirmation added. Pending network outcomes retain the same ticket; known validation rejections clear the failed intent. Changed quantity/plan/account/mode/settings immediately invalidate the previous preview identity.
- Staggered per-side preview polling to avoid deterministic account-lease contention; poll timing is bounded and in-flight reads are not overlapped.
- Verification: 57 assistant/navbar UI tests passed, including chart/detail synchronization, edited SL target propagation, duplicate click submission once, immediate lot-preview invalidation, daily-cap block, PE Live mode routing, and retry after a known expired preview. Primary and active production builds passed.
- Browser verified both lot controls and mode-labelled Buy buttons, CE lot edits synchronized to the detailed ticket, and restoration to default 1 lot / 65 units. Current Paper session is market-closed and both Buy controls remain disabled with the broker reason. No real or paper broker trade was submitted in UI verification. Screenshot /tmp/kotak-buy-on-chart.jpg; deployment backup /tmp/kotak-chart-buy-backup. No backend restart required.

### 15 October — chart decision clarity review

Browser inspection found the chart Buy area omitted the selected reward multiple and total rupee outcomes. Keep the existing terminal layout and execution flow; put the decision values before each Buy button. Add side-specific 1:1.5 / 1:2 / 1:5 controls, synchronized with the detailed ticket and price lines. Show premium, loss at SL and potential profit for all selected lots. Use gross planned-price amounts with an explicit before-fees label until the matching broker preview is current; then show its estimated net risk/reward, charges and net ratio. Invalid quantities/levels show unavailable amounts.

Implementation also removes expired previews from consumers and distinguishes checking/expired/broker-busy statuses from ready. Updated orders immediately lose their old preview approval; existing entry/exit limits and broker execution remain unchanged. Tests cover ratio-to-target changes, immediate approval invalidation, lot-scaled amounts, invalid quantity, net estimates and expired preview handling. No trade submission is part of browser verification.

Verification: 61 assistant/navbar tests across 13 files passed; primary and active production builds passed (existing large-bundle warning). Browser verified CE two lots / 130 units, gross SL loss ₹1,878.50, 1:5 target ₹216.45 and gross potential profit ₹9,392.50, with the detailed ticket synchronized. Restored one lot and 1:2. Paper mode and market-closed entry block retained. Deployed only the controller/views and tests, backup /tmp/kotak-chart-review-backup; no server restart. Screenshot /tmp/kotak-chart-decision-review.jpg.

### 15 October — charges, estimated net P&L and hover selection

- Added a shared chart/detail cost table: gross P&L, estimated round-trip charges and net P&L at SL/target, plus premium, net ratio and an expandable tax breakdown. Estimates remain available outside market hours and never authorize Buy. The matching broker preview remains mandatory for entry.
- API brokerage uses the account setting (confirmed ₹0). Browser estimates use the same verified 2026 NFO/BFO premium-turnover rates as the execution calculator: STT, stamp, exchange, SEBI, IPFT and GST. Literal regression cases match the Python calculator, including NSE/BSE differences and configured nonzero brokerage. Date/invalid-input guards suppress unsupported figures. Reverify both implementations when rates change.
- Configured exit slippage is included in both gross and net estimates so the table balances. Default CE example: gross target ₹1,872.00, charges ₹25.82, net ₹1,846.18; SL gross −₹945.75, charges ₹20.41, net −₹966.16. At zero slippage the target charges are ₹25.83 and net ₹1,852.67.
- Open managed trades now show current-bid gross P&L, estimated entry/exit charges and net P&L for remaining quantity. Costs recalculate from the latest executable quote rather than reusing the previous quote's fee offset. Stale/crossed quotes, zero remaining quantity and unverified entry basis show unavailable values. Realised account figures remain in the existing journal strip.
- Hovering CE/PE charts or the top CE/PE selection buttons selects that side's ticket; it cannot place an order. Strike ladder selection remains a click. Keyboard/touch selection buttons remain.
- Verification: 67 assistant/navbar tests across 15 files passed; primary and active production builds passed (existing bundle-size warning). Browser verified PE chart pointer entry selected PE and populated entry ₹131.75, and both option cost tables displayed separate fees/net figures. Open-trade calculations tested with fixtures; no broker trade submitted. UI-only deployment, no server restart; backup /tmp/kotak-net-costs-hover-backup.
- Final browser verification in the current Live/light-theme session: CE two-lot target fees ₹51.63; restored one lot / 1:2 and CE selection. Source/deployed files match. Screenshot /tmp/kotak-charges-net-pnl-hover.jpg. Broker book reads currently report “Kotak book read failed; account state is unknown”; Buy is disabled and live-position/account P&L cannot be validated until those reads recover. Planned-price fee estimates remain available; no locks, credentials, mode, risk settings or broker orders were changed to bypass the data failure.

### 15 October — prominent RSI numbers and candle-close timer

- Added a two-decimal RSI14 readout above every CE/index/PE chart and enabled the latest RSI value label on the RSI pane's right axis. The readout identifies hovered vs latest/last bars, preserves zero RSI, and shows unavailable during warmup or a contract/timeframe change rather than leaking the old instrument's value.
- Added a MM:SS countdown driven by the existing one-second chart clock and the latest actual bar's start plus selected 1m/5m/15m duration. Converts the chart's IST-shifted timestamps back to UTC before comparing time. Historical bars show Closed; missing/future bars show unavailable. Countdown never restarts until a real next candle arrives and remains independent of the hovered candle.
- Retained the hovered candle's RSI/OHLC selection during data/clock updates; no signal, order or exit behavior changed.
- Verification: 72 assistant/navbar tests across 17 files passed. Tests cover timeframe durations, fractional-second rounding, close/new-bar boundaries, missing/future/old history, zero/missing RSI and independent hover/countdown values. Primary and active production builds passed; deployed files match source. Backup /tmp/kotak-rsi-timer-backup; no backend restart.
- Browser verified CE RSI48.66, index57.29, PE52.28, numerical RSI axis labels and Closed for the historical bars. Moving onto a PE candle changed its readout to49.99 with Hovered bar while the timer remained Closed; restored CE selection. Screenshot /tmp/kotak-rsi-bar-close-timer.jpg. No broker order submitted.

### 15 October — database-backed lifecycle and restart recovery

- Retained immediate streamed market ticks and the one-second account/reconciliation loop; no millisecond broker REST flood. A permanently stopped feed client is replaced and its contracts resubscribed.
- Trade intent, order tags/IDs, fills, policies and changed lifecycle checkpoints commit to SQLite before submission and after broker outcomes. Added **Terminal trade history** for active/completed records, filtered by account mode. The running database is `db/openalgo.db` in the native checkout, table `kotak_assistant_account`, WAL mode; integrity verified OK.
- Reclaim a lease immediately only when its owner is a provably dead process on the same OS host, using an atomic comparison against the exact previous owner. Real subprocess-crash coverage verifies restoration without a five-minute wait; live, other-host and legacy owners remain protected.
- Fixed Kotak's exact documented empty-report response (5203 / No Data / data not found); failed/auth/malformed reports still fail closed. Live read-only broker books now return confirmed zero orders, positions and fills.
- Installed user launchd service `io.openalgo.kotak-terminal`, binding localhost5001, starting at login and restarting the server after exit. Verified automatic restart PID10219 to PID10567 and HTTP200 with no active trades/runs. Recovery reconciles existing broker IDs and never authorizes a fresh automatic entry.
- Verification: 103 backend checks and 74 assistant/navbar UI checks passed, Ruff and primary/deployed production builds passed. Browser confirmed account recovery, chart/strike loading and the expanded empty history panel in the existing Live/light-theme session. No real or paper broker trade submitted. Backup `/tmp/kotak-durable-tracking-backup`; screenshot `/tmp/kotak-durable-tracking-verified.jpg`; operational details in `docs/validation/kotak-terminal-recovery.md`.
- Server targets/trailing require a running computer and valid broker session. After Mac reboot the user service starts at login; accepted broker SL remains subject to order type/DAY validity during downtime.

### 15 October — partial panel refresh and recommended timeframe

- Kept the deduplicated one-second desk snapshot check and immediate streamed ticks. Memoized chart boundaries and retained chart-level/marker/position references so account-only or quote-only refreshes do not recreate unchanged chart overlays. Each chart's own countdown/feed continues independently. Memoized saved trade history; unchanged records retain their panel.
- Stable ticket-price dependencies update entry/SL/target lines only when prices change. The page, strike selection, input focus, edited lots/entry/SL/target and chart viewport remain in place during polling. The header explicitly says **panels refresh 1s**. Existing broker caching/freshness validation remains in effect; the UI cadence does not manufacture fresh broker data.
- User requested the recommended timeframe instead of the prior 1m default. Defaulted the shared CE/index/PE chart selector to **5m · Recommended**, matching the existing setup's five-minute confirmation horizon. Manual 1m/15m choices remain available and are preserved through partial updates; no signal or execution rule changed.
- Regression first reproduced fill-marker recreation on an unrelated price/account update. Added real-chart tests against the canvas boundary for unchanged overlays/viewport, and timed desk tests for refreshed account/quote values while preserving input focus, manual levels, lots, strike, expiry and selected timeframe.
- Verification: 77 assistant/navbar checks across19files passed; source and running production builds passed, with the existing bundle-size warning. Source/deployed files match. UI-only deployment; no backend restart or broker trade. Backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-partial-refresh-backup-r7i57i19`.
- Browser verified the default **5m · Recommended** selector and all three 5m panes, with **panels refresh 1s** visible. The index bar countdown progressed from01:30 to01:22 without page navigation/reload; historical option bars stayed Closed. The current browser session was Paper/dark; mode/theme were not changed by this implementation. Account freshness remained explicitly labelled (16–25s in the observed frames), so the page correctly retained WAIT while those account reads were stale. Screenshot: `/tmp/kotak-partial-refresh-5m.jpg`.

### 15 October — index UP/DOWN, points and percentage

- Added a compact day-movement strip below the contract selector: index name, green upward arrow/UP or red downward arrow/DOWN, signed points, signed percent, and the explicit previous-close reference. FLAT and stale/unavailable data remain neutral. This reports the index's day movement; existing setup confirmation and order behavior remain separate.
- Previous close comes from normalized Quote-mode `close` or REST `prev_close`; the displayed percent is point change divided by that reference. Added an index Quote subscription alongside the existing Depth price stream on the shared feed, because Kotak Depth/LTP frames do not carry the reference. Option Depth subscriptions retain their order-book data; no new connection or broker mutation was added. SENSEX uses its own quote/reference after switching.
- Added semantic direction colours with separate light, dark and Analyzer palettes. Measured text/arrow contrast on badge surfaces: light UP6.81:1, DOWN7.60:1; dark/Analyzer UP10.62:1, DOWN8.51:1. SVG arrows plus explicit words and signed values communicate direction without relying on colour. Labels wrap between groups, use tabular figures, and remain static.
- Tests cover UP/DOWN/FLAT arithmetic, missing/invalid close or index price, REST and stream field formats, live changes, SENSEX isolation, quote-age expiry and future timestamps. Fixed the fresh-tick boundary so the movement uses the current render time, avoiding false stale labels between the desk's one-second clock ticks.
- Verification: 93 assistant/navbar checks across20files passed; source/deployed production builds passed with the existing bundle warning; deployed files match source. UI-only deployment; trading server not restarted. Backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-index-movement-backup-k_fbitkw`.
- Browser verified **NIFTY UP +48.60 pts (+0.21%) vs previous close22,622.70**, followed by live changes to **+18.00 pts (+0.08%)** without navigation. The SVG arrow and direction text computed to green rgb(134,239,172) on rgb(5,46,22) in the existing Paper theme. Confirmed broker REST previous close22,622.70 via read-only quote access. Earlier stale data correctly displayed neutral **Last UP** until a fresh quote arrived. Preserved 5m default, current mode/theme, ticket and entry guard; no orders placed. Screenshot: `/tmp/kotak-index-movement-verified.jpg`.

### 15 October — manual Buy remains the user's decision

- User reported disabled Buy and requested control over entry. UI inspection found **Set risk limits first**: all four optional rupee budgets had incorrectly been prerequisites. Nullable budgets are now optional, with each configured risk/premium budget independently enforced; configured daily-loss/giveback halts remain mandatory. Unbounded `max_lots` is represented as null, and recommendations use plan eligibility rather than truthiness of that optional cap.
- Valid ticket fields now enable manual Buy independently of a background preview. A click obtains current broker validation if needed, validates account/mode/settings/order identity and expiry, and submits through the same durable broker-intent path. No additional arming or confirmation. Invalid/off-tick prices, invalid lots, concurrent submission and configured money halts still disable Buy. Broker failures are surfaced at click time and never bypassed.
- An explicit persisted boolean `manual_entry` identifies terminal entries. Fixed trade-count, loss-streak cooldown and consumed-setup rules are advisory for these tickets; their previous behavior remains for default/nonmanual API tickets. Manual entries do not consume setup IDs. Entry guard now displays **CAUTION** and **Guidance only; manual entry is your decision** for fixed counts. Configured money limits, current books/quotes, cash, contract/expiry/freeze checks, no overlapping/averaging positions, and protection ownership are still enforced. Existing SL/target exits remain managed independently.
- Background previews cannot start or publish over an in-flight/unresolved submission. Unknown outcomes retain the same ticket for retry; duplicate clicks are synchronously locked. Tests cover fresh click-time preview, broker rejection, contract changes during validation, invalid ticket fields, expired preview replacement and unknown-outcome reuse.
- Live account audit exposed another adapter mismatch: positions returned `stat=ok`, `stCode=200`, and a list, which the uppercase-only success parser rejected. Canonicalize only that exact success with no error/errMsg. Session failures, other codes and malformed data still fail. Added success and lowercase401 regressions.
- Verification: 114 backend checks and 98 assistant/navbar UI checks passed; production build and production-code Ruff passed. Broad test-file Ruff still reports ten pre-existing C408/E701/E702 violations outside the added cases; existing pytest logger shutdown warnings remain. Focused read-only execution reviews approved all three deltas. Deployed files match source. Backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-manual-entry-backup-_yz0tznb`.
- Activation: confirmed zero assistant-managed trades, scalping states and strategy runs. The separate live position had a broker-held SELL SL for its65units; no broker orders were changed/adopted. Supervised cold restart from PID10567 to PID20104 returned dashboard HTTP200. No real or paper order was submitted during verification.
- Considered allowing nonmarketable manual limits to queue until cutoff. Automatic approval review rejected deploying the longer lifetime because a later unintended fill was not explicitly authorized. Selected the safer alternative: removed the proposed price/lifetime changes and their extra tests from primary, confirmed execution code matches the already deployed version, and retained the original marketable-entry price check plus five-second pending-entry timeout. Added visible timeout text to chart controls and the detailed ticket. This caption-only deployment changed no order policy and required no further server restart. Final validation remains114backend/98UI passing.
- Final browser verification: both exact chart controls, **Buy CE · 1 lot · PAPER** and **Buy PE · 1 lot · PAPER**, are enabled with valid ticket fields. Both panes show **Ready · broker checks passed** and the five-second pending-entry caption. Preserved the existing Paper/Analyze session, dark theme, one lot and 1:2 ratio; no trade button clicked. Screenshot: `/tmp/kotak-manual-buy-enabled.jpg`.

### 15 October — explain live setup checks instead of a constant Unconfirmed label

- Reproduced **Data Fresh / Setup Unconfirmed** in the dashboard. Prices and account polling were live. The analysis collapsed missing triggers, missing target levels, insufficient reward/risk and unavailable candle history into the same generic label. A read-only replay of archived live candles at10:44 showed CALL trend and a valid pattern, but no confirmed resistance above the latest completed close; the existing strategy therefore had no2:1 structural target. This was a status explanation bug, not evidence that the market feed had frozen.
- Analysis now returns evaluation time, last completed1m/5m close times, candle-history quality, five-minute trend, trigger confirmation, target availability and reward/risk. Each WAIT outcome has a specific state and reason. No entry eligibility, setup ID, stop, target or expiry rule was relaxed. Across180 recorded evaluation instants, old and updated action/setup/entry/invalidation/target/expiry decisions matched exactly; diagnostics distinguished low reward, waiting trigger, missing target and candle quality states.
- The existing entry guard now displays the specific setup status, three compact checks and an IST evaluation/candle timestamp row. Freshness includes candle age and evaluation age, so live ticks cannot hide delayed analysis. Its one-second clock uses the existing partial-refresh cadence. Timer text is outside the live status region to avoid repeated screen-reader announcements. Manual Buy/exit handling remains unchanged.
- Test-first regressions failed for missing diagnostics and stale analysis appearing checked, then passed. Final verification:121backend checks,100assistant/navbar interface checks, production builds in source and active checkout, and targeted Ruff checks passed. Existing large-bundle and pytest shutdown-logger warnings remain. Six source/deployed files match; execution.py is unchanged. Backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-setup-status-backup-lvgvhwcs`.
- Activation used the existing launchd service, cold restart PID20104 to33057, dashboardHTTP200. Confirmed zero live assistant trades, scalping monitors and strategy runs before activation. One persisted protected Paper trade recovered with a fresh heartbeat and continued HOLD monitoring. No broker order APIs were called by the activation script; no Buy/Exit controls were clicked during verification.
- Final browser verification showed **Data Fresh / Setup No target level**, **5m trend Uptrend / 1m trigger Waiting / Target room No resistance above**. The evaluation clock advanced from10:51:41 to10:52:12 IST and the latest1m close advanced from10:51 to10:52 while the5m close correctly stayed10:50. Both exact CE/PE one-lot Paper Buy controls remained enabled. All three charts loaded in the existing Paper/dark session. Screenshot: `/tmp/kotak-setup-status-verified.jpg`.

### 15 October — expose the actual live order authorization rejection

- Traced tracking ID4c8c1a1402dd4f8785027381bfed0ef3 to the unique original11:07:30.295 server response: HTTP401, `stat=Not_Ok`, `stCode=100008`, `errMsg=unauthorized`. Kotak's current official static-IP documentation identifies that exact payload as a non-whitelisted-IP rejection; its report, data and websocket APIs are exempt from that check. The existing order endpoint and headers match Kotak's published API documentation. Fresh read-only account books at11:08 showed18 executed orders, no fills in23150CE and no nonzero position.
- Root display bug: the assistant read `emsg`/`error`, omitting Kotak's `errMsg` and `stCode`, so a definitive rejection received the contradictory generic reason **Broker submission outcome unknown**. Submission parsing now preserves the actual message, HTTP status and broker code, with specific guidance for100008 and1037. Malformed responses and5xx/network uncertainty remain unknown; they never authorize resubmission. Initial lifecycle text now accurately says submission started, awaiting broker response. No order timing, pricing, risk or retry rules changed.
- HTTP status/code/error are saved with the existing durable operation and survive restart. Definitive rejections with no order ID now show **No broker ID returned**, rather than **awaiting ID**. Recovered the original record's reason from its uniquely correlated response log after fresh read-only books confirmed no matching tag/order/fill. Its status, quantities and original two timeline events remain intact; the correction adds a third event. Full prior account-state backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-rejected-trade-before-rargwt6e.json`.
- User requested public IPs, then proposed192.168.0.35. Verified an observed public IPv4 and no globally assigned IPv6 interface. Explained the proposed address is private LAN space and cannot fix Kotak's public-IP whitelist. No whitelist, network, VPN, session credential or broker order settings were changed. Stability of the observed public address has not been established; registering a different security-sensitive address requires specific authorization and confirmation that it is the intended static address.
- Test-first regressions reproduced missing rejection details, lost persistence metadata and misleading ID text. Final verification:128backend checks and101assistant/navbar UI checks passed; source and active production builds passed; targeted production Ruff passed. Existing large-bundle and pytest shutdown-logger warnings remain. Seven files deployed, backup `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-auth-message-backup-d_grqk6i`. No actual or Paper broker trade was submitted, retried, cancelled or modified during verification.
- Supervised activation PID33057 to37317 returned dashboardHTTP200 after confirming zero live managed trades, protected Paper trades, scalping states and strategy runs. Browser verification in the user's existing Live/light session showed the corrected HTTP401/code100008 IP-whitelist reason and **No broker ID returned**, with0filled/0remaining and the added correction event. The original timeline remains intact. Screenshot: `/tmp/kotak-ip-rejection-verified.jpg`.

### 15 October — user-authorized Kotak API token update

- Saved the user-provided API access token only as `BROKER_API_SECRET` in the running native Kotak checkout's `.env`, through the existing atomic environment writer. Verified the saved value and application configuration reader agree, every other setting is unchanged, and permissions remain0600. The primary checkout is configured for Delta and was deliberately left unchanged. No token value is recorded in this document or tool output.
- Private recovery backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-token-backup-icuywkg1`. Supervised restart PID37317 to37880 returned dashboardHTTP200 after checking zero active trades/strategy monitors. No order APIs called.
- A fresh Kotak TOTP/MPIN login at `/broker/kotak/totp` is still required to issue a new broker session using the new API token. The existing encrypted composite session was not manually edited or represented as freshly authenticated. Whitelist/network settings were not changed.

### 15 October — current price in open-trade monitoring

- Added a prominent **Current price (LTP)** beside estimated net P&L for each managed open trade, using that trade's symbol/exchange quote. Displays feed source, quote-receipt time in IST and age. Uses the existing shared feed, broker-quote fallback and one-second desk refresh; no additional connection or polling loop.
- Quotes older than five seconds show **Last price (LTP) / Stale**. Missing or invalid LTP is unavailable and is never replaced with the entry or bid. LTP freshness is separate from executable two-sided depth; estimated P&L still requires the existing fresh bid/ask checks. The bid is labelled **Last exit bid** when stale.
- Named trade sections and labelled calculation outputs support assistive technology; rapidly changing prices/P&L have live announcements disabled. Order-request feedback retains its status output. Existing entry, SL, target, exit and server monitoring behavior is unchanged.
- Verification:105 assistant UI tests across19files passed in the source checkout;82 tests across13files passed in the active checkout. Targeted lint passed; the active TypeScript check and staged production build passed with the existing bundle-size warning. Three scoped files synchronized; staged assets activated with the index swapped last, old assets retained and server PID37880 unchanged. Backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-live-price-backup-pum9_z9_`.
- Browser verified the existing protected Paper trade **NIFTY19OCT2623100CE** using live market quotes: LTP changed from71.65 through71.75/71.15 to74.50, with advancing receipt timestamps and estimated P&L. Retained entry70.95, SL64.60 and target83.65. No Buy/Exit controls were clicked and no orders were submitted for verification. Screenshot: `/tmp/kotak-live-price-verified.jpg`.


### 15 October — tracking-only Kotak Neo trades, RSI dial and current-bar volume

- Added a tracking ticket in the empty left column below strikes. It uses the selected contract and lot size, auto-fills from ask/LTP, and retains an edited actual fill during market updates. Auto fill restores the current quote. Editable SL defaults to the existing 10% premium buffer with tick rounding; target follows entry + risk × the chosen 1:1.5, 1:2, 1:3, 1:4, 1:5 or 1:6 ratio. Correcting an automatically planned tracked entry recalculates its saved SL and target.
- Tracking records appear inside Open trades & live monitoring. They support entry correction and an explicitly entered closing price; Record close stores the result and shows gross, estimated fees and net P&L in closed tracking history. Tracking-only actions use IndexedDB, scoped to the local username/Kotak account. They survive page/server restarts on this browser and make no broker order/adoption/exit calls. These records do not participate in the server execution coordinator or automatic exits. No backend trading rules changed.
- Added a 270-degree RSI 14 speedometer, numerical reading, labelled 30/70 zones and unavailable/stale states. It uses the existing Wilder calculation and selected 1m/5m/15m timeframe. Chart candles are shared through a bounded account/mode/contract/timeframe store. Tracking-only views do not request historical candles; they reuse the selected chart and existing shared feed. Managed positions can refresh missing/old history through the existing read-only endpoint.
- Volume always references the current forming candle, independently of crosshair hover. With complete current-session closed candles, current volume equals the live day counter minus closed-bar volume. Otherwise it uses the known current candle volume or shows unavailable; an unobserved synthetic bar is not assigned invented volume. Added option Quote subscriptions for selected/monitored contracts on the existing shared connection because Kotak Depth frames omit day volume.
- Buyer/seller figures sum the available visible bid/ask ladder quantities, with level counts and theme-aware green/red text. They are explicitly labelled pending order-book quantities. The feed does not expose executed buyer/seller volume per candle, and no such split is fabricated. Day volume remains separately labelled.
- Verification:123 source UI checks across24files and100 active-checkout checks across18files passed. TypeScript checks and staged production builds passed; targeted lint passed. Existing large-bundle warning remains. Final19 scoped files match the active checkout, assets were staged and the HTML index swapped last, and server PID37880 remained running. Earlier feature backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-tracking-indicators-backup-irycfwtz`; final backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-tracking-final-backup-y8mz0i48`.
- Browser verified local database readiness, selected-contract auto fill, and entry100 / SL90 / ratio1:3 / target130. Restored live auto fill and ratio1:2 after checking. Current12:20 candle volume advanced from747045 to818220, with RSI58.72→59.72 and live five-level buyer/seller quantities. No tracking example was saved into the user's journal, and no Buy/Exit controls or broker order APIs were used. Screenshot: `/tmp/kotak-tracking-current-bar-verified.jpg`.

### 15 October — full external-trade levels and restart restoration

- External records previously displayed entry/SL/target in a small inline summary; older records could lack saved levels entirely. Added full filled-entry, SL and profit-target boxes using the existing terminal colours, risk, potential gross profit, R:R and separate SL/target fee/net-P&L estimates. Saved custom levels remain intact; incomplete legacy plans visibly identify automatic 10%/default1:2 assumptions. Live P&L remains unavailable until a fresh quote, while saved prices and planned results remain visible offline.
- External Add/Edit/Record close remain browser IndexedDB operations and never place, adopt, modify or close broker orders. Local plans are explicitly monitored levels, without fabricated broker protection or execution acknowledgements. Correct entry recalculates automatic/custom-stop targets consistently for legacy records too.
- Added scoped JSON backup/download and restore for browser changes or data clearing. Whole-file validation rejects invalid/cross-account files; restore adds missing IDs atomically and never overwrites existing records. Normal browser/app/server reopening restores trades without imports. No server schema, credentials or trading rules changed.
- Review found a pre-existing stale-window overwrite: correcting an entry in an obsolete window could reopen a record closed elsewhere. Reproduced against real IndexedDB in an isolated UI fixture, then guarded save inside the same readwrite transaction. Rejected writes reload committed records and preserve the close.
- Verification:128 source assistant UI tests across25files;105 active-checkout tests across19files;46 fake-broker execution/database-recovery checks. TypeScript checks, scoped lint and active staged production build passed (existing large-bundle warning only). Initial Python test setup required a valid LOG_FORMAT override; passing test exit emitted an existing logger-shutdown warning. No real/Paper broker orders were used.
- Browser integration at isolated127.0.0.1:5187 used simulated quotes and a separate origin/database: add, full-page reload, new window, actual preview-server termination/restart, retained entry101/SL90.90/target121.20, recorded close111, stale-window rejection, backup download and restore. Restore added missing PE while a stale CE backup did not reopen the closed CE. The user's5001 journal was not populated with fixtures.
- Eight scoped source/test files synchronized to the active Kotak checkout. Assets staged, old hashed assets retained, index replaced last; dashboard and29 referenced assets returned200 with live PID37880 unchanged. Rollback backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-external-monitor-backup-sioh_73v`.
- Deployed browser verified persistence controls and0 saved external trades. Screenshots: `/tmp/kotak-external-monitor-deployed.jpg` (actual dashboard), `/tmp/kotak-external-trade-plan-verified.jpg` (isolated sample). No broker acceptance or protection status was inferred from locally tracked levels.

### 15 October — automatic read-only tracking of all live Kotak Neo trades

- Added authenticated GET broker-monitor, independent of the ticket's Paper/Live mode. It reads actual Kotak positions, orders and trade fills without calling coordinator reconciliation/adoption or any submit/cancel/exit method. Funds reads are optional for this path, so an unrelated margin response cannot block position tracking. Existing execution books retain their default funds requirement.
- The observer persists account-scoped positions/orders plus immutable fill history in the existing SQL Store under a separate observer scope. Keeps the last30 observed trading days, merges reduced/empty later fill reports without erasing observations, validates stable raw fill IDs and flags conflicting or malformed data. Failed reads preserve last known positions. Fills observed while positions lag are saved even when current exposure stays unconfirmed, allowing a later reduced report to reconcile.
- Remaining weighted fill basis handles partial exits, shorts and reopened legs. Opposite-side fills with identical timestamps are explicitly unverified because broker IDs do not establish execution sequence. Carry valuations are labelled and no original-entry/net-P&L is fabricated. Broker position/fill mismatches retain the previous confirmed exposure until coherent books arrive.
- Existing server monitor now checks enrolled observer scopes every5seconds, continuing read-only capture after the browser closes and resuming after server restart/reconnection. Dashboard polls every1second with broker reads coalesced/cached for2seconds. Actual option prices/depth share the existing market-data connection; no millisecond polling or extra websocket connection.
- Live broker cards appear inside Open trades & live monitoring in either ticket mode, including any symbols, signed quantities, actual reported stop/target orders, outstanding exit quantities/statuses, LTP, verified open P&L and supported option fee estimates. Stale order presence/absence is identified as last saved. Exact live terminal-managed quantities are deduplicated; additional exposure in the same contract remains visible as the broker total with overlap text, without inventing a residual cost basis. Manual tracking is relabelled as optional.
- Saved broker fills show symbols, side, units, price and IST timestamp/order ID, chronologically newest first. Prior-day saved data carries its date rather than claiming to be today. Closed broker trades remain visible through their immutable fills without pretending stale quotes are closing fills.
- Verification:138 source UI tests across26files;115 active UI tests across20files;85 backend monitor, broker adapter, routes, execution and recovery checks. TypeScript, scoped new-code lint, Python compilation and staged production build passed. Existing root-component lint issues and large vendor-bundle warning were not represented as fixed. An existing UI test's callback-created timestamp could be later than the render timestamp by1ms; its fixture now captures the timestamp before render, removing that unrelated timing flake.
- Review regressions covered missing IDs, unordered/equal-second fills, reduced reports, last-known state, lagged positions, source/mode isolation, background polling, same-contract additional exposure, stale protection labels and restart/day boundaries. No live or Paper trades were submitted for testing.
- Preflight confirmed zero active terminal trades, scalping monitors, Kotak strategy runs and broker open positions. Graceful supervised restart loaded the backend (PID37880 to74312); anonymous broker-monitor request correctly returned401 and dashboard returned200. Fifteen scoped files synchronized; assets staged and index activated last with29 references verified. Later history-order UI activation retained PID74312. Rollback backup: `/var/folders/wx/jdc4vmdx2n3_40v_z4tw16f80000gp/T/kotak-auto-monitor-backup-o1gr0gwg`.
- Live verification: dashboard in Paper mode automatically imported18 actual Kotak fills dated2026-10-15 and confirmed zero open positions. SQL observation separately confirmed18 saved fills, zero open positions, fresh book age and no error. Browser verified newest-first history and advancing sync age. Screenshot: `/tmp/kotak-auto-broker-tracking-verified.jpg`. No credentials, static-IP settings or broker orders changed.
