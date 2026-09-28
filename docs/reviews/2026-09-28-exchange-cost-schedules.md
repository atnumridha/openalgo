# Exchange-specific fee schedule correction

SENSEX Sandbox entry was refused with `cost_schedule_exchange_mismatch` because the account had only a dated NFO fee schedule. The old settings model stored one schedule per account, so saving BFO costs would overwrite NIFTY's costs. Arming a workflow alone did not establish entry readiness.

The additive `trading_risk_cost_schedule` table stores each owner's NFO, BFO and MCX schedules separately. Existing settings remain readable without changing their values. Saving another exchange preserves the default; updating that default's exchange keeps its legacy representation current. Entry admission selects the resolved contract exchange and retains mismatch, expiry, broker, cash, whole-lot and loss checks. Reserved trades retain their original fee snapshot. Qualification binding and dispatch select the same exchange; NIFTY ML explicitly selects NFO.

The costs screen switches between saved markets, clears the fee form for an unsaved market and provides editable BFO/MCX planning presets. It never relabels NSE fees as BSE fees. BSE presets cover SENSEX/BANKEX (not every BSE derivative). MCX sell tax is CTT. These are planning assumptions, not broker-reconciled charges, and the effective end date remains explicit.

Sources checked 28 September 2026:
- [Kotak Neo API brokerage](https://www.kotakneo.com/support/what-is-the-brokerage-for-using-neo-trade-api/) supports zero API brokerage on Trade Free plans.
- [Exchange transaction charges](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges) lists SENSEX/BANKEX options at 0.0325% and MCX options at 0.0418% of premium per side.
- [Current statutory rates](https://groww.in/pricing/futures-and-options) lists equity-options sell STT at 0.15%, commodity-options sell CTT at 0.05%, buy stamp duty at 0.003% and SEBI fees at 0.0001%.

No allocation, stops, risk ceilings, live opt-ins or authorization gates are changed by this correction. Strategy entry can still be rejected for valid risk, data, instrument or signal reasons.

## Verification

The regression tests first reproduced the single-schedule overwrite and missing market selector, then passed with the correction. The UI suite passed all 2,799 tests on supported Node 24.15; the first Node 26 attempt failed because its native `localStorage` shadowed the browser test environment. The TypeScript/Vite build passed, with the existing chunk-size warning. Independent review found no actionable source-code issues.

The full backend suite recorded 6,697 passed, 31 skipped, one expected failure, 10 failures and 11 teardown errors. The same 10 failures and 11 errors reproduce on a clean archive of unchanged baseline `87c4344ee`, so the full suite is not green but these are not introduced by this correction. TradeSmart tests call an obsolete private rate-limiter signature; two Telegram tests lack an async pytest runner and the eventlet startup test lacks its optional dependency; OpenScript teardown cannot inspect macOS processes inside the filesystem sandbox. Existing warning categories include return-not-None test functions, Pydantic forward references and a SQLAlchemy identity-map warning.

Baseline-confirmed failures/errors (unchanged files):
- `FAILED test/test_telegram_bot.py::test_bot`
- `FAILED test/test_telegram_charts.py::test_chart_generation`
- `FAILED test/test_telegram_startup.py::test_bot_starts_and_stops_cleanly_in_eventlet_env`
- `FAILED test/test_tradesmart_rate_limiter.py::TestCeilings::test_quotes_are_not_exempt_from_any_window`
- `FAILED test/test_tradesmart_rate_limiter.py::TestPacing::test_the_call_after_the_cap_waits_a_full_second`
- `FAILED test/test_tradesmart_rate_limiter.py::TestPacing::test_an_option_chain_batch_is_paced_not_rejected`
- `FAILED test/test_tradesmart_rate_limiter.py::TestPacing::test_history_and_quotes_share_one_budget`
- `FAILED test/test_tradesmart_rate_limiter.py::TestWindowBookkeeping::test_entries_older_than_a_minute_stop_constraining`
- `FAILED test/test_tradesmart_rate_limiter.py::TestWindowBookkeeping::test_reservations_stay_ordered`
- `FAILED test/test_tradesmart_rate_limiter.py::TestConcurrency::test_threads_space_out_rather_than_firing_together`
- `ERROR test/test_openscript_runner.py::test_starting_a_run_hands_the_worker_back_at_once`
- `ERROR test/test_openscript_runner.py::test_stopping_a_run_reaps_the_process`
- `ERROR test/test_openscript_runner.py::test_the_log_goes_where_this_platform_already_keeps_strategy_logs`
- `ERROR test/test_openscript_runner.py::test_a_second_start_is_refused_while_the_first_is_running`
- `ERROR test/test_openscript_runner.py::test_every_run_is_stopped_before_the_worker_goes`
- `ERROR test/test_openscript_runner.py::test_a_run_starts_from_the_script_name_alone`
- `ERROR test/test_openscript_runner.py::test_what_the_caller_holds_wins_over_what_was_saved`
- `ERROR test/test_openscript_runner.py::test_a_script_with_no_run_settings_is_refused_by_name`
- `ERROR test/test_openscript_runner.py::test_settings_missing_one_field_say_which_one`
- `ERROR test/test_openscript_runner.py::test_a_product_that_is_not_one_this_platform_sends_never_reaches_a_command_line`
- `ERROR test/test_openscript_runner.py::test_removing_the_settings_removes_the_run`

## Local rollout and browser verification

The focused backend set passed **168 tests** in the isolated worktree and again on merged main. Main-checkout pytest initially shadowed the installed `openalgo` SDK with the repository package; preloading the SDK before invoking pytest resolved those eight import failures without a source change.

Restarted the app and research worker after verifying zero open managed runs, zero pending risk positions and zero live opt-ins. Both services returned ready. Through the actual UI, saved BFO and MCX planning schedules for 28 September–10 October 2026 and switched back to confirm NSE fees remained intact. Read-only before/after snapshots match for the existing default NSE costs, allocations/policy/revisions, sixteen strategy activation/live flags and all Flow activation flags.

Retried the exact SENSEX 5/15-minute Sandbox start in the browser. It passed fee selection and now correctly returns `per_trade_risk_exceeded`: its one-lot, 20-point stop does not fit the effective INR100 all-in per-trade allowance at INR10,000 allocated equity. No open run or order was created. The risk limit was not bypassed, and no strategy was live-enabled. This verifies the reported cost defect is fixed; it does not claim every template is affordable or profitable.
