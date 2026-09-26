# Rules-based profit research platform implementation plan

> Implement the design approved in this conversation. Use test-driven development and independent code review. The user requested implementation after reviewing the platform plan and the article-to-feature mapping.

**Goal:** Build reproducible, cost-aware trading research and enforce the user's shared capital limits through the existing Strategy Module execution path.

**Architecture:** Keep pure risk decisions in `services/risk`, persist independent risk evidence, and integrate through the existing portfolio governor and managed exits. Add immutable research datasets and versioned deterministic experiments in a separate bounded worker, exposed through authenticated Strategy APIs and a Research page. Research never imports a live order dispatcher.

**Constraints:** ₹10,000 allocation; first filled trade has ₹1,000 planned-loss allowance; every subsequent trade shares another ₹1,000; no replenishment by profits and no transfer between buckets; ₹2,000 daily total; 20% persistent peak-equity drawdown pause. Costs count toward risk and net outcomes. Whole lots, verified multipliers, 20% cash buffer. At most one index and one MCX position, two derivatives total. Existing broker/session authorization and protective stops remain mandatory. No live activation or data purchase. Preserve unrelated broker reconnect edits.

## Tasks

- [x] 1. Add a pure budget policy and durable risk ledger, with tests for the exact daily buckets, no-fill attempts, pending reservations, loss overruns, restarts, daily rollover and persistent drawdown.
- [x] 2. Integrate the ledger with Strategy Module admissions and monitoring. Snapshot fills and costs without relying on deletable run history; fail closed on unknown outcomes. Add authenticated risk status and explicitly reviewed pause recovery. Existing managed exits remain the only exit path.
- [x] 3. Add immutable, provenance-bearing datasets and deterministic research replay. Include baseline trend/breakout rules and an explicit VWAP pullback candidate; use closed underlying bars and subsequent option executions. Require point-in-time contracts and model per-order costs. Unsupported/insufficient inputs must be visible, never fabricated.
- [x] 4. Persist bounded research jobs with cancellation and restart recovery. Separate development and final evaluation; consume final holdout only after version freeze. Report net expectancy, profit factor, drawdown, exposure and execution stress. Paper evidence and release approvals bind exact versions; no backtest alone enables live entry.
- [x] 5. Add a Strategy Research interface for dataset import, candidate rules, experiment controls, cost assumptions, reports and qualification status. Show the user's separate daily budgets and distinguish unavailable evidence from zero results.
- [x] 6. Verify focused backend and frontend tests, relevant existing execution tests, frontend build, resource lifetime audit, and independent review. Record limitations explicitly; no profit claim without real data and forward evidence.

## Interfaces and review focus

Risk policy and budget evaluation are pure dataclasses/functions. Persistence must use repository SQLAlchemy engine/session conventions and atomic transactions. One scope identifies user and execution mode; broker-specific evidence cannot multiply the user's allocation. A trade is a filled position lifecycle; partial fills do not create fresh budgets. Unknown dispatch outcomes retain reservations.

Research APIs use authenticated user ownership and JSON response envelopes consistent with Strategy APIs. Workers are separate OS processes, with no unbounded per-request executors, open pipes or in-memory job registries. Dataset versions are immutable and tied to reports. Candle-only data cannot qualify a strategy for live release. Missing costs or contract metadata cannot silently become zero.

Review especially: concurrent first-trade reservation, stale/unknown order state, strategy deletion/sandbox reset, final-test reuse, broker reconnect or code/config changes invalidating approvals, data imported with future timestamps, and partial fills counted as extra orders.

## Verification ledger

- Initial state: branch `codex/repair-installed-flows`, HEAD `b97c3c239`; unrelated edits in `blueprints/brlogin.py` and `test/test_kotak_reconnect.py` are excluded from this work.
- Approved conversation design is the spec; this file records implementation tasks without repeating the full design in another document.


## Delivered scope

The allocation is an explicit per-user profile enabled by saving costs in Research; existing generic cash/short/multileg flows retain their legacy governor until activation. Task 4 is complete through the [forward qualification implementation](2026-09-26-forward-qualification.md): durable prospective collection, executable quotes, conservative costs/stress, fixed eligibility checks, reconciliation and version-bound reviewed approvals now replace the permanent denial. An eligible approved campaign can pass live admission while the existing daily authorization, Flow activation, broker pin and protective-stop controls remain required. No profitability claim, real-data result, broker activation or deployment is part of this change.

Independent review found and drove fixes for late corrective fills, target/stop gaps, marked-equity drawdown, migration configuration loading, cancellation/completion races, broker position identity, order dispatch timing, cash commitments on partial fills, stale reconciliation snapshots and bounded retries. Tests demonstrate both orders of the reconciliation race. Production monitoring only reconciles active positions and skips unchanged evidence.


### Foundation checks (before forward qualification)

- Final focused backend command (risk, research, migrations, engine, signals, governor, segment/edge QA, webhooks, residual safety and docs): **608 passed, 1 expected failure**.
- Full backend run before final targeted fixes: **5,975 passed, 30 failed, 29 skipped, 1 expected failure, 11 errors**. The one documentation source-anchor regression was fixed and its suite passes. The remaining **29 failures** reproduced at unchanged HEAD in an isolated `/private/tmp` checkout: 19 automation-control cases, 3 Telegram cases, 7 TradeSmart rate-limiter cases. Eleven OpenScript teardown errors are macOS sandbox `sysctl` process-enumeration denials. Full-suite green is not claimed.
- Frontend full suite: **2,754 passed** with `NODE_OPTIONS=--no-experimental-webstorage` for Node 26 compatibility. The final session-open template edit passed its **18 focused Research tests**. Production build and scoped formatting pass.
- Required migration is idempotent, preserves existing account peak/pause evidence and imports without an exported DATABASE_URL. Direct Research bookmarks resolve to the SPA.
- Risk ledger resource audit: **900 transactions**, file descriptors **4 to 4**, SQLite **NullPool**. Research agent independently audited 600 DB operations without FD growth. Scoped Ruff and `git diff --check` pass.
- Independent reviewer rechecked both reconciliation interleavings and the broker/dispatch/cash fixes; no blocking finding remains in that reviewed scope.
- Application and worker were not started or restarted, profile was not enabled, and broker orders were not sent. No commit or deployment was made. Locally built frontend artifacts remain available; CI supplies tracked production bundles.
