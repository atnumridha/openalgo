# OpenAlgoAll sweep setups

## Requested result

Extend the existing TradingView `OAlgo All` indicator with Gautam Jha Sweep Reversal only, as selected by the user. Keep the existing EMA, candle, Fibonacci, RSI and volume studies. Mark the reference levels, sweep, confirmation, entry reference, SL and target in readable English. The 4H PO3 + FVG module is excluded.

## Approach

Add independent setup engines and chart drawings to `scripts/tradingview/openalgo_combined_indicator.pine`. This directly extends the requested indicator and shares its existing label controls. Separate new scripts would use more indicator slots. Connecting these observations to broker execution would change the task from chart marking to trading and is outside this change.

## Preferred setup: 1H sweep reversal

- Default on. Use the chart symbol's 1H candles and the preceding completed UTC day's high and low. Identify incomplete history instead of substituting the current day's extremes.
- Use the supplied 12:30–21:30 IST window as a fixed rule, not a claim that it always equals the London/New York overlap. Both sweep and confirmation candles must fit inside the window.
- Long: a completed green 1H candle sweeps below the previous-day low. Its immediate next 1H candle must be green and break the sweep high. Short is the mirror at the previous-day high.
- Confirm after the next candle closes. The screenshots' simultaneous requirement for candle colour and an intrabar entry cannot guarantee both in advance. The plotted actionable reference is the confirmation close; retain the sweep high/low as the trigger boundary. Do not backdate a confirmed entry to an earlier intrabar touch.
- Offer a distinct pending sweep label (off by default), then one confirmed Long/Short label with a dotted leader. Put SL one minimum tick beyond the sweep extreme and target at the opposite previous-day level. Reject invalid or already-passed targets and confirmations that also cross the stop. State this conservative correction in the tooltip.
- One confirmed setup per direction per UTC day. These are signal counts, not a record of actual trades.
- No EMA, RSI, MACD, daily-trend or dollar-index gate on this module.

## Display and timing

- Reuse the current readable font size and bullish green/bearish red colours. Distinguish setup names in labels and tooltips.
- Retain bounded drawing history. Show the latest setup's reference/SL/target lines with prices. Keep forming observations separate from completed confirmations.
- Compute on the specified source timeframes. On a chart above the source timeframe, process all available source intrabars; if the account's intrabar history is unavailable, state the limitation instead of silently using one arbitrary candle.
- Keep UTC level boundaries separate from the user's IST display time. Suppress these new engines on nonstandard candle charts or clearly report unsupported chart types.
- No orders, changes to broker automation, risk sizing or purported win probabilities. Supplied backtest claims are unverified and are not copied as BTC performance statistics.

## Validation

Test actual Pine engine code on synthetic Long and Short sequences, immediate-next-bar expiry, session boundaries, missing intervals, UTC rollover, one-per-direction limits and stop/target conflicts. Verify no duplicate source events on lower chart timeframes. Compile and inspect the updated indicator on the user's BTC chart in TradingView if accessible. Report synthetic rule checks separately from live-market or performance evidence.

Status: approved with the user's selection, "Gautam Jha only", on 04-Nov-2026.

## User refinement: pattern visibility in both charts

The user requested the same behavior for TradingView OpenAlgoAll and OpenAlgo: show pattern labels for only the last ten actual chart candles by default, with an explicit option for all available historical labels. Unconfirmed/pending observations default off and have a separate opt-in. Keep latest confirmed Entry/SL/Target reference guides, EMA lines and pivots. Apply the window to rendering only; retain full verified history for pattern recognition, trend analysis and trading eligibility. A new forming candle counts toward the ten chart candles, and expired labels disappear even without a new signal. Existing closed-candle confirmation rules remain unchanged.
