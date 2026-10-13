# Native OpenAlgo Kotak Feature Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution in this session, or superpowers:subagent-driven-development if the user selects that method. Steps use checkbox syntax for tracking.

**Goal:** Complete the native application with our charts, manual protection, reports, replay, fees and market overview, and verify the full user journey.

**Architecture:** Extend OpenAlgo's existing native pages using the verified broker/execution services from Part 1. Migrate historical records through a schema-aware importer; runtime indicators use the upstream loader. Replay consumes the same pure signal/risk core as automation.

**Tech Stack:** Native OpenAlgo Flask/React, its chart library/runtime indicator contract, native SQLAlchemy engine factory and preserved actual-data archives.

**Spec:** [Approved migration design](../specs/2026-10-13-native-openalgo-kotak-migration-design.md).

**Dependency:** [Part 1: clean installation, Kotak and strategy foundation](2026-10-13-openalgo-kotak-foundation.md) must pass first.

## Global Constraints

- Carry all Part 1 constraints: clean official base, configured ports 5001/8767/5557, private server-side credentials, one active preset, default Analyzer / Stopped, user-controlled Live arm.
- Confirmed 15m strategy signals, 09:45–15:15 IST entries and 15:29 owned-position timer; 6R initial index target and preserved trails/guards.
- Chart timeframe and symbol choices must not alter execution rules. CE/PE charts display actual selected contract premium prices.
- Manual SL/target uses option premium rupees; trailing activation/distance uses net rupees. Manage only explicitly identified terminal-owned exposure.
- Gross P&L is before fees; actual paid charges and calculated estimates remain separate. Exclude zero-fill cancellations and retain filled portions.
- Backtests use actual observations with source/coverage metadata. Expired-option gaps remain visible; no invented P&L, guaranteed profit or claimed 80% win rate.
- Existing report results remain historical artifacts. One-year selection is supported only to the extent real data exists.
- Preserve OpenAlgo's UI system and runtime indicator loader; no iframe or standalone broker/execution app inside the native application.

## Review Focus

- A chart may switch to another contract while a trade is open; its risk lines must not appear on the wrong price scale. Verify in Task 2.
- Importing a report twice must not double fills, charges or P&L; missing opening inventory must stay unresolved. Verify in Task 1.
- A broker quote may contain LTP but no valid previous close or timestamp; breadth/price change must not silently invent them. Verify in Task 4.
- Promotional brokerage may expire, and a cancelled order may have partial fills; calculate charges from applicable dates and executed quantity. Verify in Task 1.
- A replay may lose option minutes around entry/exit or report a same-bar stop/target touch; retain conservative ambiguity and missing-data status. Verify in Task 3.

---

### Task 1: Historical migration and fee-aware native reports

**Files:**
- Create: `scripts/migrate_neo_desk.py`, `services/neo_desk/history.py`, `fees.py`, `migration.py`, `database/neo_history_db.py`.
- Modify: `blueprints/neo_desk.py`, `frontend/src/pages/TradeBook.tsx`, `PnLTracker.tsx`.
- Create: `frontend/src/components/neo-desk/RecordedTradeHistory.tsx`, `FeeBreakdown.tsx`.
- Tests: `test/neo_desk/test_migration.py`, `test_history.py`, `test_fees.py`, matching frontend report tests.

**Interfaces:**
- `migrate_archive(source: Path, destination, owner_id: str, dry_run: bool) -> MigrationManifest`: source hashes, schema versions, stable fill IDs, imported/reused counts and reconciliation totals.
- `history_page(owner_id, symbol, start, end, cursor) -> HistoryPage`: FIFO closed/open quantities with explicit fee/inventory completeness.
- `estimate_charges(fills, promotion: PromotionWindow, plan: FeePlan) -> ChargeEstimate`: per-date brokerage and statutory breakdown; zero-fill cancellation creates no executed charge.
- Reports preserve `gross`, `actual_fees`, `estimated_fees`, `net`, source and completeness as separate fields.

- [ ] Back up/checksum the current journal, fill archive, fee imports, datasets and reports. Inspect actual schema/version and create a manifest; do not move an open trade into the new engine.
- [ ] Write failing tests for repeat import, same ID/conflicting payload, partial cancellation, duplicate execution events, missing entry inventory and incomplete actual charges.
- [ ] Add literal fee fixtures for recorded promotional dates, the applicable ₹10 plan rate after promotion, statutory taxes and a zero-fill cancelled order. Unverified promotion dates must not be guessed.
- [ ] Pin `test_repeat_import_is_idempotent`: a second import of the same fill IDs adds zero fills and leaves gross/actual-fee totals unchanged. Pin `test_cancelled_partial_fill_is_retained`: a 65-unit cancelled order filled for 20 units contributes exactly 20 executed units; a zero-fill cancellation contributes none. Pin `test_missing_opening_inventory`: an exit without its prior inventory remains unresolved and does not contribute invented gross/net P&L.
- [ ] Run failing tests, then implement normalized import and fee estimation through native persistence. Preserve original reports separately rather than recalculating their published totals.
- [ ] Run a dry-run migration and compare counts/quantities/gross/actual-fee totals to the old archive; only then import. A mismatch blocks cutover and remains reported.
- [ ] Add native reports UI with symbol/date filters, import/export and completeness labels. Actual paid fees cannot be derived solely from the broker's daily trade book.
- [ ] Run backend/frontend report tests and verify the UI against migrated records. Commit source/tests and the public manifest schema; keep private records outside Git.

### Task 2: Actual option charts and manual trade protection

**Files:**
- Modify: `frontend/src/pages/Scalping.tsx`, `Trading.tsx`, existing native chart components.
- Create: `frontend/src/components/neo-desk/OwnedTradeControls.tsx`, `TradeRiskOverlay.ts`, `services/neo_desk/chart_views.py`.
- Add committed indicator templates and provision runtime files under `strategies/indicators/` through OpenAlgo's custom indicator loader.
- Tests: `test/neo_desk/test_chart_views.py`, frontend contract/overlay/control tests.

**Interfaces:**
- `chart_view(owner_id, instrument_id, interval) -> ChartView`: actual instrument identity, candles/quotes, source timestamps, preview signals and matching owned-trade annotations.
- `risk_overlay(instrument_id, owned_trade) -> Overlay[]`: option prices only for the option contract; index reference levels only for the index.
- `OwnedTradeControls` consumes Part 1's protection/close routes and current `trade_id`, filled quantity and mode.

- [ ] Read the fresh checkout's chart-indicator skill and contract. Write failing tests for CE versus PE selection, expiry/strike identity, live updates, timeframe persistence and wrong-instrument risk lines.
- [ ] Test manual premium SL/target, tick validation, no loosening of raised protection, fee-aware cash trail, pending-order locks and exact-quantity square-off confirmation.
- [ ] Pin `test_overlay_matches_option_scale`: a PE trade with option entry `50`, stop `45`, target `80` renders those prices only on its exact PE contract; the CE chart renders no owned PE bracket. Pin `test_manual_close_identity`: a stale `trade_id` request is rejected; a confirmed current partial 20-unit trade submits one `SELL` of `20`, never the configured full lot.
- [ ] Run tests, then integrate actual NIFTY/CE/PE charts and indicators: Donchian 20, EMA 200, visual FVG, RSI, confirmed support/resistance and potential liquidity zones. Use existing built-ins where parity holds and validate custom runtime descriptors where needed.
- [ ] Display signal previews separately from executed fills. Render effective SL/target/trailing state from the server, without implying that an index 6R target is an option-cash return.
- [ ] Run the upstream indicator validator and relevant chart/vector tests. Verify actual UI contract selection, indicator toggles, bracket changes, trail ratcheting and a simulated confirmed square-off.
- [ ] Commit source/tests/templates, without bundling runtime user indicator files into the main frontend build.

### Task 3: Native historical replay and annotated backtest charts

**Files:**
- Create: `services/neo_desk/replay.py`, `datasets.py`, `research_jobs.py`, `frontend/src/pages/NeoBacktests.tsx`, `frontend/src/components/neo-desk/ReplayChart.tsx`.
- Modify: `blueprints/neo_desk.py`, `frontend/src/App.tsx`, native tools/navigation registry.
- Tests: `test/neo_desk/test_replay.py`, `test_coverage.py`, `test_research_jobs.py`, frontend replay tests.

**Interfaces:**
- `run_replay(dataset: HistoricalDataset, request: ReplayRequest) -> ReplayReport`: shared preset signals/risk, initial cash, optional whole-lot reinvestment, fees/friction, observed fills, unresolved exposure and coverage.
- `ReplayRequest`: symbol/expiry/date range up to one year, preset, actual data identifier and lot-compounding choice; chart interval is independent of execution bars.
- `ReplayReport`: trade rows, equity, fees, win counts, drawdown, skipped/rejected setups, source metadata and gaps; no winning result is selected from incomplete P&L.

- [ ] Write failing parity tests using preserved actual-data fixtures and independent hand-checked entry/exit cases; verify no future-price selection, conservative ambiguous-bar exits and no forward-filled missing option prices.
- [ ] Add tests for the 15:15/15:29 schedule, ₹10,000 initial research cash, affordability by whole lots, fees reducing reinvestable cash and one-year date validation.
- [ ] Pin `test_compounding_whole_lots`: with cash `10000`, premium `50`, lot `65` and zero fixture costs, research sizing permits `3` whole lots and retains `250` cash; with `7000` cash it permits `2`, never a fractional lot. Pin `test_missing_option_exit_is_unresolved`: removing the only executable exit observation prevents a complete realized return rather than forward-filling one.
- [ ] Run failures, then adapt existing dataset/replay calculations to the shared native core. Historical replay must not call any live order route.
- [ ] Migrate dataset/report references with provenance intact and add native job/status/results pages. Retain partial-data status and unresolved positions rather than presenting a fabricated complete month.
- [ ] Run replay/backend/frontend tests. Complete at least one available real-data run end to end and compare its traded rows and totals independently; report unavailable expired-option coverage explicitly.
- [ ] Verify selected backtest trades on index and option charts with entry, exit, effective stop/target and trail segments. Commit source/tests.

### Task 4: Native market overview, operational feedback and full cutover validation

**Files:**
- Create: `services/neo_desk/overview.py`, `health.py`, `frontend/src/components/neo-desk/MarketOverview.tsx`, `ExecutionFeedback.tsx`.
- Modify: `frontend/src/pages/Dashboard.tsx`, native navigation and Part 1's state push views.
- Tests: `test/neo_desk/test_overview.py`, `test_health.py`, frontend dashboard/error tests; UI evidence under private runtime reports.

**Interfaces:**
- `market_overview(index_quote, confirmed_bars, constituent_quotes, now) -> Overview`: NIFTY change, RSI, trend context, advances/declines/unchanged, coverage and source timestamps.
- `execution_feedback(owner_id) -> HealthView`: activation, fresh-data/account blockers, setup waiting reason, last decision, current mode and immediately visible operational errors.
- Native state updates use SocketIO/events and do not make React a trading engine.

- [ ] Write failing cases for absent previous close, partial breadth, stale source data, uncertain RSI bars, failed broker requests and disconnected push updates.
- [ ] Pin `test_breadth_coverage`: two advances, one decline, one unchanged and 46 unavailable constituent quotes display counts `2/1/1`, coverage `4/50` and missing `46`; missing previous close contributes unavailable. Pin `test_account_error_visible`: failed funds refresh immediately exposes its error and age of the last known value instead of replacing it with a fabricated zero.
- [ ] Run failures, then add native overview and actionable feedback. Separate manual broker account P&L from strategy-owned paper/live results and distinguish estimates from actual charges.
- [ ] Run full native backend/frontend tests, type checking, production build and relevant repository verification/redaction tools. Report pre-existing failures by name.
- [ ] Test the actual application journey: authenticated login/session reuse → balances/books → selected option chart → preset/readiness → Analyzer start → simulated entry/fill → running P&L → manual protection/trail → owned exit → reports → replay. Confirm duplicate tabs/requests cannot duplicate financial intents.
- [ ] Save a verification report with screenshots, source commit, environment versions, test results, migration reconciliation, real-data coverage and any limitations. Do not claim real order execution or profitability from mocked execution.
- [ ] Check both applications are flat with no pending orders before cutover. Present the verified native URL, selected profile/mode, TOTP/session behavior and daily startup instructions. The user controls real Live activation.
- [ ] Commit source/tests and public validation documentation; retain private migration backups. Keep rollback available until the user adopts the new application.

## Completion criteria

Both parts must pass. The deliverable is the native application with preserved data, usable controls and end-to-end paper evidence, plus configured Live capability awaiting the user's arm action. A plan, a copied UI, a healthy broker connection or a synthetic profitable result alone is not completion.
