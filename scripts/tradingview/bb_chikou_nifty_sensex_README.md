# Bollinger Bands + Chikou signals for Nifty and Sensex

Source: `bb_chikou_nifty_sensex.pine` (Pine Script v6).

## Install in TradingView

1. Open a regular candlestick chart for the Nifty 50 index or Sensex index. The indicator uses the chart's own OHLC; apply it separately to each chart.
2. Open Pine Editor, create a new indicator, and replace its contents with the complete `.pine` file, including `//@version=6`.
3. Save, then choose **Add to chart**.
4. The supplied strategy summary used 15-minute candles. Begin reviewing on that timeframe to reproduce its context. Other intraday timeframes calculate their own independent signals; they have not been optimized or validated for profitability.
5. Keep **Indian cash session only** enabled for the default 09:15–15:30 IST weekday filter. Use regular time-based candles. Daily charts do not produce signals with this filter enabled.

## Exact signal rules

Default bands are SMA(20) ± 2 population standard deviations of close.

For a **BULL**:

1. A completed setup candle's high touches or exceeds its upper Bollinger Band, without also touching the lower band.
2. With **Require first touch** enabled, the candle before the setup must not have touched its own upper band. After a failed setup, a fresh first touch requires an intervening candle without that band touch.
3. The immediately following candle must **close strictly above the setup candle's high**. A wick-only break does not qualify, and the setup expires after that next candle.
4. Its close must also be strictly above the high of the candle 26 bars earlier, and above the current SMA, so the initial risk is positive.
5. Both candles must satisfy the session filter, share an IST calendar day, and be adjacent in time. No overnight or missing-bar setup carryover.

For a **BEAR**, reverse the conditions: first lower-band touch, next close below the setup low, current close below the low 26 bars earlier, and below the current SMA.

Chikou clearance is evaluated on the confirmation candle. **Full candle** is the default and compares against the historical high/low. **Close only** compares against the historical close instead. The displacement is a literal **26 bars**, not 26 calendar days. If comparing with another Ichimoku implementation, align its actual plotted displacement before comparing signals.

The purple Chikou line displays each confirmed close 26 bars back. That shifted visualization gains a new point in the past when each current candle closes; BULL/BEAR markers and alerts always belong to the current confirmation candle. No future-data requests are used. Bands can move while the live candle forms; signals wait for confirmation.

## Entry, stop and target

| Reference | Calculation |
| --- | --- |
| Entry, blue | Confirmation candle close |
| Initial stop, red | SMA(20) on the confirmation candle |
| Bull target, green | Entry + (entry − stop) × reward/risk |
| Bear target, green | Entry − (stop − entry) × reward/risk |

Reward/risk defaults to **1.0**. The stop is frozen when the signal appears; it does not trail the moving SMA. The source summary inconsistently mentions SMA(20), SMA(30), and an outer band; this implementation consistently uses the middle SMA(20).

Levels show the latest signal and are replaced by the next signal or cleared at the first confirmed candle of the next IST day. They do not track open positions, detect stop/target hits, or report trade outcomes. Further qualifying setups can signal while earlier reference levels remain on the chart. Entry is an indicative close, not an assured executable fill; fees and slippage are not modeled. Displayed SMA/target values are mathematical values rather than tick-rounded orders.

Apply the indicator to the underlying index if you want index signals. Applying it to an option chart calculates option-premium signals instead. Index-point stop/target distances do not translate directly to option-premium distances.

## Optional squeeze filter

The summary provides no quantitative squeeze threshold. This implementation offers one explicitly configurable definition, **off by default**:

- Band width = (upper − lower) / abs(middle).
- A squeeze occurs when width is at most 0.8 × its 50-bar average, with a positive average width.
- An enabled squeeze filter requires a squeeze within 10 bars of or on the setup candle, and wider bands on confirmation than on the setup candle.
- Short loaded histories can lack the roughly 69 bars needed to initialize the squeeze average with default settings. Load additional history before expecting filtered signals.

These settings are not Nifty/Sensex-optimized. The default indicator needs at least the SMA and Chikou lookback history before setups can form.

## Alerts

Create an alert with this indicator as its condition, then select **BB Chikou BULL** or **BB Chikou BEAR** and choose **Once Per Bar Close**. Create one alert per direction, per chart. Messages contain ticker, interval, indicative entry, initial stop, and target. Hidden signal plots supply these values even when visible levels are disabled.

Recreate alerts after changing the indicator settings, chart symbol, timeframe, or source, so the server-side alert uses the intended configuration. See [TradingView's alert documentation](https://www.tradingview.com/pine-script-docs/concepts/alerts/) and [repainting documentation](https://www.tradingview.com/pine-script-docs/concepts/repainting/).

## Validation and limits

Local behavioral checks run the actual Pine source with independent **PineTS 0.13.0**, using synthetic OHLC bars. This is not TradingView's compiler or historical market backtesting. Unconfirmed-state gating is checked by substituting an unconfirmed state in the test harness; it is not a live-tick integration test.

For a reproducible isolated check without changing application dependencies:

```sh
npm install --prefix /private/tmp/bb-chikou-validation --cache /private/tmp/bb-chikou-npm-cache pinets@0.13.0
PINETS_MODULE=/private/tmp/bb-chikou-validation/node_modules/pinets node --test scripts/tradingview/tests/bb_chikou.test.cjs
```

Before relying on alerts, compile the source in Pine Editor and use Bar Replay on each index. Check a qualifying upper/lower touch followed by confirmation, a wick-only rejection, Chikou clearance, and the fixed stop/target values in the Data Window. Check that open candles do not produce signals and that the Chikou line is the only plot shifted backward. Historical revisions from a data provider can change calculations on reload. This indicator has no demonstrated win rate or profitability claim.
