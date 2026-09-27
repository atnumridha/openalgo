# Three scalping strategies tested with INR25,000

EMA9/15 with dual-index confirmation and a 15-minute maximum hold was the strongest **research candidate** in this comparison. The MACD/EMA200 and 5EMA reversal implementations lost money after modeled costs. None is qualified for live trading or proven to earn money under the user's portfolio risk limits.

This is a historical development comparison over **1 January 2025–23 April 2026**. It uses actual NIFTY prices, Bank Nifty confirmation where specified, and historical ITM option prices. The protected period beginning 24 April 2026 was not used. Previously examined development dates are not fresh, independent evidence.

## Primary comparison: 2R target, 15-minute maximum hold

Assume INR25,000 capital, a 20% cash buffer and one option lot whose premium plus entry charges fit INR20,000. Every strategy has a maximum of three serial index entries per day. Downward signals are priced as **buying puts**, not selling options.

| Strategy | Affordable option observations, base | Option win rate after base costs | Mean net outcome, base | Mean net outcome, stress | Sum of net observations, base / stress |
|---|---:|---:|---:|---:|---:|
| EMA9/15 + Bank Nifty confirmation | 219 | 46.58% | +INR108.04 | +INR19.44 | +INR23,661.24 / +INR4,256.61 |
| MACD + EMA200 + support/resistance | 58 | 44.83% | -INR120.05 | -INR208.08 | -INR6,963.07 / -INR12,068.40 |
| 5EMA reversal | 915 | 40.98% | -INR52.42 | -INR140.99 | -INR47,961.57 / -INR128,866.72 |

**These sums are not portfolio returns on INR25,000.** Each row prices independent one-lot opportunities with an initial-capital affordability filter. It does not compound capital, apply daily loss buckets or stop trading at portfolio drawdown. A funded portfolio would accept a different sequence of trades and stop earlier after losses. The 5EMA stress subset contains 914 observations because one additional lot fails affordability when costs rise. The other main subsets have the same counts under stress.

Base: 10 basis points of adverse slippage per side, zero brokerage plus explicit exchange, SEBI, GST, stamp and STT charges. Stress: 30 basis points per side, INR20 brokerage per order plus the same tax/fee formula. These are hypothetical applications of configured current fees to historical prices, not verified historical bill amounts.

## Accuracy is not the same as hitting a 2R target

| Primary strategy | Completed index trades | Positive index outcome | Full index 2R target reached | Time exits | Stop exits |
|---|---:|---:|---:|---:|---:|
| EMA9/15 | 240 | 54.17% | 10/240 = 4.17% | 183 | 47 |
| MACD | 60 | 48.33% | 7/60 = 11.67% | 40 | 13 |
| 5EMA | 963 | 44.55% | 100/963 = 10.38% | 558 | 305 |

A small positive time exit counts as a win but does not deliver 2R. The index stop/target is also not an option-premium stop/target: delta, time value, execution delay and costs change the option payoff. This test does **not** establish a net 1:2 option reward/risk ratio.

The EMA9/15 positive-index rate has a 95% moving-day-block bootstrap interval of approximately **47.7%–59.6%**. This objective implementation does not substantiate the video's 90%+ claim. The 5EMA transcript's stated 62%–70% accuracy was not reproduced under these NIFTY scalp assumptions either.

Coverage: EMA9/15 has 241 attempted index observations, one unresolved due to a missing minute; 231 have ITM option prices, nine lack eligible observed ITM/listing evidence, and 219 fit initial capital. MACD has 60 completed index trades and 58 priced, affordable options. The 5EMA main test has 969 attempts; six are rejected because the next open is already through the stop, 18 lack eligible ITM evidence, 945 have prices, and 915 fit initial capital. Rejected/unavailable observations are retained in saved records, not converted to wins or zero returns.

## Native video targets, tested separately

With the same 15-minute maximum holding time:

| Strategy and stated target | Affordable options | Net win rate, base | Mean net outcome, base | Mean net outcome, stress |
|---|---:|---:|---:|---:|
| MACD, 1.5R | 58 | 44.83% | -INR126.51 | -INR214.46 |
| 5EMA reversal, 3R | 915 | 39.78% | -INR62.77 | -INR151.36 |

Neither native target improved the conclusion. The user-selected 5–15 minute cap is an adaptation: the transcripts describe trades that can run longer.

## All fifteen comparisons

This fixed set tests three EMA9/15 durations, six MACD target/duration combinations and six 5EMA target/duration combinations. All results were retained.

| Strategy | Target | Maximum minutes | Base affordable count | Base net win rate | Base sum of independent outcomes | Stress sum of independent outcomes |
|---|---:|---:|---:|---:|---:|---:|
| EMA9/15 | 2R | 5 | 225 | 42.67% | -9,332.13 | -29,227.69 |
| EMA9/15 | 2R | 10 | 223 | 43.95% | +17,547.91 | -2,205.86 |
| EMA9/15 | 2R | 15 | 219 | 46.58% | +23,661.24 | +4,256.61 |
| MACD | 1.5R | 5 | 60 | 43.33% | -5,252.32 | -10,525.50 |
| MACD | 1.5R | 10 | 60 | 46.67% | -3,769.16 | -9,034.90 |
| MACD | 1.5R | 15 | 58 | 44.83% | -7,337.34 | -12,438.95 |
| MACD | 2R | 5 | 60 | 43.33% | -5,038.98 | -10,312.16 |
| MACD | 2R | 10 | 60 | 46.67% | -3,518.40 | -8,791.61 |
| MACD | 2R | 15 | 58 | 44.83% | -6,963.07 | -12,068.40 |
| 5EMA | 2R | 5 | 912 | 40.35% | -78,591.40 | -159,187.45 |
| 5EMA | 2R | 10 | 915 | 41.64% | -72,062.41 | -153,165.34 |
| 5EMA | 2R | 15 | 915 | 40.98% | -47,961.57 | -128,866.72 |
| 5EMA | 3R | 5 | 912 | 40.13% | -84,294.20 | -164,879.48 |
| 5EMA | 3R | 10 | 915 | 40.98% | -76,138.53 | -157,231.19 |
| 5EMA | 3R | 15 | 915 | 39.78% | -57,437.89 | -138,339.82 |

Money values are INR. Comparisons are correlated and exploratory; they are not fifteen independent confirmations.

## What changed with INR25,000

For the same main EMA9/15 signals and contracts, increasing the initial capital assumption changes which one-lot premiums fit, not predictions or prices:

| Capital / spendable premium | Affordable base observations | Net win rate | Mean base / stress outcome |
|---|---:|---:|---:|
| INR10,000 / INR8,000 | 70 | 38.57% | -INR39.22 / -INR99.91 |
| INR25,000 / INR20,000 | 219 | 46.58% | +INR108.04 / +INR19.44 |

The stress subset at INR10,000 has 69 observations. More capital makes more ITM contracts accessible in this sample; it does not demonstrate that capital alone causes profitable trading.

## Why the leading setup is not ready for live use

- **Uncertain edge:** EMA9/15's mean base option outcome has a day-block 95% interval of about **-INR40 to +INR288**; stress about **-INR129 to +INR199**. Both include losses.
- **Period dependence:** EMA9/15 stress results were negative in 2025 Q1, Q2 and Q3; its combined gain depends on the Jan–Apr 2026 segment. The five stress-period sums were -1,835.41, -6,954.42, -273.61, +519.23 and +12,800.82.
- **Risk mismatch:** 21 EMA9/15 base observations lost more than INR1,000; the largest lost INR2,700.34. MACD had 11 such losses; 5EMA had 123. Raising research capital did not raise the user's planned loss budgets. An index candle stop cannot guarantee a rupee option loss cap.
- **Execution evidence:** one-minute OHLC does not prove tick-level executable prices, spreads, depth, stop ordering or broker fills. Price and liquidity screens reduce, but do not eliminate, these limitations.

Keep EMA9/15 as the candidate for the next distinct, preregistered study: option-premium stops sized to the actual loss buckets, net 2R targets, full shared-capital replay, then forward paper qualification. Do not clip historical losses to INR1,000 or label this comparison a profitable live portfolio. MACD and 5EMA should not be promoted from this evidence.

## Exact implementations and differences from the transcripts

- EMA9/15: EMA alignment plus a directional pin/full/big candle touching the EMA zone. Both EMAs need a three-candle slope of at least 0.10 ATR per candle; Bank Nifty must agree and avoid an objectively defined nearby prior high/low. Visual 30-degree angles and discretionary resistance were replaced by these registered definitions. The full original EMA9/15 transcript was unavailable; its supplied summary was used.
- MACD: standard **EMA12 minus EMA26**, signal EMA9; crossover below zero for buys/above for sells, with price on the correct side of a **200-bar** EMA. Support/resistance uses confirmed two-left/two-right pivots and a recent retest. Stop is 0.10 ATR beyond EMA200. This corrects the supplied transcript's inaccurate description of the MACD lines; see [TradingView's definition](https://www.tradingview.com/support/solutions/43000502344-moving-average-convergence-divergence-macd-indicator/).
- 5EMA: an entire 5-minute candle above EMA5 creates a bearish alert; an entire 15-minute candle below EMA5 creates a bullish alert. Later price breaks trigger entry, with the alert candle's opposite extreme as stop. Old alerts are checked before new closed candles replace them. Tick entry is approximated with an observed one-minute break followed by next-minute-open execution. No discretionary swing stop, reduced stop, trailing or partial exits. Bank Nifty-specific point-stop guidance is not transplanted into NIFTY.
- All use long ITM NIFTY options to compare signal quality on a common instrument. The 5EMA video's ATM/OTM alternatives, option selling, futures, news-stock setups and longer trend-following exits were **not tested**. These results do not reject every possible interpretation of the videos.

## Data, code and verification

The existing Kotak NIFTY five-minute source is supplemented by newly downloaded **120,683 screened NIFTY one-minute candles over 323 observed sessions**, and **28,724 screened Bank Nifty five-minute candles over 383 sessions** including October–December 2024 warmup. Invalid/out-of-session observations were rejected without price repair. Public Upstox-origin minute options and previous-session NSE listings provide actual premiums, expiries and lot sizes; historical source limitations in [the download report](five-minute-history-2026-09-26.md) still apply.

Implementation: `services/research/ema_scalp.py`, `services/research/scalp_strategies.py`, `scripts/research_ema_scalp.py` and `scripts/research_scalp_compare.py`. Existing live strategy logic, ML models and risk controls were not changed.

Canonical evidence: `data/research/scalp-comparison-2026-09-26-verified/`. It contains registered plan/code/input/transcript hashes, all fifteen separate index/option ledgers, base/stress prices, quarterly diagnostics and availability counts. The earlier INR10,000, INR25,000 and first-comparison outputs remain separate for audit.

Verification includes 427 related tests, independent reconstruction of 6,878 completed chart outcomes, confirmation of three genuinely missing-minute outcomes, 82 independent raw-price/fee sample checks, and checks that all 6,731 option selections use a completed quote no later than the signal and prior-session listings. Sparse confidence intervals are unavailable when fewer than two five-day blocks exist. File reads use context managers, DuckDB connections are closed, archive processing is bounded, and standalone broker-download sessions/HTTP resources were closed; resource review was static, not a live-process leak stress test.

Reproduce from the `openalgo` directory with an unused output path:

```sh
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/research_scalp_compare.py \
  --output data/research/scalp-comparison-new-run
```

This uses the saved local price snapshots and supplied transcript attachments. It does not download, train ML, enable automation or place orders.
