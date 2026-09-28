# Automation review screen implementation plan

> Execute inline with test-driven development and an independent final review.

**Goal:** Let the operator tell whether managed automation is checking signals,
why it is waiting, and whether a requested emergency stop has completed.

**Architecture:** Add owner-scoped read APIs over durable strategy, Flow execution,
event and order records plus the running scheduler. A React screen polls every
three seconds. Emergency stop first blocks all selected automation admissions,
then uses the existing disable-and-close service and reports each outcome.

**Design:** `/strategy/monitor`, linked prominently from Strategies. A restrained
operations layout uses an activity rail, strategy table, expandable records,
explicit Sandbox/Live labels, IST timestamps and a red emergency-stop action.
Old early-entry failures are explained as waiting without rewriting audit logs.
The screen never starts automation or places an entry order.

**Constraints:** Preserve the seven sandbox activations and nine uninstalled
templates during development and verification. No production kill-switch tests.
No new dependencies. Authenticate every route, scope every record to its owner,
redact credentials, paginate retained logs, and report unavailable/stale data.
The stop scope is saved managed strategies, not unrelated broker positions.
Pending exits and failed reconciliation must never be shown as confirmed flat.

## Tasks

- [x] Backend monitor and log APIs: `services/strategy_module/monitor.py`,
  blueprint routes and isolated tests. Include current automation vs run status,
  scheduler running/paused, next check, last execution, missing/stale checks,
  normal waiting windows, unknown linkage and paginated execution/event/order
  streams. Tests cover ownership, malformed cursors, source failures, redaction,
  stale schedules, source timezone and early-session waiting.
- [x] Emergency stop: first persist `closing` for all requested owned strategies
  under admission leases, then call `disable_and_close` per strategy even after
  an individual error. Validate explicit confirmation and all IDs before mutation.
  Test all admissions blocked before the first close, partial failure, pending
  fills, ownership, confirmation and an empty account. Reuse individual disable.
- [x] Frontend screen/API types and route. Show fresh/stale connection evidence,
  filter strategy/mode/status, inspect complete paginated retained records,
  pause log auto-refresh, manual refresh, individual stop and confirmed emergency
  stop with per-strategy outcomes. Test stale data, pagination, cancellation and
  partial/pending results; TypeScript/build and isolated browser verification.
- [ ] Independent review, integration tests, build, safe publication and verify
  served assets/API with existing account automation settings unchanged.

## Progress

Baseline is main `d448dfa6b`; isolated branch `codex/automation-review-screen`.
Existing single-strategy disable-and-close includes durable closing admission,
broker reconciliation, Flow teardown and pending-exit handling. The existing
webhook-only kill route is not used as the new automation-wide stop primitive.

User added detailed signal diagnostics and a review of strategy/rule issues.
Recorded technical snapshots use the evaluated closed bars; opening the screen
does not fetch broker quotes or start entries. Pure risk evidence and session
authorization reads avoid monitor-induced account writes. Bulk emergency scope
is supported managed scalping/signal strategies, with explicit unresolved
legacy-batch results; idle unlinked drafts are not poisoned into closing.
Independent review findings about detached runs, active linked Flows and failure
recording were addressed with regressions.

Verification before rollout: 249 Python checks, 29 frontend tests, production
build. Isolated browser QA verified seven-row layout, technical detail, retained
log expansion/pagination, cancel/typed STOP ALL, and pending/failed closure results.
No production stop control was invoked. Strategy review findings are in
`docs/reviews/2026-09-28-strategy-rules-review.md`.
