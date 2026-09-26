# Trading Safety Remediation Implementation Plan

> **For agentic workers:** Use test driven development for each change. The current checkout contains the user's uncommitted work and runs the visible app; preserve it and do not commit, switch branches, enable live mode, or place broker orders.

**Goal:** Close the avoidable loss paths identified in the 25 September review while retaining sandbox execution and explicit live authorization.

**Architecture:** Keep the Strategy Module as the only order owner. Separate definitive broker rejection from uncertain delivery, apply one portfolio policy to both execution modes using mode-specific account facts, reject stale or thin market evidence, and persist critical notification delivery state. Any live setup without verifiable broker-side protection must fail closed.

**Tech Stack:** Existing Flask, SQLAlchemy, pytest, Flow, WebSocket proxy, and React implementation. No new broker or market-data source.

**Spec:** `docs/reviews/2026-09-25-trading-risk-review.md`; the user approved proceeding after receiving that review. The existing SENSEX/MCX design in `docs/superpowers/specs/2026-09-25-sensex-mcx-intraday-strategy-expansion-design.md` supplies instrument and session constraints.

## Global constraints

- No order is placed, modified, or cancelled during verification against the operator account.
- Keep the twelve installed strategies live-disabled and workflows sandbox until a distinct live go/no-go decision.
- No guessed fills, prices, timestamps, funds, contracts, or broker acknowledgement.
- Preserve operator edits already present in this dirty checkout.
- Entries fail closed when authoritative state is missing. Exits remain available, but an uncertain exit cannot be retried until reconciled.
- Apply the same risk policy to sandbox and live using separate account facts and reservations.
- New I/O paths must respect the eventlet and resource-lifecycle rules in `CLAUDE.md`.

## Review focus

- Broker accepts an order but the HTTP reply is lost: no second entry/exit is dispatched without reconciliation.
- Stop budget is exhausted before a workflow trigger: no fresh entry and exits remain possible.
- A completed candle belongs to yesterday or an earlier session: no current signal.
- Option quote is stale, crossed, too wide, or lacks executable depth: no admission.
- Process restarts after a partial fill: no assumption that an unprotected or unknown position is flat.

## Task 1: Resolve uncertain broker order outcomes

**Files:** `services/strategy_module/order_dispatch.py`, `engine.py`, `recovery.py`, `order_events.py`, their focused tests and the audit schema only if necessary.

**Interfaces:** The dispatch result must distinguish accepted, definitively rejected, and unknown. Engine intent state and recovery consume that distinction. A broker order ID is evidence only when confirmed by a broker response or authoritative orderbook.

- [ ] Add a failing test where placement raises a timeout after an attempted live call; assert the order outcome is unknown and the intent remains pending.
- [ ] Add failing entry and exit tests proving the engine does not free exposure/reservations or a covering-exit claim while the outcome is unknown.
- [ ] Add restart/recovery tests proving unknown orders are reconciled against broker orders/positions before any retry; absent a reliable matching key, require operator intervention and hold entries.
- [ ] Implement the smallest explicit unknown state and durable evidence needed to satisfy those tests. Preserve definitive broker rejections and partial-fill handling.
- [ ] Run the focused dispatch, engine, order-event and recovery suites; inspect the diff for lost-ACK regressions.

## Task 2: Enforce portfolio admission in sandbox and live

**Files:** `services/strategy_module/portfolio_governor.py`, `broker/kotak/api/data.py` quote normalization, supporting sandbox account access if required, focused governor and engine tests.

**Interfaces:** `acquire_entry_admission` returns the same policy decision/lease for both modes; account facts remain broker- and mode-scoped.

- [ ] Add failing tests where simulated insufficient cash, position cap, combined risk, 20% buffer, and 4% daily lock reject sandbox entries just as live entries do.
- [ ] Use isolated sandbox funds and positions, but fetch tradable price evidence from the configured broker's read-only quote path; a missing leg-embedded `sandbox_price` must not disable every valid paper setup or permit an invented fill.
- [ ] Add a failing concurrency test for simultaneous sandbox entries competing for the final permitted slot.
- [ ] Add failing tests for a prior-day wide-spread option quote, zero depth, absent broker timestamp, and inconsistent bid/ask; all reject live admission.
- [ ] Preserve Kotak's authoritative `lstup_time` and best-level depth quantity from its quote response instead of stamping retrieval time as trade time.
- [ ] Add tests that profitable sandbox runs do not mask live losses and that negative normal leg-stop outcomes count toward cooldown.
- [ ] Treat history-query failure or truncation as unavailable P&L, not an empty winning session (`list_user_runs` currently returns `[]` on database errors and caps results at 500).
- [ ] Implement mode-specific fact collection, durable reservations, fresh quote validation and scoped realized/unrealized session P&L without blocking exits.
- [ ] Replace the single NSE entry window with the existing exchange calendar's venue-aware cutoff; test evening MCX and an exceptional close.
- [ ] Run governor, engine, signal and migration suites.

## Task 3: Block entries after spent daily loss budget

**Files:** `services/strategy_module/engine.py`, `signals.py`, related database functions and tests.

**Interfaces:** A session-scoped realized-plus-unrealized admission function executes before every new batch or signal leg, and is persisted across process restarts.

- [ ] Add failing batch and existing-signal-run tests for a prior ₹1,000 loss followed by another trigger, including restart and a simultaneous trigger.
- [ ] Apply Task 1's durable unknown-live-order guard before every signal entry as well as before batch starts; an unresolved broker write blocks further entry until reconciled.
- [ ] Assert every exit path stays callable after the lock.
- [ ] Enforce the per-strategy session budget before order dispatch and record an auditable rejection; fail closed when P&L cannot be reconciled.
- [ ] Keep the mark-to-market stop in the tick path as a second line of defence; run engine/signal/scheduler suites.

## Task 4: Require current, coherent market data

**Files:** `services/flow_executor_service.py`, `services/indicator_service.py`, `services/strategy_module/tick_feed.py`, `services/websocket_client.py`, starter workflow tests.

- [ ] Add a failing Flow test where the latest closed 5-minute bar is from the prior session; the signal must not authorize a run.
- [ ] Add tests for 5/15-minute alignment, sparse data, and one trigger per completed bar.
- [ ] Configure the strategy WebSocket client from the same endpoint as the proxy; test a nondefault 8766 port and REST fallback/stale transitions.
- [ ] Make quote timestamp validation use the broker's market timestamp instead of the local time of receipt.
- [ ] Run Flow, indicator, tick-feed and WebSocket suites.

## Task 5: Broker-side protection and bounded execution

**Files:** broker capability layer, `services/strategy_module/order_dispatch.py`, `engine.py`, `order_events.py`, recovery, strategy config validation, related tests.

- [ ] Determine from the actual Kotak adapter which protective stop types and acknowledgements are supported; document unsupported combinations explicitly.
- [ ] Add failing tests: post-fill stop placement/size, partial fill, stop rejection, process restart, local-exit/stop race, cancel/reconcile, and unsupported broker capability.
- [ ] Implement broker-side protection only where the adapter can verify it. Block live entry for instruments without a supported protective path; never claim that the stop limits realized loss to the trigger value.
- [ ] Bound entry price with a marketable limit cap based on a fresh ask; reconcile unfilled balances and reject excessive spread/slippage.
- [ ] Run focused execution/recovery suites and a sandbox broker-adapter contract test.

## Task 6: Reliable critical alerts and status

**Files:** `services/strategy_module/lifecycle_events.py`, `services/whatsapp_alert_service.py`, a durable outbox in the existing database layer, focused tests and UI status surface.

- [ ] Add a failing test for a disconnected WhatsApp bot: retain a critical alert with its original event timestamp and mark it undelivered.
- [ ] Add restart, deduplication, bounded retry, expiry, and failure-display tests; notifications must never block exits.
- [ ] Implement a bounded durable outbox and delivery worker using existing eventlet-safe facilities; display failed/late status in the UI.
- [ ] Run lifecycle, WhatsApp, database and frontend tests.

## Task 7: Integrated acceptance

- [ ] Run the complete backend and frontend suites, relevant static checks, and the repository resource audit on touched I/O paths.
- [ ] Verify the authenticated UI displays all twelve sandbox workflows and no strategy has live execution enabled.
- [ ] Verify only sandbox/test execution paths with mocked broker orders. Check restart and stale-data simulations.
- [ ] Update the review with an evidence table for each resolved finding and explicitly list anything still open.
- [ ] Do not call the platform live-ready unless every blocking gate has actual verification evidence.
