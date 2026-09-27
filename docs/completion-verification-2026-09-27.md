# Completion verification — 2026-09-27

This record separates software checks from investment evidence. The new model deployment path remains opt-in and gated. No strategy was installed or activated, no saved live fee schedule or allocation was changed, and no order was submitted during these checks.

## Browser verification

An isolated OpenAlgo Research app and worker used fresh temporary databases. Broker reconciliation was stubbed and broker/order routes were absent. The browser exercised the real research and risk routes:

- Saved the Kotak fee draft with a date range covering the synthetic test data.
- Reviewed only the test Sandbox allocation from ₹10,000 to ₹25,000 with a required reason. Separate Sandbox/Live totals displayed correctly after the build. Live stayed ₹10,000. First/later/daily loss allowances stayed ₹1,000/₹1,000/₹2,000.
- Imported an explicitly synthetic 80-session dataset through the file chooser. The UI validated 21,600 bars.
- Confirmed the new research capital defaults to ₹25,000 and rejected zero without queuing work.
- Queued and completed a random-forest development test, froze its artifact, and acknowledged a one-shot final test. The final completed with the identical model hash and `refitted=false`; the isolated consumption ledger recorded 60 final sessions.
- Confirmed that the consumed final action was disabled and installation was rejected with the specific requirement for at least 20 resolved trades and positive net results. No strategy or Flow was created.

The fixture predicted only “skip”: its 100% classification accuracy equalled its 100% majority-class baseline, with zero executed trades and zero profit. This verifies workflow behavior only. It supplies no financial or forward qualification evidence. Both temporary processes were stopped and the test browser tab closed.

The successful installer path was exercised with isolated unit mocks. A real Kotak history/quote/fill loop has not been verified; history retrieval can exceed the 55-second signal window, in which case the adapter waits. Forward qualification still requires actual future sessions and operator activation.

## Independent task reviews

The capital/replay review and frozen-ML review passed after fixes. Reviewed boundaries include canonical dataset validation, global holdout protection, complete source identity, float32 JSON-forest inference, contract and quantity preservation, shared conservative risk admission, all-ineligible opportunities, allocation revision invalidation and stale session-seed rejection before holdout consumption.

Final windows with a preceding feature session more than seven calendar days old are unsupported and fail before consumption. This conservative support limit accepts weekends and short closures; it is not a complete exchange-holiday calendar. Dataset 3 has a one-day development/final boundary. Older-quarter datasets 4–7 have months-long gaps into the common 2026 holdout and cannot use that boundary as a recent seed.

## Verification results

- Frontend: `NODE_OPTIONS=--no-experimental-webstorage npm run test:run` — 177 files, 2,786 tests passed. Two headless-canvas warnings occurred; they did not fail the suite.
- Focused ML fixes: 48 tests passed; shared risk/qualification regressions: 97 passed; stale-seed and ML/jobs coverage: 40 passed.
- Backend release regression: 4,084 passed, 16 skipped, one expected failure, seven warnings across 134 suite targets. Includes fresh and legacy schema migrations, isolated status/apply with no exported database URL, risk/qualification and ML contracts.
- Final frontend rerun: 2,786 passed across 177 files. Production build succeeded; its existing chunk-size warning remains.
- Whole-branch review and publication verification are recorded below when complete.

## Account preservation

A read-only database snapshot matched the initial baseline: five saved strategies, all stopped and none live-enabled; existing Flow activation unchanged; identical raw saved-cost hash; unchanged allocations/peaks/pause flags; zero Strategy Module orders, zero risk trades and zero final-use records. The refreshed production Positions UI showed zero open positions and ₹0 P&L.

## Release review and hygiene

The whole-branch review found no critical/P1 issue in the inspected paths. It found one explicit migration omission for scalping columns; its fix and scoped review are recorded below. The separate equity parser review is approved; its final cached-source checks passed 24 tests, and its CI checks passed 22 with two optional cache checks skipped. The final immutable rerun reproduced all 869 scenario ledgers and model outputs.

`git diff --check` passed. All 31 asset references in the built HTML exist. A non-network secret scan of 249 changed text files was reviewed: flagged values were provenance/revision hashes and explicit test-only credentials. Raw vendor inputs, local account snapshots and execution ledgers remain ignored.

A whole-branch Python lint pass is **not** clean: it reports 47 style/import findings, mostly in earlier historical simulation helpers and six import blocks. Narrower completion-source Ruff checks passed. This report does not claim repository-wide lint cleanliness.

Immediately before planned restart, the account snapshot still matched the initial baseline and the refreshed broker Positions UI showed no open positions. No final sessions had been consumed.

The explicit migration now adds both missing nullable scalping columns. Focused migration checks passed **43 tests, with one Windows-only skip**; scoped independent review approved the fix with no new P1/P2 findings. The whole-branch source review is approved. The ML implementation hash remained exactly `e21d7d5e709e334d5301eb6bcde5f3fb6987bf7f45e7db1615b0b89568ad387c`.

## Running application

The locally owned supervisor stopped cleanly and restarted after migrations. Status reported app PID 86544 and research worker PID 86553 ready. The served HTML matched the built HTML byte-for-byte; all 31 referenced assets matched their local build files. The actual Research UI displayed both unchanged ₹10,000 account allocations after restart. The post-restart account snapshot still matched the baseline exactly.

The selected development run was queued through the real Research UI as run **12**, dataset **3**, ₹25,000 research capital, seed 42, three chronological folds, minimum 10 training sessions, 100 trees, probability threshold 0.5 and 15-minute maximum holding time. Historical cost dates/reference were changed only in the research form draft; the saved enabled profile costs were not updated.

## Real-data UI final and account verification

Run 12 completed and exactly matched the offline selected model, predictions, signal schedule, and all base/stress trade and analytics records. Only run-kind/dependency/runner-provenance configuration metadata differed. It was frozen through the UI. The one-shot final ran as **13** across 60 sessions, with the same model/artifact hash and `split.refitted=false`.

The final **failed**: base net **-₹4,442.45**, 47 trades, 38.30% wins, maximum drawdown 19.9782%; stress net **-₹3,948.62**, 45 trades. Accuracy **51.36%** was below the **57.79%** majority baseline. Both ledgers reconcile. The actual UI installation action was rejected for non-positive final net P&L; no strategy or Flow was created. Returning to run 12 showed the final action disabled. The results tab was left open for review.

Afterward, a read-only account comparison showed only the intended `final_use_count` change (0 → 60). The same five strategies remained stopped, none live-enabled, with identical Flow activation, saved fee hashes and account capital/peaks/pause flags. Strategy Module orders and risk trades remained zero. No future Sandbox evidence was invented. See `completion-options-study-2026-09-27.md` for the full interpretation.

## Controller decision

Preserve the existing live risk guard and use its conservative, versioned admission formula for new ML replay/sizing. This avoids admitting research sizes that the live guard would reject. The tradeoff is that some otherwise tradable opportunities may be rejected or sized down; it does not loosen the guard.
