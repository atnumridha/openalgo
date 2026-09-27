# Kotak setup and trading UI validation — 2026-09-26

## Applied configuration

Saved through the authenticated Research UI and verified after browser reload and by a read-only database check:

- Kotak Neo Trade API / NSE options (NFO), September 26 through October 10, 2026.
- ₹0 API brokerage under the published Trade Free API pricing; statutory and exchange assumptions are documented in [Trading research](trading-research.md#costs).
- 10 basis points adverse slippage per side is an estimate, not a broker charge.
- Managed shared capital profile enabled: ₹10,000 capital; ₹1,000 first-trade allowance; ₹1,000 shared by all later trades; ₹2,000 daily loss allowance; 20% drawdown pause and 20% cash buffer.
- This is one exchange-scoped schedule. Managed BSE/MCX entries are refused rather than priced with NSE charges.

## Browser checks

Used the actual signed-in Chrome application at `127.0.0.1:5001`:

- Four separate steps replace the single long Research form.
- Kotak preset loads a draft with readable percentage units and explicit exchange/broker scope.
- Missing end date refuses saving; draft values survive changing steps.
- Cost save reports success, enables the shared limits, and survives a reload.
- Historical execution and campaign enrollment remain disabled with no eligible data/results.
- Results explains that no experiment exists. Sandbox/live guidance links to the actual strategy controls.
- Strategies shows nine armed Sandbox-only automations, no active managed run, and inactive live authorization.
- A confirmed **Start sandbox** attempt for NIFTY 5/15-Minute Trend Signal Receiver was refused: **“The entry exchange is unavailable.”** The audit event records `portfolio_governor_rejected`; no managed run opened. No live order was submitted.

That refusal was initially shown only in a transient toast. The start dialog now retains the error and clears it when a new dialog is opened. A regression test covers this behavior; the final production build includes it. A second manual browser verification of this last error-display fix did not complete because the computer-use service reported no available window.

The user's original unsaved Research tab was preserved. Verification used a separate tab. The managed app and worker were restarted after checking there were no active managed runs, no live-enabled strategies, and zero positions displayed by the broker Positions page. Both services reported ready afterward.

## Automated validation

- Backend strategy, qualification, research, risk and startup suites: **1,981 passed, 1 expected failure**. One SQLAlchemy identity-map warning remains in the test run.
- Research, qualification and strategy-list UI suites: **60 passed**.
- TypeScript/production build, scoped Biome and Ruff checks, and `git diff --check`: passed. The build retains the existing large-chunk advisory.
- Automation-control fixture failures were corrected by adding explicit matching test broker bindings and matching batch/signal kinds; production validation was not relaxed.
- Changes add bounded UI state and pure fee validation; they add no background process, socket, database connection, subscription or unbounded cache.

## Qualification still outstanding

This is not evidence of profitable trading or successful live execution. At verification there were no imported historical datasets, research runs or prospective qualification campaigns. Historical data, successful execution under available market conditions, and actual forward evidence are still required. Current release policy requires a qualifying sealed historical screen followed by 30 forward sessions and 100 closed trades, with the documented performance and execution checks. Live release, per-strategy enablement and daily authorization remain separate gates.

The NSE preset is current-date evidence, not a historical tax table. A compatible verified historical fee schedule is required for older imported sessions. Live enablement and real financial transactions were not performed during this UI test.

## Official NSE daily history addition

The later data-source work adds a separate daily archive and one-click controls under **Research → Historical test**. It does not change trading rules, risk limits, broker settings, qualification thresholds or live authorization. The original five-minute NIFTY dataset remains the only intraday dataset listed during this validation.

### Source checks

- Downloads use the official NSE derivatives archives, including the UDiFF transition on 8 July 2024. Both source formats were checked against real exchange files.
- Compared all 31,143 option records for 30 April 2025 in the `sajal101agrawal/nse-options-last-5-years` repository, commit `3b50394cffb9c63fa3630d566b4e19098298ac9b`, with the official exchange ZIP. Contract identities and eight fields (OHLC, settlement, volume, open interest and open-interest change) matched with zero differences. This checks one session, not the whole repository.
- The local evidence receipt is `data/research/nse-daily/cross-check-2025-04-30.json`. The third-party pipeline was not installed, and its CSVs are not the automatic download source.
- Untraded records and settlement prices remain distinguishable from traded OHLC. Legacy lot sizes are left unknown when absent. Modern instrument IDs preserve separate contracts whose accelerated actual expiries coincide.

### Browser and lifecycle checks

- Used a separate signed-in Chrome tab and visually inspected the production build. The daily card displays saved sessions, coverage, progress, pause/resume controls and NIFTY CSV export.
- Paused the actual backfill, verified the paused state, resumed it from the UI, and confirmed that the saved session count increased. A CSV download event was received from the export link. The expanded activity table displayed real NIFTY observations.
- Ran the macOS one-click launcher with a separate temporary output directory for 25 September 2026: it downloaded and validated one official session, returned exit code zero and reported no errors. The main backfill was unaffected.
- Reloaded the final build and verified that the upload section says **Add intraday market history** and explains the distinction from daily history. Daily data does not appear in the intraday dataset selector.
- Positions and order totals were zero before the managed app/worker restart. Both services reported ready after restart. No order, live authorization, strategy or fee configuration was changed by these data checks.
- A transient network `ReadError` during the real backfill exposed a resilience gap. The downloader now retries transport/server failures up to three times against the same official URL, then stops visibly for later resume. Access-denial and rate-limit responses stop without retrying or changing host.
- Code review also prompted regression coverage for a pause requested before the child starts and a child process exiting unsuccessfully before writing its manifest.
- A previous UI worker failure cannot mask the running/completed state of a newer CLI download. Regression tests reproduce both a nonzero exit and a startup exception; a fresh startup failure still surfaces even when an older successful archive exists.

### Automated checks and resource audit

- Focused archive, endpoint and existing research suites: **82 passed**. New coverage includes source validation, duplicate identity, absent sessions, bounded retries, denied access, resume/integrity repair, cancellation, authentication, export and strict prior-session snapshots.
- Full frontend suite: **175 test files, 2,777 tests passed** with `NODE_OPTIONS=--no-experimental-webstorage npm run test:run`. Node 26's experimental global Web Storage caused the first run to fail; disabling that runtime feature restored the project's test environment. After the final wording edits, the focused Research/daily-card suites passed **24 tests**.
- Production TypeScript/Vite build passed, retaining the existing large-chunk advisory. Scoped Ruff and Biome checks passed.
- The full Python suite reported **6,088 passed, 29 skipped, one expected failure, 10 failures and 11 teardown errors**. The failures are outside this addition: two Telegram async tests lack their async runner; the Telegram eventlet startup test lacks eventlet; seven unchanged TradeSmart limiter tests fail their existing API/timing expectations (also reproduced in isolation). Eleven OpenScript teardown errors hit macOS sandbox restrictions on `psutil` process enumeration. The focused feature suites pass; the full Python suite is not green.
- Resource audit: streamed responses, archive handles, output files and the child HTTP client close through context/finally handling. Prefetch is bounded to three requests; its executor joins on exit. The web service permits one job, reaps its child and closes the log. Repeated local snapshots (100 reads) left file descriptors unchanged: **4 before, 4 after**. Production eventlet was not exercised because it is absent from this local environment.

### Completed archive and integrity audit

The backfill completed on 26 September 2026 at 16:20 IST. It checked all **2,357 calendar dates** from **13 April 2020 through 25 September 2026**, downloading **1,604 sessions** (1,052 legacy and 552 UDiFF files). NSE returned no archive for 753 dates, including 88 weekdays; these remain explicitly unavailable rather than being labelled confirmed holidays. There were **zero validation errors** and no unchecked dates.

The archive contains **74,414,786 option records**, of which 55,876,775 are explicitly marked untraded. These counts describe daily contract records, not executed trades. Original and normalized files total 3,422,621,013 bytes. The final audit checked SHA-256 hashes for **all 3,208 stored files**, with **zero integrity failures**.

Every one of the comparison repository's 1,246 published sessions is present in the official download. For 1,046 overlapping legacy sessions, the complete original CSV bytes matched the pinned repository's Git blob hashes, with zero mismatches. The separate 30 April 2025 modern-format field comparison is described above. This verifies much broader legacy coverage without importing or executing the third-party processing code.

The detailed receipt is `data/research/nse-daily/integrity-audit-2026-09-26.json`. Daily history supports market context only; this verification is not evidence of profitable intraday execution or live qualification.

After the final status fix, the local services were restarted and reported ready. A fresh browser reload showed **1,604 sessions saved**, **2020-04-13 to 2026-09-25**, the enabled **Update NSE history** button and the CSV export link. The paused/downloading indicators were gone. The original intraday dataset and strategy-test controls remained separate.
