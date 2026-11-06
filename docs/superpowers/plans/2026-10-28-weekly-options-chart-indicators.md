# Weekly options indicators implementation plan

Goal: install two independently selectable Pine v6 indicators on the user's NIFTY TradingView chart, with clear entry, hold, stop, expiry and missing-data states.

Scope is the two leading researched cash-settlement variants. The user requested implementation and individual indicators; prior conversation opted out of further planning questions. No strategy parameter optimisation, broker order placement or historical win-rate claims inside the indicators.

Implementation choices: one explicitly selected expiry cycle and entry timestamp per script; exact configured contract code; standard NIFTY 1-minute chart; confirmed candles. Fixed requested strike banks avoid Pine's prohibition on new realtime request contexts. Out-of-bank, stale or absent data blocks signals. ATM parity/IV and delta selection use actual requested premiums. ATR can use the independently computed NSE weekly value for this cycle; optional continuous-futures mode is labelled as a different source.

- [x] Specify executable acceptance cases for absent quote, required stop observation, entry time, stop gating, expiry priority and single-cycle lifecycle.
- [x] Implement separate SD condor and ATR strangle scripts, bounded option requests, exact timestamp matching, one cycle, no late entry, no automatic rollover, and green/red/yellow status tables.
- [x] Compile in TradingView; correct errors and verify both independent indicators and their chart states. Compare selected strikes with the frozen research where available.
- [x] Save source files and brief operating notes; report current status and any unresolved data limitations.

Verification: 20 focused PineTS cases passed; full local suite 139/139 passed on 28 October 2026. Tests include the production lifecycle, full indicator assembly with absent external quotes, and an independent Black-76 price/IV benchmark. This is not TradingView compiler verification.

Installation: user authorized testing one indicator at a time after TradingView reported a one-saved-script Basic-plan limit. Chrome full-screen mode caused stale accessibility controls; exiting full screen restored reliable input. Both clean sources compiled and ran in TradingView on NSE:NIFTY, 1 minute, on 28 October 2026. Both chart instances are present independently; SD CONDOR is hidden and ATR STRANGLE is visible. Old studies are hidden. The chart is scaled to price only so distant option strikes do not flatten candles.

Observed SD result: WAIT for 29 October 15:25 IST; expiry 3 November; 38/38 fresh exact-bar quotes; preview short PE/CE 22100/23300, agreeing with the recent research preview. No entry expected yet.

Observed ATR result: green entry on the bar closing 28 October 11:15 IST; short PE/CE 21650/23400, credit reference 21.25, stop threshold 53.13, entry VIX 16.40 and pinned weekly ATR 632.79. Latest state HOLD, debit 16.60, 38/38 fresh quotes. The prior Kotak research snapshot selected PE 21700 with incomplete entry data; TradingView selected 21650. This platform case is not identical execution/data to the external backtest and is not a closed winning trade. Verified the readable green label in the 10:45–11:45 chart range. Screenshots saved in workspace/weekly-options-indicators/.

Persistence verified: TradingView reported All changes saved. Reloaded the layout at https://in.tradingview.com/chart/lyqjV7r1/?symbol=NSE%3ANIFTY. Both independent instances remained present; ATR remained enabled, SD remained hidden, and no compilation/runtime error was present for either new indicator. No private script was overwritten and no broker order was submitted.

Acceptance: invalid symbols are handled with ignore_invalid_symbol and WAIT, no failed requests collapse the entire indicator. Entry is a signal with a quoted premium reference, not a broker fill. Stop levels use an optional actual filled credit override or the signal reference, labelled. The script does not claim exact next-open backtest execution. Expiry emits an expiry/cash-settlement event without pretending last-traded option prices are official settlement. Refresh expiry dates and strike-bank anchors for each new cycle.
