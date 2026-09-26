# Sandbox strategy bulk controls

## Intent and scope

The operator wants one action on the Strategies page to make the installed intraday signal strategies eligible to respond to new signals, and an individual enable/disable control. Disabling must request closure of any open position immediately. The existing twelve signal workflows may already be active while their strategy rows say `stopped`: signal runs open only on an entry signal. The UI must distinguish **armed**, **run open**, **closing**, and **disabled**.

This change controls sandbox signal strategies only. It does not switch a strategy to live mode, grant live authorization, place an order when arming, alter the current risk limits, or reset sandbox data. Existing batch strategies keep their explicit per-strategy Start/Stop path and are reported as ineligible for bulk arming.

## Selected approach

Use a durable strategy admission state and keep Flow activation as the scanner's operational state. This is safer than treating `status=stopped` as disabled (it is normal before the first signal), and safer than toggling Flow alone (that could also suppress protective exits). The strategy entry gate is authoritative; Flow activation/deactivation is coordinated with it. All installed strategy-to-workflow associations must be resolved from explicit strategy IDs and broker ownership, never by matching display names.

Alternatives rejected: calling the existing `/start` route for each strategy would fail for signal strategies and could place immediate batch orders; merely activating/deactivating workflows would not reliably block racing entries or preserve exits.

## Durable state and migration

Add an automation admission state to `sm_strategy`: `disabled`, `armed`, `closing`, or `close_failed`, with a timestamp and last reason/error suitable for UI/audit. The state is separate from `live_enabled`, `status`, and `current_run_id`. Any state other than `armed` blocks **new entries**. Exits, stop requests, reconciliation, and intraday square-off are always allowed.

Migration is idempotent and preserves existing strategy definitions, runs, and Flow activation choices. Existing signal strategies with `live_enabled=false` and one active, sandbox-only workflow become `armed`; others become `disabled`. Ambiguous ownership, mixed/live mode, or missing workflow association defaults to `disabled` and appears as an actionable error. New signal strategies default to `disabled` until explicitly armed. No migration creates an order or clears a run.

## Individual controls

Enable checks ownership, broker connection, sandbox execution mode, configured risk controls, and a unique linked workflow. It enables the strategy admission state and activates the linked workflow if needed. Success means **armed for future signals**, not running a position. It is idempotent. A live-enabled strategy cannot be armed by this sandbox control.

Disable first commits `closing` (blocking new entries at the final order-admission gate), then requests `engine.stop_run` for any open run. It keeps the linked workflow and protective exit path available while an exit is pending. Only after confirmed flat, including reconciliation of unknown order/position outcomes, does it deactivate the linked workflow and commit `disabled`. If any exit, deactivation, or broker confirmation fails, it remains entry-blocked in `close_failed`/`closing`, exposes the unresolved run and error, and emits the existing critical-alert path. Retrying disable is safe. The UI never labels an exit request as a completed close.

The entry gate checks fresh durable state for each `long_entry` and `short_entry`, including an already-open run and immediately before dispatch. It does not rely on a stale in-memory strategy snapshot. Manual/scheduled exits still work when entry market data is unavailable.

## Bulk control and API/UI

Add an authenticated, owner-scoped sandbox bulk-arm endpoint. It processes eligible saved signal strategies independently and idempotently, returns an itemized result (`armed`, `already_armed`, or `skipped` with reason), and never silently changes execution mode. It must reject an unresolved closing state and cannot arm a strategy with unknown order/position outcome. One failure does not roll back successful arms, but the response and UI count each result accurately.

The Strategies page presents `Start all (sandbox)` as one action and shows per-strategy `Enable`/`Disable` controls. It shows admission state separately from run state, linked workflow health, and any close-pending/error reason. A running position's Disable control explains that it requests closure and shows pending status until confirmed flat. The page never calls the existing batch `/start` route for a signal strategy.

The bulk action applies to the current user's saved sandbox signal strategies, including the twelve installed receivers when eligible. Batch, live-enabled, wrong-broker, unlinked, or invalid strategies are skipped with explicit reasons. No action is taken on another user's strategy or workflow.

## Consistency, recovery, and verification

The database entry gate is the fail-closed source of truth across concurrent signals and process restarts. Workflow activation may be temporarily out of sync; recovery reconciles linked workflow state without accepting new entries until checks pass. If an enable partially fails, revert to `disabled`. If a disable partially fails, remain entry-blocked and keep/recover protective exits. Audit each transition and bulk result without exposing credentials.

Tests cover migration defaults, owner/broker isolation, sandbox-only checks, duplicate clicks, partial bulk results, concurrent entry versus disable, existing-run entry rejection, exits while disabled, successful/failed/partial closes, restart recovery, missing/ambiguous workflow links, and frontend state/error rendering. Verify the twelve installed strategies' displayed state and one-click action in the running UI after deployment. Restart only after active workflow/run ownership is reconciled; the separate sandbox-reset preview error is caused by the currently running server predating its endpoint.
