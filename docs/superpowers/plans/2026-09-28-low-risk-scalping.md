# ₹300 cash-risk scalping

User request: maximum ₹300 planned loss per trade, target 1:3 before charges, more eligible trades, maximum ₹2,000 daily loss, stop entering for the day after three consecutive losses. This explicitly replaces earlier ₹1,000 first/later risk allowances. Execution continues under the user's existing implementation/publication authorization.

## Global constraints

- Research capital stays ₹25,000. Existing saved account allocations, broker credentials, costs and strategy/Flow activation stay unchanged. No orders, new strategy installation or activation.
- Selected convention (clarification pending): price-stop risk ≤₹300 before fees; gross target exactly 3× actual tick-rounded stop distance. Charges remain modeled in net P&L, daily loss usage and drawdown; reserve fee/slippage headroom before admission.
- New low-risk sizing is ONE whole option lot. Cap the former technical/volatility stop distance at ₹300 / lot monetary units, round toward the entry so planned gross risk never exceeds ₹300. Target 3× that actual distance. Reject invalid ticks/affordability, never fractional lots or tighter-than-one-tick stops. Preserve technical signal/liquidity/contract/freshness rules. This is a new exit recipe, not a silent alteration of a frozen model.
- Daily allowance is a shared ₹2,000 gross-loss sum after costs: winning trades do not refill it. Pending/open planned net risk is reserved. Loss means a completed trade with net P&L <0. A completed non-loss breaks an ongoing streak; void/unfilled/partial closes do not. Reaching three consecutive completed net losses latches an entry-only stop through the trading day, even if a pre-existing exposure later wins or an operator resumes portfolio drawdown. Protective exits continue. Resets only at the next trading day with unresolved exposure guards retained.
- Loss order and day latch must be durable/account-mode scoped and serialized under existing account transaction. Late updates cannot erase a latch or duplicate a close. Fail closed when required sequencing facts are absent; do not fabricate old completion timestamps.
- Keep 20% peak-equity drawdown pause, 20% cash buffer, exposure limits and conservative net-risk reserve. New entries are constrained by min(remaining daily, drawdown headroom), plus separate gross per-trade cap.
- Remove the arbitrary 3-entry daily cap for this new recipe. Default 5-minute post-exit cooldown; one new closed-bar signal per entry and existing concurrency/idempotency guards still apply. Compare 0/5/15-minute cooldowns in explicitly exploratory development only.
- Preserve old recorded configurations using explicit policy/recipe versions. New source/policy identities invalidate previous qualification, model artifacts/releases and frozen jobs appropriately; never relabel old results as new.
- Consumed final sessions 2026-04-24..2026-07-21 remain excluded. No second final or forward evidence invented. Existing data can support exploratory research, not a fresh profitability proof.
- Publish reviewed/tested changes to main, safely restart owned services only with fresh exposure checks, and verify actual UI. Raw inputs/results remain ignored.

## Tasks

### Task 1: Shared policy and durable daily circuit breaker

Files: services/risk/budget.py, database/trading_risk_db.py, services/strategy_module/trading_budget.py, explicit upgrade helpers; focused risk/ledger/service/API/migration tests.

- [ ] Tests first: per-trade gross300 + net daily headroom; shared2000 not first/later buckets; wins never refill; 3-loss latch across strategy IDs and restart; nonloss reset before threshold, latch stays after threshold; next day reset, prior exposure block; concurrent reservations, idempotent/late closure updates, resume cannot clear day stop; old policy replay behavior.
- [ ] Implement a versioned current policy and explicit legacy factory/selector. Preserve clear separate gross-risk versus fee-inclusive-reserve inputs. Document exact public interfaces for Task2 in report. Budget snapshots expose per_trade_limit, consecutive_losses, daily_stopped/daily_stop_reason and remaining allowance. Compatibility old fields cannot enforce obsolete pools on new policy.
- [ ] Store closure order/day latch with real durable facts using additive idempotent migration, preserve old rows, use existing account lock. No synthetic backfill dates. New policy admission fails safely for missing necessary current-day completion facts.
- [ ] Wire managed reservation and monitoring: proposed gross entry risk cap, conservative cost reserve, consistent policy identity, entry-only streak blocking, protective exits unaffected. Runtime risk profile is current policy, prior position evidence remains managed conservatively.
- [ ] Run covering suites, lint touched files, report red/green commands/results, no production DB writes. Commit task after review only via controller.

### Task 2: Replay, ML, current scalping adapters and UI

Consumes Task1's documented versioned policy/snapshot/decision interfaces. Files: research replay/ml/ml_live/jobs/ml_install, strategy ml_forest/scalping and relevant context/version adapters; frontend Research/types/tests and changed template descriptions only where needed. One focused module may factor the shared tick-rounded cash stop/3R calculation.

- [ ] Tests first for one-lot300 boundary, target3R before charges, base/stress charges, fee-inclusive daily rejection, 3loss stop in chronological replay, two losses then win then losses, day reset, old version2R unchanged, artifact train/serve parity, more than3 successful daily entries, configurable 0/5/15 pacing/new config hashes, live contract/quantity/target preservation and exits.
- [ ] Bind current policy/exit/pacing recipe into new configurations and model evidence. New ML labels, sizing, replay and live adapter consume identical rules. Existing canonical old configurations can still be replayed under legacy math; frozen/qualification releases cannot silently migrate.
- [ ] Apply current one-lot monetary stop/3R to new managed scalping entries. Preserve signal recipes; option-premium stop/target becomes the exit basis for this new policy, with existing session deadline/protective mechanisms retained. Previously open runs retain persisted context and recovery semantics.
- [ ] UI shows per-trade300, shareddaily2000,3Rbeforecharges, loss-streak count/dayblocked and reason; remove first/later-pool explanations for current profile. New test defaults show current exit recipe. No order/activation/install side effects.
- [ ] Add reproducible bounded research runner for latest user policy: each dataset3..7 development only, ML holds5/10/15 trained once per hold then replay cooldowns0/5/15, base/stress. Canonical exports/global protected dates validated; frozen settings/seed42/100trees/3folds/mintrain10/threshold.5; immutable output/source/config hashes/ledgers. Record opportunity rejection reasons and insufficient samples honestly. Keep current default5min cooldown; study ranking does not auto-activate or change runtime settings.
- [ ] Run focused backend/frontend and type/build checks; report exact interfaces and source changes, tests red/green, limitations. No real broker calls or datasets during unit work.

### Task 3: Research, integration verification, review and publication

Controller runs fixed study after source stable; all45 variants may share15 frozen fitting operations. Compare prior2R/1000 result only as non-identical historical context; do not imply improvement from incomparable trade samples. Report net/gross/charges, win%, counts, expectancy, maxDD, stopped days, rejectedlot/fees/cooldown counts. Verify ledgers, ≤300 planned gross each, target3R, no new entry after thirdloss/dayceiling and no protected outcomes. If zero/few opportunities or losses, report failure rather than weaken limits.

Run broad relevant backend and frontend suites once, actual UI in isolated environment for deliberate loss-streak fixtures, read-only actual state baseline and updated actual app UI after safe release. Independent task and final reviews, one final fix wave, safe main merge/push, preserve settings/activation/orders. No new model installation or live broker trade.

## Interface and plan self-review

Task1/2 share policy factory, gross/net reservation inputs and closure ordering. Task2 consumes Task1 report before edits; no two implementations overlap. Task1 migration helper must be called by runtime and explicit upgrade. Task2 recipe identity covers labels/replay/live and legacy selection. Task3 uses same supported runner/config, excludes consumed final. Each task retains corresponding boundary tests. Existing local app remains on main while implementation is isolated.
