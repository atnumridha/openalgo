# DPA Liquidity Sweep | OTE

Separate Pine v6 TradingView strategy for **standard underlying price charts**. It does not combine with PK, BB/Chikou or the nine-indicator dashboard.

Reference: [Justin Bennett's liquidity sweep article](https://dailypriceaction.com/blog/liquidity-sweep-reversals/), including the annotated acceptance-level illustration. This is a mechanical interpretation of a discretionary method, not a claim of identical signals to the author.

## Use

Open `dpa_liquidity_sweep_strategy.pine` in TradingView's Pine Editor and add/update it on **NSE:NIFTY** or **BSE:SENSEX**, preferably **15-minute standard candles**. Structure timeframe defaults to **1 hour**. Green **Bull** and red **Bear** labels appear only on confirmed entry candles. Orange Sweep means continue waiting. The table explains the current phase, OTE, acceptance level and frozen trade levels.

Bull means underlying upward bias; Bear means downward bias. These do not independently specify a CE/PE strike, option fill, expiry or premium return. Native orders simulate one underlying unit, with INR accounting and ₹100,000 initial capital. Index spot itself is not directly executable.

## Mechanical choices

- Both timeframes use symmetric **2-left / 2-right confirmed pivots**, adjustable from 1–10. No pivot label is backdated. The hourly tuple uses the previous completed hourly value with `lookahead_on`.
- A new directional impulse requires two descending confirmed highs and lows (Bear), or ascending highs and lows (Bull), with origin before endpoint. Anchors persist during the retracement.
- A local confirmed high/low must have formed under the same already-available HTF impulse and lie inside **62–79% OTE**. For Bear, track the lowest pullback low after the local high and before its sweep. Bull mirrors this with a pullback high.
- A sweep must cross the local level and close back inside. It never triggers entry by itself. A later candle must close through the frozen pullback level. Choose the article's close-entry branch; discretionary FVG/order-block retests, tighter structural stops and distribution-channel judgments are not implemented.
- Stop goes beyond the most extreme sweep price seen through confirmation, plus **2 minimum ticks**. Target stays at the frozen external endpoint. Both remain fixed after entry.
- An origin or target touch retires the entire impulse for new entries until its key changes. Context changes cancel pending sequences. A breakout close cancels the local candidate. There is no arbitrary candle-count expiration and no daily forced exit.

## Costs and fills

Defaults in **Properties**: commission **0.02% per fill**, adverse slippage **1 tick**, no leverage, 1-unit quantity, no pyramiding. Entries process on the confirmed bar's close. Native protective stop and target orders then manage the position, including overnight gaps. Close fills are an execution assumption; alerts received after a session closes may execute only next session.

The **Cost model** inputs calculate admission R. Keep them synchronized with Properties if changing costs. Net reward deducts entry/target commissions. Net risk adds entry/stop commissions and adverse stop slippage; planned entry already includes adverse entry slippage. Admit only if net reward/risk is at least **2R**. Gaps can produce worse realized fills than planned R. Default broker-emulator intrabar OHLC sequencing is not tick data.

The optional date filter limits **new entries**, including requiring the confirmation close within the interval. Existing positions retain their protective exits after the end date. Date filtering is off by default so the available chart history can be tested without hand-picking days.

## Validation

See `docs/validation/dpa-liquidity-sweep-2026-10-28.md` for actual TradingView results and account restrictions. Automated fixtures execute the production Pine rules, context functions and native strategy orders. Fixtures substitute deterministic external context/metadata and pivot discovery only for native-order scenarios; actual context discovery is tested separately. TradingView compilation and broker-emulator results remain authoritative.

Tests:

```sh
PINETS_MODULE=/private/tmp/bb-chikou-validation/node_modules/pinets \
/Users/nmandal/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
--test scripts/tradingview/tests/*.test.cjs
```

The existing PineTS module is reused; no new dependency installation is needed. The suite is synthetic rule verification, not a profitability test or proof of full discretionary equivalence.

## Delta BTCUSD perpetual backtest preset

Use `dpa_btcusd_backtest.pine` on **DELTAIN:BTCUSD.P,15m**. It keeps the same confirmed-pivot rule cores and uses USD accounting, one Delta lot(0.001BTC), conservative0.059% per-fill costs including GST, and one tick slippage. Funding is excluded. Sizing divides0.001 by the chart's `syminfo.pointvalue`; the table shows the resulting quantity and actual loaded data timestamps. Both presets show the latest confirmed table immediately on live charts. See `docs/validation/dpa-btcusd-2026-10-28.md` for actual results; the tested sample had no admitted trades.
