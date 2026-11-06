# Delta Backend Auto Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans task by task. Approved design execution is authorized; do not ask for approval again.

**Goal:** Move existing 1m/5m Long/Short Auto to the local backend with durable context memory and safe restart recovery.
**Architecture:** Pure Python decision module; SQLite-bound automation coordinator/daemon through existing TradingService; authenticated configuration/status; chart controls become backend client. Existing protection worker and broker order ledger remain authoritative.
**Tech Stack:** Python Decimal/sqlite/threading, Flask, React/TypeScript.
**Spec:** docs/plans/2026-11-02-delta-continuous-trading-design.md (user explicitly approved 2 November).

## Global Constraints
- One account trade/order at a time; maker entries, reduce-only market risk exits.
- 1m EMA9/15 with agreeing 5m; closed fresh contiguous evidence; optional candle patterns.
- ₹20 planned max loss incl standard fees; 2R reference (not an executable TP in trend mode); 50x/100% defaults editable.
- Latest amendment: trend-mode candle/ATR trailing replaces fixed rupee giveback. At least ₹15 verified net peak, then wait for structural SL to cover ₹10 net; no synthetic ₹10 pullback exit. Existing stop never loosens.
- Unknown requests reconcile, never blindly retry. Existing 15s unfilled Auto TTL and durable idempotency retained.
- Never use real orders as tests. No agent-driven Auto arming. Existing explicit Auto On may migrate only through authenticated browser handoff.

## Review Focus
- Two tabs/processes and Off during preflight: one backend executor and no posts after acknowledged Off.
- Restart/credential binding/partial or unknown fills: fail closed; preserve broker protection.
- Gapped/malformed/forming/late candles: no invented confirmations.
- Decimal ticks, fee credits, promotions and tiny balances: conservative validated money/size.
- Missing browser and changed chart timeframe: persisted worker startup/context continues independently.

### Task 1: Pure strategy and parity tests
Files: services/delta_chart/auto_strategy.py; test/test_delta_auto_strategy.py.
Interface: decide(state, fast_candles, slow_candles, settings, observed_at, now) -> {context, action?, reason}; raw UTC OHLC, state same service.state, settings leverage/balance_fraction/manual_quantity. action omits account/request_id/symbol; coordinator supplies binding. context contains source_time, direction, higher_direction, trend_summary, support/resistance, patterns, bars counts. Never financial side effects.
- [ ] Add failing tests for both sides, closed fresh55+bars, no-pattern entry, ATR/SR/anti-chase, 2R, decimal ticks, sizing/₹20/fees.
- [ ] Implement same EMA engine and frontend strategy math using Decimal.
- [ ] Verify tests and compare golden frontend fixture calculations.

### Task 2: Durable backend owner and authenticated controls
Files: services/delta_chart/automation.py; service.py; blueprints/delta_chart.py; install/lib/gunicorn_hooks.py; tests.
Interface: Automation(service).configure(user,data), status(user,account), authorize_entry(user,data), tick(); AutomationWorker.start/stop with Flask application-context factory. POST /automation accepts symbol,account,enabled,leverage,balance_fraction,manual_quantity. state.automation returns owner=backend, enabled, account,symbol,leverage,balance_fraction,manual_quantity,generation,status,message,checked_at,next_check_at,context,events.
- [ ] Failing tests: config binding/limits; durable startup; unknown outcomes, Off/generation revocation, two process/tab ownership, one source attempt, no management blockage.
- [ ] Persist configuration, latest context and bounded events. Deterministic attempt IDs and digest-binding; all orders through TradingService.
- [ ] Start worker after Gunicorn app init and inside Flask app context; signal entry worker stopped on shutdown. Never arm from startup absent saved enabled config.
- [ ] API CSRF/session tests, read-only state, action owner guard. Record optional completed-trade outcomes from exact owned fill IDs with verified fees.

### Task 3: Backend UI controls
Files: frontend/src/components/neo-desk/DeltaBackendAuto.tsx/.test.tsx; api/deltaChart.ts; DeltaTradePanel.tsx and tests.
- [ ] New compact component consumes state.automation, configure callback API, selected leverage/fraction/lots.
- [ ] Switch enables backend or disables it; status direction, last-check age, next-check and blocking reason, expandable memory events. Default browser-only Auto UI remains only for old API/test compatibility.
- [ ] Once backend capability present, disable browser auto effects/recovery. Migrate existing explicitly saved local Auto On once through authenticated configure; failed/unknown handoff does not arm browser. Preserve off choice and account/symbol binding.
- [ ] Disable manual entries while backend enabled; no change to close/SL controls; tests for controls and malformed/offline state.

### Task 4: Verification and release
- [ ] Full existing Delta backend/frontend regressions plus new tests, typecheck/build, read-only live shadow signal checks.
- [ ] Independent bounded review; address findings before publication.
- [ ] Hash verified source release, retained assets/index last, inspect broker protection/unknown intents before graceful reload.
- [ ] Confirm healthy process, new assets, persisted settings and startup behavior without agent enabling Auto or placing orders. Document limits: local machine awake/network needed; no profitability or millisecond-feed guarantee.


## Later user amendments (authoritative)

The user requested additional source-inspired crypto strategies and then replaced mandatory 2R exits with trend management. EMA, liquidity sweep, FVG/MSS, breakout/retest, range RSI, double extrema and EMA/Fibonacci can propose entries under the same account/risk gates. Conflicting eligible directions wait. No fixed TP is created for new trend-mode plans; existing owned TP cancellation requires verified live SL and exact terminal TP proof. At 23:00 IST the latest request replaced a fixed ₹10 trailing gap with completed candle/volatility structure, delaying the ₹10 lock until feasible. These numeric source adaptations have mechanics tests, not established profitable performance.
