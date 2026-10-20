# Combined Kotak Neo and Flattrade Terminal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operate Kotak Neo and Flattrade from one terminal with manual broker selection per entry, durable ownership and shared discipline.

**Architecture:** Keep broker credentials, symbol databases and execution in isolated OpenAlgo worker processes. Add an authenticated coordinator to the existing Kotak-hosted terminal, a fixed-connection worker protocol and a durable shared ledger. Existing Kotak trades remain on their original account and controller; rollout is feature-flagged.

**Tech Stack:** Flask, SQLAlchemy/SQLite WAL, existing httpx broker adapters, React/TypeScript, TanStack Query, pytest and Vitest; no new product dependency.

**Spec:** `docs/superpowers/specs/2026-10-20-kotak-flattrade-terminal-design.md` (approved by user).

## Global Constraints

- Choose Kotak or Flattrade per entry; never automatically reroute an entry or an exit.
- All option entries are purchases. Existing trade ownership and no-loosening protection rules remain authoritative.
- Separate broker + account + live/paper mode for every identity, cache, operation and fill.
- Live and paper never share ledgers. Shared defaults: three filled entry orders/day, INR 1,000 daily loss, INR 2,000 profit advisory, configurable 120-second reminder; profit advisory permits entries below three, loss/trade cap does not. Exits remain available.
- Planned INR 1,000 per-trade cash risk is separate from the daily limit and is not a guaranteed execution cap.
- Bind services to loopback; configured workers are allowlisted, authenticated and account-checked. Do not expose arbitrary proxy endpoints or browser-visible service secrets.
- Flattrade credentials/static IP/daily login are external prerequisites. Do not submit live test trades or change broker account security settings.
- Existing five KotakAssistant screen-test failures are known baseline failures; resolve before claiming combined UI validation passes.
- Feature disabled is the default until migration/read-only checks pass. Rollback blocks combined entries and preserves original protection management.

## Review Focus

1. Same symbol/order/fill IDs on both accounts must remain distinct (Tasks 1, 3, 4).
2. A crash between dispatch and broker acknowledgement must retain an unknown reservation, not resend (Tasks 3, 4).
3. A broker selector change during preview/submit must never alter an in-flight intent or an existing exit (Tasks 4, 6).
4. An unavailable broker or a wrong account fingerprint must not become zero P&L or permit new entries against incomplete shared limits (Tasks 2, 5).
5. Partial fills, external orders and the IST day boundary must not double-count or silently reset a loss latch (Tasks 3, 5).

## File and interface map

Create `services/combined_terminal/`:
- `contracts.py`: immutable connection/command/result envelopes and validation.
- `registry.py`: private fixed-worker configuration and owner authorization.
- `transport.py`: signed fixed-origin HTTP requests and response validation.
- `ledger.py`: transactions, intent state and shared daily reservations.
- `worker.py`: allowlisted worker operations and broker-local controller facade.
- `flattrade_gateway.py`: Flattrade implementation of existing Gateway method contract.
- `coordinator.py`: entry orchestration and immutable owning-broker mutations.
- `aggregate.py`: normalized read-only account totals, completeness and discipline.
- `runtime.py`: restart reconciliation and bounded polling.
Create `database/combined_terminal_db.py` and `upgrade/migrate_combined_terminal.py` for additive tables.
Create `blueprints/combined_terminal.py` (user-authenticated `/combined-terminal/api`) and `blueprints/broker_worker.py` (service-authenticated `/broker-worker/api`).
Create `scripts/combined_terminal/supervise.py` and an operations guide. Modify `app.py`, `upgrade/migrate_all.py`, `.sample.env` only to wire disabled-by-default services.
Create frontend `api/combinedTerminal.ts`, `components/combined-terminal/{CombinedTerminal,BrokerConnections,BrokerTicket,CombinedPositions,CombinedSummary}.tsx`; mount via Dashboard only when enabled. Extract reusable chart/preview presentation from existing Kotak components without rewriting the legacy route.

Contract types in Task 1 are authoritative for all tasks:
- `ConnectionRef(id: str, owner: str, broker: Literal['kotak','flattrade'], account: str, mode: Literal['live','analyze'])` contains no raw client ID/token.
- `WorkerCommand(operation_id: str, connection: ConnectionRef, action: str, payload: dict, created_at: float)`.
- `WorkerResult(operation_id: str, connection: ConnectionRef, state: str, data: dict, captured_at: float, error: str | None)`; mutation state is accepted/rejected/unknown, never infer rejection from timeout.
- `AccountSnapshot(connection: ConnectionRef, captured_at: float, books_complete: bool, quotes_fresh: bool, orders: list, fills: list, positions: list, funds: dict | None, realized_net: float | None, estimated_open_net: float | None, error: str | None)`.
- `EntryIntent(operation_id: str, connection: ConnectionRef, preview_id: str, payload_hash: str, state: str)`; preview binds account, symbol, exchange, quantity, entry, SL, target, risk policy and expiry time.
- Identity helper `scoped_id(connection: ConnectionRef, kind: str, broker_id: str) -> str` uses a canonical encoded tuple, not ambiguous delimiter concatenation.

### Task 1: Protocol, configuration and authorization

**Files:** contracts.py, registry.py, transport.py; `test/combined_terminal/test_protocol.py`.
**Interfaces:** `Registry.connection(user: str, connection_id: str) -> ConnectionRef`; `Transport.call(command: WorkerCommand) -> WorkerResult`; types above.

- [ ] Write failing tests `test_colliding_broker_ids_remain_distinct`, `test_connection_requires_owner`, `test_wrong_account_response_rejected`, `test_private_fields_not_serialized`, `test_remote_or_redirected_worker_refused`. Assert identical broker IDs across Kotak/Flattrade produce unequal scoped IDs; wrong owner/account is rejected before submission; serialized client status contains no token/secret/base URL.
- [ ] Run `LOG_FORMAT='%(levelname)s %(message)s' .venv/bin/pytest test/combined_terminal/test_protocol.py -q`; verify failures identify missing protocol behavior.
- [ ] Implement strict envelope validation, supported operations and private registry. Transport accepts only configured loopback origins, does not follow redirects, sets bounded timeouts and validates exact account/operation IDs. Authenticate raw request body with per-worker HMAC-SHA256, timestamp and nonce; compare signatures in constant time. Reject requests older than 30 seconds and nonce replays; persisted operation ID remains the idempotency key across valid retries.
- [ ] Add `test_signature_replay_and_tamper_refused` with unchanged dispatch count after stale/replayed/tampered requests. Rerun protocol tests; commit only Task 1 files when passing.

### Task 2: Broker-local worker and Flattrade gateway

**Files:** worker.py, flattrade_gateway.py, broker_worker blueprint; modify existing Kotak Gateway only through a facade. Tests: `test/combined_terminal/test_worker.py`, `test_flattrade_gateway.py`.
**Interfaces:** `Worker.execute(command: WorkerCommand) -> WorkerResult`; `Worker.snapshot(connection: ConnectionRef) -> AccountSnapshot`. `FlattradeGateway` supplies the existing Coordinator's user/mode/account/scope attributes plus metadata, session_open, other_controller, cached, watch, quote, books, stop_limit, submit, cancel, history, history_range and ladder methods with the current Kotak Gateway signatures.

- [ ] Write failing adapter tests for accepted/rejected/unknown submission, malformed books, stale quote, unsupported V2 order types, tick/lot/freeze metadata, SL-limit non-fill and mismatched login account. Assert no mutation on metadata/auth/quote failure and no translation to unsupported market/SL-market/bracket orders.
- [ ] Run the two new pytest files; verify failures, then implement worker dispatch allowlist, local identity check and Flattrade normalization using existing broker adapter/mapping/rate limiters. Verify current V2 API/WebSocket docs before choosing endpoints. Normalize errors without returning raw credential-bearing payloads. Preserve legacy Kotak scope and controller unchanged in its facade.
- [ ] Implement broker-local fee configuration and capability checks. A protective SL-limit must use validated tick/band/protection constraints; unavailable constraints refuse preview. Preserve explicit unfilled-stop state and existing management escalation, never claim guaranteed stop execution.
- [ ] Rerun worker/adapter tests plus `test/test_kotak_assistant_execution.py`, `test/test_kotak_assistant_recovery.py`, `test/test_flattrade_protocol.py`, `test/test_flattrade_collateral.py`; commit on pass. Use fake broker HTTP/feed responses only.

### Task 3: Shared durable ledger and entry reservation

**Files:** ledger.py, database/combined_terminal_db.py, upgrade migration, migrate_all wiring; tests `test/combined_terminal/test_ledger.py`.
**Interfaces:** `Ledger.reserve(user: str, intent: EntryIntent, snapshot_ids: dict[str,str], now: float) -> EntryIntent`; `Ledger.record_result(operation_id: str, result: WorkerResult) -> EntryIntent`; `Ledger.observe(snapshot: AccountSnapshot, now: float) -> None`; `Ledger.intent(user: str, operation_id: str) -> EntryIntent`.

- [ ] Write failing tests for two database connections racing for the third entry: exactly one reservation succeeds; count 2 filled + 1 reserved blocks another. Repeated operation ID returns its existing intent only when payload/account hashes match; mismatch raises conflict.
- [ ] Run ledger tests; implement additive schema for connections, intents, observations, namespaced fills/orders and day checkpoints. Use one transaction for daily capacity check + reservation. Unknown/submitting/partially-filled intents retain capacity; definitive zero-fill rejection/cancellation releases it; any fill consumes one entry for the order.
- [ ] Add tests for restart after dispatch, partial fill then cancel, colliding IDs, changed fills, external add-on orders, IST midnight and latched daily loss. Preserve previous day intents through rollover; assign fills by IST fill time, not order creation time. Import existing trades as references to original owner/controller, never duplicate them or relabel paper/live.
- [ ] Run `pytest test/combined_terminal/test_ledger.py -q` with standard LOG_FORMAT and migration against temporary fresh/existing SQLite databases; assert old tables unchanged and migration idempotent; commit on pass.

### Task 4: Preview-bound manual entry and owning-broker exit

**Files:** coordinator.py, combined_terminal blueprint, app wiring, Kotak assistant entry compatibility guard; tests `test/combined_terminal/test_routing.py`.
**Interfaces:** `TerminalCoordinator.preview(user: str, connection_id: str, ticket: dict) -> dict`; `enter(user: str, preview_id: str, operation_id: str) -> EntryIntent`; `mutate_trade(user: str, trade_id: str, action: str, payload: dict) -> WorkerResult`.

- [ ] Write failing tests asserting selector changes invalidate previews, wrong account cannot submit, retry of unknown entry does not dispatch again, and an exit always resolves saved owner even if payload supplies another broker. Missing/stale combined books prevents entry but not authorized position-reducing exit.
- [ ] Run routing tests; implement server-authorized connection resolution and immutable preview snapshot; preview TTL 10 seconds, recheck quote/funds/metadata/costs/risk at dispatch. Reserve before network I/O; persist returned broker IDs/results. No blind retry on timeout. Idempotent worker dispatch must persist intent before touching broker adapter.
- [ ] Wire cookie auth/CSRF on browser mutation endpoints and signed auth on worker endpoints. When combined mode is enabled, legacy Kotak terminal entry endpoint delegates to the shared gate (or explicitly refuses with combined-ticket link), so the old ticket cannot bypass shared limits. Preserve legacy exit/reconcile APIs and owning trade IDs.
- [ ] Run routing tests plus existing route/execution/recovery tests. Assert GET requests never call submit/adopt/exit; unauthorized users cannot query other account data. Commit on pass.

### Task 5: Combined monitoring, discipline and restart recovery

**Files:** aggregate.py, runtime.py; tests `test/combined_terminal/test_aggregate.py`, `test_recovery.py`.
**Interfaces:** `aggregate(snapshots: list[AccountSnapshot], day: dict, now: float) -> dict`; `Runtime.reconcile_once(now: float) -> None`; `Runtime.snapshot(user: str, mode: str) -> dict`.

- [ ] Write failing tests for missing worker, stale books, unavailable funds, duplicate fills and broker-identical IDs; assert combined realized/estimated open net separately become unavailable when incomplete, each with reason and capture time. Never sum live and analyze.
- [ ] Implement bounded per-worker polling, cache/deduplication and persistent snapshot observations. Freshness thresholds: connection/quote 5 seconds for entry, books 10 seconds; missing capture time fails closed. Display partial totals explicitly but do not use them for entry eligibility. Poll UI once per second without overlapping requests.
- [ ] Add restart tests killing a fake worker/coordinator after submitting, before acknowledgement and during partial exit. Verify no duplicate entry, accepted stop never loosens, exits on healthy account remain available, original worker continues management without browser/coordinator, and reconnect verifies actual account before resuming management.
- [ ] Pin shared defaults 3/1000/2000/120 and profit continuation below three; configurable reminders, external over-limit warnings and latched loss survive restart. Run aggregate/recovery plus existing discipline/profit/cash-policy tests; commit on pass.

### Task 6: Shared UI with manual broker ticket

**Files:** frontend API and five components listed above; Dashboard mount and reusable Kotak presentation extraction. Tests adjacent to components and `api/combinedTerminal.test.ts`.
**Interfaces:** `combinedTerminalApi.snapshot(mode)`, `.preview(connectionId,ticket)`, `.enter(previewId,operationId)`, `.mutateTrade(tradeId,action,payload)` call Task 4 routes. React snapshot types mirror AccountSnapshot and the Task 5 combined view; no private registry properties.

- [ ] Reproduce and resolve the five existing `KotakAssistant.test.tsx` failures without weakening assertions. Write failing tests for Kotak default/manual Flattrade selection, disconnected card, selector change during pending preview and stale/missing selected-broker quote. Assert refresh preserves edits and cached response for previous broker cannot populate current ticket.
- [ ] Implement compact connection cards, shared charts/setup presentation, broker-bound preview and explicit manual buy button. Include broker/source/time labels and INR risk/cost/net estimates. Leave unavailable broker controls explained and disabled. Data from another broker cannot make the selected broker execution-ready.
- [ ] Implement combined position rows with owning-broker badges and immutable exit/SL routing, separate realized/estimated net totals, existing reminders and selected-broker funds. Add tests that changing ticket broker never changes position actions; polling never places orders; retry after unknown shows reconciliation rather than fresh Buy.
- [ ] Run Node 24 Vitest on combined components and all Kotak assistant components plus fee/currency tests; require zero failures. Run production build. Commit source and matching regenerated dist together on pass.

### Task 7: Isolated launcher, private setup and read-only activation

**Files:** scripts/combined_terminal/supervise.py, `.sample.env`, `docs/userguide/combined-terminal.md`, feature flags in app/runtime; tests `test/combined_terminal/test_launcher.py`.
**Interfaces:** worker launch config contains worker role, unique DB paths/ports/feed ports, configured broker/account and private HMAC file path. `COMBINED_TERMINAL_ENABLED=false` default; broker workers require `COMBINED_WORKER_ENABLED=true` and configured expected account.

- [ ] Write launcher tests for duplicate port, shared DB refusal, invalid role, missing credentials, unexpected account and stopped child recovery. Assert no credential values in errors/argv/logs, only private local file references. Never clone another account's production auth database.
- [ ] Implement supervision using existing Kotak macOS launcher pattern (no Gunicorn preload or HUP). Reserve Flattrade HTTP 5002 only after checking availability; assign distinct WS/ZMQ ports and reject collisions. Retain existing Kotak 5001 process/config.
- [ ] Document masked user-managed setup of Flattrade client ID/API key/secret, exact registered callback and static IP, then daily OAuth login. Verify both accounts read-only and compatibility before enabling combined entries. Without credentials show setup-required and test with fake worker; never claim real connectivity.
- [ ] Run launcher tests, backend regression selection, UI tests/build and browser verification of disconnected/connected fake states. Back up existing files/database before deployment; retain rollback path that stops new entries and leaves broker-local protection running. Commit only source/docs/build, no secrets or runtime data.

### Task 8: End-to-end evidence and final review

**Files:** `test/combined_terminal/test_end_to_end.py`; local validation results under ignored `workspace/validation/combined-terminal/`.
**Interfaces:** no new product interface; drive Tasks 1–7 through real Flask routes and two fake HTTP workers backed by temporary SQLite databases.

- [ ] Write integration tests for manual Kotak entry then Flattrade entry, third-slot contention, unknown submission, original-owner exit, external trade import, outage/reconnect and restart. Assert each expected broker mutation occurs once and none on the other broker; snapshots/journal remain namespaced.
- [ ] Run all combined backend/UI tests, selected existing execution/recovery/discipline/Flattrade regressions, build and `git diff --check`. Record exact counts and real connection blockers separately from fake-test results.
- [ ] Review whole branch against approved spec; verify no change to credentials/active live orders, no live test fills, no service secrets in staged files. Use a fresh reviewer only if the user selects/delegates review; otherwise perform self-review and disclose its scope.
- [ ] Present interface screenshot, tests, migration/rollback status and remaining real-login/static-IP prerequisites. Commit verified changes. Push this implementation only under the user's authorized destination/scope; do not force-push or create a PR without request.

## Plan self-review

- Spec coverage: worker isolation/auth (1–2,7), durable ownership/recovery (3–5), UI/fees/shared limits (2–6), connection and V2 constraints (2,7), rollback/verification (7–8).
- All five review-focus cases have owning tests above. Same-broker ID duplication and cross-broker ID collision are distinct cases.
- Signatures use ConnectionRef/WorkerCommand/WorkerResult/AccountSnapshot consistently. Internal broker APIs remain worker-local; no ambiguous global credential switching.
- Real Flattrade login and static IP cannot be completed using the supplied secret alone. This is a deployment prerequisite, not grounds to fabricate a successful integration or use live test orders.
- Planned execution approach: native implementation in this session is recommended for the closely coupled interfaces; user review/selection is pending. No product code changed while writing this plan.
