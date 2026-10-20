# Combined Kotak Neo and Flattrade terminal

Status: proposed design for review; implementation has not started.
Date: 20 October 2026 (Asia/Kolkata).

## Agreed outcome

The user wants Kotak Neo and Flattrade in one terminal, retaining charts,
setup explanations, manual buying, SL/target management, tracking and journal.
The user explicitly selected **Choose Kotak or Flattrade per entry**.
An exit must always use the connection holding the position. Combining brokers
is not evidence of higher trading profitability or execution reliability.

## Approach and alternatives

Recommended: a single terminal UI and authenticated server-side coordinator,
backed by separate broker worker processes. Each worker retains its own existing
OpenAlgo broker authentication, symbol database and execution adapter. Keep the
existing Kotak instance on loopback port 5001; reserve a separately configured
loopback endpoint for Flattrade after checking availability. The central service
must bind to loopback and use authenticated, fixed-allowlist worker connections.

Alternative: change OpenAlgo's global auth/database model to support several
broker sessions in one process. This touches many existing single-broker caches,
feeds and execution paths; avoid it for the first release.

Alternative: switch credentials within one instance. Rejected: replacing the
active session breaks simultaneous monitoring and obscures position ownership.

## User flow

- Connection cards show each broker's session, quote freshness, available funds,
  execution readiness and specific blockers. Disconnected brokers stay visible.
- The entry ticket includes a clear Kotak Neo / Flattrade selector, retained
  across refreshes. Kotak is the initial selection for compatibility.
- Selecting a broker refreshes its contract metadata, executable quote, funds,
  charges estimate and order preview. Invalidate a preview after a broker change.
- Selecting a broker never sends an order. The existing manual entry action
  sends one intent to the selected broker after server-side validation.
- Chart prices carry their data source and timestamp. Preview and protection
  decisions require the execution broker's fresh quote; a different broker's
  chart quote is not a substitute for an executable quote.
- One open-trades area lists both brokers with broker badges, entry/quantity,
  current price, SL, target, gross P&L, estimated costs and net P&L. Position rows
  with stale data remain visible and explicitly unavailable where appropriate.
- Exit and stop controls resolve the saved owning connection. Changing the
  entry selector has no effect on any existing trade or its protection.
- Combined totals retain per-broker details. Realized costs and estimated
  liquidation costs are distinguishable; stale/missing account data makes a
  combined figure incomplete, never silently zero.

## Service boundaries

Existing frontend Kotak-only rendering and guarded routes cannot merely be
renamed: Gateway, account identity, feeds and submission reconciliation also
assume Kotak. Introduce an explicit broker-neutral terminal service boundary.

Define worker operations for connection status, contract metadata, quotes,
history, funds, books, preview, submit, reconcile, cancel, amend protection and
reduce-only/position-reducing exit. Each response carries connection ID, broker,
account fingerprint, capture time and capability flags. Worker endpoints must
not expose a general proxy or accept arbitrary URLs/credentials from requests.

The coordinator authenticates the terminal user, authorizes the chosen connection,
validates CSRF for mutations, reserves daily entry capacity and persists intent
before dispatch. Worker service credentials are stored locally with restrictive
permissions, never in the browser, logs, source or Git. Browser requests cannot
select an arbitrary account by editing an ID. Sessions and secrets remain isolated
from market research and model input.

## Durable ownership and execution

Namespace every trade, order and fill by broker + account + live/paper mode;
order IDs and trade IDs can collide between brokers. Store connection ownership,
strategy/version, risk policy, intent UUID, correlation tag, broker order IDs,
fills and accepted protection in the existing database/migrations.

State machine: reserved -> submitting -> accepted/pending/unknown/rejected ->
partially filled/filled -> managing -> exiting -> closed. Unknown submissions
retain reservation and block duplicate retry until reconciled by durable evidence.
Never route a timeout, rejection, stop or exit to the other broker automatically.
A worker must acknowledge the exact account identity expected by the coordinator.

Partial fills protect only actual filled quantity. Stop/target cancellation and
replacement retain the existing ownership and no-loosening rules. A protective
exit failure is prominent and does not label the position closed. Existing broker
stops, if accepted, remain distinct from server-monitored target instructions.

On restart, restore intents/reservations/trade policy before allowing entries;
reconcile each account independently. One unavailable worker cannot stop the
other account's existing exit/protection management. Missing combined daily data
blocks new entries under the combined cap while exits remain available.

## Shared discipline and costs

Keep live and paper ledgers separate. Defaults follow the user's existing policy:
three filled entry orders per IST trading day, daily loss threshold INR 1,000,
profit milestone INR 2,000 and configurable full-screen reminders every two
minutes. The profit milestone advises stopping but permits further entries while
below three; the loss/trade cap blocks entries. Exits stay available.

Per-trade INR 1,000 planned cash risk is a separate policy from the daily loss
limit. Neither is a guaranteed execution cap. Two simultaneous tabs must not both
reserve the final entry slot. Reject/cancel releases only definitively unfilled
reservations. Partial fills consume one entry; further fills of that same order
do not consume another. Distinct filled add-on orders count as separate entries,
matching current order-based discipline. Observe broker-app trades too; warn and
update totals if external activity exceeds the limit (the terminal cannot prevent
orders entered in a broker app).

Use current per-broker fee settings and contract metadata. Zero brokerage does
not remove statutory charges. Do not claim exact live net P&L before fee/fill
reconciliation. Preserve the existing loss/profit milestone latch behavior.

## Flattrade connection and capability checks

Flattrade adapter exists, but production connection requires the correct client
ID, API key, secret, registered redirect URL, daily OAuth login and registered
static outbound IP. No usable connection is established by possessing the secret
alone. Configure missing values through a local masked setup flow. Never commit
or repeat the chat-supplied secret. New credentials/OTP entry remains with the user.

Validate current API V2 endpoints and WebSocket subscription handling against
https://pi.flattrade.in/docs. Flattrade documents limit/SL-limit orders only and
no cover/bracket orders under V2. A stop trigger is not guaranteed to fill a
stop-limit order; expose non-fill/escalation state. Do not map unsupported order
types silently or invent a protected price without validating broker constraints.

## Validation and rollout

1. Adapter contract tests for both brokers, normalized errors, metadata, stale
   quotes, rejection vs unknown outcome and V2 unsupported order types.
2. Isolation tests for colliding IDs, account changes, forged connection IDs,
   broker selector changes, cross-account exits and credential redaction.
3. Shared-ledger tests for simultaneous last-slot reservations, partial fills,
   duplicates, external trades, loss latch, profit continuation and IST reset.
4. Restart and outage tests with unknown submission, accepted stop, partial exit,
   unavailable worker and no duplicate orders or broadened risk.
5. UI tests for disconnected states, broker selection, preview invalidation,
   source labels and combined totals. Repair or clearly isolate the five existing
   KotakAssistant screen failures before claiming the new UI passes.
6. Back up each instance, deploy the coordinator and Flattrade worker separately,
   retain Kotak compatibility, verify real read-only connectivity first. Use fake
   adapters or paper mode for order lifecycle verification; no live test trades.
7. Rollback disables new combined entries, preserves ledgers and continues
   managing existing positions on their original broker.

## Acceptance and remaining dependencies

Accepted when both accounts can appear in one UI; the ticket submits only to the
manually selected connection; positions always exit on their owning connection;
shared limits cannot be bypassed by switching brokers; restart recovery retains
ownership; missing/stale data is explicit; no secrets enter client payloads/logs.

Flattrade credential completion, daily login, static IP registration and live
read-only checks remain external prerequisites. Automatic broker selection,
simultaneous duplicate orders, cross-broker position transfer and arbitrage are
outside this version. A performance comparison requires measured observations.
