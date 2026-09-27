# Low-risk policy code review

Reviewed product commits: c96301fc6, fc8db3737 and documentation anchors 233e53a75, plus reviewed UI correction ee65dca2a. Task1, Task2 and final whole-branch review approved; operational verification is recorded in the implementation report.

# Spec compliance: Issues found

Task 1 implements the versioned shared policy, separate gross cap/net reserve, account-serialized completion ordering, persistent daily latch, and additive migration. Two completion-accounting cases still violate the specified daily/streak semantics.

# Strengths

- `services/risk/budget.py:26,165` establishes an explicit current factory and separate gross-risk admission; `services/strategy_module/trading_budget.py:172` passes the actual entry price risk independently of fee-inclusive reserves.
- `database/trading_risk_db.py:109,247` leaves existing completion facts unknown and preserves saved allocations during explicit safe policy transition. `test/test_trading_risk_ledger.py:209` covers repeated migration and unavailable legacy order.
- `test/test_trading_risk_ledger.py:131,187` covers durable latching, duplicate completion, late corrections, resume, day reset, and concurrent admission. `test/risk/test_trading_budget.py:69` checks wins do not replenish loss allowance and distinguishes gross from net limits.

# Important findings

1. **Unfilled completion can reset the loss streak.** `services/risk/budget.py:118-125` includes every closed row regardless of `filled`; `database/trading_risk_db.py:388-413` permits a previously unfilled reservation to be closed with `filled=False`. A zero-P&L unfilled close between three real completed losses resets the streak and admits another entry. The brief explicitly says unfilled events must not break the streak. Reject the invalid ledger transition and/or exclude unfilled rows from completion-streak evaluation; cover the pure API as well as the ledger. Normal reconciliation uses `void` for an unfilled order, but the public policy/ledger boundary does not enforce that invariant.

2. **An exposure closed on a later trading day is charged to its entry day.** `database/trading_risk_db.py:194,413,420` records a real close timestamp but snapshots the reservation's `session_day`; once closed, the row is excluded from a different day's snapshot. `services/risk/budget.py:66,118` likewise derives completion streak and loss usage solely from entry session. For example, yesterday's unresolved exposure blocks entries until it closes this morning; if it loses, then two new trades today lose, today's snapshot counts only two losses and permits another entry. Today's allowance also omits the earlier completed loss. Persist/derive completion trading day for the current policy, use it for current-day closed losses and streaks, and retain entry-day/prior-exposure semantics while the position is unresolved. Preserve explicit legacy replay behavior and do not fabricate historic completion dates.

# Critical findings

None.

# Minor findings

None.

# Focused checks and limitations

- Read the supplied stable diff once; recovered the middle section omitted by tool-output truncation. Did not re-run the reported 64-test suite.
- Named boundary check: inspected reconciliation close-state assignment and current-day monitoring in `services/strategy_module/trading_budget.py:239,281,307,338-386`. Normal unfilled cancellation becomes `void`; filled partial exposure remains `open`; monitor asks for the current trading day. This establishes the service behavior behind the two findings without broad repository exploration.
- Ran an isolated pure-module Python probe with bytecode disabled and no database/broker import. Constructed current-policy `BudgetTrade` rows with net losses of 100 and proposed net/gross risk of 100/80. For `[filled loss, unfilled closed zero, filled loss, filled loss]` in one day, observed `entry_allowed`, `allowed=True`, `consecutive_losses=2`. For `[prior-session closed loss, current-session closed loss, current-session closed loss]`, observed `entry_allowed`, `consecutive_losses=2`, `daily_loss=200`. The latter probe confirms the policy's entry-session attribution; the ledger source establishes that a later real closure never changes that attribution.
- Cannot independently verify the historical red/green run output from the report alone; it reports 64 passing tests and Ruff success. No evidence of warnings was supplied.
- Cannot verify Task 2 recipe sizing, 3R tick rounding, cooldown removal/comparisons, artifact/source invalidation, or consumed-session exclusion from this Task 1 diff. Controller must validate those at integration. Publication, service restart/exposure checks, and actual UI verification are later controller responsibilities.
- No product changes, commits, production database access, broker calls, or subagents were used. Only this requested report was written.

# Task quality: Needs fixes

The policy boundaries and regression coverage are otherwise coherent, but completion accounting can allow entries past the specified third-loss stop and daily loss usage. Resolve these two cases before integrating Task 2 against the public interfaces.

# Scoped re-review: fix round 1

**Spec verdict: Issues remain. Task quality: Needs fixes.**

- **Finding 1 addressed.** `database/trading_risk_db.py:417-418` rejects an unfilled close before changing evidence or sequence; `services/risk/budget.py:69-82` ignores zero-P&L unfilled closed rows and fails closed on their nonzero P&L. The new regressions at `test/risk/test_trading_budget.py:104` and `test/test_trading_risk_ledger.py:262` exercise both boundaries.
- **Finding 2 not fully addressed.** The additive `completion_day` field, snapshot selection, preserved entry-day exposure guard, and pure-policy completion filtering correctly address ordinary overnight closes. Tests at `test/risk/test_trading_budget.py:118`, `test/test_trading_risk_ledger.py:279`, and `test/test_trading_risk_api.py:83` cover those cases. However, the new conversion below uses a different definition of trading day from managed admission and monitoring.

## Important new breakage in the fix

- **Use the existing trading-session boundary for completion day.** `database/trading_risk_db.py:433` sets `completion_day = at.astimezone(IST).date().isoformat()`. The existing `services/strategy_module/session.py:39-52` defines a trading day by `SESSION_EXPIRY_TIME` (03:00 IST by default), explicitly assigning 01:00 Tuesday to Monday's session. `services/strategy_module/trading_budget.py:51` uses this helper for admission/monitoring. Consequently a loss observed Tuesday 01:00 is stored against Tuesday while the active budget query still asks for Monday: that loss does not consume the active session's allowance or streak, and can admit an extra entry past the third loss. It then leaks into the next session's allowance after reset. Derive completion day with the existing session helper (or a shared lower-layer equivalent preserving the configured reset). Add regression cases immediately before and after the configured reset; the new completion tests all use 10:00 and cannot expose this mismatch.

## Scoped evidence and limitations

- Read `task-1-fix1.diff` and updated `task-1-report.md`; recovered only the small API-test span truncated by the combined output. No product changes or test-suite rerun.
- Named boundary check: verified whether new IST calendar conversion matches managed trading-day semantics; inspected `services/strategy_module/session.py:1-60` and the existing helper reference in `services/strategy_module/trading_budget.py:19,51`. Initial guessed helper paths did not exist; located the actual import before inspection.
- The updated report states 69 covering tests and touched Ruff checks passed. Their supplied cases cover the original findings at ordinary daytime instants; no additional execution was needed to establish the explicit calendar/session mismatch.
- `database/trading_risk_db.py:273-279` now blocks transition for any historic filled close with unknown sequence/completion day. This is deliberately conservative and avoids fabricated facts, as documented. Deployment must account for this documented transition limitation; the scoped fix does not supply an operator evidence-reconciliation workflow.
- All earlier cross-task and controller verification limitations remain. Only the requested report was appended.

# Scoped re-review: fix round 2

**Spec verdict: Compliant for Task 1 reviewed scope. Task quality: Approved; ready for integration.**

- **Outstanding session-boundary finding addressed.** `database/trading_risk_db.py:433` now normalizes the aware observation instant to IST and delegates to the existing `session.session_day` helper. This matches managed admission/monitoring and honors the configured reset. First-completion-only assignment preserves the original completion day on late corrections.
- `test/test_trading_risk_ledger.py:305` adds before/at/after-reset cases, UTC inputs, custom 05:30 reset, daily-loss attribution, exclusion from the other session, and correction-day preservation. `test/test_trading_risk_api.py:106` checks status reporting before and at the default boundary. These assertions exercise the previously failing behavior.
- The two original important findings and the round-1 session-boundary regression are now addressed. No new important or critical issue found in this scoped fix.
- Read the full `task-1-fix2.diff` and updated report. Accepted the reported 77-test covering run and touched-file lint result; no repeat suite or additional product mutation was needed. Only this report was appended.
- Earlier cross-task/controller verification limitations and the documented conservative block on legacy accounts with unknown filled-completion facts remain. Approval is the Task 1 gate, not whole-branch/deployment approval.


# Task 2 review and resolution

### Spec Compliance

- ❌ Issues found: queued optimization does not preserve bound nondefault pacing (`services/research/jobs.py:754`); current ML context does not meet the persisted recovery contract (`services/strategy_module/ml_forest.py:335`, `services/strategy_module/recovery.py:756`).
- ✅ Shared one-lot tick-rounded gross stop and exact 3R geometry are implemented in `services/risk/cash_exit.py:10`; current labels, replay, and live planning call it and separately reserve modeled costs (`services/research/ml.py:159`, `services/research/replay.py:519`, `services/research/ml_live.py:162`).
- ✅ Current configuration, artifact, source, and policy identity are explicitly bound; missing-version configurations retain legacy math (`services/risk/cash_exit.py:38`, `services/research/jobs.py:416`, `services/research/jobs.py:501`).
- ⚠️ Controller-owned boundaries not verified here: actual UI and generated distribution, full integration results, real dataset study/results, service restart/exposure audit, and publication. No profitability assertion follows from this code review.

### Strengths

- `services/risk/cash_exit.py:10-29` uses Decimal arithmetic, explicit tick evidence, whole-lot units, rounding toward entry, and the actual rounded distance for the 3R target. The tests cover the 65-unit ₹299 rounding boundary and shared base/stress economics (`test/test_low_risk_recipe.py:18`, `test/test_low_risk_recipe.py:154`).
- `services/research/replay.py:717-745` records completed trade order/day and delegates daily allowance/streak state to the shared policy. Tests exercise loss/loss/win resets, three-loss blocking, six successful entries, and next-session reset (`test/test_low_risk_recipe.py:133`, `test/test_low_risk_recipe.py:294`).
- `services/strategy_module/scalping.py:384-398` persists current premium stop/target points; its versioned option-premium context preserves the deadline and leaves recorded legacy exit interpretation intact (`services/strategy_module/scalping.py:177`, `test/test_low_risk_recipe.py:202`).
- `services/research/low_risk_study.py:108-183` verifies canonical exports/hashes, excludes protected dates, freezes source identity and output hashes, and explicitly marks the study exploratory. Per-hold fitting is reused across cooldowns (`services/research/low_risk_study.py:44-83`).
- `frontend/src/pages/strategy/List.tsx:823` clearly distinguishes earlier-rule historical percentages from the current recipe; `frontend/src/pages/strategy/Research.tsx:216` exposes current cash risk and loss-streak state.

### Issues

#### Critical (Must Fix)

- None identified.

#### Important (Should Fix)

- **Queued optimization silently changes pacing and misidentifies the result.** `services/research/jobs.py:754-764`: `queue_run` accepts and hashes `cooldown_minutes=0` or `15` at lines 589-596, but the worker passes no pacing into `optimize_experiment`; that function rebuilds a default 5-minute configuration at line 107. The worker then labels the result with the queued configuration hash. A requested 0/15-minute search therefore evaluates different admission opportunities and can promote a different configuration than the requested one. Preserve the queued pacing through the optimizer, or explicitly reject unsupported pacing at queue time. Add a queued-worker regression checking both evaluated configurations and reported identities.
- **Current ML runs cannot recover their persisted exit recipe.** `services/strategy_module/ml_forest.py:335-346`: the persisted context expands `entry_plan`, which supplies `sl_pts`/`target_pts` (`services/research/ml_live.py:210-211`) but never `premium_stop_points`/`premium_target_points`. `engine.py:405` skips `protect_leg` for ML, `engine.py:531` persists the context, and `database/strategy_module_db.py:1623` stores it unchanged. Recovery unconditionally reads `scalp_context["premium_stop_points"]` before rebuilding even checkpointed runs (`services/strategy_module/recovery.py:754-758`), causing KeyError after a restart with ML exposure. This seam predates the new recipe, but the required current adapter persistence/recovery remains unsatisfied. Persist the recovery fields for current ML and support already-recorded ML contexts using their original stored distances; add a real isolated recovery regression preserving contract, quantity, stop, target, and deadline.

#### Minor (Nice to Have)

- `task-2-report.md` records an existing Vite large-chunk warning. It is disclosed existing build noise, not a new task blocker.

### Checks and Boundaries

- Read the stable Task2 diff once in bounded chunks; read the Task2 brief and Task1/Task2 reports first. No broad suite rerun and no production edits, commits, broker calls, or subagents.
- Named outside-diff risk check: current ML/scalping context persistence through entry and recovery. Inspected focused engine call sites, `create_run`, recovery context restoration, and all writers of the two premium recovery fields; no normalization bridge exists for ML.
- Named outside-diff risk check: qualified model installation bypass. `services/research/ml_install.py:26` calls the updated `historical_ml_reason`; `services/research/qualification_context.py:185` includes all research/risk/strategy Python sources in its binding.
- Named outside-diff risk check: new scalping pacing durable-history semantics. `database/strategy_module_db.py:2397` scopes filled-run history by strategy/mode and refuses active exposure; failures propagate rather than admitting an entry.
- Focused synthetic optimization reproduction returned `queued_pacing={cooldown_minutes: 0, daily_trade_cap: None}` and `evaluated_best_pacing={cooldown_minutes: 5, daily_trade_cap: None}`. Real optimizer/replay ran; only `session_analytics` was stubbed to avoid its unrelated portfolio/database imports. The initial unstubbed attempt stopped at missing `API_KEY_PEPPER`; it is not evidence of a task defect and was not worked around with production credentials.
- No live restart/recovery test was run; the ML recovery finding follows from the exact persisted dictionary and unconditional missing-key read. Controller should require an isolated regression before accepting its fix.

### Assessment

**Task quality:** Needs fixes.

**Reasoning:** Core cash-risk arithmetic, version identity, chronological loss gating, and bounded-study isolation are coherent. Nondefault optimization evidence and ML restart persistence must be corrected before Task2 can be trusted end to end.

## Round 1 re-review — supersedes the initial blocked verdict

### Spec Compliance

- ✅ Spec compliant for the reviewed Task2 scope: both Important findings are resolved in `task-2-fix1.diff`; no new blocking defect identified in that fix.
- `services/research/jobs.py:108` binds the supplied cooldown into the optimizer base; `services/research/jobs.py:772` passes the queued pacing to the optimizer. The added queued-worker regression exercises real evaluation, candidate hashes, report identity and promotion for both 0 and 15 minutes (`test/test_research_optimization.py:129`).
- `services/strategy_module/ml_forest.py:340` now writes the recovery field names from the actual plan. `services/strategy_module/recovery.py:755` restores older ML contexts from their original stored distances, validates required geometry, and does not recalculate the recipe. Four real recovery cases preserve quantity, symbol, context/deadline, stop/target and checkpoint effective protection (`test/test_strategy_module_recovery.py:2843`).
- `frontend/src/pages/strategy/Research.tsx:386` detects legacy or blocked modes and qualifies the setup summary; the added UI regression prevents the earlier misleading all-modes assertion (`frontend/src/pages/strategy/Research.test.tsx:813`).
- `scripts/research_conlan_portfolio.py:107` and `:130` explicitly construct legacy replay configurations, preserving this archival study's intended recipe instead of combining current defaults with legacy identity.
- ⚠️ Actual UI/built artifact audit, broad integration, immutable study outcomes, restart exposure checks and publication remain controller-owned boundaries.

### Strengths

- `services/research/jobs.py:62` includes recovery source in implementation identity, so recovery behavior changes invalidate model evidence instead of silently changing qualified execution semantics.
- `test/test_research_optimization.py:129` and `test/test_strategy_module_recovery.py:2843` exercise the failed integration seams directly; the fixes preserve archived run facts and extend existing contracts without replacing prior outcomes.

### Issues

- Critical: none identified in the fix.
- Important: none outstanding from this review.
- Minor: the updated implementer evidence discloses one pre-existing SQLAlchemy identity-map warning and the existing Vite chunk-size warning; neither is introduced by this fix.

### Checks and Assessment

- Read the fix diff once and the updated report's exact red/green and 382-backend/26-frontend/build/Ruff evidence. No suites were repeated, and no further outside-diff investigation was necessary to assess the fixes.
- Anchor-only BDD documentation and regenerated distribution are not represented in this scoped fix diff; controller retains their verification.
- **Task quality: Approved.** The corrected optimizer maintains the requested pacing identity end to end, and ML recovery restores recorded current and legacy geometry. No new blocking regression was identified in the scoped changes.


# Final whole-branch code review

Reviewed base `972754d35126fa2dc6c5bffb2a8d5ed94f27b3be` through product-source head `fc8db3737`, plus the two documentation-anchor changes in `233e53a75262821fc248c393d31a96880e8fcba6`. Review performed against the binding final-review brief, Task 1/2 reports and completed fix-review conclusions, and progress ledger.

## Spec compliance

Compliant for the reviewed implementation scope. No outstanding Critical or Important code finding identified.

- `services/risk/cash_exit.py:10` supplies common Decimal one-lot geometry: cap the technical distance at ₹300 per lot, round the stop toward entry, refuse invalid ticks/less-than-one-tick distances, and target exactly three times the rounded distance. ML labels, replay and live plans share this helper; scalping persists the resulting premium geometry. Tighter stops are the controller's explicit new recipe decision, not evidence of improved profitability.
- `services/risk/budget.py:133` counts negative net results without profit replenishment, reserves outstanding risk without double-counting negative marks, retains drawdown/cash/exposure protections, and separates gross per-trade risk from conservative net admission. Completion order determines the streak; reaching three losses latches the day's entry stop even if subsequent completed outcomes change the current streak.
- `database/trading_risk_db.py:181` selects policy by the recorded account version. Additive migration preserves old rows and unknown completion facts. The account transaction serializes reservations, sequence assignment and persisted day stops; completion uses the existing configured trading-session boundary. Prior unresolved exposure still blocks the next day's entry. Legacy transitions preserve allocations and refuse incomplete historical evidence.
- `services/research/jobs.py:105` and `:769` preserve the queued cooldown through optimization; source/policy/configuration/model identities prevent earlier evidence being relabeled as current. New current configurations have no three-entry cap and default to five-minute cooldown. The final/historical gates retain exact configuration hashes, including pacing.
- `services/strategy_module/ml_forest.py:340` persists current exit distances under recovery's field names. `services/strategy_module/recovery.py:755` restores older ML distances from recorded context rather than recalculating today's recipe. Current and legacy checkpointed/non-checkpointed regressions cover this seam.
- `services/research/low_risk_study.py:21` excludes protected/consumed dates before fitting; `:108` checks canonical inputs; `:159` checks source stability and hashes outputs; `:178` explicitly marks the result ineligible for live. The runner writes files only and does not invoke installation, qualification promotion, strategy changes or activation.
- The UI exposes shared daily allowance, actual account policy/transition state, per-trade cap and day stop. Earlier historical percentages remain explicitly labeled earlier-rule results. Both supplemental BDD anchors resolve to their intended declarations.

## Strengths

- Risk accounting is centralized rather than duplicated between the live planner and replay. Gross stop risk and net reserve remain separate at admission.
- Durable stop history is account/mode scoped and survives correction, resume and later-session updates. The completion-day fixes address overnight and configured-reset cases instead of only ordinary daytime fixtures.
- Regression coverage exercises integration behavior: real queued optimization identity/promotion, durable concurrent reservations, persisted ML recovery with checkpoints, current-versus-legacy replay math, and mixed-mode rendered UI.
- The study treats fitting failure and insufficient samples as explicit unavailable/limited evidence, keeps the final sessions excluded, and does not silently install a winning development variant.

## Issues

### Critical (Must Fix)

None identified.

### Important (Should Fix)

None identified. Earlier review findings concerning unfilled streak reset, overnight/session attribution, queued pacing identity and ML recovery are resolved in the reviewed source.

### Minor (Nice to Have)

No new actionable minor finding. Reported pre-existing Vite chunk-size and test-environment warnings do not block this change.

## Evidence and limitations

- Read the supplied whole-branch source diff in bounded chunks, recovering the initially truncated section rather than repeating the full diff. Read the two-line documentation supplement. Did not rerun already-passing suites.
- Independently hashed all 316 files listed in `final-assets.json`: zero missing files or mismatches. This verifies supplied build identity, not actual deployed browser behavior.
- Accepted the controller's reported broad backend result: 4,143 passed, 16 skipped, one xfailed. Accepted the reported full frontend 2,786 passing tests before the last UI fix, followed by amended Research 26 passing tests and TypeScript/Vite build. Task reports provide focused red/green evidence; these aggregate suite outcomes were not independently rerun by this reviewer.
- Named outside-diff checks: live ML passes the bound recipe into scoring/planning and the durable stop into admission; reconciliation leaves partially closed/working orders open and voids unfilled terminal orders; day-stop-only snapshots do not add protective-exit buckets; account writes use the existing SQLite immediate transaction/row lock; persisted recovery fields match the current writers.
- Named eligibility check prompted by the brief's exploratory pacing wording: `services/research/jobs.py:530` validates source, model and exact parent/final configuration identity; `services/research/ml_install.py:26` calls that gate; `services/strategy_module/ml_forest.py:49` repeats the frozen-model checks; `services/research/qualification_context.py:254` binds the final configuration hash into forward qualification. No bypass from this file-based study to installation/activation was found.
- Controller clarified that five minutes is the current default and this study's zero/fifteen-minute variants are exploratory only. A separately qualified, explicitly reviewed and session-authorized future recipe may retain its chosen pacing; there is no requirement for a permanent five-minute-only platform restriction. The reviewed code is consistent with that ruling and does not auto-promote the study variants.
- Existing legacy accounts with filled historical closes lacking completion facts intentionally remain blocked from transition until evidence is reconciled. This is a documented fail-closed migration boundary, not fabricated migration success.
- No production DB access, broker calls, orders, source edits, commits or subagents were used. Only this scratch report was written. Controller-owned untracked narrative documents were left untouched; product source stayed frozen.

## Recommendations

Complete the controller-owned immutable study/arithmetic audit, actual UI checks, fresh exposure audit and safe publication/restart steps. Report observed sample sizes, charges, rejected admissions and negative outcomes directly; approval of the implementation does not qualify the strategy or establish profitability.

## Declined to judge

- Real-data profitability and independent study arithmetic: controller's ongoing immutable study/audit owns these; this review cannot infer empirical results from code or earlier win-rate badges.
- Actual production exposure, credentials/settings preservation, installed UI, service restart and remote-main publication: controller owns fresh operational verification; no production access was authorized for this reviewer.
- A permanent five-minute-only restriction on future separately qualified recipes: controller explicitly ruled this outside the requested behavior; current default remains five minutes and this study remains exploratory.

## Assessment

**Ready to merge? Yes, for the reviewed code.**

The shared policy, recipe/version identity, persistent recovery and UI changes satisfy the binding implementation constraints, with no unresolved blocking defect found. This verdict does not mark the overall task complete: controller-owned empirical, deployment and actual-UI checks remain necessary, and no fresh final/forward qualification evidence is supplied by this review.

## Final UI fix-wave scoped re-review

**Verdict: Approved. The controller's remaining card-copy finding is addressed.**

- `frontend/src/components/strategy/ScalpingStrategies.tsx:15`, `:21` and `:27` now describe the current ₹300 gross stop and 3R option target for all three cards. The stale index-2R and 10/20-point descriptions are removed. ATM/ITM distinctions and the rendered 15-minute limit remain intact.
- `:59` explicitly identifies the earlier-rule historical research, `:87` labels its percentages/counts as earlier-rule wins, and `:127` makes the current entry and before-charges basis explicit. The diff does not change ordering, historical values, callbacks, activation or other control behavior.
- The new actual-render regression checks every card, expected historical ordering/counts/percentages, contract selection, current exits, holding limit and provenance. The updated implementer report records the initial failure followed by 53 passing frontend tests across ScalpingStrategies, List and Research, passing targeted Biome lint, and passing TypeScript/Vite build. Accepted this scoped evidence without repeating those suites.
- Independently checked all 316 files in `final-card-assets.json`; zero missing files or hash mismatches. This supersedes the earlier asset-manifest check for the rebuilt distribution. Controller still owns verification of the deployed UI.
- Critical: none. Important: none. Minor: no new actionable finding. The existing build-size and Node warning disclosures remain non-blocking.
- Scope was the supplied `final-card-fix.diff`, updated report's final section, affected line references and rebuilt manifest only. No Python/source changes, DB/broker access, tests, commits or subagents were performed; this report appendix was the only write.
- Controller reports the completed 90-scenario arithmetic audit passed and all nine aggregate ML configurations lost. Those empirical outcomes were not re-audited in this narrow UI review; this copy fix preserves their status as exploratory and does not introduce a profitability claim. No additional behavior was declined as outside this fix.

**Ready to merge this fix? Yes.** It resolves the observed stale descriptions and historical-provenance ambiguity without changing execution or controls. Complete controller-owned deployment/UI verification before claiming the user-visible repair is live.
