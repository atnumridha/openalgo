# Reviewed-only BTC paper/live and month test

Active user objective: run on TradingView Paper Trading live BTCUSD.P and backtest last1month. User explicitly chose reviewed setups only (no automatic candidate-performance benchmark). User clarified **1 TradingView unit =1BTC**, not1Delta lot. Paper simulator connected; no open position/order submitted at start. Existing account realized+211.72/equity100211.72 is PRIOR account state, not this test's P&L. No real broker/API order calls permitted.

## Source and fixed policy
### Source-only correction after expanded live-demo request
The user reiterated “use his approaches only” and requested every completed live replay/demo. The earlier next-candle **close beyond the response extreme** is a user-modified hybrid, not the demonstrated next-candle **high/low break**. Preserve its 94-candidate review as an earlier, unscored variant; do not report it as a source-method backtest. No outcomes have been inspected. The source-only test must select body/context/T1/T2 using data ending at the **response close**, before the entry candle, and include entry/SL-order ambiguity rather than excluding possible losses.

Discovery from successful entries alone is insufficient. Enumerate prospective response plans before their next bar, including failed/nontriggered/ambiguous plans. A rejected weak body must not silently consume an actual attempt. Freshness after an actual accepted response/attempt requires explicit source evidence; raw colour-only candidates are not actual attempts. Completed official Live inventory currently contains 23 replays, reviewed in three full-caption batches; visual coverage must remain separately stated.

Use exact tested indicator core, source hash8479c672d0cbba4e2d31be435fef1f14f963438258a92108c56fcfa1f788e67b. DailyDQRS1m source-only body/context/target review. Default user next-candle-close confirmation. No automatic proxies or candidate benchmark. Candidate extraction is discovery for manual review only.

User delegated runner choice ('use best as per Gautam'). Declared BEFORE outcomes: selected source-mentioned next-swing variant, **0.8BTC T1 nearest reviewed unspent swing,0.2BTC T2 next reviewed unspent swing; originalSL, no autotrail**. This is a reproducible chosen variant, not a universal finalrunner rule supplied by all lessons. Maxactiveposition1BTC (no stacking/netting reversals); skip overlapping plans. DQRS3actualattempts /2fullSL perUTCexchange day; partialprofitthenSL is not a fullSL. Costs/slippage/funding assumptions must be explicit. Do not optimize policy against outcomes. Flag OHLC stop/targets samebar ambiguity, no fictional tick order; report range/conservative case if needed. Unclosed positions at end separately marked, no invented terminal close.

## Data and review
Window fixed2026-09-28T02:40:00Z to2026-10-28T02:40:00Z exclusive. Workspace `workspace/gautam-btc-month/`. Verified1m_backtest.csv43200rows,1m_with_warmup46240fromSep26, dailyUTC32completeexactOHLCVmatch. Zero gaps/duplicates. Audit docs/validation/gautam-btc-month-data-2026-10-28.md. APIactualminuteepochs fresh; don'ttruststale ticker.time string. Delta contract0.001BTC, tick0.5, taker0.0005; TVunit1BTC confirmed bypaper ticket~80902USDnotional, defaultpaper10xmargin. No global paperaccountfees reset/change yet.

Exact source engine execution with completed daily array fixtures produced94 discoverycandidates across21days, NO performance. `extract-review-queue.cjs`, `review-queue.json`.94maskedfuture PNGs rendered viaSVG/Sharp in `review-charts/`; each240pastbars plus14barbodyzoom, dataendsentryconfirmation, no outcomes. Review Type is Codex retrospective application with future hidden, not author's own signals/live approval.

Manual visual reviewers (userexplicitlyauthorizedmultiplethreads):
- gautam_popular_lessons IDs1–32 → reviews/part1.json.
- gautam_live_trades IDs33–64 → reviews/part2.json.
- gautam_coverage IDs65–94 → reviews/part3.json.
Everyimagevisuallyinspected, qualitativebodyjudgment, T1selectedmanuallywithbarindex then checkedusingONLYCSVprefixendingentry. No numericalpivot/bodyfilter. T2secondpass required afteruserdelegatedpolicy; preserve sealedbody/T1, addmanualnextturnorNEED_MORE_HISTORY. No outcomes read/run so far. NeedsT2expansion handled byroot ifrequested.

## Platform constraints and outstanding work
Official TradingView docs: Pine cannot place orders in PaperTrading account. Paper fills require manualticket afterreview, sourcevalidnextbar only; noentryonunreviewedcandidate. Live daily setup currentlyWAITinsidePDH81271/PDL79468. Order preview opened only toverifyUnits1=1BTC; notsubmitted. Ensurepreviewclosed. Sourceindicatormainchart remains compiled1m,layoutsaved.

Standardintraday chart barlimits maypreventnative1month1m (~43200bars); needverifyactualloadedhistory/DeepBacktestingeligibility, neverpassshortchartcoverageasfullmonth. Fullmonthlydataset availableforseparatereviewedtest ifnativeblocked. Native separate reviewedledgerstrategy companion not yetcreated. NeedtestsRED→GREENbeforeproductionstrategy, nativecompile/application, fullmonthreviewledger validation/evaluation, livepaperobservations and finalproof/report. No automatedPaperconnectionexists; don'tclaimrunningautomaticpaperorders.

## Implementation tasks for the original-break reviewed test

- [x] Extract all 23 currently listed completed Live captions; assign full sequential example/mistake coverage in three independent batches. Selected visuals remain separately attributed.
- [x] Default indicator to source-original next-bar break; retain earlier close mode explicitly labelled user variant. Tests failed before change, then passed.
- [x] Require reviewed T1 as well as body timestamp for reviewed indicator output; add response-close candidate notices before the entry window. Two regressions failed, then all 39 indicator tests passed.
- [x] Generate 216 prospective raw response plans without inspecting their next candles. Render response-close-only review charts. This is a conservative discovery subset; no completeness claim for author discretion.
- [x] Seal every manual decision/T1/T2 using only data through each response; validate timestamp, exact price, past origin, and untouched chronology. Save hashes before outcomes. Preserve unapproved/rejected decisions as well.
- [x] Add `scripts/tradingview/validation/gautam_reviewed_backtest.cjs`, tested by `tests/gautam_reviewed_backtest.test.cjs`. Interface `simulate(bars, plans, options)` consumes closed 1m OHLC and preapproved plans and returns fills/trades/skips, gross/fees/net, daily risk counters and open mark. No future data for plan selection; no ordinary loser removed as a mistake.
- [x] Test exact next-bar-only entry, strict break at next tradable tick, no trade/no loss if untriggered, stop gap price, 80/20 limits, original stop retained, one active BTC, actual three-attempt/two-full-SL day limit, target-only approval, unknown OHLC ordering and unclosed positions. Fail these tests before implementing.
- [x] Use a declared local fill model for the full month: TV default heuristic plus two explicit OHLC-path sensitivity scenarios. These are model scenarios, not proved best/worst bounds. All fills include 0.059% assumed taker+GST, one-tick slippage on stop/market fills only, no funding adjustment. State exclusions; never claim this is the native TradingView report.
- [x] Create reviewed-ledger Pine strategy companion for native compilation/display. Default BTCUSD.P 1m only, qty1 BTC, no stacking, 0.8/0.2 exits, no arbitrary R/pivot/body/ATR filters. Cancel unfilled entry after immediate next candle. Show loaded coverage and limited-history warning; no auto Paper connection.
- [x] Native compile both files, compare available-chart behavior, save chart/report proof. Observe live current state without forced late entry. Report actual full-month local results separately from native limited history and paper fills.

## Final evidence

Current indicator SHA256 ed7d6878ee105819e9d27b953accc8787e46de6cbc0d18d1075c5fa4a17ea50b; strategy d8d67ed73877966c3f6f9c3c205f716147c9ac1241ea1e3a3589f285ffbd5d62. All216 prospectively reviewed:126approved/90rejected; seal3ba129772cf98b70c626d314c239e0d534c0ba8bc9990ba6bee9296f18930761 preceded outcomes. Local full-month47settledentries net−$5,357.526565 before funding, gross−$772.90, fees$4,584.626565. Independent Python audit reconciled all fills and close-equity rows; minimum modeled equity buffer>$12k. All119tests passed.

Native TradingView compiled both actual files,126ledger rows/0errors. Loaded19Oct00UTC onward:14entries/28partial-exit legs, net−$2,290.92 matches same14 local positions−$2,290.916515. Basic-plan Deep Backtesting blocks native last30days; screenshot saved, no upgrade. Final live main indicator restored, chart saved, WAIT; Paper Positions and Orders both empty at09:48IST, no submitted orders. Native strategy cannot connect directly to Paper account; no completed live trade claimed. Full source/coverage/model boundaries, proofs and results: docs/validation/gautam-reviewed-month-2026-10-28.md.
