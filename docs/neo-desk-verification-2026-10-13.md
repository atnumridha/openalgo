# Native OpenAlgo / Kotak verification — 13 October 2026

Native terminal: http://127.0.0.1:5001/scalping. Native replay: http://127.0.0.1:5001/neo-backtests.
Branch `codex/neo-native-kotak`, based on official snapshot `f2d28cd54f6484a329032ecd62af138c663e2e0f`. The old port 8787 terminal and its data remain available for rollback. No external publish, merge or real test order was performed.

## Execution and latest sizing request

Four selectable presets, one active at a time. Default `orb_trail`; the Price Break & Retest preset is Sandbox research only. The deployment is **Sandbox / Stopped / flat**. A successful connection alone does not start entries.

Automation prefers **two whole 65-unit lots (130 units maximum)** when fees-inclusive entry spending and live bid/ask depth permit; otherwise one lot or no entry. Controlled profiles also check their planned premium risk against ₹500 and 5% of available funds. Near ₹50 with their 10% stop, that risk check normally permits one lot even when cash could fund two. Original ORB retains its monitored ₹500 loss threshold. Slippage/gaps can exceed thresholds.

Research uses the same at-most-two-lot sizing math. Without reinvestment, sizing allowance cannot exceed initial ₹10,000; with reinvestment it follows available model cash up to the two-lot maximum. Unknown exit proceeds are never reinvested. Native order quantity, expected resolver quantity and persisted protection all use the selected quantity.

Confirmed 15-minute NIFTY setups; buy CE or PE, never short options. Entry window 09:45–15:15 IST; exact owned square-off 15:29 IST. Index 6R targets describe index points, not a guaranteed option return. Existing ₹1,000 daily guard / three accepted entries remain.

## UI and feed evidence

Actual authenticated session reused without requesting a new TOTP. Native funds/books, recorded execution history, NIFTY and exact CE/PE prices, runtime indicators and backtest job/results were inspected from the browser.

The sample browser WebSocket port 8765 differed from isolated proxy 8767. Provisioning and actual private configuration now agree at 8767; protocol authentication/subscription and actual SFeed authentication were verified. Numeric server millisecond timestamps now update chart candles directly. Stale/after-hours snapshots cannot fabricate candles. Exchange-to-client latency cannot be measured after market close; no zero-lag guarantee is made.

Missing custom indicators now produce a visible per-chart error and leave controls usable. Historical refreshes do not erase that indicator error. Live overlays are tied to exact instrument/run/confirmed quantity; index targets are not plotted on option-premium scales.

An isolated browser fixture used synthetic market prices and the real native Sandbox order/position persistence. UI Start → one native 130-unit entry → duplicate setup refused → manual option SL ₹47.50 / target ₹100 → cash trail → synthetic premium ₹70 → gross running ₹2,600 / net estimate ₹2,555.99 → effective stop ₹68.10 → loosening refused immediately → tightened stop ₹68.50 → exact-owned square-off → flat / Stopped. Database facts show **two orders, two fills, zero remaining quantity**. The fixture explicitly blocked Live dispatch and used separate temporary databases. These figures prove execution/control plumbing only, not profitability. Recorded Sandbox fill facts were applied through the native event handler; the test was not a broker fill test.

Private screenshots are under the original worktree's `artifacts/`: `native-openalgo-history.png`, `native-openalgo-charts.png`, `native-openalgo-feed-fixed.png`, `native-openalgo-replay-fixed.png`, `native-openalgo-simulated-running.png`, `native-openalgo-simulated-flat.png`. Account data and migration backups are excluded from Git.

## Historical coverage and replay failure

The failing selected `kotak-active` archive had no verified option candle file. The selector now requires supported 15-minute NIFTY and 1-minute option files, actual files with hash metadata, supported contract identities and overlapping historical validity. Synthetic/index-only/wrong-timeframe archives are excluded. Loading verifies checksums, timezone-aware valid OHLC and duplicate timestamps. Known failures have actionable safe messages.

Available verified archive `nifty-13oct-active-nse-20261011`: 20 trading dates, 10 September–9 October 2026, only the 13 October expiry; 98 archived CE/PE contracts; data ends before final settlement. Index warmup begins 11 August. Index SHA-256 `b4d7c333b1de59ae6508558eade834d1d35587bb224d4da330594f8ad25aafa3`; options SHA-256 `57165ddaaa1576cf58eff7d66500402a23cb70f7f9a0af236a288802031fa4fc`. Missing minutes are not forward filled. Expired contracts and unobserved quotes are not synthesized.

All four presets reran with the two-lot maximum. ORB index trail has one unresolved 130-unit entry, no resolved close, estimated entry charges ₹14.78. ORB option controls and Price Retest each encounter an unresolved trade before a resolved close. Donchian has one resolved close at ₹1,035.65 net estimate plus one unresolved trade. **Every complete-period return remains unavailable**. The job completes successfully while accurately describing incomplete historical coverage. These observations cannot select a profitable month winner. The approved ORB default is retained, not promoted using an incomplete ranking.

Replay assumes observed OHLC open/low with ₹0.50 friction; historical bid/ask/depth and exact intrabar execution order are unavailable. Existing stops evaluate before newly earned trails; index changes use confirmed 15-minute closes. One-year selection is supported only where real data exists.

## Migration, fees and context

1,205 backup files preserved privately; 103 recorded fills imported with zero additional rows on repeat. Current-day API refresh reuses duplicate fills and uses fill timestamps rather than order timestamps. Missing opening inventory and same-time ambiguity stay unresolved. Gross resolved subtotal has explicit coverage. Paid fees stay unknown where not actually reported. Reports now offer the user-confirmed free-brokerage assumption and the standard ₹10 executed-order plan separately. No promotion dates or actual paid charges are fabricated. Historical strategy risk/replay costs retain the conservative standard plan when a dated historical offer is unverified. Zero-fill cancellations do not contribute; partial executions do. Actual paid fees are never relabelled from estimates.

Official NIFTY membership request required CSV headers; after correction, actual broker snapshots cover 50/50 constituents with no context error. These were after-hours last-reported values, not fresh execution quotes. Missing previous close / uncertain timestamps stay labelled. NSE MCP is delayed informational context; trade-price charts use Kotak streaming.

## Verification

Python 3.12.14; Gunicorn gthread, one worker/64 threads; loopback HTTP5001/WS8767/ZMQ5557; debug off.

Full frontend: **3,494 passed across 257 files**. Final native frontend and Live controls also passed targeted tests. Type checking and production build passed; existing large-chunk warning remains. Native backend/risk/session tests: 326 passed in 1.69s. Full backend: earlier final-user run **8,091 passed, 58 failed, 3 fixture errors, 78 skipped, 5 xfailed**, with exactly the 61 clean-baseline failure identities. The subsequent final-reviewed run reports **8,093 passed, 60 failed, 3 fixture errors, 78 skipped, 5 xfailed**. Two additional failures occur in byte-identical upstream Flow wait/Upstox retry tests: the former depends on distance from midnight, the latter captures sleeps from unrelated background threads. Both passed in isolation (2/2) after the midnight rollover; file hashes match the official base for both implementations and tests. Their evidence is retained privately. This is not a globally green backend suite. Baseline names are listed below, rather than claiming the full backend is green.

Ruff native feature checks passed. Biome native feature lint has no errors/warnings, nine template-literal style infos. Production dependency audit: zero vulnerabilities. Full dependency audit retains four high-severity transitive test-tool findings (`braces`, `expect`, `jest-message-util`, `micromatch`); no unrelated dependency upgrade was performed.

Final 30-second passive native worker probe: 248 descriptors throughout; RSS about 569.5→569.6MB; threads +1 and plateaued. This is bounded observation, not a long-session leak guarantee. Final read-only account check: zero broker positions with nonzero quantity, zero pending broker orders; zero native open runs/provider pending. Old journal recorded zero intents and no owned exposure.

## Daily startup

1. Keep the machine and native server available; open the native terminal.
2. A valid same-day broker session is reused. After expiry, enter only the fresh TOTP; mobile/MPIN/token stay server-side.
3. Verify current broker trading allowance, selected instrument/expiry and actual feed timestamps during market hours. Read any blocking/waiting reason.
4. Select one preset while flat/stopped and press Start Sandbox for paper entries. A qualified confirmed setup is required; zero entries may correctly reflect unmet rules.
5. For real trading, the user chooses Live, confirms new real orders and presses Start Live. Migration/testing does not activate Live.
6. Stop entries keeps existing owned exits managed. Use exact-owned premium controls and confirm square-off to exit that trade. Review broker positions separately for manual holdings.
7. To roll back, stop entries and verify owned/pending exposure is flat first. The original terminal remains preserved; avoid running both automations simultaneously.

## Decisions carried from approved plans

- Ruling: New managed checkout is outside this turn's sandbox writable roots; use scoped approved file/dependency commands in that checkout — preserves clean isolation — cost if wrong: deployment permission failure, with current terminal unaffected.
- Ruling: Preserve approved Live activation semantics using native trader wording “Start Live”; upstream forbids user-facing “arm” vocabulary — same explicit user-controlled action — cost if wrong: wording expectation only.
- Ruling: Pin the observed approved upstream SHA despite origin advancing during fetch — verified clean source remains reproducible — cost if wrong: later upstream fixes require a separate update.
- Ruling: Proceed with the requested migration while retaining the pre-existing baseline failure register; no blanket full-suite green claim — cost if wrong: unrelated upstream defects remain outside the Kotak feature evidence.
- Ruling: Reuse only a verified legacy signed owner browser cookie plus a bound unexpired broker cache and successful read-only broker validation; the cache alone cannot sign in a browser — satisfies the approved session-reuse requirement — cost if wrong: account binding/authentication failure; final independent review must examine this.
- Ruling: Native direct launcher refuses Werkzeug with debug off on macOS; add the upstream-required Gunicorn >=25,<26 runtime and explicitly select gthread with one worker/64 threads — preserves debug-off loopback operation and uses the supported runtime — cost if wrong: runtime regression; verify native gthread paths.
- Task 2: Ruling: Native batch runs are the provider lifecycle; add a server-side hook to signals.py and pass checked literal contracts/limit prices through the existing resolver and engine — preserves all native order ownership, partial-fill and mode invariants — cost if wrong: provider entry refused, with no alternate execution pipe.
- Task 3: Ruling: Extend the pure shared risk package with typed index/option protection rather than altering existing per-position vectors — the existing browser trail contract remains unchanged, and the new index/cash rules are server authoritative — cost if wrong: missing cross-language coverage, mitigated by separate typed golden fixtures and UI display-only stops.
- Task 3: Ruling: Reuse the native scheduler, recovery and stop_run machinery through one supplemental management job; no replacement tick feed or exit pipe — native exact fill/claim/mode semantics remain authoritative — cost if wrong: quote polling latency, surfaced in readiness and runtime checks.
- Task 4: Ruling: Broker REST depth snapshots may omit an exchange timestamp; preserve exchange_time=None and label server observation time, permitting only a directly verified depth response younger than five seconds — avoids fabricating exchange time while retaining executable depth evidence — cost if wrong: broker-side snapshot staleness cannot be measured, so strict spread/depth checks and refusal on delayed reads remain.
- Task 4: Ruling: Kotak Net is the entry trading limit and cash stays separate; absent Net refuses new entries rather than deriving spending from collateral/cash — preserves reported affordability — cost if wrong: a valid account can be blocked when broker omits Net.
- Task 4: Ruling: combine the full simulated browser trade journey with Part 2 final verification — its running P&L/manual controls/replay surfaces are produced there; foundation now proves real native Sandbox dispatch, fills, trail-triggered exit and flat persistence with a synthetic quote boundary — cost if wrong: browser integration regression delayed until final gate.
- Task 4: Ruling: optional Neo controls require a public build flag and server feature gate; marked native provider legs reject ordinary batch Start — keeps upstream deployments quiet and prevents entries without a confirmed setup — cost if wrong: misconfigured flag hides provider controls.
- Task 1: Ruling: adapt the preserved conservative FIFO mathematics to native owner-partitioned SQLAlchemy facts — avoids a second SQLite broker pipe while preserving previous accounting semantics — cost if wrong: historical matching mismatch; reconciliation is required.
- Task 1: Ruling: estimate ₹10 executed-order brokerage unless a dated promotion is verified — the user reports an active free period but its expiry is unknown; paid charges remain separate — cost if wrong: conservative estimates overstate costs during the free period.
- Task 2: Ruling: the Neo instance uses the native openalgo-charts engine in Scalping, preserving the upstream lightweight chart for normal installations — this enables the approved runtime indicator loader and instrument-bound overlays consistently — cost if wrong: chart interaction differences in the optional instance.
- Task 3: Ruling: a missing option minute makes protection/execution order unprovable, leaves the trade unresolved and stops reinvesting unknown proceeds — historical OHLC cannot supply missing executable bid/ask; no invented cash returned — cost if wrong: replay is more conservative and shorter than actual trading would have been.
- Task 4: Ruling: NSE MCP is informational context with documented 1–3 minute delay; use Kotak streaming for execution-price charts rather than that delayed source — preserves low-delay trade prices — cost if wrong: some public context fields may remain unavailable during provider outages.

## Pre-existing backend failure/error register

- `test/test_agent_chatgpt_oauth.py::test_the_subscription_models_are_offered_by_the_catalogue`
- `test/test_agent_chatgpt_wiring.py::TestTheProviderAsksForNoKey::test_every_model_it_offers_can_call_functions`
- `test/test_flow_custom_legs.py::TestALegReachesTheBrokerAsBuilt::test_a_relative_leg_expiry_is_resolved_to_a_date`
- `test/test_flow_custom_legs.py::TestTheLegBuilderOffersListedContracts::test_a_relative_type_is_resolved_when_no_date_is_given`
- `test/test_flow_custom_legs.py::TestTheLegBuilderOffersListedContracts::test_every_relative_type_reports_the_date_it_currently_picks`
- `test/test_gthread_deploy_launcher.py::test_an_unknown_value_starts_eventlet_and_says_why`
- `test/test_gthread_deploy_launcher.py::test_nothing_set_starts_eventlet_with_todays_flags`
- `test/test_gthread_deploy_launcher.py::test_the_last_assignment_wins`
- `test/test_gthread_deploy_switch_worker.py::test_a_customised_unit_is_left_untouched`
- `test/test_gthread_deploy_switch_worker.py::test_a_failed_start_puts_the_previous_file_back`
- `test/test_gthread_deploy_switch_worker.py::test_a_rendered_file_systemd_rejects_is_not_installed`
- `test/test_gthread_deploy_switch_worker.py::test_a_rollback_without_the_launcher_starts_as_before_the_switch[multi]`
- `test/test_gthread_deploy_switch_worker.py::test_a_rollback_without_the_launcher_starts_as_before_the_switch[single]`
- `test/test_gthread_deploy_switch_worker.py::test_a_service_can_be_picked_by_folder`
- `test/test_gthread_deploy_switch_worker.py::test_a_short_stop_window_is_lengthened`
- `test/test_gthread_deploy_switch_worker.py::test_a_unit_with_a_reload_command_is_refused`
- `test/test_gthread_deploy_switch_worker.py::test_an_already_switched_unit_is_left_alone`
- `test/test_gthread_deploy_switch_worker.py::test_an_installer_unit_is_switched_and_nothing_else_changes[multi]`
- `test/test_gthread_deploy_switch_worker.py::test_an_installer_unit_is_switched_and_nothing_else_changes[single]`
- `test/test_gthread_deploy_switch_worker.py::test_check_is_silent_and_true_only_when_a_switch_is_wanted`
- `test/test_gthread_deploy_switch_worker.py::test_dry_run_changes_nothing`
- `test/test_gthread_deploy_switch_worker.py::test_restore_puts_the_installer_file_back`
- `test/test_gthread_deploy_switch_worker.py::test_service_copy_failure_puts_env_back_before_any_restart`
- `test/test_gthread_deploy_switch_worker.py::test_several_services_need_a_name_or_all`
- `test/test_gthread_deploy_switch_worker.py::test_the_stop_window_is_kept_when_long_enough`
- `test/test_gthread_deploy_switch_worker.py::test_the_trading_day_boundaries[0900-True]`
- `test/test_gthread_deploy_switch_worker.py::test_the_trading_day_boundaries[2329-True]`
- `test/test_gthread_deploy_switch_worker.py::test_the_trading_day_is_refused_without_force`
- `test/test_gthread_deploy_switch_worker.py::test_to_sets_env_and_switches_back_and_forth`
- `test/test_gthread_deploy_switch_worker.py::test_update_during_the_trading_day_explains_and_changes_nothing`
- `test/test_gthread_deploy_switch_worker.py::test_update_is_unchanged_for_an_install_that_has_not_opted_in[#`
- `test/test_gthread_deploy_switch_worker.py::test_update_is_unchanged_for_an_install_that_has_not_opted_in[APP_KEY`
- `test/test_gthread_deploy_switch_worker.py::test_update_is_unchanged_for_an_install_that_has_not_opted_in[OPENALGO_WORKER_CLASS`
- `test/test_gthread_deploy_switch_worker.py::test_update_switches_an_opted_in_install_once`
- `test/test_gthread_deploy_switch_worker.py::test_when_nothing_starts_the_manual_rollback_is_printed`
- `test/test_gthread_hosts_python_launch.py::test_bootstrap_applies_the_limits`
- `test/test_gthread_memory_flow.py::test_already_inactive_deactivate_retries_held_subscription`
- `test/test_gthread_memory_flow.py::test_cleanup_refuses_a_workflow_still_executing[deactivate]`
- `test/test_gthread_memory_flow.py::test_cleanup_refuses_a_workflow_still_executing[delete]`
- `test/test_gthread_memory_flow.py::test_deactivate_waits_for_subscription_release`
- `test/test_gthread_memory_flow.py::test_delete_waits_for_subscription_release`
- `test/test_gthread_review_deploy.py::test_a_dry_run_restore_says_it_would_set_env_back`
- `test/test_gthread_review_deploy.py::test_restore_leaves_an_env_that_never_asked_for_gthread_alone`
- `test/test_gthread_review_deploy.py::test_restore_sets_env_back_so_the_next_update_does_not_switch_again`
- `test/test_mstock.py::TestMstockBroker::test_get_funds`
- `test/test_mstock.py::TestMstockBroker::test_get_holdings`
- `test/test_mstock.py::TestMstockBroker::test_get_positions`
- `test/test_mstock.py::TestMstockBroker::test_place_order`
- `test/test_rate_limits_mock.py::test_endpoint`
- `test/test_rate_limits_mock.py::test_multiple_clients`
- `test/test_rate_limits_mock.py::test_rate_limit_reset`
- `test/test_telegram_bot.py::test_bot`
- `test/test_telegram_charts.py::test_chart_generation`
- `test/test_telegram_startup.py::test_bot_starts_and_stops_cleanly_in_eventlet_env`
- `test/test_tradesmart_rate_limiter.py::TestCeilings::test_quotes_are_not_exempt_from_any_window`
- `test/test_tradesmart_rate_limiter.py::TestConcurrency::test_threads_space_out_rather_than_firing_together`
- `test/test_tradesmart_rate_limiter.py::TestPacing::test_an_option_chain_batch_is_paced_not_rejected`
- `test/test_tradesmart_rate_limiter.py::TestPacing::test_history_and_quotes_share_one_budget`
- `test/test_tradesmart_rate_limiter.py::TestPacing::test_the_call_after_the_cap_waits_a_full_second`
- `test/test_tradesmart_rate_limiter.py::TestWindowBookkeeping::test_entries_older_than_a_minute_stop_constraining`
- `test/test_tradesmart_rate_limiter.py::TestWindowBookkeeping::test_reservations_stay_ordered`


## Final review repairs and UI verification

One independent whole-branch reviewer found seven important problems. Regression tests first reproduced them, then passed after fixes: unavailable protection jobs permitting entries; owner locks blocking square-off during process/broker waits; eventlet CPU-bound replay; skipped entry-minute protection; missing entry observations counted as complete results; incorrect originating-mode display; and failed research commits leaking queue capacity. Stop/Start transition fencing is persisted and cleared after restart without deleting owned protection. No second review was dispatched.

Actual native UI verified Sandbox Start becomes Active with a running signal process, and Stop becomes Stopped. Read-only reconciliation found no native open runs, no pending entries, no broker nonzero positions and no pending broker orders. No real orders were placed for testing. A separate synthetic UI journey used the real native Sandbox dispatch/persistence: 130-unit entry, duplicate refusal, manual SL/target, ratcheting cash trail, loosening refusal, exact square-off, two fills and flat state. Its ₹2,600 gross is synthetic and must never be read as account earnings.

Native Trading now has NIFTY expiry plus CE and PE strike filters. It defaults to the nearest active expiry independently of descending expiry display. The displayed expiry rolls past expiry-day market close; exact CE/PE symbols are taken from broker metadata. Actual 19-October 22,750 CE and 22,650 PE charts showed ₹193.60 and ₹84.05, matching the logged-in broker chart. Custom Donchian20/EMA200, FVG/confirmed structure and RSI14 loaded visibly. Visual zones are limited to eight recent drawings. Startup waits for native chart restoration. NIFTY underlying history never routes to NFO while chain metadata is loading. Source/session checks prevent after-hours snapshots becoming invented candles. The native chart timeframe remains selectable; strategy execution remains confirmed NIFTY15m.

Readiness now follows current entry mode/activation immediately, while owned trades retain their originating mode. Start Live is one explicit trader action that authorizes real option orders; the separate consent checkbox has been removed at the user’s request. Backend authentication, confirmation flags, mode and ownership guards remain enforced; no extra arming step. The three supported live profiles passed authenticated Start/Stop tests with broker dispatch mocked. Actual live execution quality is not established by these tests.

## Corrected report fee assumptions

The flagged report had combined two recorded days and used standard executed-order brokerage despite the user's active free offer. The corrected report makes plan and date scope visible, shows per-trade estimated charges/net, and explains unresolved execution sequences or unreported paid charges. The corrected private totals and executed-order counts are preserved in runtime verification evidence. The figures are estimates, not paid-charge facts or strategy earnings. Zero-fill cancelled orders are excluded; actual fills on partly cancelled orders still count. Brokerage is allocated across an order's split fills rather than all falling on the first fill. Exact actual paid charges still require broker execution reports/contract notes.

[Kotak's calculator](https://www.kotakneo.com/calculator/brokerage-calculator/) describes its charges as indicative. The active offer is a user-confirmed assumption, not a broker-verified date window; the standard plan is available for comparison and remains the conservative historical model default.

## One-year data boundary

The Kotak API returned 6,386 real NIFTY15m index candles for 14 October2025–13 October2026; the private CSV and coverage proof are preserved. This does not supply the missing expired option prices. [Kotak's historical-data documentation](https://github.com/Kotak-Neo/Kotak-Neo/blob/main/docs/market-data-apis/historical-data.md) excludes expired/delisted instruments. The native UI accepts a range up to one year, exposes month/year shortcuts, and explicitly marks dates outside the option archive as missing. The real 30-day archive replay completed from the browser, including an entry-minute observation and stop/target chart. A one-year requested range also completed as an incomplete replay with the extra missing-date gap. No complete one-month/year options return, 80% win rate or winning-strategy ranking is established.

## Reviewer limitations and final rulings

The reviewer declined to establish actual Live fills/latency/profitability, long-session resource stability, independent private migration/paid-charge reconciliation, and inherited per-device/Socket.IO revocation behavior. These stand as explicit limits. Their cost if wrong is, respectively, actual rejection/slippage; unseen longer-session resource growth; missing account facts altering totals; and retained upstream session defects. Native feature gates, authenticated commands, CSRF, exact ownership and mode controls remain verified within the documented scope.

## Exhaustive final ruling register

- Ruling: New managed checkout is outside this turn's sandbox writable roots; use scoped approved file/dependency commands in that checkout — preserves clean isolation — cost if wrong: deployment permission failure, with current terminal unaffected.
- Ruling: Preserve approved Live activation semantics using native trader wording “Start Live”; upstream forbids user-facing “arm” vocabulary — same explicit user-controlled action — cost if wrong: wording expectation only.
- Ruling: Pin the observed approved upstream SHA despite origin advancing during fetch — verified clean source remains reproducible — cost if wrong: later upstream fixes require a separate update.
- Ruling: Proceed with the requested migration while retaining the pre-existing baseline failure register; no blanket full-suite green claim — cost if wrong: unrelated upstream defects remain outside the Kotak feature evidence.
- Ruling: Reuse only a verified legacy signed owner browser cookie plus a bound unexpired broker cache and successful read-only broker validation; the cache alone cannot sign in a browser — satisfies the approved session-reuse requirement — cost if wrong: account binding/authentication failure; final independent review must examine this.
- Ruling: Native direct launcher refuses Werkzeug with debug off on macOS; add the upstream-required Gunicorn >=25,<26 runtime and explicitly select gthread with one worker/64 threads — preserves debug-off loopback operation and uses the supported runtime — cost if wrong: runtime regression; verify native gthread paths.
- Task 2: Ruling: Native batch runs are the provider lifecycle; add a server-side hook to signals.py and pass checked literal contracts/limit prices through the existing resolver and engine — preserves all native order ownership, partial-fill and mode invariants — cost if wrong: provider entry refused, with no alternate execution pipe.
- Task 3: Ruling: Extend the pure shared risk package with typed index/option protection rather than altering existing per-position vectors — the existing browser trail contract remains unchanged, and the new index/cash rules are server authoritative — cost if wrong: missing cross-language coverage, mitigated by separate typed golden fixtures and UI display-only stops.
- Task 3: Ruling: Reuse the native scheduler, recovery and stop_run machinery through one supplemental management job; no replacement tick feed or exit pipe — native exact fill/claim/mode semantics remain authoritative — cost if wrong: quote polling latency, surfaced in readiness and runtime checks.
- Task 4: Ruling: Broker REST depth snapshots may omit an exchange timestamp; preserve exchange_time=None and label server observation time, permitting only a directly verified depth response younger than five seconds — avoids fabricating exchange time while retaining executable depth evidence — cost if wrong: broker-side snapshot staleness cannot be measured, so strict spread/depth checks and refusal on delayed reads remain.
- Task 4: Ruling: Kotak Net is the entry trading limit and cash stays separate; absent Net refuses new entries rather than deriving spending from collateral/cash — preserves reported affordability — cost if wrong: a valid account can be blocked when broker omits Net.
- Task 4: Ruling: combine the full simulated browser trade journey with Part 2 final verification — its running P&L/manual controls/replay surfaces are produced there; foundation now proves real native Sandbox dispatch, fills, trail-triggered exit and flat persistence with a synthetic quote boundary — cost if wrong: browser integration regression delayed until final gate.
- Task 4: Ruling: optional Neo controls require a public build flag and server feature gate; marked native provider legs reject ordinary batch Start — keeps upstream deployments quiet and prevents entries without a confirmed setup — cost if wrong: misconfigured flag hides provider controls.
- Task 1: Ruling: adapt the preserved conservative FIFO mathematics to native owner-partitioned SQLAlchemy facts — avoids a second SQLite broker pipe while preserving previous accounting semantics — cost if wrong: historical matching mismatch; reconciliation is required.
- Task 1: Ruling: estimate ₹10 executed-order brokerage unless a dated promotion is verified — the user reports an active free period but its expiry is unknown; paid charges remain separate — cost if wrong: conservative estimates overstate costs during the free period.
- Task 2: Ruling: the Neo instance uses the native openalgo-charts engine in Scalping, preserving the upstream lightweight chart for normal installations — this enables the approved runtime indicator loader and instrument-bound overlays consistently — cost if wrong: chart interaction differences in the optional instance.
- Task 3: Ruling: a missing option minute makes protection/execution order unprovable, leaves the trade unresolved and stops reinvesting unknown proceeds — historical OHLC cannot supply missing executable bid/ask; no invented cash returned — cost if wrong: replay is more conservative and shorter than actual trading would have been.
- Task 4: Ruling: NSE MCP is informational context with documented 1–3 minute delay; use Kotak streaming for execution-price charts rather than that delayed source — preserves low-delay trade prices — cost if wrong: some public context fields may remain unavailable during provider outages.
- Final: Ruling: actual Live fill quality, broker latency and profitability were declined by the reviewer — verify read-only account/session, Sandbox plumbing and mocked Live routing, leave the final real-order activation with the user — cost if wrong: actual broker execution can still reject or slip.
- Final: Ruling: long-session FD/RSS stability was declined by the reviewer — bounded static lifecycle audit and 30-second measurement only; no all-day leak guarantee — cost if wrong: a longer session could reveal growth not observed here.
- Final: Ruling: private migration completeness and paid-fee reconciliation were declined by the reviewer — retain imported fill coverage and actual-fee unknowns; no complete lifetime-history claim — cost if wrong: unrecorded executions or charges can change totals.
- Final: Ruling: upstream per-device revocation/broad Socket.IO session behavior was declined by the reviewer — no branch-specific financial-action bypass established; existing platform session behavior retained — cost if wrong: upstream session revocation defects remain.
- Final: Ruling: apply the user's active free-brokerage offer to the report as an explicit assumption, without inventing promotion dates or paid charges — standard ₹10 plan remains selectable; historical risk/replay defaults remain conservative — cost if wrong: report estimates differ when selected dates fall outside the offer.
- Final: Ruling: final broad backend run retains upstream failures, with two additional timing-dependent failures in byte-identical Flow/Upstox files — isolate and report them rather than modifying unrelated brokers or claiming global green — cost if wrong: unrelated platform behavior remains outside native Kotak evidence.


## Date rollover and handoff

At the 14-October rollover, the saved 13-October broker API session expired. The real account check therefore became unavailable; no current zero-position/pending-order assertion is made from that expired response. Native owned runs/pending entries remain zero and entries remain Stopped. The actual login UI asks only for Authenticator TOTP; saved mobile/MPIN remain private. The user was asked to reconnect locally for a final live-session check. Do not infer API authentication from the separate logged-in Neo website or claim Live activation while this login is pending.

Kotak's Options calculator tab was exercised directly. Its displayed rates match the estimate model: sell-side STT0.15%, transaction charges0.0355299%, SEBI0.0001%, GST18% and buy-side stamp0.003%; the 30-day promotion removes brokerage, not those statutory charges. Calculator estimates remain distinct from actual contract-note charges.

Direct Start Live UI regression first failed on the previously disabled button, then passed after removing the separate checkbox. The explicit Live click sends confirmation; Sandbox starts and Stop do not. No real Live click was performed by the agent.
