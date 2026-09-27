# Corrected replay and bounded strategy comparison — 26 September 2026

Implementation defects are corrected, and all five planned historical experiments were run through the UI. One baseline control is profitable in this sample. None of the candidates meets the predefined evidence threshold for final testing; repeatable profitability remains unproven.

Follow-up: [240 additional sessions and cost stress tests](strategy-robustness-2026-09-26.md) found losses in all four new 2025 quarters. The earlier positive control did not demonstrate robust profitability.

## What changed

- Five-minute underlying signals can now execute against one-minute option candles. Target-before-later-stop sequences are preserved; missing execution bars invalidate the replay. Same-minute protective-exit/target ambiguity remains conservative and is visible in Results.
- Tick size and execution interval are included in immutable dataset hashes. Decimal arithmetic prevents exact targets from rounding up an extra tick. Original candidates retain percentage targets.
- Added a separate filtered breakout hypothesis: independent prior-bar trend, 15-minute cooldown, three-entry daily cap, non-expiry contracts, observed liquidity/affordability, and volatility-adjusted stops. These are research rules, not a new live Flow.
- Kept capital ₹10,000, first filled trade risk ₹1,000, all later trades sharing another ₹1,000 per day, daily ₹2,000, persistent 20% drawdown protection and 20% cash buffer.
- Results show signal/execution resolution and unresolved candle ambiguity without adding more tuning fields.

## Fixed experiment and outcomes

Plan: [preregistered comparison](plans/2026-09-26-replay-and-filtered-strategy.md). Exactly four filtered variants and one original control; no added variants after observing outcomes.

Dataset #3 has 87,318 rows, 182 contracts and 120 sessions. Its daily universe is selected at 09:20 from observed affordable premiums, prior-session NSE listings and 1–7 calendar days to expiry. No future strategy return enters contract selection. Raw minute bars were checked against NSE daily ranges; no selected rows required omission. Two sessions lacked the 09:20 underlying close and therefore supplied no selected option contracts. Eleven further call-side and thirteen put-side selections had no eligible opening contract.

Training: 42 sessions, 22 January–24 March 2026. Exploratory later period: 18 sessions, 25 March–23 April. Each split starts independently at ₹10,000; do not sum their P&Ls as one continuous account return. The final 60 sessions, 24 April–21 July, remain unused.

Net figures include the same hypothetical current Kotak NFO cost schedule applied to historical prices, with 10 basis points adverse slippage per side. They are not actual broker fills or a verified historical fee table. Stress uses 30 basis points and 1.5× brokerage (the assumed brokerage is zero).

| UI run | Rules | Training net | Later-period net | Stressed later net | Trades: training / later |
|---|---|---:|---:|---:|---:|
| #3 | Original breakout control | +₹1,883.90 | +₹816.19 | +₹760.94 | 11 / 3 |
| #4 | Filtered: 10 bars, 1.5R target | −₹1,594.10 | −₹1,512.88 | −₹1,545.38 | 5 / 2 |
| #5 | Filtered: 10 bars, 2.0R target | −₹1,097.03 | −₹1,512.88 | −₹1,545.38 | 6 / 2 |
| #6 | Filtered: 20 bars, 1.5R target | −₹1,594.10 | −₹1,509.07 | −₹1,561.05 | 5 / 3 |
| #7 | Filtered: 20 bars, 2.0R target | −₹1,097.03 | −₹1,509.07 | −₹1,561.05 | 6 / 3 |

R is the planned stop distance; 2R means twice that distance. All five runs have complete recorded outcomes and zero ambiguous exits in all three splits.

## Interpretation and decision

The new dataset excludes expiry-day contracts and uses finer execution resolution, so Run #3 is not a controlled estimate of the change from older Run #2. Several things changed at once. Its original selector also retains missing-quote rejections for the limited imported universe; this is a control, not a deployable proof of edge.

Run #3 earned +₹1,883.90 over 11 training trades and +₹816.19 over just three later-period trades. Stressed later-period P&L stayed positive at +₹760.94. However, training maximum observed drawdown was 19.08% and the exploratory later-period bootstrap interval includes losses (5th percentile −₹1,444.44). The small sample does not establish a durable advantage.

All four filtered variants lost in both periods. Their extra conditions are rejected as improvements by this experiment. They remain labeled research hypotheses for inspection; they were not promoted or connected to live orders.

No version passed the preregistered requirement for positive training, later and stress results plus at least 20 training and 10 later trades, no incomplete outcomes and no ambiguous exits. Therefore no version was frozen, the final holdout was not consumed, and trading was not activated. Gathering additional independent evidence and forward paper observations is necessary before any live-profit claim; increasing risk or retuning against the reserved dates is not a remedy for the failed evidence threshold.

## Verification

- All five experiments were imported/queued/viewed through the browser UI, saved as runs #3–#7, and reproduced independently with exact report equality.
- Dataset, configuration and implementation hashes match. The session-use ledger confirms zero use of the reserved dates.
- 334 research/risk/qualification tests passed, including 20 new regressions. Independent reviewer found the tick-boundary and original-target issues; both now have regression coverage.
- All 2,777 frontend tests passed under Node 26 with `NODE_OPTIONS=--no-experimental-webstorage`; the ordinary run exposed Node’s unavailable native localStorage. Production build passed with its bundle-size warning.
- Full backend run: 6,117 passed, 29 skipped, 1 expected failure, 10 failed and 11 errors. Failures outside this change remain listed below; this is not a claim that the whole repository is green.
- Resource audit (static): replay state is per-run, bounded by the 100,000-row/2,000-contract import caps; ATR histories retain 11 bars per symbol and reset daily. No new production sockets, threads or DB connections. Preparation/verification DuckDB, gzip and SQLAlchemy resources use context managers; engines are disposed in `finally`. No leak was diagnosed; no long-duration leak measurement claimed.
- Managed local app and worker were reloaded. All nine saved strategies remain stopped, strategy order count is zero, and saved live costs retain their original 26 September–10 October dates. No broker orders were sent by this work.

### Backend checks that are not green

Telegram async tests lack an async runner, its subprocess environment lacks eventlet, TradeSmart rate-limiter tests have signature/concurrency failures, and OpenScript cleanup cannot enumerate processes inside the restricted sandbox. These are outside the modified research/risk path.

- `FAILED test/test_telegram_bot.py::test_bot - Failed: async def functions are ...`
- `FAILED test/test_telegram_charts.py::test_chart_generation - Failed: async de...`
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

## Evidence

Local data and complete reports (ignored by Git): `data/research/filtered-minute-2026-09-26/`. Files include `preregistered-comparison.json`, `validation.json`, `contract-selection.csv`, `nifty-2026-mixed-resolution.json`, `run-3.json` through `run-7.json`, `comparison.json`, `test-results.json`, preparation and independent-verification scripts.

Dataset SHA-256: `749fd29a6d78f55c0ea52cb1f9dc33a81f549ed300259c40ef0dcbf68f3c715a`.
Implementation fingerprint: `1b32efb798bdb2aaa0ffda32d368aaf382d371fbd48ab338ac907ce6ed4f54d4`.

Underlying source: existing Kotak Neo five-minute history. Options: public rissin/Upstox archive, with provider redistribution rights still unverified; use remains private exploratory analysis. Official prior-day NSE archives supply lot sizes and listing checks. Tick source: [NSE NIFTY options contract specifications](https://www.nseindia.com/static/products-services/equity-derivatives-nifty50).
