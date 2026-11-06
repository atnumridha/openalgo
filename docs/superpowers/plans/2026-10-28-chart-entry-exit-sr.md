# Chart entry, exit, stop and support/resistance

User-authorized scope: implement a separate, chart-native, long-only indicator and install it in TradingView. Keep combination scripts independent and hidden. No broker orders or position synchronization. Continue inline without another planning question.

## Rules and presentation

- Use the active chart's ordinary OHLC, with confirmed candles only. CE and PE premium charts both use long entries. No external underlying or pinned expiry.
- Confirm swings with 3 left / 3 right bars, reveal levels only on confirmation. Keep 40 recent swing levels for nearest support/resistance.
- Arm a confirmed resistance breakout above a rising EMA21. Buy only on a later bullish retest within 8 candles, closing back above the broken level (0.15 ATR touch tolerance).
- Suggested SL is below the lower of the retest low and broken resistance by max(2 ticks, 0.1 ATR). Target is 2R, capped below an already confirmed overhead resistance. Reject less than 1.5R of room. Freeze the bracket at entry.
- Check protective touches starting with the following bar. A bar touching both levels is ambiguous, never an assumed winner. Gaps below SL use opening price as a reference. Missing bars during a signal trade require review and end tracking with unknown outcome.
- NSE/BSE intraday entries use 09:20–15:00 IST; a signal trade exits at/after 15:15 candle close. Other markets use continuous intraday sessions. Show closed-market / no-data states separately from historical labels.
- Chart labels: ENTRY, EXIT reason, fixed entry / SL / target lines; current S/R lines with price labels. Small readable decision table shows exact symbol and explicitly says signal tracking, not broker position.
- Existing strategy win rates do not apply. This is a new unvalidated breakout/retest rule set. Indicator levels are suggestions and alerts do not place broker stops.

## Execution

1. Write failing behavioral tests against extracted production Pine core. Implement state machine, levels, sessions and overlay.
2. Verify synthetic edge cases, complete existing Pine suite, and replay cached market bars with reported coverage/limitations (no win-rate claims from synthetic tests).
3. Fresh independent read-only review. Fix important findings with regressions.
4. Compile/install new draft in TradingView, hide combination indicators, inspect exact option chart, save layout and verify.

## Review focus

No future pivot information; no entry-bar stop; fixed SL/target; same-bar collision; session rollover and missing bars; long put semantics; chart indicator must not imply synchronization with an existing broker position. Installation and displayed prices must match the source.

## Progress

- Initial inspection complete. Existing ORB research does not establish this new rule set's performance. Preserve all unrelated work.
- Implementation and tests complete: 18 focused / 183 full suite passed. Replay final defaults: 26 entries, 9 positive, 16 negative, 1 unknown, before costs, on 7,696 cached bars across ten NIFTY options (27–28 Oct). This fails the requested 80% threshold; display is marked Research.
- Independent review found an overnight warmup defect blocking 30m/60m charts. Reproduced with timestamped wrapper tests (0 !== 1), then corrected to use total indicator history and a three-bar recovery after unexpected gaps. Scheduled NSE/BSE breaks still cancel setups/tracking through the gap branch, but do not require 21 new same-day candles. Both regressions and full suite pass.
- Installation completed: docking the stalled overlay editor into split-view restored input. New source compiled and was added as ENTRY EXIT S/R on NSE:NIFTY261103C23050 1-minute. Old SD CONDOR CHART and ATR STRANGLE CHART verified hidden; layout reports All changes saved. Screenshot workspace/chart-entry-exit-sr/installed.png confirms research panel, S/R 49.70 / 50.55, no active signal trade, last SL touched 28 Oct 13:10 IST. No broker actions. The current chart was not included in the ten-contract replay.
- User challenged how this meets 80%. Explicitly acknowledged that it does not: 9/25 determinate outcomes = 36% before costs, plus one unknown. This fulfills only chart-display functionality; strategy qualification remains unmet. Previous multi-leg results cannot be transferred to this new single-contract rule set.
