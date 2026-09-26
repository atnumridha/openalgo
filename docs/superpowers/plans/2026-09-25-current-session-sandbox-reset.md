# Current-Session Sandbox Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guarded, repeatable way to clear the signed-in user's current-session sandbox strategy tests and reverse their verified realised P&L in simulated funds; execute it once for today's tests only after verification.

**Architecture:** A read-only preview computes an owner-scoped, versioned reset set from Strategy Module and sandbox ledgers. A short user-scoped admission lock protects revalidation and a durable, recoverable two-database mutation. The Strategies UI previews and confirms; no live broker command is involved.

**Tech Stack:** Flask, SQLAlchemy, SQLite/PostgreSQL configuration, Python `Decimal`, React/TypeScript, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-current-session-sandbox-reset-design.md`

## Global Constraints

- "Today" starts at `SESSION_EXPIRY_TIME` (03:00 IST by default), not midnight.
- Only owner-scoped `mode=sandbox` Strategy Module runs started in this session are eligible.
- Saved strategies, workflows, configuration, market history, older sessions, live broker data, and live risk state remain unchanged.
- Refuse if any affected run, sandbox order, or position is open, or if fill attribution/P&L is uncertain.
- Reverse only verified realised P&L: `new_available_balance = old_available_balance - selected_realised_pnl`.
- Keep duplicate-candle and webhook idempotency claims; never automatically replay a signal or restart a strategy.
- Back up and journal before deletion; a partial failure blocks new sandbox entries until recovered.
- Do not execute today's data reset until backend tests, frontend tests, fresh preview, and backup have been verified.
- The repository currently has an unrelated in-progress merge and pre-existing modifications. Never resolve, commit, or discard those changes on this task's behalf.

## Review Focus

1. A run stops between preview and confirmation: stale token returns 409, not a partial reset (Task 1 and 3).
2. Two attempts or a browser retry: idempotency never credits or debits funds twice (Task 2 and 3).
3. A manual trade shares a netted instrument with a strategy fill: attribution blocks the reset (Task 1).
4. Process failure between database commits: recovery gate remains closed and exact pre-reset rows/funds are restorable (Task 2).
5. A run spans the 03:00 IST boundary or belongs to another user/live mode: it is excluded or blocks as appropriate (Task 1).

---

## File map and interfaces

- Create `services/strategy_module/sandbox_reset.py`: preview, admission validation, exact P&L reconciliation, and orchestration. Public `preview(user_id: str, now: datetime | None = None) -> ResetPreview`; `execute(user_id: str, expected_version: str) -> ResetResult`.
- Create `database/sandbox_reset_journal.py`: durable reset operation, snapshot references, state transitions, and recovery gate. `begin`, `mark_sandbox_done`, `complete`, `mark_recovery_required`, `assert_recovered`.
- Modify `database/strategy_module_db.py`: owner-scoped run selection and explicit deletion of run dependencies, without deleting strategy definitions or durable reset audit.
- Modify `database/sandbox_db.py`: exact sandbox order/trade selection and transactional P&L reversal, never touching all-data `/sandbox/reset`.
- Modify `services/strategy_module/portfolio_governor.py`, `services/strategy_module/engine.py`, and `services/strategy_module/signals.py`: share the user's sandbox admission gate for all entry paths. Exits remain permitted.
- Modify `blueprints/strategy_module.py`: authenticated, CSRF-protected preview and execute endpoints.
- Modify `frontend/src/api/strategy_module.ts`, `frontend/src/pages/strategy/List.tsx`: typed preview and explicit confirmation UI.
- Add focused backend and frontend tests. Do not modify `frontend/dist` until the final build step.

### Task 1: Owner-scoped preview and exact attribution

**Files:** Create `services/strategy_module/sandbox_reset.py`; modify `database/strategy_module_db.py` and `database/sandbox_db.py`; test `test/test_strategy_module_sandbox_reset.py`.

**Interfaces:** `preview(user_id, now=None)` returns a frozen `ResetPreview` with `session_start_utc`, `session_end_utc`, ordered run/order/trade IDs, `realised_pnl: Decimal`, `funds_before: Decimal`, `funds_after: Decimal`, `blockers: tuple[str,...]`, and a SHA-256 `version` of the selected facts. It performs no writes and returns no credentials.

- [ ] **Step 1: Write failing tests for scope, attribution, and blockers.**

```python
def test_preview_only_selects_owned_sandbox_runs_from_current_session(seeded_reset_db):
    view = reset.preview("owner", now=IST.localize(datetime(2026, 9, 25, 12)))
    assert view.run_ids == (seeded_reset_db.owned_sandbox_run_id,)
    assert seeded_reset_db.other_user_run_id not in view.run_ids
    assert seeded_reset_db.live_run_id not in view.run_ids

def test_preview_reverses_loss_and_profit_exactly(seeded_reset_db):
    view = reset.preview("owner", now=IST.localize(datetime(2026, 9, 25, 12)))
    assert view.funds_after == view.funds_before - view.realised_pnl

@pytest.mark.parametrize("fault", ["open_run", "pending_order", "open_position", "mixed_trade", "bad_fill", "cross_session_run"])
def test_preview_blocks_unreconcilable_state(seeded_reset_db, fault):
    seeded_reset_db.inject(fault)
    assert reset.preview("owner", now=seeded_reset_db.now).blockers
```

- [ ] **Step 2: Run `uv run pytest -q test/test_strategy_module_sandbox_reset.py` and confirm red failures refer to missing preview behavior.**
- [ ] **Step 3: Implement `ResetPreview` and read-only selectors.** Use `session_started_at(now)` and UTC conversion for `sm_strategy_run`; convert the same session boundary to naive IST for sandbox order/trade timestamps. Reconcile by exact `broker_order_id -> sandbox_orders.orderid -> sandbox_trades.orderid`, `Decimal` quantity/price, and existing `filled_orders_have_usable_evidence`. Include current funds fields and all selected IDs in the version hash. Refuse mixed trading in a selected instrument and any non-flat/pending state; cap row counts to prevent unbounded reset.
- [ ] **Step 4: Run the focused tests; add the stale-preview-version assertion by changing one trade between previews.**
- [ ] **Step 5: Review diff only; do not commit while the unrelated merge is open.**

### Task 2: Durable journal, admission gate, and reversible mutation

**Files:** Create `database/sandbox_reset_journal.py`; modify `database/strategy_module_db.py`, `database/sandbox_db.py`, `services/strategy_module/portfolio_governor.py`, `services/strategy_module/engine.py`, and `services/strategy_module/signals.py`; test `test/test_strategy_module_sandbox_reset.py` and `test/test_strategy_module_sandbox_reset_recovery.py`.

**Interfaces:** `execute(user_id, expected_version)` returns `ResetResult(audit_id, counts, realised_pnl, funds_after, already_done)` or raises typed `ResetBlocked` / `ResetRecoveryRequired`. `assert_recovered(user_id)` refuses *new sandbox entries only*, never exits. `run_reset_under_lock(user_id, callback)` shares the existing account admission lease.

- [ ] **Step 1: Write failing tests for exact deletion, no double credit, crash recovery, and entry/exit behavior.**

```python
def test_execute_removes_only_selected_runs_and_reverses_funds_once(seeded_reset_db):
    view = reset.preview("owner", now=seeded_reset_db.now)
    result = reset.execute("owner", view.version, now=seeded_reset_db.now)
    assert result.funds_after == view.funds_after
    assert seeded_reset_db.funds().available_balance == view.funds_after
    assert seeded_reset_db.older_run_exists()
    assert seeded_reset_db.live_run_exists()
    assert reset.execute("owner", result.version, now=seeded_reset_db.now).already_done

def test_failure_after_first_commit_blocks_entries_until_recovery(seeded_reset_db, failpoint):
    failpoint("after_sandbox_commit")
    with pytest.raises(reset.ResetRecoveryRequired):
        reset.execute("owner", reset.preview("owner").version)
    assert not seeded_reset_db.can_enter_sandbox()
    assert seeded_reset_db.can_exit_sandbox()
```

- [ ] **Step 2: Run both test files and confirm they fail for missing journal/mutation.**
- [ ] **Step 3: Add a durable operation row and immutable row snapshot.** Store owner/session/selected IDs/version/pre-post funds/state/backup references; never store secrets. Make one active reset per owner. Use a bounded backup path beneath `db/backups/`, validated against configured database paths. The backup must use the database engine's safe snapshot mechanism; unsupported backend or failed backup returns a blocker before deletion.
- [ ] **Step 4: Revalidate under the shared account admission lease.** Explicitly delete selected run-linked comparison rows, checkpoints, orders, events, and runs; delete only matched sandbox trades/orders; reverse `SandboxFunds.available_balance`, `realized_pnl`, `today_realized_pnl`, and `total_pnl` using `Decimal`. Do not change starting capital, configuration, live reservations, or unlinked trade rows. Recompute or remove only selected sandbox risk summaries/reservations.
- [ ] **Step 5: Make cross-database completion recoverable.** Journal state transitions precede each commit. If second commit fails, keep a durable `recovery_required` gate and restore exact pre-reset rows/funds from the snapshot in a tested recovery function; clear the gate only after both databases and counts agree. Never silently retry a debit/credit.
- [ ] **Step 6: Run focused tests including injected failures, same-user concurrent entry, different-user isolation, repeat reset, and exit while recovery is required.**
- [ ] **Step 7: Review diff only; do not commit while the unrelated merge is open.**

### Task 3: Authenticated API and Strategies-page control

**Files:** Modify `blueprints/strategy_module.py`, `frontend/src/api/strategy_module.ts`, `frontend/src/pages/strategy/List.tsx`; test `test/test_strategy_module_sandbox_reset_api.py` and `frontend/src/pages/strategy/List.test.tsx`.

**Interfaces:** `GET /strategy/api/sandbox-reset/preview` returns counts, bounds, P&L, funds and blockers; `POST /strategy/api/sandbox-reset` accepts `{ "version": "..." }` and returns audit ID/result. 409 means stale or blocked, 503 means recovery required. Neither route accepts a broker or mode override.

- [ ] **Step 1: Write failing API and UI tests.**

```python
def test_post_requires_owned_session_csrf_and_current_preview(client, sandbox_reset_fixture):
    assert client.post("/strategy/api/sandbox-reset", json={"version": "x"}).status_code in (401, 403)
    login_and_csrf(client, "owner")
    assert client.post("/strategy/api/sandbox-reset", json={"version": "stale"}, headers=csrf_headers()).status_code == 409

def test_preview_never_exposes_credentials(client, sandbox_reset_fixture):
    login_and_csrf(client, "owner")
    body = client.get("/strategy/api/sandbox-reset/preview").get_json()
    assert "api_key" not in str(body).lower()
```

```tsx
it('shows blockers and never enables confirmation for an unsafe preview', async () => {
  mockResetPreview({ blockers: ['Open sandbox position'] })
  render(<StrategyList />)
  await userEvent.click(screen.getByRole('button', { name: /reset today/i }))
  expect(screen.getByRole('button', { name: /confirm reset/i })).toBeDisabled()
})
```

- [ ] **Step 2: Run targeted pytest and Vitest; confirm failures are the missing routes/control.**
- [ ] **Step 3: Add the GET/POST routes with `@check_session_validity`, shared rate limit, strict JSON/version validation, and existing CSRF middleware.** Return typed errors without echoing internal row data.
- [ ] **Step 4: Add a separate Strategies-page dialog.** Show exact session, counts, signed P&L adjustment and projected simulated balance; require explicit confirmation; disable on blockers/loading; refresh strategy/funds queries on success. Do not repurpose `/sandbox/reset`.
- [ ] **Step 5: Run the focused backend/frontend tests and frontend typecheck.**
- [ ] **Step 6: Review diff only; do not commit while the unrelated merge is open.**

### Task 4: Full verification and today's one-time operation

**Files:** Test files above; generated frontend assets only if build requires them; no new production interface.

**Interfaces:** Consumes Task 1-3 API. Produces a verified reset receipt or a blocker report; no order write.

- [ ] **Step 1: Run all focused reset tests plus existing strategy, sandbox, and Flow regression tests; fix genuine regressions without relaxing safety.**
- [ ] **Step 2: Run the frontend test suite, typecheck, and build. Inspect the exact diff and account for pre-existing failures separately.**
- [ ] **Step 3: On the running app, verify the reset dialog and read-only preview for the signed-in account. Confirm the 16 previously observed stopped sandbox runs still match the owner's current-session set; do not assume the global count is the owner's count.**
- [ ] **Step 4: Take a fresh, verified backup and compare the preview's selected IDs, realised P&L, current funds and projected funds to the database. If any blocker or mismatch exists, stop and report it; do not use `/sandbox/reset`.**
- [ ] **Step 5: Execute once through the guarded POST only after the checks pass. Verify audit ID, exact fund balance, zero selected runs, unchanged older/live rows, and an eligible new sandbox test. Do not start or place a trade merely to prove the reset.**
- [ ] **Step 6: Report the result, counts, P&L reversal, backup location, tests, any remaining limitations, and the unrelated merge state. Do not claim a commit while Git's merge remains in progress.**

## Self-review notes

- Coverage: scope, UI, attribution, funds, journal, failure recovery, tests, and one authorized execution are each owned by a task.
- No step assumes a run summary is sufficient evidence for changing funds.
- Existing `/sandbox/reset` is deliberately untouched.
- Exact helper/fixture names in example tests are to be defined in the test files before use; production interfaces are fixed above.
