# Equity Risk and Executable Profit Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Implement the risk controls approved by the user without activating strategies or altering historical recipes.

**Architecture:** Add a versioned equity policy and technical-stop recipe, keeping prior policy/recipe implementations available for reproducible research and recovery. Persist day-opening equity under the account lock. Use fresh executable bids for the new recipe and reconcile broker stop modifications before accepting protection.

**Tech Stack:** Python, SQLAlchemy, Flask, React/TypeScript, pytest, Vitest.

**Spec:** Approved recommendations recorded below; user instruction: implement them to better manage risk and profit.

## Global Constraints / Design

- New policy `equity-1pct-v2`: all-in planned loss <= min(1% current equity, INR300); 50% risk at >=5% peak-equity drawdown; pause at >=8%.
- Daily loss allowance = min(3% persisted session-opening equity, INR2000). Profits never replenish spent loss allowance. Stop after three consecutive net losses. One pending/open managed position per account/mode.
- Current saved allocations are preserved. Capital allocation changes cannot enlarge an already-established day allowance. New policy never silently rewrites open legacy exposure.
- New recipe `one-lot-technical-profit-trail-v3`: technical stop rounded away from entry to the price tick, then whole-lot sizing/admission. Skip unaffordable risk; no artificial stop tightening. Keep prior fixed-cash and profit-v2 math reproducible.
- Keep INR300/600 baseline profit ratchet, no hard take-profit, no wider stop, no averaging down. Research-only volatility trail cannot become production default from this task.
- New recipe exits/profit ratchets use fresh bid and sufficient depth; stale/incomplete data stops new entries and cannot create fictitious profit. Preserve emergency exits and broker fallback protection.
- Kotak stop ratchets persist intent before dispatch, verify broker trigger/remaining quantity afterward, reconcile uncertain outcomes without blind retries, and retain exit ownership under partial-fill/cancel races.
- Preserve all activation states, live release checks, qualification requirements, fee schedules, and historical results. No real orders in verification.

## Review Focus

- Midnight/restart/allocation changes must not replenish an already-used day budget.
- Two workers/strategies racing must not reserve two positions.
- New configuration mixed with an old recipe or artifact must fail closed.
- Broker modify timeout/partial fill must not produce a second exit or claim an unverified stop.
- Stale/wide/insufficient-depth quotes must not raise app or broker profit stops.

### Task 1: Account policy and ledger
Files: services/risk/budget.py, database/trading_risk_db.py and their tests.
Interfaces: current_policy(capital); policy_for_version(version, capital); SHARED_POLICY_VERSIONS; budget_snapshot/evaluate_budget gain optional day_start_equity keyword. Snapshots expose day_start_equity, daily_limit, per_trade_limit, risk_reduced, drawdown_pct. Existing old policy math remains selectable.
- [x] Write and run failing tests for all-in risk, 5/8% thresholds, fixed daily baseline, nonreplenishment, one-position concurrency, safe migration.
- [x] Implement policy selection, pure checks and durable session baseline.
- [x] Run budget/ledger regression tests.

### Task 2: Verified Kotak stop modifications
Files: services/strategy_module/live_protection.py, order_dispatch.py or a focused helper module, broker-stop tests. Engine integration remains with parent.
Interface: ratchet_stop(strategy, run_id, leg, client=None) or a documented equivalent callable outside the engine state lock; return explicit verified/pending/failure state and fail closed. Reuse existing protective-order ownership, persistent evidence and reconciliation patterns.
- [x] Write and run failing tests covering verified advance, no widening, timeout reconciliation, partial fill, quantity mismatch, duplicate invocation and restart.
- [x] Implement bounded verified modify without broker actions in tests.
- [x] Run protective-order/recovery tests.

### Task 3: Recipe, executable pricing, and consumer integration
Files: services/risk/cash_exit.py, profit_exit.py; research replay/ml/jobs and strategy scalping/ml/risk/engine consumers; UI risk labels.
- [x] Pin old replay geometry and failing new stop-first/quote tests.
- [x] Bind new recipes explicitly to policy versions and technical stops; adapt admission/replay day baseline, live qualification and recovery.
- [x] Validate fresh bid/depth on new managed option recipe; wire broker ratchet outside locks.
- [x] Show dynamic actual account limits with clear all-in scope, one-position restriction and drawdown thresholds.
- [x] Run regression tests and build frontend.

### Task 4: Evidence and release
- [x] Compare baseline/new risk/volatility variant on identical frozen development signals and costs, preserving sealed final sessions. Report losses and skips honestly.
- [x] Run broad backend/affected frontend tests, isolated UI checks and independent code review; fix actionable findings.
- [x] Publish verified changes to main, verify runtime and unchanged activation/cost/allocation state; document limitations.

## Execution Ledger
- 2026-09-28: Reused clean project-local isolated worktree, fast-forwarded to 570111b35 and created codex/risk-profit-hardening. No production changes yet.
- Ruling: risk reduction means halving the current per-trade budget at 5% drawdown; this is conservative and does not change trade signals. Daily baseline remains fixed even if allocation is increased during the session.
- User steering: new recipe must protect INR900 gross at INR1000 executable gross peak; thereafter use max(INR900, peak minus INR300). INR1500 -> INR1200, INR1800 -> INR1500. Never lower a stop; charges/slippage mean this is a planned gross floor, not a guaranteed realization. Old v2 remains unchanged.

- Verification: 4267 backend passed,16 skipped,1 expected failure;61 affected frontend passed;TypeScript/Vite/Ruff passed. Independent P1 recovery finding fixed with RED/GREEN test and scoped re-review. Thirty frozen-signal replays saved; no profitability claim or live activation.
