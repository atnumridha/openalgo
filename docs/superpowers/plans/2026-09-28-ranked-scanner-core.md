# Ranked Opportunity Scanner Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let all enabled managed strategies compare fresh opportunities every second and admit top-ranked matches under existing per-mode budget and risk rules.

**Architecture:** Add a pure candidate/ranking layer and a bounded owner/mode scanner over the existing Strategy Module feed, signal, governor, and engine. Strategy providers retain their own signals and produce several instrument choices; the coordinator ranks them, then revalidates and admits each candidate serially. This plan ships existing-strategy scanning only; the Kotak-style basket catalog and multi-leg risk extension are in the companion plan.

**Tech Stack:** Python/Flask/SQLAlchemy, existing OpenAlgo/Kotak WebSocket feed and Strategy Module, pytest, React/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-09-28-ranked-opportunity-scanner-design.md`

## Global Constraints

- Target one decision cycle per second from fresh data, not one trade or broker update per second.
- An enabled strategy is armed or actively scheduled; installation, saving and deployment never arm or change mode.
- Preserve existing signals, closed-bar rules, broker/account pins, Sandbox/Live separation, research release, live authorization, stops, session windows, and risk ceilings.
- Missing quote, cost, unit, order-state, or admission evidence blocks new entries while exits remain available.
- No new Redis service or second order executor; no unbounded market-wide REST polling.
- Do not alter the current dirty working-tree files except after examining their existing changes and explicitly merging a scoped edit.
- No real broker orders during implementation or verification.

## Review Focus

1. A quote arriving out of order or with a future exchange timestamp must not make a candidate fresh; Task 2 tests this.
2. Two workers ranking the same signal at once must not dispatch two entries; Task 4 tests this.
3. A lower-ranked candidate must be rechecked after a higher-ranked fill reserves capital; Task 4 tests this.
4. A receiver with no external signal must not invent an entry from a good-looking option; Task 3 tests this.
5. Live authorization expiring between rank and dispatch must stop that entry without blocking exits; Task 5 tests this.

---

## File map

- Create `services/strategy_module/opportunity_model.py`: immutable `Opportunity` and exclusion types.
- Create `services/strategy_module/opportunity_ranker.py`: deterministic comparable scoring and stable sort.
- Create `services/strategy_module/opportunity_market.py`: bounded discovery, quote snapshot and feed health; reuse `tick_feed.py` subscription plumbing without changing its protective-exit priority.
- Create `services/strategy_module/opportunity_providers.py`: provider protocol and registry for existing managed strategy families.
- Create `services/strategy_module/opportunity_coordinator.py`: owner/mode cycles, claim, ranking and admission loop.
- Modify `database/strategy_module_db.py` and add a migration under `upgrade/`: durable candidate claim and scanner settings; use the repo's migration registration pattern.
- Modify `services/strategy_module/engine.py`, `automation_control.py`, `scalping.py`, `receiver.py`, `portfolio_governor.py` only at their existing entry boundaries.
- Modify `blueprints/strategy_module.py`, `frontend/src/api/strategy_module.ts`, and existing Strategy Module review components for arm/configuration/status.
- Create focused `test/test_strategy_module_opportunity_*.py` and UI tests alongside existing Strategy Module tests.

### Task 1: Candidate contract and ranker

**Files:** Create `services/strategy_module/opportunity_model.py`, `services/strategy_module/opportunity_ranker.py`, `test/test_strategy_module_opportunity_ranker.py`.

**Interfaces:** Produce frozen `LegIntent(exchange: str, symbol: str, side: str, quantity: int, option_type: str | None, strike: Decimal | None, expiry: date | None, lot_size: int, multiplier: Decimal)` and frozen `Opportunity(owner: str, strategy_id: int, mode: str, broker_connection_id: str, signal_key: str, strategy_version: str, legs: tuple[LegIntent, ...], observed_at: datetime, signal_strength: Decimal, net_reward_risk: Decimal, execution_quality: Decimal, source: str)`. Produce `rank_opportunities(candidates: Iterable[Opportunity]) -> list[Opportunity]`. Score version `rank-v1`: `0.5*signal_strength + 0.3*min(net_reward_risk/3, 1) + 0.2*execution_quality`; require finite signal/execution scores in `[0,1]` and positive finite net R. Existing binary signals may report strength `1` rather than invent a probability. Stable ties use strategy ID, signal key and leg identity.

- [ ] **Step 1: Write failing tests** named `test_rank_v1_order_and_ties`, `test_invalid_score_evidence`, `test_mixed_mode_rejected`: `assert [x.signal_key for x in rank_opportunities(candidates)] == ["best", "tie_a", "tie_b"]`; `assert` invalid decimals raise `ValueError`; `assert` mixed modes raise `ValueError`.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_opportunity_ranker.py`; expect failure for missing module.
- [ ] **Step 3: Implement** the frozen type, validation, `rank_opportunities`, and an explicit `RANK_VERSION` constant. Keep scoring pure and document its exact formula in this module and its test.
- [ ] **Step 4: Run** the same command; expect all tests pass.
- [ ] **Step 5: Commit** only the new modules and their test.

### Task 2: Bounded market snapshots

**Files:** Create `services/strategy_module/opportunity_market.py`, `test/test_strategy_module_opportunity_market.py`; modify `services/strategy_module/tick_feed.py` only to expose a safe scanner subscription/snapshot adapter.

**Interfaces:** Produce `MarketSnapshot(as_of: datetime, contracts: tuple[dict, ...], feed_state: str, discovery_version: str, entry_eligible: bool)` and `OpportunityMarket.refresh_universe(owner, broker_connection_id, allowed_exchanges) -> None`, `OpportunityMarket.snapshot(owner, broker_connection_id, now) -> MarketSnapshot`. Inputs use verified instrument-master metadata and current quote timestamps; shortlist capacity and subscription pacing are configuration bounds, not unlimited defaults. Protective-exit subscriptions have priority.

- [ ] **Step 1: Write failing tests** named `test_bounded_fresh_snapshot` and `test_bad_feed_never_enters`: `assert len(snapshot.contracts) <= configured_cap`; `assert not snapshot.entry_eligible` after stale/crossed/future/out-of-order/missing quotes or 429; `assert protective_symbols <= subscribed_symbols` after reconnect. Parameterize exact NSE/BSE/MCX and changed-expiry/lot fixtures.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_opportunity_market.py`; expect missing interface failures.
- [ ] **Step 3: Implement** discovery cache and snapshot adapter using existing market-data clients; cap REST batches at the repo's conservative Kotak size and never use fallback data newer than its source timestamp.
- [ ] **Step 4: Run** the focused test plus `pytest -q test/test_strategy_module_tick_feed.py`; expect pass.
- [ ] **Step 5: Commit** only this adapter and tests.

### Task 3: Providers for every existing managed family

**Files:** Create `services/strategy_module/opportunity_providers.py`, `test/test_strategy_module_opportunity_providers.py`; modify `services/strategy_module/scalping.py`, `receiver.py`, and existing ML/batch signal adapters as needed after enumerating every family from `database/strategy_module_db.py` and `automation_control.py`.

**Interfaces:** `ProviderResult(candidates: tuple[Opportunity, ...], exclusions: tuple[str, ...])`; `CandidateProvider.propose(strategy: dict, signal: dict | None, market: MarketSnapshot) -> ProviderResult`; `provider_for(strategy: dict) -> CandidateProvider`. Providers may produce multiple contracts only within saved allowed universe and original signal direction; no signal returns empty candidates. Unsupported legacy config returns an exclusion, not a silently unranked live entry.

- [ ] **Step 1: Write failing parameterized tests** named `test_each_enabled_family_proposes_multiple_contracts` and `test_signal_constraints_remain_authoritative`: `assert len(provider_for(strategy).propose(...).candidates) >= 2` for a prepared valid universe; `assert provider_for(strategy).propose(...).candidates == ()` for absent/stale/wrong-direction signals or disallowed broker/universe. Compare existing indicator fixture output before and after adaptation.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_opportunity_providers.py`; expect missing providers.
- [ ] **Step 3: Implement** the registry and family adapters. Factor contract choice after each family's established signal calculation; do not replace the signal or invent a universal bullish/bearish predictor.
- [ ] **Step 4: Run** the focused test plus `pytest -q test/test_receiver_integration.py test/test_strategy_module_scalping.py test/test_strategy_module_signals.py`; expect pass.
- [ ] **Step 5: Commit** only provider integration and tests.

### Task 4: Durable ranked coordinator

**Files:** Create `services/strategy_module/opportunity_coordinator.py`, `test/test_strategy_module_opportunity_coordinator.py`; modify `database/strategy_module_db.py`; add/register the corresponding migration under `upgrade/`.

**Interfaces:** `run_cycle(owner: str, mode: str, now: datetime) -> CycleReport`; `CycleReport(scope: str, ranked_ids: list[str], admitted_ids: list[str], rejected: dict[str, str])`. One owner/mode lease gates a cycle; a durable unique claim uses owner, mode, strategy ID, signal key, rule version and exact contract/leg identity. Store only claims/audit, not an executable backlog. Revalidate remaining opportunities after every admitted entry.

- [ ] **Step 1: Write failing tests** named `test_ranked_budget_admissions`, `test_concurrent_cycle_claim`, `test_rerank_not_backlog`: `assert report.admitted_ids == [top_id, affordable_next_id]`; `assert live_report.scope != sandbox_report.scope`; `assert sum(worker_orders) == 1`; `assert old_candidate_id not in next_cycle.admitted_ids`. Use an isolated migrated DB and assert claim rows contain identities, not serialized executable orders.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_opportunity_coordinator.py`; expect missing coordinator/schema failure.
- [ ] **Step 3: Implement** the claim/migration and coordinator with its own owner/mode cycle lease. The engine alone acquires the existing governor admission lease; the coordinator must not hold it when calling the engine. Persist a claim before broker side effects; release only a provably unsent claim, retain unknown outcomes for reconciliation.
- [ ] **Step 4: Run** the focused test plus `pytest -q test/test_strategy_module_portfolio_governor.py test/test_strategy_module_db.py`; expect pass.
- [ ] **Step 5: Commit** only coordinator, migration, store and tests.

### Task 5: Managed execution handoff and activation

**Files:** Modify `services/strategy_module/engine.py`, `automation_control.py`, `blueprints/strategy_module.py`; create `test/test_strategy_module_opportunity_execution.py`.

**Interfaces:** Add an internal-only `start_ranked_candidate(candidate: Opportunity, *, trigger_source: str) -> StartResult` at the engine boundary. The function re-resolves exact legs and rechecks quote, pin, signal version, live authorization, protection, risk and budget immediately before dispatch. Existing `/start` and Flow paths continue unchanged during staged rollout; at completed release every armed supported managed strategy is routed through the scanner without a second per-strategy opt-in. An already-Live-armed strategy must be stopped for rule-version/research review before it changes behavior. No user-supplied candidate can bypass provider validation.

- [ ] **Step 1: Write failing tests** named `test_arm_is_not_entry`, `test_live_recheck_before_dispatch`, `test_uncertain_entry_keeps_exits`: `assert broker.orders == []` after arm; `assert broker.orders == []` after revoked Live authorization; `assert entry_result.ok is False` for unknown prior order; `assert exit_result.ok is True` while scanner is paused. Assert stopped strategies unchanged and changed-rule Live strategies held for review.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_opportunity_execution.py`; expect failure.
- [ ] **Step 3: Implement** internal handoff and activation integration, preserving the existing per-strategy start/stop/kill-switch semantics and atomic governor reservation.
- [ ] **Step 4: Run** focused tests plus `pytest -q test/test_strategy_module_engine.py test/test_strategy_module_automation_control.py test/test_strategy_module_live_authorization.py`; expect pass.
- [ ] **Step 5: Commit** only handoff files and tests.

### Task 6: Operator configuration and audit

**Files:** Modify `blueprints/strategy_module.py`, `frontend/src/api/strategy_module.ts`, the existing Strategy Module review component(s); create `test/test_strategy_module_opportunity_api.py` and corresponding Vitest component tests.

**Interfaces:** Owner-scoped endpoints read/write scanner bounds and expose `CycleReport`/health. Bounds include allowed exchanges/underlyings, expiry range, premium/price band, minimum depth/liquidity, maximum spread, and candidate count; inherited account risk ceilings cannot be raised here. UI shows armed/mode, data age, ranked candidate provenance, reasons for no entry and order-versus-fill state.

- [ ] **Step 1: Write failing API/UI tests** named `test_scanner_settings_are_owner_scoped` and `showsScannerRejections`: `assert other_owner_get.status_code == 404`; `assert bad_bounds.status_code == 400`; `assert saved.automation_state == "disabled"`; `expect(screen.getByText(/stale quote/i)).toBeVisible()`; assert the Live badge is distinct from Sandbox.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_opportunity_api.py` and the focused Vitest file; expect failures.
- [ ] **Step 3: Implement** endpoints, serializable report and UI without adding an alternate trading action.
- [ ] **Step 4: Run** focused tests, `npm --prefix frontend run test -- --run` and `npm --prefix frontend run build`; expect pass.
- [ ] **Step 5: Commit** only the API/UI and tests.

### Task 7: Replay, regression and Sandbox release gate

**Files:** Create `test/test_strategy_module_opportunity_replay.py`; update `docs/trading-capital-profile.md` and scanner operations docs with the actual rollout flags and evidence.

**Interfaces:** A deterministic replay fixture drives simultaneous strategy signals, quotes, risk facts, orders and late fills through the real coordinator/engine with fake broker I/O. The scanner ships disabled by deployment default; after verified rollout it evaluates all already-armed supported strategies without changing their mode or arming stopped strategies. Existing Live-armed configurations are held for review before the new rule version may send orders.

- [ ] **Step 1: Write failing replay tests** named `test_replay_budget_and_faults` and `test_replay_restart_unknown_fill`: `assert replay.admitted <= GovernorPolicy().max_derivative_positions`; `assert replay.new_entries_after_outage == 0`; `assert recovered.unknown_reservations == persisted.unknown_reservations`; `assert fake_broker.real_network_calls == 0`. Include simultaneous family signals, cooldown/drawdown, quote churn and late/partial fills.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_opportunity_replay.py`; expect failures.
- [ ] **Step 3: Complete** replay integration, release flag and operator documentation; do not loosen any account policy to make a fixture pass.
- [ ] **Step 4: Run** focused tests, then all Strategy Module/risk backend tests, UI tests and TypeScript build in a clean test environment. Record exact commands/results; inspect the scoped diff and the unrelated dirty files before any merge.
- [ ] **Step 5: Commit** replay/documentation, request an independent risk-focused review, and correct findings with tests. Do not arm or trade Live as part of validation.

## Handoff to companion plan

Only after this plan's Sandbox scanner and existing-strategy regression gate pass, execute `docs/superpowers/plans/2026-09-28-kotak-baskets-and-risk.md`. The companion adds static templates, entry-criterion configuration, multi-leg accounting/protection and mocked Live readiness. Neither plan alone authorizes a real-money order.
