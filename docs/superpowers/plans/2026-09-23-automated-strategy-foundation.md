# Automated Strategy Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add session-scoped live authorization, Strategy Module portfolio entry governance, lifecycle WhatsApp alerts, and an idempotent sandbox starter pack with UI controls.

**Architecture:** Extend the existing Strategy Module at its live-entry seams while leaving its order engine, exits, scheduler, recovery, and sandbox behavior intact. Reuse the existing WhatsApp transport and strategy CRUD contracts; expose a small safety API consumed by the existing Strategies page.

**Tech Stack:** Python 3.13, Flask, SQLAlchemy, pytest, React 19, TypeScript, TanStack Query, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-23-automated-strategy-foundation-design.md`

## Global Constraints

- Live trading requires both the durable per-strategy `live_enabled` flag and a current trading-session authorization.
- Expired or revoked authorization blocks new live entries and never blocks exits.
- Sandbox behavior remains independent of live authorization and live broker facts.
- The governor applies only to Strategy Module automated entries in this project.
- New live entries fail closed when required account or risk facts are unavailable.
- Initial limits are: two cash positions, one NIFTY options position, 1.5% cash-trade risk, 3% long-option lot risk, 4% combined open risk, 20% cash buffer, 4% daily loss, three consecutive stopped runs, 30-minute cooldown after two consecutive stopped runs, and minimum reward-to-risk 1.5.
- Live entry hours are 09:20-15:00 IST, with long-option entries ending at 14:45 IST.
- WhatsApp notification failure never blocks trading or risk exits.
- Starter-pack strategies are stopped, sandbox-only, live-disabled, and unscheduled; installation never starts or activates anything.
- No secrets or broker credentials are logged or committed.

## Review Focus

- A live exit after authorization expiry must still dispatch; Task 2 tests the exit path separately from entries.
- A background scheduler or webhook has no Flask request context; Task 1 tests authorization through the process registry rather than reading `flask.session` in engine code.
- Broker fund/position response shapes vary; Task 2 tests normalized aliases and missing facts fail closed.
- Duplicate starter-pack installation must not rotate tokens or create extra rows; Task 4 tests a second install.
- WhatsApp may be unpaired or throw asynchronously; Task 3 tests that lifecycle execution still succeeds.

---

### Task 1: Trading-session live authorization

**Files:**
- Create: `services/strategy_module/live_authorization.py`
- Modify: `blueprints/strategy_module.py`
- Modify: `services/strategy_module/engine.py`
- Modify: `services/strategy_module/signals.py`
- Modify: `services/strategy_module/scheduler.py`
- Modify: `blueprints/auth.py`
- Test: `test/test_strategy_module_live_authorization.py`
- Test: `test/test_strategy_module_lifecycle_api.py`
- Test: `test/test_strategy_module_signals.py`
- Test: `test/test_strategy_module_scheduler.py`

**Interfaces:**
- Produces: `grant(user_id: str) -> LiveAuthorization`, `revoke(user_id: str) -> None`, `status(user_id: str) -> LiveAuthorization`, and `require_live_entry(user_id: str) -> tuple[bool, str | None]`.
- Consumes: `utils.session.get_trading_session_date()` and `services.strategy_module.session.session_reset_time()`.
- Engine, signals, and scheduler use `require_live_entry`; Flask routes only mirror the state into the browser session for display and explicit revocation.

- [ ] **Step 1: Write failing service tests**

```python
def test_grant_expires_when_trading_session_day_changes(monkeypatch):
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-23")
    authz.grant("alice")
    monkeypatch.setattr(authz, "get_trading_session_date", lambda: "2026-09-24")
    assert authz.status("alice").active is False


def test_revocation_blocks_new_entries():
    authz.grant("alice")
    authz.revoke("alice")
    assert authz.require_live_entry("alice") == (
        False,
        "Live automation is not authorized for this trading session",
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest -q test/test_strategy_module_live_authorization.py`

Expected: collection fails because `services.strategy_module.live_authorization` does not exist.

- [ ] **Step 3: Implement the process-local authorization registry**

```python
@dataclass(frozen=True, slots=True)
class LiveAuthorization:
    active: bool
    session_day: str
    expires_at: str


def require_live_entry(user_id: str) -> tuple[bool, str | None]:
    current = status(user_id)
    if current.active:
        return True, None
    return False, "Live automation is not authorized for this trading session"
```

Guard the registry with a lock, bind grants to the current username and trading-session date, and return inactive status after reset or restart.

- [ ] **Step 4: Add authenticated grant, revoke, and status routes**

Add:

```text
GET    /strategy/api/automation/live-authorization
POST   /strategy/api/automation/live-authorization
DELETE /strategy/api/automation/live-authorization
```

The POST body must be `{"confirm": true}`. Store only `username`, `session_day`, and `expires_at` in Flask session; never store credentials.

- [ ] **Step 5: Add RED tests for all live entry seams and allowed exits**

Test that:

```python
assert engine.start_run(batch_id, "alice", "live").error == (
    "Live automation is not authorized for this trading session"
)
```

Also assert a signal live entry and scheduled live start are refused without a grant, then accepted after a grant. Exercise an existing live exit function after revocation and assert its dispatch mock was called.

- [ ] **Step 6: Integrate the backstop without touching sandbox or exits**

Call `require_live_entry(user_id)` immediately before a live batch run claims the strategy, immediately before a live signal entry claim, and in the scheduled live-start path. Do not add this check to `stop_run`, `_exit_legs`, signal exits, kill switch, cancellation, or reconciliation.

- [ ] **Step 7: Revoke authorization during logout and verify GREEN**

Call `live_authorization.revoke(username)` before `session.clear()` in the existing logout path. Run:

`uv run pytest -q test/test_strategy_module_live_authorization.py test/test_strategy_module_lifecycle_api.py test/test_strategy_module_signals.py test/test_strategy_module_scheduler.py`

- [ ] **Step 8: Commit**

```bash
git add services/strategy_module/live_authorization.py blueprints/strategy_module.py services/strategy_module/engine.py services/strategy_module/signals.py services/strategy_module/scheduler.py blueprints/auth.py test/test_strategy_module_live_authorization.py test/test_strategy_module_lifecycle_api.py test/test_strategy_module_signals.py test/test_strategy_module_scheduler.py
git commit -m "feat(strategy): require session live authorization"
```

### Task 2: Strategy Module portfolio entry governor

**Files:**
- Create: `services/strategy_module/portfolio_governor.py`
- Modify: `services/strategy_module/engine.py`
- Modify: `services/strategy_module/signals.py`
- Modify: `services/strategy_module/order_dispatch.py`
- Test: `test/test_strategy_module_portfolio_governor.py`
- Test: `test/test_strategy_module_engine.py`
- Test: `test/test_strategy_module_signals.py`
- Test: `test/test_strategy_module_order_dispatch.py`

**Interfaces:**
- Produces: `GovernorPolicy`, `EntryFacts`, `GovernorDecision`, `evaluate_entry(facts, policy, now)`, and `build_entry_facts(user_id, strategy, resolved_legs, api_key, mode)`.
- `GovernorDecision` contains `allowed`, `code`, `message`, and `metrics`.
- Entry callers pass `intent="entry"`; every exit caller passes `intent="exit"` to `dispatch_order`.

- [ ] **Step 1: Write RED tests for the pure decision function**

Use literal fixtures to cover `outside_entry_window`, `option_window_closed`, `risk_missing`, `cash_trade_risk`, `option_lot_risk`, `combined_open_risk`, `cash_buffer`, `daily_loss_lock`, `consecutive_loss_lock`, `cooldown`, `position_limit`, and an allowed decision. Include:

```python
def test_exit_is_never_evaluated_as_an_entry():
    decision = evaluate_entry(facts(intent="exit", available_cash=None), DEFAULT_POLICY, NOW)
    assert decision.allowed is True
    assert decision.code == "exit_allowed"
```

- [ ] **Step 2: Run the governor tests and verify RED**

Run: `uv run pytest -q test/test_strategy_module_portfolio_governor.py`

Expected: import fails because the governor module does not exist.

- [ ] **Step 3: Implement the pure policy and decision types**

```python
@dataclass(frozen=True, slots=True)
class GovernorPolicy:
    max_cash_positions: int = 2
    max_nifty_option_positions: int = 1
    cash_risk_pct: Decimal = Decimal("0.015")
    option_risk_pct: Decimal = Decimal("0.03")
    combined_risk_pct: Decimal = Decimal("0.04")
    cash_buffer_pct: Decimal = Decimal("0.20")
    daily_loss_pct: Decimal = Decimal("0.04")
    minimum_reward_risk: Decimal = Decimal("1.5")
    cooldown_minutes: int = 30
```

Use `Decimal`, IST-aware time comparisons, and stable lowercase reason codes. Risk equals configured stop distance times quantity; estimated debit equals quote ask (falling back to LTP only when ask is absent and positive) times quantity.

- [ ] **Step 4: Write RED adapter tests for broker facts**

Cover fund aliases such as `availablecash`, `available_cash`, and `cash`; position aliases such as `netqty`, `net_qty`, and `quantity`; missing quotes; unavailable broker state; and sandbox bypass.

- [ ] **Step 5: Implement fact collection through existing services**

Use `get_auth_token_broker`, `funds_service.get_funds(..., auth_token=..., broker=...)`, `positionbook_service.get_positionbook(..., auth_token=..., broker=...)`, and `quotes_service.get_quotes`. Read prior Strategy Module runs from the store for session P&L, stop reasons, and cooldown. Do not read web prices or another broker connection.

- [ ] **Step 6: Integrate the governor before every entry dispatch**

For batch runs, evaluate all resolved entry legs once before the strategy is claimed. For signal runs, evaluate the individual entering leg before its durable entry claim. Audit a rejection as `portfolio_governor_rejected` with the decision payload. Sandbox entries return an immediate `sandbox_allowed` decision. Exits pass `intent="exit"` and cannot be rejected by this layer.

- [ ] **Step 7: Verify integration GREEN**

Run:

`uv run pytest -q test/test_strategy_module_portfolio_governor.py test/test_strategy_module_engine.py test/test_strategy_module_signals.py test/test_strategy_module_order_dispatch.py`

- [ ] **Step 8: Commit**

```bash
git add services/strategy_module/portfolio_governor.py services/strategy_module/engine.py services/strategy_module/signals.py services/strategy_module/order_dispatch.py test/test_strategy_module_portfolio_governor.py test/test_strategy_module_engine.py test/test_strategy_module_signals.py test/test_strategy_module_order_dispatch.py
git commit -m "feat(strategy): govern automated live entries"
```

### Task 3: WhatsApp strategy lifecycle alerts

**Files:**
- Create: `services/strategy_module/lifecycle_events.py`
- Modify: `services/strategy_module/engine.py`
- Modify: `services/strategy_module/signals.py`
- Modify: `services/strategy_module/scheduler.py`
- Modify: `services/strategy_module/recovery.py`
- Modify: `services/strategy_module/order_events.py`
- Modify: `blueprints/strategy_module.py`
- Modify: `services/whatsapp_alert_service.py`
- Test: `test/test_strategy_module_lifecycle_alerts.py`

**Interfaces:**
- Produces: `record_and_notify(strategy_id, user_id, kind, message, **fields)`.
- Produces: `WhatsAppAlertService.send_strategy_lifecycle_alert(user_id, event) -> None`.
- Consumes: existing `store.record_event`, `broadcast.push_event`, paired-owner lookup, and `alert_executor`.

- [ ] **Step 1: Write RED tests for material filtering and failure isolation**

Assert that a `run_started`, governor rejection, stop, target, daily-loss lock, kill switch, and recovery failure enqueue one lifecycle alert; a routine delta does not; and a throwing WhatsApp sender does not change the return from `record_and_notify`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest -q test/test_strategy_module_lifecycle_alerts.py`

- [ ] **Step 3: Implement the lifecycle event wrapper**

The wrapper records the event first, broadcasts it second, then submits a best-effort WhatsApp task only when `kind` is in an explicit material-event allowlist. Return the event row even if broadcast or notification fails.

- [ ] **Step 4: Implement plain-text WhatsApp lifecycle formatting**

Messages must contain strategy name/id, mode when available, event summary, IST timestamp, and action required for critical events. Do not duplicate symbol/quantity/order-id fields already emitted by generic accepted-order alerts.

- [ ] **Step 5: Replace material direct event writes at the service boundary**

Use the wrapper in engine, signals, scheduler, recovery, order events, and lifecycle routes for the material allowlist. Leave high-frequency and purely diagnostic events on the existing DB/broadcast path.

- [ ] **Step 6: Verify GREEN**

Run: `uv run pytest -q test/test_strategy_module_lifecycle_alerts.py test/test_strategy_module_engine.py test/test_strategy_module_signals.py test/test_strategy_module_recovery.py test/test_strategy_module_order_events.py test/test_strategy_module_lifecycle_api.py`

- [ ] **Step 7: Commit**

```bash
git add services/strategy_module/lifecycle_events.py services/strategy_module/engine.py services/strategy_module/signals.py services/strategy_module/scheduler.py services/strategy_module/recovery.py services/strategy_module/order_events.py blueprints/strategy_module.py services/whatsapp_alert_service.py test/test_strategy_module_lifecycle_alerts.py
git commit -m "feat(strategy): send lifecycle WhatsApp alerts"
```

### Task 4: Idempotent sandbox starter pack

**Files:**
- Create: `services/strategy_module/starter_pack.py`
- Modify: `blueprints/strategy_module.py`
- Test: `test/test_strategy_module_starter_pack.py`

**Interfaces:**
- Produces: `starter_definitions() -> tuple[dict, ...]` and `install(user_id: str) -> InstallResult`.
- Reuses: `validate_strategy_config`, `store.create_strategy`, and the store's unique `(user_id, name)` constraint.

- [ ] **Step 1: Write RED tests for all six definitions**

For every definition, call the real validator and assert no error, `scheduler is None`, positive stop and target, target/stop at least 1.5, and a positive daily loss limit. Assert cash templates use `strategy_kind == "signal"`; assert reusable NIFTY option templates use `strategy_kind == "batch"` with dynamically resolved ATM legs rather than an expiring exact symbol.

- [ ] **Step 2: Write RED installation tests**

The first call creates six stopped strategies with `live_enabled is False`; the second creates zero, returns six existing entries, does not rotate any token, and leaves no run rows.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `uv run pytest -q test/test_strategy_module_starter_pack.py`

- [ ] **Step 4: Implement fixed, validated definitions**

Each definition is an ordinary validated Strategy Module payload with `pricetype="MARKET"`, `strategy_type="intraday"`, `entry_time="09:20"`, `exit_time="15:20"`, no scheduler, and conservative per-leg stop/target fields. Cash templates use exact liquid symbols and signal-mode unit quantities. NIFTY option templates use batch-mode weekly ATM legs and one lot so contract resolution rolls through the existing master-contract logic instead of storing an expiring symbol.

- [ ] **Step 5: Add the authenticated install route**

Add `POST /strategy/api/automation/starter-pack`. Return `201` when any rows were created and `200` when all already existed. Response fields are `created`, `existing`, and one-time `webhook_tokens` for created rows only.

- [ ] **Step 6: Verify GREEN and regression tests**

Run: `uv run pytest -q test/test_strategy_module_starter_pack.py test/test_strategy_module_api.py test/test_strategy_module_db.py`

- [ ] **Step 7: Commit**

```bash
git add services/strategy_module/starter_pack.py blueprints/strategy_module.py test/test_strategy_module_starter_pack.py
git commit -m "feat(strategy): add sandbox starter pack"
```

### Task 5: Automation safety controls in the Strategies UI

**Files:**
- Modify: `frontend/src/api/strategy_module.ts`
- Modify: `frontend/src/types/strategy_module.ts`
- Create: `frontend/src/pages/strategy/AutomationSafetyCard.tsx`
- Create: `frontend/src/pages/strategy/AutomationSafetyCard.test.tsx`
- Modify: `frontend/src/pages/strategy/List.tsx`
- Modify: `frontend/src/pages/strategy/List.test.tsx`

**Interfaces:**
- Consumes the live-authorization status/grant/revoke routes and starter-pack install route.
- Produces a self-contained safety card embedded above the saved-strategies table.

- [ ] **Step 1: Write RED component tests**

Test inactive and active authorization states, expiry rendering, grant confirmation, revoke confirmation, starter-pack review text, created/existing results, query invalidation, API errors, and links to `/agent` and `/flow`.

- [ ] **Step 2: Run Vitest and verify RED**

Run: `cd frontend && npm test -- --run src/pages/strategy/AutomationSafetyCard.test.tsx`

- [ ] **Step 3: Add exact API types and calls**

```typescript
export interface LiveAuthorizationStatus {
  active: boolean
  session_day: string
  expires_at: string
}

export interface StarterPackInstallResult {
  created: StrategySummary[]
  existing: StrategySummary[]
  webhook_tokens: Record<string, string>
}
```

Implement `getLiveAuthorization`, `grantLiveAuthorization`, `revokeLiveAuthorization`, and `installStarterPack` using the existing API client and error normalization.

- [ ] **Step 4: Implement the safety card**

Show all safety gates, policy defaults, and the statement "Installing does not start trading." Grant requires a destructive confirmation dialog. Starter-pack install requires a review dialog and never calls a start, live-toggle, or activation endpoint.

- [ ] **Step 5: Embed the card and verify GREEN**

Run:

`cd frontend && npm test -- --run src/pages/strategy/AutomationSafetyCard.test.tsx src/pages/strategy/List.test.tsx`

- [ ] **Step 6: Run frontend typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/strategy_module.ts frontend/src/types/strategy_module.ts frontend/src/pages/strategy/AutomationSafetyCard.tsx frontend/src/pages/strategy/AutomationSafetyCard.test.tsx frontend/src/pages/strategy/List.tsx frontend/src/pages/strategy/List.test.tsx
git commit -m "feat(strategy): add automation safety controls"
```

### Task 6: Documentation and end-to-end verification

**Files:**
- Modify: `docs/api/strategy-services/README.md`
- Modify: `docs/whatsapp.md`
- Test: `test/test_strategy_module_docs.py`

**Interfaces:**
- Documents the user-visible gates and the separation between AI analysis, Flow activation, Strategy Module execution, and live authorization.

- [ ] **Step 1: Write a RED documentation contract test**

Extend the existing docs test to require links or headings for session live authorization, portfolio governor, starter pack, WhatsApp lifecycle alerts, and the statement that exits remain allowed after revocation.

- [ ] **Step 2: Run the docs test and verify RED**

Run: `uv run pytest -q test/test_strategy_module_docs.py`

- [ ] **Step 3: Update operator documentation**

Document the UI sequence: install pack, configure Flow/AI signal producer, test in sandbox, review WhatsApp, enable the individual strategy, authorize live automation for the session, and monitor/kill-switch. State every default limit and reset condition.

- [ ] **Step 4: Run complete backend verification**

Run: `uv run pytest -q test/test_strategy_module_*.py test/test_whatsapp*.py`

- [ ] **Step 5: Run complete frontend verification**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run lint`

- [ ] **Step 6: Run formatting and static checks**

Run: `uv run ruff check services/strategy_module blueprints/strategy_module.py services/whatsapp_alert_service.py test/test_strategy_module_*.py && uv run ruff format --check services/strategy_module blueprints/strategy_module.py services/whatsapp_alert_service.py test/test_strategy_module_*.py`

- [ ] **Step 7: Commit**

```bash
git add docs/api/strategy-services/README.md docs/whatsapp.md test/test_strategy_module_docs.py
git commit -m "docs(strategy): explain automated safety controls"
```
