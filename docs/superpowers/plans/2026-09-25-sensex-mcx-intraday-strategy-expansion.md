# SENSEX and MCX Intraday Strategy Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six exchange-aware SENSEX and MCX intraday strategies and workflows, activate them in sandbox, and extend portfolio risk controls and lifecycle status without weakening live-trading gates.

**Architecture:** Extend the existing Strategy Module starter pack, dynamic option resolver, Flow engine, exchange calendar, portfolio governor, and WhatsApp lifecycle path. Do not create another scheduler, order engine, market-data client, or notification transport. Contract resolution remains runtime and instrument-master-backed; workflows only produce deterministic signals into the Strategy Module.

**Tech Stack:** Python 3.13, Flask, SQLAlchemy, pytest, React 19, TypeScript, Vitest, existing OpenAlgo Strategy Module and Flow services.

**Spec:** `docs/superpowers/specs/2026-09-25-sensex-mcx-intraday-strategy-expansion-design.md`

## Global constraints

- New templates are intraday, long-option-only, stopped/live-disabled when installed, and sandbox when run.
- SENSEX uses BSE_INDEX/BFO; GOLDM, CRUDEOILM, SILVERM, and NATGASMINI use MCX/MCX.
- Expiry, symbol, lot size, and tick size are resolved at runtime from the instrument master.
- Completed five-minute and fifteen-minute data drive signals; stale or incomplete data produces no entry.
- Existing six starter strategies and user workflows are preserved.
- The portfolio governor never blocks exits and current NIFTY-compatible fields remain readable during migration.
- Activation of the new workflows is sandbox-only; live entries still require per-strategy opt-in and session authorization.

### Task 1: Extend the safe starter strategy pack

**Files:**
- Modify: `services/strategy_module/starter_pack.py`
- Modify: `test/test_strategy_module_starter_pack.py`

- [ ] Write failing tests for two SENSEX and four MCX dynamic option templates.
- [ ] Assert exchange, underlying, expiry cycle, intraday times, long-only option leg, stop/target ratio, and absence of literal option symbols.
- [ ] Implement an exchange-aware option-definition helper and add the six definitions without changing existing names.
- [ ] Verify idempotent installation creates twelve total templates and never starts or live-enables them.
- [ ] Run `uv run pytest -q test/test_strategy_module_starter_pack.py`.

### Task 2: Generalize derivative exposure governance

**Files:**
- Modify: `services/strategy_module/portfolio_governor.py`
- Modify: `test/test_strategy_module_portfolio_governor.py`
- Modify as required: `test/test_strategy_module_engine.py`, `test/test_strategy_module_signals.py`, `test/test_strategy_module_recovery.py`

- [ ] Write failing pure-policy tests for NIFTY, SENSEX, MCX, and combined derivative limits.
- [ ] Add derivative bucket classification and counters to facts and durable reservation components while accepting legacy NIFTY-only payloads.
- [ ] Enforce one NIFTY, one SENSEX, one aggregate MCX, and two total derivative positions.
- [ ] Preserve exit bypass, reservation reconciliation, and concurrent admission behavior.
- [ ] Apply stricter configurable option-risk admission to SILVERM and NATGASMINI.
- [ ] Run focused governor, engine, signal, and recovery suites.

### Task 3: Add idempotent sandbox workflow installation

**Files:**
- Create: `services/strategy_module/starter_workflows.py`
- Modify: `services/strategy_module/starter_pack.py`
- Modify: `blueprints/strategy_module.py`
- Test: `test/test_strategy_module_starter_workflows.py`
- Reuse: `database/flow_db.py`, `services/flow_workflow_validator.py`, `services/flow_scheduler_service.py`

- [ ] Write failing tests for six valid workflow graphs and idempotent name matching.
- [ ] Build five-minute aligned, market-hours-only workflow definitions with BFO/MCX exchange metadata and completed-candle checks.
- [ ] Route valid signals to the corresponding Strategy Module webhook surface; keep order placement inside Strategy Module.
- [ ] Store new workflows inactive during creation, then expose an explicit sandbox activation operation that registers the existing scheduler with the current API key.
- [ ] Ensure missing broker/API-key/contract data fails with an actionable inactive or no-trade status rather than partial activation.
- [ ] Run workflow validator, scheduler, market-hours, and new installer tests.

### Task 4: Surface lifecycle, last decision, and WhatsApp status

**Files:**
- Modify as required: `services/strategy_module/lifecycle_events.py`
- Modify as required: `services/whatsapp_alert_service.py`
- Modify: `frontend/src/pages/strategy/List.tsx`
- Modify: `frontend/src/pages/strategy/List.test.tsx`
- Modify: `frontend/src/pages/strategy/AutomationSafetyCard.tsx`
- Modify: `frontend/src/pages/strategy/AutomationSafetyCard.test.tsx`

- [ ] Write failing tests for material contract/liquidity/risk rejection messages and daily summaries.
- [ ] Reuse the non-blocking lifecycle notification path; do not send routine no-signal messages.
- [ ] Show exchange, sandbox/live state, workflow activation, last evaluation, resolved contract when available, and last rejection reason.
- [ ] Replace fixed six-template UI language with dynamic starter-pack counts.
- [ ] Run focused backend notification tests and frontend Vitest suites.

### Task 5: Migrate, verify, and activate sandbox workflows

**Files:**
- Modify: `upgrade/migrate_strategy_module.py`
- Modify: `test/test_migrate_strategy_module.py`
- Update: relevant API and operator documentation

- [ ] Write a failing migration test proving existing users receive only missing definitions/workflows without duplication or live enablement.
- [ ] Implement a rerunnable migration/installer step that preserves existing strategies and workflows.
- [ ] Run the complete backend and frontend test suites.
- [ ] Restart the application and verify Strategies, Flow, WhatsApp, broker connection, positions, and orders from the authenticated UI.
- [ ] Activate only the six new workflows in sandbox and confirm their schedules are registered.
- [ ] Confirm no live authorization is implicitly granted and no order is placed during verification.
