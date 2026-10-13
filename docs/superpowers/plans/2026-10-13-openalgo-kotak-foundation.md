# Native OpenAlgo Kotak Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution in this session, or superpowers:subagent-driven-development if the user selects that method. Steps use checkbox syntax for tracking.

**Goal:** Start a clean native OpenAlgo instance connected to Kotak and execute our four presets through its own paper/live infrastructure.

**Architecture:** Use a clean official upstream checkout, one native broker session and the existing strategy order/reconciliation paths. Add a small Neo Desk signal provider and native controls; shared risk rules remain in `services/risk/`. The existing terminal stays available while this instance is validated.

**Tech Stack:** Upstream pinned Python dependencies, Flask, native OpenAlgo strategy services, React and the repository's pinned Node dependencies.

**Spec:** [Approved migration design](../specs/2026-10-13-native-openalgo-kotak-migration-design.md).

## Global Constraints

- Base repository `https://github.com/marketcalls/openalgo`; observed commit `f2d28cd54f6484a329032ecd62af138c663e2e0f`.
- New app port 5001, WebSocket proxy 8767, ZeroMQ 5557; bind the application to 127.0.0.1. Recheck availability before starting.
- Source credentials from the current private terminal settings. Map UCC to `BROKER_API_KEY`, current Trade API token to `BROKER_API_SECRET`; keep mobile and MPIN server-side.
- Start in Analyzer mode with entries stopped. Real orders require the user's Live arm action; no real transaction is a development test.
- One active preset; ORB index trail selected. CE and PE are both bought as long options. Price Retest is Analyzer-only.
- 15m confirmed signals, 09:45–15:15 IST entry executions, 15:29 scheduled owned-position exit, 6R targets.
- ₹50 ±5 premium selection; one metadata-verified lot, expected 65; fresh trading-limit affordability including estimated entry costs.
- ₹500 planned trade-risk, ₹1,000 daily guard and three-entry guard; preserve preset-specific trailing rules and stricter option conditions.
- Do not reset the dirty current checkout, import unrelated local modifications, replay old setups or alter unrelated OpenAlgo features.
- Follow the fresh checkout's repository instructions. Shared risk core has no I/O; execution mode is pinned to owned exposure; exit claims are atomic; SQLite uses the native engine factory.

## Review Focus

- A bad TOTP must leave a valid broker session and an active engine intact; verify in Task 1.
- A PE setup must buy a put, rather than sell a call or create a short option; verify in Task 2.
- A stopped or crashed signal runner must not stop management of an already-owned position; verify in Task 3.
- Changing Analyzer mode must not send a Live-owned exit to the simulator; verify in Task 3.
- Two browser tabs or worker instances must not create duplicate entries/exits; verify in Tasks 2–4.

---

### Task 1: Clean instance and native Kotak authentication

**Files:**
- New isolated official checkout; private instance configuration and dependency environments.
- Modify: `blueprints/brlogin.py`, `frontend/src/pages/BrokerTOTP.tsx`, `blueprints/auth.py`.
- Create: `services/kotak_saved_login.py`, `scripts/setup_neo_instance.py`.
- Tests: `test/test_neo_saved_login.py`, `frontend/src/pages/BrokerTOTP.test.tsx`.

**Interfaces:**
- `read_saved_kotak_settings(source: Path) -> SavedKotakSettings`: private server-only values; no printable credential representation.
- `authenticate_saved_kotak(totp: str) -> tuple[str | None, str | None]`: stages verification with stored mobile/MPIN before replacing native authentication.
- `restore_verified_session(owner_id: str, source: Path, now: datetime) -> bool`: translates a still-valid old broker session into native storage, without authenticating a new browser.
- Native account/session storage remains authoritative. Bind an existing owner; where none exists, verified Kotak ownership establishes the single local owner using native user/session records.

- [ ] Fetch the verified official ref and create a managed clean checkout through the native worktree tool. Record its exact commit and empty source diff; never pull into the dirty terminal checkout.
- [ ] Read the new checkout's `CLAUDE.md`/applicable instructions. Install its locked dependencies and record baseline native backend/frontend tests before custom changes. If dependencies or baseline fail, diagnose and record the concrete issue before migration proceeds.
- [ ] Write failing authentication tests: only `totp` is submitted by React; absent/malformed code fails; rejected verification preserves the original session and Active state; a forged browser header cannot authenticate; foreign-origin and missing-CSRF requests fail.
- [ ] Write failing same-day restoration tests: valid source session restores to native storage; expired/revoked source session does not; a fresh browser is not granted access solely because broker credentials are cached.
- [ ] Pin `test_rejected_totp_preserves_active_session`: with native auth `session-A` and activation `Active`, failed staged verification leaves auth `session-A`, activation `Active` and creates zero order intents. Pin `test_totp_only_form`: the submitted body contains exactly the user-entered `totp`; mobile/MPIN controls and values are absent.
- [ ] Run `pytest test/test_neo_saved_login.py -q` and the focused BrokerTOTP frontend test; confirm the intended failures.
- [ ] Implement private configuration provisioning, fresh app encryption/session keys, the TOTP-only native broker callback and owner/session binding. Redact broker response bodies and credentials from errors/logs.
- [ ] Run the focused tests, native auth/session regression tests, frontend type checking and production build. Scan the tracked diff and built assets for credential values without printing those values.
- [ ] Start the separate instance and its explicitly configured services. Verify the native login/dashboard UI, read-only funds/books/master data/quotes and connection status. Reuse a valid session; require a fresh user-entered TOTP only when necessary.
- [ ] Commit only source, tests and public setup documentation; exclude `.env`, databases, sessions, logs and generated keys.

### Task 2: Pure preset signals and native entry routing

**Files:**
- Create: `services/neo_desk/__init__.py`, `types.py`, `presets.py`, `indicators.py`, `signals.py`, `selection.py`, `entries.py`; `test/neo_desk/conftest.py` holds independent confirmed-bar/quote fixtures.
- Modify: `services/strategy_module/signals.py` for a provider entry hook, reusing its native run and order machinery.
- Create: `database/neo_desk_db.py` using the native engine factory.
- Tests: `test/neo_desk/test_signals.py`, `test_selection.py`, `test_native_entries.py`.

**Interfaces:**
- `get_preset(profile: str) -> NeoPreset`: immutable validated rules for `orb_trail`, `orb_controls`, `donchian_controls`, `price_retest`.
- `evaluate_setup(bars: Sequence[Candle], preset: NeoPreset) -> Setup | None`: confirmed timestamp, `CE`/`PE`, index reference, ATR/structure and initial bracket; deterministic and no I/O.
- `select_contract(contracts, quotes, preset, available_limit, now) -> Selection`: verified identity, one-lot quantity, affordability and explicit rejection reason.
- `submit_setup(owner_id: str, setup: Setup, selection: Selection, mode: str) -> EntryResult`: atomically claims the signal/profile, then routes a **BUY** for either option type through native order dispatch.
- `NeoDeskConfig`: profile, activation, pinned run mode, expiry selection policy, `last_entry_minute=915`, `square_off_minute=929`; serialized monetary values use decimal strings.
- `types.py` owns `NeoPreset`, `Candle`, `Setup`, `Selection`, `EntryResult` and `NeoDeskConfig`. A `Setup` carries timezone-aware `candle_open`/`execute_at`, `direction`, `index_reference`, `initial_stop`, `target` and a stable deduplication key. A `Selection` carries contract identity, verified lot/tick, observed prices, costs and rejection status.

- [ ] Preserve independent golden fixtures from the old pure calculations. Write failing tests for both directions of all four profiles, missing opening range, uncertain/forming bars, incomplete warmup, recovered setups and Donchian trend rejection.
- [ ] Add final-close boundaries: 15m candle opened at 15:00 may emit at 15:15; 15:15 opening may not. Price Retest rejects Live mode. A stale quote, insufficient depth/limit, bad lot metadata or expired contract prevents selection.
- [ ] Add native execution tests asserting CE and PE intents both use `BUY`, correct contract IDs and one verified lot; duplicate signal/profile claims and two concurrent workers produce only one intent.
- [ ] Pin `test_final_confirmed_close`: the independent breakout fixture at 15:00 returns `execute_at=15:15 IST`; the same completed-breakout fixture at 15:15 returns `None`. Pin `test_put_setup_buys_put`: PE selection submits `action='BUY'`, selected PE symbol, quantity `65`, and creates no short-option intent. Pin `test_duplicate_signal_claim`: two simultaneous submissions leave exactly one native order record.
- [ ] Run the focused tests and observe failures, then extract the established calculations and implement native provider translation. Do not copy the standalone broker client or execution service.
- [ ] Keep one durable active-profile claim per owner. Use native strategy run/order ownership and reconciliation records, preserving the source mode and profile on the trade.
- [ ] Run the focused tests and existing strategy signal/order-dispatch regressions. Verify all eight direction/profile cases using deterministic data, with the Live broker boundary refusing any development submission.
- [ ] Commit this independently testable entry-provider change.

### Task 3: Shared stops, trailing protection and independent square-off

**Files:**
- Modify: `services/risk/models.py`, `position.py`, `aggregate.py`, `services/strategy_module/risk_adapter.py`, `tick_feed.py`, `scheduler.py`, `recovery.py`.
- Create: `services/neo_desk/risk_adapter.py`, `lifecycle.py`.
- Modify contract fixtures: `test/risk/vectors.json` and matching frontend risk-vector consumers when the common rule contract changes.
- Tests: `test/neo_desk/test_protection.py`, `test_ownership.py`, `test_recovery.py`.

**Interfaces:**
- Pure shared core receives index reference/direction, initial risk, option bid, fees, effective premium stop/target, peak/floor and guard settings; returns a decision and ratcheted state.
- `update_protection(owner_id: str, trade_id: str, changes: ProtectionChanges) -> ProtectionView`: validates identity, fresh premium bid, ticks, planned risk and existing protection before persisting; no immediate order is inferred.
- `request_owned_exit(owner_id: str, trade_id: str, reason: str, request_id: str) -> ExitResult`: rechecks and claims exact exposure under the native run lock; uses the originating execution mode.
- `evaluate_schedule(now: datetime, owned_state, config) -> ScheduleDecision`: normalizes IST and schedules exit at 15:29 independently of candle/runner events.

- [ ] Write failing parity tests for each existing index trail, option stop, net-cash trail and fee-aware guard; preserve each preset's current activation/distance.
- [ ] Add tests for no time exit at 15:15/15:28, exit at 15:29 in IST and UTC, and a runner stopped before 15:29 while the application still manages exposure.
- [ ] Add ownership tests for partial fills, cancelled-but-filled quantities, duplicate exits, rejected dispatch releasing its claim, late fills and mode changes during an open Live-origin trade.
- [ ] Pin `test_square_off_ist`: 15:28 produces no schedule exit; 15:29 produces an exit for quantity `65`, including UTC inputs `09:58`/`09:59`. Pin `test_live_origin_exit_after_analyzer_toggle`: a Live-origin 65-unit trade exits through the Live dispatcher after Analyzer becomes enabled, with zero Analyzer exit intents. Pin `test_refused_exit_remains_managed`: refusal retains ownership, releases the exit claim and permits a later protected retry.
- [ ] Run the focused tests, then extend the shared risk core only where necessary and implement state translation/persistence in the native adapters.
- [ ] Bind quote/risk evaluation and the independent schedule to the native application lifecycle. Restart restores ownership and stops new entries until reconciliation; unknown outcomes never create a replacement entry.
- [ ] Run shared risk vectors, native strategy recovery/order-event tests and the focused suite. Compare pure old/new decisions and explicit option/accounting units.
- [ ] Commit the protection/lifecycle change.

### Task 4: Native preset controls and hosted signal runner

**Files:**
- Create: `blueprints/neo_desk.py`, `services/neo_desk/service.py`, `views.py`.
- Create: `restx_api/neo_desk.py` for the runner's OpenAlgo API-key authenticated signal-provider request; do not weaken browser CSRF routes for a subprocess.
- Modify: `app.py`, `blueprints/react_app.py`, `frontend/src/pages/Scalping.tsx`.
- Create: `frontend/src/api/neoDesk.ts`, `frontend/src/components/scalping/NeoStrategyControls.tsx`, `NeoAutomationStatus.tsx`.
- Create committed runner template: `strategies/templates/neo_desk_runner.py`; provision a runtime copy through the native Python host.
- Tests: `test/neo_desk/test_routes.py`, `test_runner.py`, `frontend/src/components/scalping/NeoStrategyControls.test.tsx`.

**Interfaces:**
- Owner-authenticated `/neodesk/api/state`, `/settings`, `/execution/start`, `/execution/stop`, `/position/protection`, `/position/close`; POST mutations use native CSRF/idempotency protections.
- Runner-only `/api/v1/neodesk/signal` resolves the owner through the native API key and rechecks selected preset, originating mode, activation, signal freshness and entry guards before dispatch. It cannot arm Live or choose another owner's state.
- `NeoDeskService.state(owner_id) -> public dict`, `change_settings(owner_id, changes)`, `command(owner_id, action, request_id)`; no credentials in responses.
- Python runner uses OpenAlgo market-data services/API and sends only confirmed setup evaluations to the provider. Its process is tracked by the existing Python host; it does not own broker authentication or a separate order pipe.
- React receives source-stamped readiness, selected profile, activation, mode, effective bracket and owned quantity through native push events.

- [ ] Write failing route/UI tests for one active preset, flat-only switching, stopped exits staying managed, immediate command errors, single start request and research-only Live rejection.
- [ ] Write runner tests for closed bars only, bounded warmup recovery, no historical catch-up entries, duplicate runner prevention and exact schedule integration.
- [ ] Pin `test_stop_retains_exit_management`: stopping an Active run with an owned trade sets activation `Stopped` but a later stop breach still creates its exact owned exit. Pin `test_research_live_rejection_visible`: selecting Price Retest then requesting Live yields a visible refusal and zero broker intents. Pin `test_runner_cannot_arm_live`: a runner signal against unarmed Live state is refused without changing activation.
- [ ] Run the tests, then add native controls and register routes/lifecycle hooks using existing OpenAlgo components. Maintain its manual Scalping functionality alongside automation.
- [ ] Install the runner template into the native Python host, selected ORB index trail, Analyzer mode and entries stopped. Set paper allocation explicitly from available allowance.
- [ ] Run full native backend/frontend suites, type checking and production build. Test the actual UI through a simulated entry, fill, live valuation, stop/target/trail exit and flat return, with no real broker order.
- [ ] Save screenshots, assertions, runtime versions and limitations. Commit the source and tests. Continue with Part 2; the migration is not complete at this checkpoint.

## Handoff to Part 2

Part 2 consumes `NeoDeskService`, its public state/control contract, `NeoPreset`, `Setup`, shared risk decisions, originating-mode ownership and native verified broker session. Keep the old terminal and its source data available until Part 2's reports, charts and migration checks finish.
