# Research workflow verification — 27 September 2026

This is the earlier verification snapshot. The later [completion verification](completion-verification-2026-09-27.md) supersedes its research-only ML boundary: frozen final inference and an explicit gated installer now exist. The historical browser observations below remain a record of the earlier build.

## Scope and environment

Tested the new research workflows on `feature/research-all-phases`, based on commit `684a047582e99f97ae3f953a19621ca03530aebb` plus the working-tree implementation. Used the production frontend build in the Codex in-app browser at an isolated localhost instance on port 5059.

The research blueprint, dataset validation, database store, job orchestration, replay, optimization and RandomForest implementation were real. Authentication, broker capabilities, risk-profile responses, daily-history status and the qualification list were test doubles. All database files and imported fixtures were under `/tmp/openalgo-research-ui-qa/`. No broker/order endpoints were registered in the test host. The user's app server and account database were not restarted or used for these mutations.

**This was functional software verification using synthetic datasets, not a market backtest or evidence of strategy profitability.** The deliberately separable mixed-label fixture produces high ML scores; those scores must not be presented as expected live accuracy. No real Sandbox campaign, live broker login, order placement, release approval, account-risk setup or NSE download was exercised in this browser session.

## Browser scenario matrix

| Scenario | Observed result |
|---|---|
| Load the built Research page | Four preparation tabs, test-service status and research controls rendered. |
| Invalid JSON dataset | Import validation error displayed; no dataset created. |
| Valid deterministic fixture | 960 bars imported; dataset selected with source and content fingerprint. |
| Empty comparison grid | Clear instruction to choose 1–256 combinations. |
| Duplicate comparison values | Duplicate-value error displayed. |
| Oversized comparison grid | 257 combinations displayed; comparison submission disabled. |
| Two-candidate optimization | Run #1 completed; comparison table and selected report rendered. |
| Preserve fixed parameters | Both candidates retained the chosen 15% stop and 30% target. |
| Promote selected parameters | Run #2 created as ordinary development with parent #1; completed. |
| Freeze development | Run #2 marked frozen. |
| Final-test acknowledgement | Submission disabled until the explicit acknowledgement was checked. |
| Final evaluation | Run #3 completed, linked to #2, consuming 60 sealed fixture sessions. |
| Prevent repeated final test | Returning to #2 showed the final-test button disabled. |
| Valid minute-execution dataset | 21,600 bars imported with the expected 80-session summary. |
| ML constant-class result | Run #4 completed; accuracy/baseline, no-trade metrics and evidence rendered. |
| ML live boundary | No freeze or promotion action for ML; research-only limitation displayed. |
| Fold and hash details | Expandable chronology and reproducibility evidence rendered. |
| Queue cancellation | Worker paused in test harness; run #5 queued, then cancelled through the UI. |
| Missing ML dependency | Simulated unavailable dependency produced an explanation and disabled training. |
| Worker offline | Offline status displayed and training disabled; restored worker re-enabled it. |
| Incompatible execution data | ML on five-minute-only option history rejected with a one-minute-data requirement. |
| Invalid ML settings | Twenty folds rejected with the allowed 2–10 range. |
| Mixed-label RandomForest | Run #6 completed; persisted artifact contained 50 fitted trees. |
| Misleading ML form controls | Found irrelevant deterministic controls/copy; corrected and rechecked the rebuilt UI with regression coverage. |
| Empty eligible-opportunity set | Run #7 failed visibly with “RandomForest research produced no usable opportunities”. |
| Recovery after failed run | Run #8 on the mixed-label fixture completed; model and prediction hashes matched #6. |
| Sandbox & live tab | Policy and final-run selector rendered; enrollment disabled without an available saved strategy. This is rendering/gating coverage only. |
| Visual inspection | Result cards, metrics, wrapping hashes and scrollable tables inspected at the browser's existing narrow viewport. |

Eight jobs were created through browser actions: six completed (#1, #2, #3, #4, #6, #8), one intentionally cancelled (#5), and one intentionally failed (#7). Database inspection confirmed these states and the promotion ancestry. No warnings or errors were returned by the browser console inspection after the final checks.

## Test-host stall investigation

The initial temporary harness ran its Flask request threads and research worker thread in one process. After earlier scenarios passed, an import and overview request stalled. A health request and the daily-status stub still responded, while a process sample showed the worker blocked during SQLite WAL connection close and request threads waiting in SQLite connection opening. The native library was `libsqlite3.3.51.0.dylib` under the local Python 3.13 runtime.

Stopped only that temporary host. Changed the harness to a separate worker process and a non-threaded test web server, following the application's separate-worker design and avoiding concurrent native SQLite calls inside one test process. Reused the isolated database, retried the import, completed the expected failed run, and then completed another real forest training run. Overview response time recovered to about 4 ms in the direct diagnostic request.

This establishes recovery of the test harness, **not a general SQLite fix or proof that the production runtime cannot encounter native locking problems**. No application database-engine change was made. The process sample is retained locally at `/tmp/research-ui-process-sample.txt` for further diagnosis if the symptom recurs under the normal startup topology.

## Automated verification

| Check | Result |
|---|---|
| Backend CI-safe and affected suites | 3,978 passed, 13 skipped, 1 expected failure; 7 warnings. |
| Frontend suite | 2,786 passed across 177 files. |
| Research page regression tests | 25 passed, included in frontend total. |
| Ruff and format check | Modified Python files passed. |
| Frontend lint | Passed; 4 existing warnings and 2 information messages. |
| Production build | Passed; existing chunk-size warning. |
| Patch whitespace | `git diff --check` passed. |

Used `NODE_OPTIONS=--no-experimental-webstorage` for the local Node 26 test runner. Backend tests imported the installed `openalgo` SDK before pytest discovery to avoid the local test-directory name collision. Relevant logs remain in `/tmp/research-backend-final.log`, `/tmp/research-frontend-final.log`, `/tmp/research-final-build.log` and `/tmp/research-final-lint.log`.

Independent code review identified late grid-bound validation and missing cancellation checks during feature-group preparation. Both findings received failing regression tests followed by fixes and passing verification. No further product changes were made after the final full-suite runs; subsequent changes were documentation and the temporary test harness.

## Remaining deployment boundary

Optimization candidates can use the existing development → freeze → final → forward-qualification path. RandomForest models remain research-only because live feature preparation and inference have no verified adapter. ML freeze/final/promotion are blocked deliberately and are not reported as completed live functionality. Production broker behavior and future profitability remain unverified by this work.
