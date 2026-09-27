# Whole-branch completion review — 2026-09-27

Reviewed the package from main `c5f0250e8` through `684a04758` plus the supplied working-tree source/tests/docs, against `docs/superpowers/plans/2026-09-27-completion.md`. This is an integration review with deeper inspection of the new capital, ML deployment, qualification, migration and real-data boundaries. Earlier historical research scripts and their reports were inspected selectively, not independently re-executed. Generated frontend assets and raw vendor datasets were excluded from the review package as declared.

## Strengths

- Capital is an explicit configuration input and reaches fee-inclusive whole-lot sizing, option labels, portfolio replay, analytics and UI results. Absent legacy capital retains ₹10,000; the live `BudgetPolicy` default remains ₹10,000. Shared first/later loss budgets do not refill after profitable trades.
- ML selection and execution carry a contract identity, configuration hash and bounded JSON artifact. Forest validation rejects cycles, duplicate parents, unreachable nodes, invalid class mass and feature mismatches; scoring reproduces sklearn's float32 threshold conversion. No executable model deserialization is introduced.
- Final inference uses the frozen parent artifact without fitting. Future labels are diagnostic fields rather than an eligibility filter for prediction. Owner/underlying/session uniqueness consumes the final window once even after failure or cancellation. Development research excludes protected dates, and the full-portfolio runner verifies canonical dataset exports and global protected-date provenance.
- The live adapter uses server-observed completed bars, an explicitly bounded prior-session feature seed, current master contracts, stale/gap rejection, scored-contract preservation, replay pacing, current fee equivalence and the shared conservative admission-risk recipe. The engine retains later admission and dispatch checks. Installation creates a stopped, disabled strategy/Flow only after historical gates; no automatic install or activation is in the study path.
- Forward qualification is bound to owner, broker account, strategy, Flow, code, model, costs and allocation revisions. Prospective receipts cannot be supplied through the public API. Quote-capture failure blocks new enrolled entries while protective exits remain available. Explicit release review and session checks remain separate from historical results.
- The US study is clearly separate from NIFTY qualification. Publication date, next-day availability, statement units and current-year columns are checked; older-quarter revisions do not overwrite the latest known quarter. Reports disclose adjusted-price/release vintages, survivor selection, the unhelpful classifier baseline and fee assumptions. The final Task 3 scoped rereview approves the remaining unit-conflict fix and records unchanged financial outputs across all 869 ledgers.

## Issues

### Critical

None found in the inspected paths.

### Important

1. **[P2] Explicit Strategy Module upgrade omits the new scalping columns.**
   - **Location:** `upgrade/migrate_strategy_module.py:110` (`ADDED_COLUMNS`; adjacent new ML columns), with runtime-only additions at `database/strategy_module_db.py:703` and `:706`.
   - The explicit migration covers `ml_final_run_id` and `ml_model_hash`, but does not include `sm_strategy.scalp_profile` or `sm_strategy_run.scalp_context`, although both ORM columns are introduced by this branch. Existing-table `create_all` cannot add them. Consequently `apply()` returns success and `status()` prints “Up to date. Nothing to do.” while both mapped columns are missing.
   - **Executed reproduction:** create the current schema with `migration.apply()` on an in-memory SQLite engine, drop only `scalp_profile` and `scalp_context` to represent a prior installation, then call `apply()` and `status()` again. Both returned `True`; inspector checks showed both columns absent. A separate minimal existing-table call to `add_missing_columns()` likewise returned `True` and `missing_columns()` returned `[]` with both absent. No production database was touched.
   - **Impact:** the documented explicit upgrade does not produce the schema its success/status claim promises. A worker or standalone ORM consumer used before application startup can fail with a missing-column error. Normal application `init_db()` masks the omission by altering the tables itself, so this is a deployment/migration correctness gap rather than evidence that the already-running local instance is broken.
   - **Fix:** include both nullable columns in `ADDED_COLUMNS` and extend the existing legacy-schema/status/idempotence tests to cover them and preservation of existing scalping facts. This can be confined to the upgrade file and its tests, without changing the frozen ML implementation identity.

### Minor

No additional independently actionable correctness issue. The controller's broader Ruff pass is not clean: it reports style/import findings in historical branch files. Do not represent this review or the narrower clean checks as a whole-branch lint pass; avoid changing identity-bound source merely for unrelated formatting during final evaluation.

## Verification evidence

Read the supplied release logs: backend **4,084 passed, 16 skipped, 1 expected failure**; frontend **2,786 passed across 177 files**; production build completed with the reported existing chunk-size warning. The frontend log also records its two headless-canvas warnings. Reviewed the final Task 3 scoped rereview and relevant regression coverage for malformed trees, train/serve parity, observed bars, admission boundaries, ownership, final consumption and legacy schema behavior. No full suite or real-data study was repeated. Only the two focused in-memory migration probes above were run for a specific unresolved concern.

## Recommendations

Resolve the migration omission and obtain a narrow rereview with explicit old-schema apply/status/idempotence evidence. Preserve the frozen model/source identities while doing so. Then let the controller append the real selected-model one-shot final result, safe restart/running-artifact checks and publication verification; historical development profitability alone must not be described as forward qualification.

## Declined to judge

- Actual Kotak history-fetch latency, bid/ask depth, partial fills and broker execution: no market-session execution was requested or performed, and the plan correctly leaves prospective evidence to later operator activation.
- Future forward profitability and qualification: no future sessions exist in this task; software gates and historical evidence cannot establish them.
- Legal redistribution entitlement for raw vendor prices: raw inputs are retained privately and excluded from publication; this is not a legal review.
- Independently replaying all earlier branch research studies and every raw vendor bar: supplied reports, focused reviews and broad regression results were accepted; this review examined the integration and causal/provenance mechanisms rather than rerunning the full research history.
- Actual final consumption, locally deployed worker/frontend/backend state and remote-main publication: these controller steps intentionally follow source review and are not complete at this review snapshot. They remain requirements, not waived scope.

## Assessment

**Spec verdict: changes required for the explicit migration contract; the inspected capital, frozen inference, qualification and separate real-data-study implementation otherwise aligns with the plan.**

**Quality verdict: request changes for the single P2 above. No new P1 or critical issue found.**

**Ready to merge? With fixes.** Add and verify the two missing upgrade columns, then complete the controller's pending final/runtime/publication evidence. Task 3's final scoped approval is now present; it is no longer an outstanding review condition.

## Final scoped rereview — migration P2 addressed

**P2 status: ADDRESSED. Spec verdict: PASS for reviewed source requirements. Quality verdict: APPROVE. Ready to merge from source review: YES.** This supersedes the changes-required source verdict above; the controller's actual selected-model final, safe runtime restart/UI checks and publication verification remain pending execution steps.

Reviewed `final-fix.diff` and `final-fix-report.md`. The production delta consists of exactly two nullable `ADDED_COLUMNS` entries: `sm_strategy.scalp_profile VARCHAR(20)` and `sm_strategy_run.scalp_context JSON`, matching the runtime and ORM types. Both now participate in the existing shared status/apply mechanism, addressing the reproduced false-success condition without changing historical values or the frozen inference source.

The expanded tests exercise populated legacy schemas, status without schema mutation, the exact case where only these two columns are absent, repeated apply without schema drift, preserved existing scalping values and preserved neighboring ML identities. Accepted the supplied red/green evidence and **43 passed, 1 Windows-only skip**, two-file Ruff success and clean diff check. No full suite, focused suite or study was repeated because this small delta and its targeted evidence resolve the specific concern. No new P1/P2 issue was found in the fix.

Only this review appendix was written during rereview. Pending operational evidence remains the controller's responsibility; source approval does not claim deployment or live qualification is already complete.

## Controller verification after source approval

The actual app and worker were restarted after migrations and served the verified frontend assets. UI run 12 reproduced the selected offline model exactly; frozen final run 13 completed once without refitting and failed with -₹4,442.45 base P&L. Installation was rejected and no new strategy or Flow was created. Runtime, account-preservation and detailed financial evidence are recorded in `completion-verification-2026-09-27.md` and `completion-options-study-2026-09-27.md`. Publication verification is recorded in the task response.
