# Kotak-Style Baskets and Multi-Leg Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 16 dynamically resolved Kotak-style option baskets to the ranked scanner, with automatic execution only when explicit entry criteria and existing risk controls pass.

**Architecture:** Keep basket leg topology separate from signal generation. Install a stopped scanner-backed strategy for each selected pattern, resolve its legs from current NSE/BSE/MCX option contracts, then submit candidates to the shared coordinator from the core plan. Extend the existing managed risk, margin and broker-held stop paths for multi-leg/short entries; never create a separate executor or a shortcut around live admission.

**Tech Stack:** Python/Flask/SQLAlchemy, existing Strategy Module and Kotak adapter, pytest, React/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-09-28-ranked-opportunity-scanner-design.md`; prerequisite plan `docs/superpowers/plans/2026-09-28-ranked-scanner-core.md`.

## Global Constraints

- All 16 patterns are topology templates, not reverse-engineered Kotak proprietary entry, exit, POP or backtest logic.
- Twelve screenshot detail layouts are confirmed; Bear Put Spread, Bear Call Spread, Put Ratio Spread and Long Strangle are conventional inferred layouts and labeled so.
- Installation defaults Sandbox and stopped; entry requires configured criteria, current contracts, fresh quotes and an armed strategy.
- Preserve whole-lot ratios, same underlying/exchange/expiry, dated costs, current position caps, budget, research release and Live authorization.
- Existing allocated-capital policy presently supports only single-leg long options; multi-leg/short Live entry stays blocked until the risk extension and its tests pass.
- Do not send any real broker order, alter account risk settings, automatically arm a strategy, or claim profitability during implementation.

## Review Focus

1. A 1:2 ratio spread must not silently become 1:1 when the broker lot size changes; Task 1 tests it.
2. Equal strikes or mixed expiries must reject the entire basket rather than trade a subset; Task 2 tests it.
3. A short leg with unavailable standalone margin or contract multiplier must block Live even if a paired long is affordable; Task 4 tests it.
4. One rejected or partial leg must retain actual exposure and stop ownership, not mark the basket fully filled; Task 5 tests it.
5. A market regime that does not match an explicit saved criterion must produce no basket candidate; Task 3 tests it.

---

## File map

- Create `services/strategy_module/basket_templates.py`: 16 versioned topology definitions and provenance.
- Create `services/strategy_module/basket_resolver.py`: dynamic strike/expiry/lot and quote resolution.
- Create `services/strategy_module/basket_signals.py`: explicit owner-saved entry criteria on completed market evidence.
- Create `services/risk/basket_exposure.py`: conservative per-leg and aggregate planned-loss/margin evidence.
- Modify `services/strategy_module/template_library.py`, `portfolio_governor.py`, `trading_budget.py`, `live_protection.py`, `engine.py`, and `order_dispatch.py` at the existing managed entry/exit boundaries.
- Modify `database/strategy_module_db.py` and add/register a migration for topology/rule version and scanner-backed basket settings only if existing strategy JSON fields cannot hold them without ambiguity.
- Modify `blueprints/strategy_module.py`, `frontend/src/api/strategy_module.ts`, and `frontend/src/components/strategy/StrategyTemplateLibrary.tsx` plus strategy review UI.
- Add focused tests under `test/` and component tests alongside the changed UI.

### Task 1: Sixteen pure basket topologies

**Files:** Create `services/strategy_module/basket_templates.py`, `test/test_strategy_module_basket_templates.py`.

**Interfaces:** `BasketTemplate(id: str, name: str, category: str, legs: tuple[LegPattern, ...], provenance: str, version: str)`; `LegPattern(side: Literal['B','S'], option_type: Literal['CE','PE'], strike_offset: int, lots: int)`; `get_template(template_id: str) -> BasketTemplate`; `all_templates() -> tuple[BasketTemplate, ...]`. Offsets are relative to current ATM *strike step*, not dated absolute prices. `provenance` is `screenshot-detail` or `conventional-inference`.

- [ ] **Step 1: Write failing parameterized tests** named `test_all_16_template_shapes` and `test_template_payoff_tails`: `assert len(all_templates()) == 16`; `assert [x.lots for x in get_template("call-ratio-spread").legs] == [1, 2]`; `assert [x.lots for x in get_template("long-call-butterfly").legs] == [1, 2, 1]`; `assert len([x for x in all_templates() if x.provenance == "conventional-inference"]) == 4`. Check payoff signs below/at/above strikes, including the unbounded short-call tail.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_basket_templates.py`; expect missing module failure.
- [ ] **Step 3: Implement** the frozen topology registry with no price, expiry, lot-size, signal or stop defaults. Name the four inferred layouts explicitly in module documentation.
- [ ] **Step 4: Run** the same command; expect pass.
- [ ] **Step 5: Commit** only the registry and tests.

### Task 2: Current-contract basket resolution

**Files:** Create `services/strategy_module/basket_resolver.py`, `test/test_strategy_module_basket_resolver.py`; modify `services/strategy_module/opportunity_providers.py` only to register resolved basket proposals.

**Interfaces:** `resolve_basket(template: BasketTemplate, underlying: str, exchange: str, expiry: date, lots: int, market: MarketSnapshot) -> tuple[LegIntent, ...]`. Return the frozen core-plan leg type with verified symbol/token, strike, option type, exchange, expiry, lot size, quantity and multiplier; keep bounded bid/ask evidence in the candidate's market snapshot. The engine converts a revalidated intent to its existing leg dictionary only after admission. Reject the entire basket on inconsistent metadata.

- [ ] **Step 1: Write failing tests** named `test_basket_uses_current_contracts` and `test_invalid_leg_rejects_whole_basket`: `assert [x.quantity for x in resolve_basket(ratio, ..., lots=1, market=market)] == [current_lot, 2*current_lot]`; `assert {x.expiry for x in legs} == {selected_expiry}`; `assert` mixed expiry, equal strike, absent leg, crossed depth and changed master raise `ValueError` before any order.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_basket_resolver.py`; expect missing resolver.
- [ ] **Step 3: Implement** resolver against Task 2's market snapshot from the core plan; do not reuse screenshot strike `22800`, quantity `65`, or expired dates.
- [ ] **Step 4: Run** focused resolver and core market tests; expect pass.
- [ ] **Step 5: Commit** only resolver/provider wiring and tests.

### Task 3: Install and arm only explicitly configured baskets

**Files:** Create `services/strategy_module/basket_signals.py`, `test/test_strategy_module_basket_signals.py`; modify `services/strategy_module/template_library.py`, `blueprints/strategy_module.py`, `database/strategy_module_db.py` if needed; add/register a migration only for new durable fields.

**Interfaces:** `evaluate_basket_rule(rule: dict, completed_market_context: dict) -> tuple[bool, str]`. A saved rule is either `linked_signal` (owner-scoped enabled source strategy ID, category tag and minimum strength) or `completed_bar_regime` (lookback of at least two completed bars plus owner-saved trend, neutral and realized-range thresholds). For completed bars, calculate `trend_pct = 100*(last_close/first_close - 1)` and `range_pct = 100*(max(high)-min(low))/first_close`; bullish/bearish require signed trend beyond threshold, neutral requires absolute trend within its threshold, volatile requires range above its threshold. No default rule qualifies; session window and candidate bounds are also saved. `install(owner, template_id)` remains idempotent and returns stopped/Sandbox strategy; catalog marks scanner-backed templates as not needing a linked Flow. Use the core scanner arm/disarm lifecycle for basket strategies of existing `batch` kind, never immediate batch `/start` to arm.

- [ ] **Step 1: Write failing tests** named `test_install_is_inert` and `test_saved_regime_rule_is_required`: after `result = install(owner, template_id)`, load `row = store.get_strategy(result["strategy_id"], owner)` and assert `row.live_enabled is False`, `row.automation_state == "disabled"`, and `broker.orders == []`; `assert evaluate_basket_rule({}, bars)[0] is False`; `assert evaluate_basket_rule(rule, incomplete_bars)[0] is False`. Verify each category's explicit completed-bar fixture can qualify and other owners cannot read/install it.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_basket_signals.py test/test_strategy_template_library.py`; expect failures for missing basket support.
- [ ] **Step 3: Implement** rule validation, versioned saved configuration, catalog/install adaptation and scanner-backed arm lifecycle. Route any candidate through the core coordinator; never call batch `/start` to arm.
- [ ] **Step 4: Run** focused tests plus `pytest -q test/test_strategy_module_api.py test/test_strategy_module_starter_pack.py`; expect pass.
- [ ] **Step 5: Commit** only basket configuration/catalog and tests.

### Task 4: Basket-aware capital, margin and admission

**Files:** Create `services/risk/basket_exposure.py`, `test/risk/test_basket_exposure.py`; modify `services/strategy_module/portfolio_governor.py`, `trading_budget.py`, and Kotak margin adapter only where basket evidence is obtained.

**Interfaces:** `basket_risk_evidence(legs: tuple[dict, ...], executable_quotes: dict, cost_schedule: dict, standalone_margins: dict) -> BasketRiskEvidence`; include per-leg stop distance, aggregate planned loss including modeled charges/slippage, whole-lot quantities, maximum cash/margin commitment, contract multipliers and unbounded-tail flag. Sum standalone short-leg margin conservatively; do not assume a broker basket offset the adapter cannot verify. Pass this evidence into the existing admission policy; no new risk ceiling.

- [ ] **Step 1: Write failing tests** named `test_conservative_basket_loss_and_margin` and `test_missing_risk_evidence_blocks`: `assert evidence.planned_loss == sum(per_leg_stop_loss) + modeled_costs`; `assert evidence.required_margin >= sum(short_standalone_margins)`; `assert admission.allowed is False` when quote, stop, multiplier, margin or cost is absent; `assert legacy_single_long_decision == previous_decision`. Parameterize NFO/BFO/MCX and existing 1.5R, budget and per-mode ledger cases.
- [ ] **Step 2: Run** `pytest -q test/risk/test_basket_exposure.py`; expect missing module.
- [ ] **Step 3: Implement** conservative evidence and explicit budget-policy support for proved multi-leg plans; retain old policy for legacy trades. If a Kotak margin call cannot establish a short leg's standalone requirement, block Live rather than estimate it as zero.
- [ ] **Step 4: Run** focused risk, `pytest -q test/risk/test_trading_budget.py test/test_strategy_module_portfolio_governor.py`; expect pass.
- [ ] **Step 5: Commit** only risk/margin integration and tests after risk-focused review of the arithmetic.

### Task 5: Protective multi-leg execution and reconciliation

**Files:** Modify `services/strategy_module/engine.py`, `live_protection.py`, `order_dispatch.py`, existing order-event/recovery modules as needed; create `test/test_strategy_module_basket_execution.py`.

**Interfaces:** Existing `start_ranked_candidate` accepts a basket only after Task 4 risk evidence and every leg's fixed broker-stop plan are verified. Preserve per-leg `position_ref` and durable order IDs. Long/protective legs dispatch before short/exposure-increasing legs where possible; partial/rejected/unknown outcomes stop remaining entries and trigger existing cancel/reconcile/flatten-or-protect flow.

- [ ] **Step 1: Write failing tests** named `test_protective_leg_failure_blocks_short`, `test_partial_basket_reconciles`, and `test_unknown_order_retains_reservation`: `assert short_order_calls == 0` after protective-leg refusal; `assert state.open_quantity == broker.filled_quantity` after partial/late fills; `assert reservation.active is True` on unknown outcome; `assert exit_attempted is True` during scanner pause; `assert fake_client.real_network_calls == 0`.
- [ ] **Step 2: Run** `pytest -q test/test_strategy_module_basket_execution.py`; expect failures.
- [ ] **Step 3: Implement** minimal engine/protection extensions and audit events; do not describe a broker request as a fill or treat a multi-leg order as atomic.
- [ ] **Step 4: Run** focused tests plus `pytest -q test/test_strategy_module_order_events.py test/test_strategy_module_recovery.py test/test_strategy_module_kotak_protection_contract.py`; expect pass.
- [ ] **Step 5: Commit** only execution/reconciliation code and tests after an independent safety review.

### Task 6: Basket controls, replay and release verification

**Files:** Modify `frontend/src/components/strategy/StrategyTemplateLibrary.tsx`, `frontend/src/api/strategy_module.ts`, existing strategy review components; create/update component tests and `test/test_strategy_module_basket_replay.py`; update operator docs.

**Interfaces:** UI lists all 16 with provenance and risk warning, allows owner to configure criterion/ranges/stops and choose mode separately, previews resolved legs/cost/margin/stop evidence, and shows ranked, rejected, requested, filled and protected states distinctly. Basket settings cannot override account risk limits.

- [ ] **Step 1: Write failing UI and replay tests** named `showsSixteenBasketTemplates` and `test_basket_competes_in_ranked_replay`: `expect(screen.getAllByTestId('basket-template')).toHaveLength(16)`; `expect(screen.getByText(/unbounded risk/i)).toBeVisible()`; `assert replay.admitted_ids == expected_budget_fit_order`; `assert replay.live_orders == []` with stale or missing margin; `assert recovered.unknown_claims == persisted.unknown_claims`.
- [ ] **Step 2: Run** focused pytest/Vitest files; expect failures.
- [ ] **Step 3: Implement** UI/status and replay wiring; update documentation with actual supported exchanges, risk boundaries, live prerequisites and failure recovery.
- [ ] **Step 4: Run** both plans' focused backend suites, all Strategy Module/risk backend regressions, frontend tests, TypeScript build, and isolated Sandbox end-to-end replay. Record exact results, inspect scoped diff and obtain a whole-branch risk review. Mock Live only; no real account order.
- [ ] **Step 5: Commit** tests/UI/docs and corrective fixes. Deployment remains disabled until the owner performs the separate activation and any required research release.

## Completion boundary

Ready-to-select means the operator can choose Sandbox or Live for an armed, correctly configured strategy; it does not mean every basket passes Live admission for the current account, liquidity, margin or risk budget. A refused high-risk basket is a correct result. No profitability claim or real-money smoke trade follows from green tests.
