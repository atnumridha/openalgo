# Source-backed crypto strategies

Researched 17 October 2026 for the Delta chart at `/trading`.
The Tradetron article describes families, not fully specified algorithms:
https://tradetron.tech/blog/what-is-the-best-algorithm-for-crypto-trading

## Pinned sources

Hummingbot revision: `9af100d6822da7d2d0291a906c730ef172284ee2`.
Base: https://github.com/hummingbot/hummingbot/tree/9af100d6822da7d2d0291a906c730ef172284ee2

| Family | Exact implementation | Source defaults | Current app support |
|---|---|---|---|
| Mean reversion | `controllers/directional_trading/bollinger_v1.py` | 3m, BB100, 2 standard deviations, long %B < 0 / short %B > 1 | Closed-bar entry-rule port and research backtest |
| Momentum confirmation / reversal | `controllers/directional_trading/macd_bb_v1.py` | 3m, BB100/2, MACD21/42/9. Long below lower band with MACD < 0 and histogram > 0; mirrored short | Closed-bar entry-rule port; this combines reversal location and momentum, not a pure momentum breakout |
| Trend following | `controllers/directional_trading/supertrend_v1.py` | 3m, length20, multiplier4, trend direction and distance < 1%; 30-record source window | Closed-bar entry-rule port and research backtest |
| Grid | `controllers/generic/grid_strike.py` | User-defined boundaries, allocation, side, order spacing, limit, executor lifecycle; per-level triple barrier | Source and prerequisites only; not installed/executing |
| Arbitrage | `controllers/generic/arbitrage_controller.py` | Two ConnectorPair venues, 1% minimum profitability, conversion rates and imbalance controls | Source and prerequisites only; no second venue integration |

Freqtrade revision: `3ebac56eba525c991462c0714c65a6e2f4e36896`.
ML source: https://github.com/freqtrade/freqtrade/blob/3ebac56eba525c991462c0714c65a6e2f4e36896/freqtrade/templates/FreqaiExampleStrategy.py

FreqAI's example requires its inference gate (`do_predict == 1`) and predicted
future-average-close return above +1% for long / below -1% for short. Exits use
prediction sign reversal. It requires a configured trained model, feature
pipeline and Freqtrade runtime. It is not interchangeable with the existing
Delta model. Listed as source-only, never a fabricated signal.

## Scope and differences

The app uses a TypeScript port of the three Hummingbot *entry predicates*.
It does not install Hummingbot, its connectors, its risk manager or executors.
All app output is read-only research. The app never imports downloaded source
as executable code and never routes these signals to an order submission API.

Bollinger uses its last100 records; MACDBB last120; SuperTrend last30.
Indicators use population standard deviation, SMA-seeded EMA/MACD and Wilder
ATR/SuperTrend. Dependencies for reference vectors are pandas-ta0.4.71b0 and
TA-Lib0.6.8 (both satisfy Hummingbot's declared lower bounds).
Source timeframe is3m. Choosing a different chart timeframe is an explicit
adaptation, displayed on screen. A signal requires valid continuous completed
native candles. No Heikin Ashi/transformed prices or replay future bars enter
the strategy input. Refresh reads the existing chart once a second when open;
it does not add broker requests, subscribers or background jobs.

The chart reference entry is a candle close, not an executable bid/ask.
SL/target/holding-time controls are a separate, labelled *app exit template*:
1% price stop, 2R target, maximum12bars initially. These do not claim to reproduce
upstream triple-barrier defaults. No source strategy is claimed profitable.

Backtests use only loaded completed history (maximum2,000bars), previous-bar
signal and next-open entry, adverse two-sided slippage, configured two-sided
fees including GST. Gap entries beyond stop/target are skipped. Ambiguous
same-bar stop+target uses stop first. Stop gap exits occur at adverse open.
No fills at candle-close signals. The last position is marked closed at the
sample end. Funding, queue priority, real maker fills, liquidity and exchange
rejects are not modelled. Drawdown is closed-trade drawdown. These are sample
reviews, not one-month evidence, optimization or validated performance.

Cash simulations require actual broker contract-value metadata. Instrument quotes
(OHLC, entry, SL, target) stay native USD. Cash P&L and its cost/risk totals follow
the shared INR/USD preference; raw calculations remain in native USD.
Backtest snapshots are scoped to symbol, timeframe, strategy, settings and replay
context/cutoff. Replay cannot reveal a cached live future result.

## Attribution

Hummingbot Foundation. Hummingbot is Apache-2.0 licensed. The TypeScript ports
are modified implementations of its entry rules. License copy:
[hummingbot-APACHE-2.0.txt](hummingbot-APACHE-2.0.txt).
No upstream NOTICE file was present at the pinned root.
Freqtrade is GPL-3.0; this feature links its example without copying or embedding
its implementation. Original source, authorship and licence remain at the link.

## BTCUSD futures focus

The panel is restricted to Delta `BTCUSD` / OpenAlgo `BTCUSDFUT`, exchange
`CRYPTO`; it does not analyse spot BTCUSDT, ETH, options or other contracts.
The three Hummingbot indicators are general-market implementations **ported to
BTCUSD futures**, not strategies originally optimized or validated for BTCUSD.

Delta India's public product endpoint was checked during this work:
https://api.india.delta.exchange/v2/products/BTCUSD
It reported perpetual_futures, contract value0.001BTC, tick0.5USD,
maker rate0.0002, taker rate0.0005, live/operational.
The implementation continues to use selected-contract broker metadata rather
than hardcoding that observation into future calculations. Quantity is in
contracts. Leverage does not multiply cash P&L a second time.

Two BTC/Delta-specific repositories were also inspected directly:

- Official Delta bitcoin-futures market maker, pinned revision
  `9676a2686b2c463c3c66cb001544ec417963ef96`:
  https://github.com/delta-exchange/trading-bots/blob/9676a2686b2c463c3c66cb001544ec417963ef96/market_maker/unhedged.py
  This is a legacy sample, not a current Delta India deployment recommendation.
  `apply_risk_limits` returns buy/sell orders unchanged, and
  `check_for_position_auto_topup` may add margin. Not imported or executed.
- Community multi-timeframe Delta strategy, pinned revision
  `99ac6b7ab5e8166135ab94e0b29d20aee01cc747`:
  https://github.com/kasyap1234/delta-exchange/blob/99ac6b7ab5e8166135ab94e0b29d20aee01cc747/src/strategies/multi_timeframe.py
  Source contains higher/lower-timeframe analysis, ATR stops/targets, trailing
  and profit ladder logic. Its README advertises performance without sufficient
  independent evidence. No licence file was present in the inspected tree
  despite its README's MIT claim. Linked for review only; not copied or run.

These original BTC sources are differentiated from the source-backed indicator
ports. Neither README marketing nor GitHub availability is performance proof.

## Verification and deployment

- 36 focused frontend tests passed across8files; TypeScript and production build
  passed. Includes14 numerical reference scenarios, both MACDBB directions,
  source record windows, next-bar entries, ambiguous stops, gap handling, two-sided
  costs, replay cache invalidation, BTC-only metadata and snapshot bounds.
- Read-only browser verification on the running5050app confirmed the selected
  BTCUSDFUT5m candles, all strategy choices, source links, waiting/long states,
  INR plan prices and loaded-history results. No financial control was activated.
- The observed2,000-bar5m sample (10October02:50–17October01:25 IST) produced
  negative net results for Bollinger and SuperTrend with the default app exit
  settings. This short exploratory result does not qualify either for live use
  and was not used to tune parameters. No profitability claim is made for MACDBB.
- Resource audit: one visibility-aware1sinterval exists only while the panel
  is open and is cleared on close/unmount; tested with fake timers. No new
  broker polling, file handles, DB connections, socket subscriptions, subprocesses
  or backend jobs. Input/output arrays are capped at2,000bars/trades; replaced
  snapshots and account-keyed React remounts prevent accumulated state.
- Published hashed frontend assets while retaining old assets for existing tabs.
  Previous entry files backed up under
  `log/mac/backups/delta-btc-strategies-20261017-013228`.
  No backend restart, broker setting, open order or position mutation.

To reproduce indicator vectors outside the production environment, create an
isolated Python3.13environment with `pandas-ta==0.4.71b0` and `TA-Lib==0.6.8`,
then run `scripts/research/generate_crypto_strategy_vectors.py` from the repo
root. No such dependencies are added to the app's runtime.
