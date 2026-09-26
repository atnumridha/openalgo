# Sandbox Strategy Bulk Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-click sandbox arming and durable per-strategy enable/disable controls, with disable blocking new entries immediately and closing any open position before reporting the strategy disabled.

**Architecture:** Add a durable automation-admission state to each saved strategy and make it the fail-closed authority at every signal entry. A focused orchestration service coordinates strategy state with the uniquely linked Flow workflow, while existing engine stop/reconciliation paths remain the only authority for flattening positions. Session-authenticated API routes expose individual and bulk actions, and the Strategies page renders automation state separately from run state.

**Tech Stack:** Python 3, Flask, SQLAlchemy, SQLite/PostgreSQL-compatible migrations, pytest, React, TypeScript, TanStack Query, Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-25-sandbox-strategy-bulk-controls-design.md`

## Global Constraints

- Bulk arming is sandbox-only and must never enable live execution, grant live authorization, create a run, or place an order.
- New entries require durable state `armed`; exits, stop requests, reconciliation, and intraday square-off remain available in every state.
- Disabling commits `closing` before requesting exits and reports `disabled` only after authoritative flat confirmation and Flow deactivation.
- Workflow association uses explicit `strategy_id`, `brokerOwner`, `mode="sandbox"`, and connection ownership; display-name matching is forbidden.
- Ambiguous ownership, mixed/live mode, missing workflow linkage, or unknown order/position outcomes fail closed.
- Existing risk limits and broker-held live protection requirements are unchanged.
- The current repository has an unresolved merge and unrelated dirty changes; never reset, overwrite, or commit unrelated work.

## Review Focus

- A disable racing with a new entry must commit the entry block first, and the entry must be refused even if it holds a stale strategy snapshot.
- An accepted exit that has not filled must remain `closing`; the UI must not say disabled or flat.
- Missing, duplicated, foreign-owner, live-mode, or malformed Flow links must block arming with a precise reason.
- A partial bulk result must report each strategy independently without undoing successful arms or hiding failures.
- Restart recovery must preserve entry blocking and resume reconciliation/deactivation for `closing` and `close_failed` strategies.

---

### Task 1: Durable automation-admission state and migration

**Files:**
- Modify: `database/strategy_module_db.py`
- Modify: `upgrade/migrate_strategy_module.py`
- Modify: `test/test_migrate_strategy_module.py`
- Modify: `test/test_strategy_module_db.py`

**Interfaces:**
- Produces: `AUTOMATION_STATES = ("disabled", "armed", "closing", "close_failed")`.
- Produces: `set_automation_state(strategy_id: int, user_id: str, state: str, *, reason: str | None = None) -> tuple[bool, str | None]`.
- Produces strategy JSON fields `automation_state`, `automation_state_reason`, and `automation_state_updated_at`.

- [ ] **Step 1: Write migration tests that preserve old rows and add the three columns idempotently**

Add assertions to `test_apply_upgrades_every_populated_old_stage_idempotently`:

```python
strategy_columns = _column_details(engine, "sm_strategy")
assert strategy_columns.keys() >= {
    "automation_state", "automation_state_reason", "automation_state_updated_at"
}
with engine.connect() as connection:
    state = connection.exec_driver_sql(
        "SELECT automation_state FROM sm_strategy WHERE id = 1"
    ).scalar_one()
assert state == "disabled"
```

Add a test that runs the migration twice and proves existing non-null state/reason/timestamp remain unchanged.

- [ ] **Step 2: Run the migration tests and verify failure**

Run: `uv run pytest -q test/test_migrate_strategy_module.py`

Expected: FAIL because the automation columns are absent.

- [ ] **Step 3: Add model columns and migration DDL**

Add to `SmStrategy`:

```python
automation_state = Column(String(20), nullable=False, default="disabled")
automation_state_reason = Column(Text, nullable=True)
automation_state_updated_at = Column(DateTime, nullable=True)
```

Add to `ADDED_COLUMNS`:

```python
("sm_strategy", "automation_state", "VARCHAR(20) NOT NULL DEFAULT 'disabled'"),
("sm_strategy", "automation_state_reason", "TEXT"),
("sm_strategy", "automation_state_updated_at", "DATETIME"),
```

Expose the fields from `strategy_to_dict`, with the existing `_iso` helper for the timestamp.

- [ ] **Step 4: Write store tests for owner isolation, validation, reason clearing, and JSON serialization**

Cover valid transitions, an invalid state, a foreign owner, and this exact rule:

```python
ok, error = store.set_automation_state(strategy.id, USER, "armed", reason=None)
assert (ok, error) == (True, None)
row = store.get_strategy(strategy.id, USER)
assert row.automation_state == "armed"
assert row.automation_state_reason is None
assert row.automation_state_updated_at is not None
```

- [ ] **Step 5: Implement the atomic store setter**

Use one owner-scoped SQL update, not a read-then-write ORM sequence:

```python
def set_automation_state(strategy_id, user_id, state, *, reason=None):
    if state not in AUTOMATION_STATES:
        return False, "Unknown automation state"
    updated = db_session.query(SmStrategy).filter_by(
        id=strategy_id, user_id=user_id
    ).update({
        SmStrategy.automation_state: state,
        SmStrategy.automation_state_reason: reason,
        SmStrategy.automation_state_updated_at: _utc_now(),
    }, synchronize_session=False)
    if updated != 1:
        db_session.rollback()
        return False, "Strategy not found"
    db_session.commit()
    return True, None
```

Use the module's existing UTC helper rather than introducing a second clock convention.

- [ ] **Step 6: Run focused database and migration tests**

Run: `uv run pytest -q test/test_migrate_strategy_module.py test/test_strategy_module_db.py`

Expected: PASS.

- [ ] **Step 7: Commit the task if the merge has been resolved by the operator**

```bash
git add database/strategy_module_db.py upgrade/migrate_strategy_module.py test/test_migrate_strategy_module.py test/test_strategy_module_db.py
git commit -m "feat: persist strategy automation admission state"
```

If the merge is still active, leave only these files modified and report that a task commit is blocked; do not finish or abort the merge.

---

### Task 2: Explicit strategy-to-Flow linkage and validation

**Files:**
- Create: `services/strategy_module/automation_control.py`
- Modify: `database/flow_db.py`
- Modify: `services/strategy_module/starter_workflows.py`
- Create: `test/test_strategy_module_automation_control.py`
- Modify: `test/test_strategy_module_starter_workflows.py`

**Interfaces:**
- Produces: `WorkflowLink(workflow_id: int, active: bool, mode: str, broker_owner: str, broker_connection_id: str | None)`.
- Produces: `resolve_workflow_link(strategy, *, require_sandbox: bool = True) -> tuple[WorkflowLink | None, str | None]`.
- Consumes: Flow node data `strategyId`, `brokerOwner`, `mode` and workflow `broker_connection_id`.

- [ ] **Step 1: Write resolver tests for one valid link and every fail-closed ambiguity**

Create workflows containing a `strategyModuleRun` node and assert:

```python
link, error = automation_control.resolve_workflow_link(strategy)
assert error is None
assert link.workflow_id == workflow.id
assert link.mode == "sandbox"
```

Also test no link, two matching links, `mode="live"`, wrong `brokerOwner`, wrong `strategyId` type, wrong broker connection, and a malformed nodes payload. Each must return `(None, precise_reason)`.

- [ ] **Step 2: Run the resolver tests and verify failure**

Run: `uv run pytest -q test/test_strategy_module_automation_control.py`

Expected: FAIL because the resolver module does not exist.

- [ ] **Step 3: Add a read helper that returns workflows containing a strategy ID**

Implement in `database/flow_db.py`:

```python
def get_workflows_for_strategy(strategy_id: int):
    matches = []
    for workflow in get_all_workflows():
        for node in workflow.nodes or []:
            data = node.get("data") if isinstance(node, dict) else None
            if node.get("type") == "strategyModuleRun" and isinstance(data, dict):
                if data.get("strategyId") == strategy_id:
                    matches.append(workflow)
                    break
    return matches
```

Keep all ownership/mode validation in `automation_control.py` so database code remains a storage adapter.

- [ ] **Step 4: Implement the strict resolver and result dataclass**

Validate exactly one matching workflow; exactly one matching run node in that workflow; sandbox mode; matching user/broker owner; and matching connection identity when either side declares one. Do not infer linkage from workflow or strategy names.

- [ ] **Step 5: Pin starter-workflow linkage in tests**

Assert every installed starter workflow contains integer `strategyId`, exact `brokerOwner`, `mode="sandbox"`, and the intended broker connection identity when available. Preserve customized graph activation choices during reinstall.

- [ ] **Step 6: Run focused linkage tests**

Run: `uv run pytest -q test/test_strategy_module_automation_control.py test/test_strategy_module_starter_workflows.py`

Expected: PASS.

- [ ] **Step 7: Commit the task if Git is no longer mid-merge**

```bash
git add services/strategy_module/automation_control.py database/flow_db.py services/strategy_module/starter_workflows.py test/test_strategy_module_automation_control.py test/test_strategy_module_starter_workflows.py
git commit -m "feat: resolve strategy workflow ownership explicitly"
```

---

### Task 3: Fail-closed signal-entry admission

**Files:**
- Modify: `services/strategy_module/signals.py`
- Modify: `services/strategy_module/order_dispatch.py`
- Modify: `test/test_strategy_module_signals.py`
- Modify: `test/test_strategy_module_order_dispatch.py`

**Interfaces:**
- Produces: `require_automation_entry(strategy_id: int, user_id: str) -> tuple[bool, str | None]` in `automation_control.py`.
- Consumes: durable `SmStrategy.automation_state` immediately before order dispatch.

- [ ] **Step 1: Write failing signal tests for disabled and racing states**

Cover `disabled`, `closing`, and `close_failed` on a new run and an already-open run. Include a concurrency test where the signal starts with an `armed` snapshot, the store flips to `closing`, and the dispatcher must not be called:

```python
assert result.ok is False
assert result.error == "Strategy automation is closing; new entries are blocked"
assert placed == []
```

Also prove `long_exit` and `short_exit` remain accepted in all four automation states.

- [ ] **Step 2: Run tests and verify entries currently bypass the new state**

Run: `uv run pytest -q test/test_strategy_module_signals.py -k 'automation or disabled or closing'`

Expected: FAIL because signals do not consult automation state.

- [ ] **Step 3: Implement a fresh durable gate before `_day_run` and again inside dispatch admission**

`handle_signal` checks admission for entry actions before creating a run. The final order path calls `require_automation_entry` after portfolio admission and immediately before dispatch, using strategy ID and owner rather than the stale snapshot. Exit actions bypass this gate. Record one auditable `automation_entry_blocked` event with state and reason.

- [ ] **Step 4: Test batch/manual behavior remains unchanged**

Add/retain tests proving the existing batch `/start` path and its live authorization gates do not acquire signal automation semantics. The new bulk control never calls it.

- [ ] **Step 5: Run signal and dispatch suites**

Run: `uv run pytest -q test/test_strategy_module_signals.py test/test_strategy_module_order_dispatch.py`

Expected: PASS.

- [ ] **Step 6: Commit the task if allowed by repository state**

```bash
git add services/strategy_module/signals.py services/strategy_module/order_dispatch.py services/strategy_module/automation_control.py test/test_strategy_module_signals.py test/test_strategy_module_order_dispatch.py
git commit -m "feat: gate every automated signal entry"
```

---

### Task 4: Individual enable and disable orchestration

**Files:**
- Modify: `services/strategy_module/automation_control.py`
- Modify: `services/strategy_module/recovery.py`
- Modify: `test/test_strategy_module_automation_control.py`
- Modify: `test/test_strategy_module_recovery.py`

**Interfaces:**
- Produces `ControlResult(ok: bool, state: str, workflow_id: int | None, run_id: int | None, close_pending: bool, error: str | None)`.
- Produces `enable_sandbox(strategy_id: int, user_id: str, api_key: str) -> ControlResult`.
- Produces `disable_and_close(strategy_id: int, user_id: str) -> ControlResult`.
- Produces `recover_automation_controls(user_id: str | None = None) -> list[ControlResult]`.

- [ ] **Step 1: Write enable tests**

Test disabled-to-armed, already-armed idempotence, live-enabled refusal, unresolved order refusal, invalid/missing workflow refusal, activation rollback, owner isolation, and no call to `engine.start_run` or order dispatch.

- [ ] **Step 2: Implement enable with compensating rollback**

Validate strategy, sandbox-only state, order outcomes, and link first. Persist `armed` only after successful Flow activation/verification. If activation succeeds but state persistence fails, deactivate the workflow; if compensation fails, return an explicit inconsistent-state error and emit a critical alert.

- [ ] **Step 3: Write disable tests, including accepted-but-pending and failed exits**

Assert the sequence with mocks:

```python
assert calls[:2] == ["persist:closing", "engine.stop_run"]
assert result.state == "closing"
assert result.close_pending is True
assert workflow.is_active is True
```

For a flat strategy, deactivation then `disabled` should complete synchronously. For stop failure or unknown outcome, state must be `close_failed` or `closing`, entry must remain blocked, Flow must remain available for exits, and error details must be retained.

- [ ] **Step 4: Implement disable/close around the existing engine stop path**

Never synthesize orders or duplicate stop evaluation. Persist `closing`, refresh the run, call `engine.stop_run`, and use its `stop_pending`/exit details. Only deactivate Flow and persist `disabled` after the run is durably stopped and account/order reconciliation reports no unresolved exposure.

- [ ] **Step 5: Write and implement restart recovery tests**

Recovery must revisit `closing` and `close_failed`: retry/reconcile stop, keep blocked while exposure is possible, deactivate Flow after confirmed flat, and emit alerts only on meaningful state changes. It must never turn a `disabled` strategy back on.

- [ ] **Step 6: Run orchestration and recovery suites**

Run: `uv run pytest -q test/test_strategy_module_automation_control.py test/test_strategy_module_recovery.py`

Expected: PASS.

- [ ] **Step 7: Commit the task if repository state permits**

```bash
git add services/strategy_module/automation_control.py services/strategy_module/recovery.py test/test_strategy_module_automation_control.py test/test_strategy_module_recovery.py
git commit -m "feat: coordinate strategy enable and safe disable"
```

---

### Task 5: Owner-scoped individual and bulk APIs

**Files:**
- Modify: `blueprints/strategy_module.py`
- Modify: `test/test_strategy_module_lifecycle_api.py`
- Modify: `test/test_strategy_restx_api.py`

**Interfaces:**
- Produces: `POST /strategy/api/strategies/<sid>/automation/enable`.
- Produces: `POST /strategy/api/strategies/<sid>/automation/disable`.
- Produces: `POST /strategy/api/automation/strategies/enable-all-sandbox`.
- Response item: `{strategy_id, name, state, outcome, workflow_id, run_id, close_pending, reason}`.

- [ ] **Step 1: Write failing lifecycle API tests**

Cover authentication, 404 for foreign/missing IDs, CSRF/session conventions, individual idempotence, close-pending as success with truthful fields, engine failure, and exact result envelopes.

- [ ] **Step 2: Write bulk API tests**

Seed eligible signal strategies plus batch, live-enabled, unlinked, foreign-owner, and unresolved strategies. Assert only eligible current-user rows are armed, each skip reason is returned, and successful rows remain armed when a neighbor fails.

- [ ] **Step 3: Implement thin routes over `automation_control`**

Routes resolve `_current_user`, obtain the current API key through the established authenticated helper, invoke the service, and map validation/state conflicts to 400/409 without leaking foreign IDs. The bulk endpoint returns HTTP 200 for itemized partial results and HTTP 503 only if it cannot enumerate or process any strategy safely.

- [ ] **Step 4: Add audit-event assertions**

Assert `automation_armed`, `automation_closing`, `automation_disabled`, `automation_close_failed`, and one bulk summary event carry no API key, token, or secret.

- [ ] **Step 5: Run API suites**

Run: `uv run pytest -q test/test_strategy_module_lifecycle_api.py test/test_strategy_restx_api.py`

Expected: PASS.

- [ ] **Step 6: Commit the task if possible**

```bash
git add blueprints/strategy_module.py test/test_strategy_module_lifecycle_api.py test/test_strategy_restx_api.py
git commit -m "feat: expose sandbox strategy automation controls"
```

---

### Task 6: Strategies-page controls and truthful state display

**Files:**
- Modify: `frontend/src/types/strategy_module.ts`
- Modify: `frontend/src/api/strategy_module.ts`
- Modify: `frontend/src/pages/strategy/List.tsx`
- Modify: `frontend/src/pages/strategy/List.test.tsx`

**Interfaces:**
- Consumes the Task 5 response shape.
- Produces TypeScript `AutomationState`, `AutomationControlResult`, and `BulkAutomationResult`.

- [ ] **Step 1: Add failing API/type tests**

Define:

```typescript
export type AutomationState = 'disabled' | 'armed' | 'closing' | 'close_failed'
```

Add fetcher tests for individual enable/disable and bulk enable-all using the exact routes from Task 5.

- [ ] **Step 2: Add failing page tests for all visible states**

Test that the page:

- displays a separate Automation column;
- labels an armed/stopped signal receiver `Armed` rather than `Running`;
- shows `Start all (sandbox)` and itemized partial-result feedback;
- exposes Enable only for disabled/failed rows and Disable for armed/running rows;
- requires confirmation that Disable requests position closure;
- renders `Closing…` and disables repeat clicks while pending;
- shows the server's close failure and never says closed when `close_pending=true`;
- leaves batch and live-enabled rows ineligible with an explanatory tooltip.

- [ ] **Step 3: Implement API types and fetchers**

Add:

```typescript
export async function enableStrategyAutomation(id: number): Promise<AutomationControlResult>
export async function disableStrategyAutomation(id: number): Promise<AutomationControlResult>
export async function enableAllSandboxStrategies(): Promise<BulkAutomationResult>
```

Invalidate strategy list/detail/events and critical alerts after mutations.

- [ ] **Step 4: Implement accessible controls on `List.tsx`**

Add the bulk button beside reset/new actions, an Automation badge column, row Enable/Disable buttons, and a confirmation dialog whose copy states: “New entries stop immediately. Any open position will be sent through the existing close process and remains Closing until confirmed flat.” Use `aria-live`/`role="status"` for pending results and `role="alert"` for failures.

- [ ] **Step 5: Run frontend tests, typecheck, and build**

Run: `cd frontend && npm test -- --run src/pages/strategy/List.test.tsx`

Run: `cd frontend && npm run typecheck`

Run: `cd frontend && npm run build`

Expected: all PASS; the build refreshes `frontend/dist` through the project's normal build process.

- [ ] **Step 6: Commit the task if possible**

```bash
git add frontend/src/types/strategy_module.ts frontend/src/api/strategy_module.ts frontend/src/pages/strategy/List.tsx frontend/src/pages/strategy/List.test.tsx frontend/dist
git commit -m "feat: add sandbox strategy bulk controls"
```

---

### Task 7: Migration backfill and installed-strategy integration

**Files:**
- Modify: `upgrade/migrate_strategy_module.py`
- Modify: `services/strategy_module/starter_pack.py`
- Modify: `services/strategy_module/starter_workflows.py`
- Modify: `test/test_migrate_strategy_module.py`
- Modify: `test/test_strategy_module_starter_pack.py`
- Modify: `test/test_strategy_module_starter_workflows.py`

**Interfaces:**
- Consumes `resolve_workflow_link` and durable automation state.
- Produces deterministic backfill: safe active sandbox link plus `live_enabled=false` becomes `armed`; every ambiguous/unsafe row becomes `disabled` with reason.

- [ ] **Step 1: Write populated-database backfill tests**

Cover active valid sandbox workflow, inactive workflow, active live workflow, duplicate links, foreign owner, missing link, live-enabled strategy, customized workflow, and a second migration run that does not overwrite an operator's later choice.

- [ ] **Step 2: Implement a one-time versioned backfill**

Add a durable migration marker rather than deriving state on every boot. Only rows whose automation fields were introduced by this migration are candidates. Safe active sandbox links become armed; all others remain disabled with a concise reason. Do not activate/deactivate Flow during migration and do not create, stop, or clear runs.

- [ ] **Step 3: Make new starter strategies default disabled and linkage-complete**

Starter installation creates definitions and links but leaves automation disabled until the operator clicks Start all. Reinstall remains idempotent and preserves custom settings plus current activation/admission choices.

- [ ] **Step 4: Run migration/starter integration suites**

Run: `uv run pytest -q test/test_migrate_strategy_module.py test/test_strategy_module_starter_pack.py test/test_strategy_module_starter_workflows.py`

Expected: PASS.

- [ ] **Step 5: Commit the task if possible**

```bash
git add upgrade/migrate_strategy_module.py services/strategy_module/starter_pack.py services/strategy_module/starter_workflows.py test/test_migrate_strategy_module.py test/test_strategy_module_starter_pack.py test/test_strategy_module_starter_workflows.py
git commit -m "feat: backfill sandbox automation admission safely"
```

---

### Task 8: Full verification, runtime migration, restart, and UI acceptance

**Files:**
- Modify only if genuine regressions are found; do not weaken safety assertions.
- Verify: `docs/superpowers/specs/2026-09-25-sandbox-strategy-bulk-controls-design.md`
- Verify: `docs/superpowers/plans/2026-09-25-sandbox-strategy-bulk-controls.md`

**Interfaces:**
- Consumes all prior tasks.
- Produces a verified running UI only after the existing stale Flow execution and sandbox reset blockers are reconciled without deleting live data.

- [ ] **Step 1: Run the complete backend strategy/Flow/sandbox suites**

Run: `uv run pytest -q test/test_strategy_module_*.py test/test_strategy_restx_api.py test/test_flow_*.py test/sandbox`

Expected: PASS except already-documented unrelated failures; list every non-passing test and prove it predates or is fixed by this change.

- [ ] **Step 2: Run the complete frontend suite**

Run: `cd frontend && npm test -- --run`

Run: `cd frontend && npm run typecheck`

Run: `cd frontend && npm run build`

Expected: new controls PASS; explicitly account for every unrelated existing failure.

- [ ] **Step 3: Back up and preview the runtime migration**

Use the project's existing database backup/migration workflow. Run the migration's status/preview first, record the exact target database and proposed columns/backfill counts, and do not continue if it targets another database or finds ambiguous destructive work.

- [ ] **Step 4: Reconcile the pre-existing running Flow record before restart**

Read the execution, current strategy runs, sandbox positions, and order outcomes. If it is stale and flat, finalize it through the existing recovery path with an audit reason. If exposure or an unknown outcome remains, do not restart or reset; report the blocker. Do not silently delete execution history or adjust the ₹0.85 ledger discrepancy.

- [ ] **Step 5: Apply migration and restart the app only after the safety check passes**

Restart using the project's established process. Confirm `/strategy/api/sandbox-reset/preview` now returns JSON rather than the SPA 404 and that existing sessions reconnect without changing live mode.

- [ ] **Step 6: Verify all installed strategies in the UI**

Confirm the Strategies page shows all twelve saved intraday strategies, a separate automation badge, `Start all (sandbox)`, and individual controls. Click Start all once and verify itemized results; do not claim every strategy armed unless all twelve passed validation. Disable one flat sandbox strategy and verify its linked Flow deactivates. Re-enable it and verify no order/run is created until a valid signal.

- [ ] **Step 7: Verify disable with an open sandbox run in an isolated test strategy**

Create or use a disposable sandbox-only test strategy, open a simulated position through the normal signal path, click Disable, and verify: state changes to Closing before exit; new entries are rejected; exit remains available; state becomes Disabled only after confirmed flat; audit and WhatsApp critical-alert status remain truthful. Do not perform this acceptance test against live mode.

- [ ] **Step 8: Review the final diff and commit only scoped files after the merge is resolved**

Use the verification-before-completion skill. Review for credentials and unrelated changes, then commit scoped files. If the original merge remains active, do not create a commit; report the exact blocker and leave the verified working tree intact.
