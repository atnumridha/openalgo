# Tradetron scalping guide: historical test — 27 September 2026

**All 15 corrected variants lost money after modeled costs.** None demonstrated a profitable options edge in this study. RSI divergence with the 15-minute cap was closest to break-even; the guide's explicit EMA 5/10 idea also lost money.

The [Tradetron guide](https://tradetron.tech/blog/scalping-trading-the-ultimate-guide-for-indian-traders-in-2025) supplies EMA periods and a one-minute timeframe, but otherwise describes broad ideas, not complete executable strategies. These are five documented NIFTY/ITM-option adaptations, not a test of a published Tradetron marketplace algorithm. The page was read on 27 September 2026 and displays an update date of 13 July 2026.

Dates: **1 January 2025–23 April 2026**. Capital allowance: **₹25,000**, with a **₹5,000 buffer**. Primary comparisons use a **maximum 15-minute hold**, a signal-close **15-index-point stop**, and a target at **twice actual index entry-to-stop distance**. EMA uses one-minute candles; the other four use five-minute candles. Five/ten-minute holding limits are predeclared sensitivities. No settings were selected to maximize these outcomes.

## Primary option results

| Setup | Candle minutes | Affordable trades | Win rate after base costs | Mean base P&L/trade | Mean with higher costs |
| --- | --- | --- | --- | --- | --- |
| EMA 5/10 | 1 | 891 | 37.93% | −₹76.36 | −₹166.49 |
| RSI divergence | 5 | 360 | 43.06% | −₹19.74 | −₹107.60 |
| Bollinger squeeze | 5 | 431 | 33.64% | −₹95.79 | −₹182.29 |
| Pin-bar level rejection | 5 | 170 | 40.59% | −₹103.60 | −₹192.91 |
| Range bounce | 5 | 317 | 41.32% | −₹105.23 | −₹191.98 |

Win rate means positive option profit after modeled fees and slippage; it is not prediction accuracy for all market bars or the fraction reaching 2R. Each result is conditional on the scheduling, contract, data-quality and affordability filters below.

| Setup | Base win-rate 95% interval | Base mean P&L 95% interval | Stress mean P&L 95% interval |
| --- | --- | --- | --- |
| EMA 5/10 | 34.67% to 41.19% | −₹131.97 to −₹17.11 | −₹222.28 to −₹107.74 |
| RSI divergence | 37.50% to 47.78% | −₹92.31 to ₹52.33 | −₹180.23 to −₹34.94 |
| Bollinger squeeze | 28.83% to 38.64% | −₹166.17 to −₹19.90 | −₹252.80 to −₹106.28 |
| Pin-bar level rejection | 32.95% to 48.50% | −₹205.03 to −₹6.47 | −₹293.67 to −₹97.02 |
| Range bounce | 35.22% to 46.34% | −₹184.12 to −₹38.61 | −₹270.75 to −₹125.28 |

Intervals use 2,000 moving blocks of five active trading days, seed 42. They are conditional on observed opportunities and are not corrected for strategy selection or repeated experiments. These are reused exploratory data, not fresh out-of-sample confirmation. Protected 24 April–21 July 2026 outcomes remain unused.

## What was and was not tested

The [frozen specification and correctness amendment](plans/2026-09-27-tradetron-scalping-correctness-amendment.md) gives every threshold and timing convention.

- EMA: completed EMA5/10 cross, 50 observed bars of warm-up, with numerical equality handled explicitly.
- RSI divergence: consecutive strict pivots with two neighboring bars on each side, confirmed two bars later; compare price and RSI14 slopes between pivots. No entry is backdated to a pivot.
- Bollinger: 20-bar bands at two standard deviations; a prior squeeze followed by a band breakout. No volume confirmation is claimed.
- Pin bar: rejection of the prior 20-bar intraday extreme with explicit wick/body proportions.
- Range: bounce from the prior 20-bar extreme inside a range no wider than four ATRs.

VWAP, volume-confirmed breakouts and news-based scalping were **not tested**: the available study inputs have no suitable traded-index/futures volume or timestamped news stream. Generic descriptions of momentum, mean reversion and premium decay do not define additional reproducible algorithms. Futures, Bank Nifty and short options are outside this NIFTY long-option study.

## Why a 1:2 target did not ensure profits

| Setup | Completed index outcomes | Full 2R hits | Stop exits | Time exits | Index mean R |
| --- | --- | --- | --- | --- | --- |
| EMA 5/10 | 962 | 265 (27.55%) | 527 | 170 | 0.0767 |
| RSI divergence | 375 | 59 (15.73%) | 161 | 155 | 0.0102 |
| Bollinger squeeze | 451 | 55 (12.20%) | 197 | 199 | -0.0715 |
| Pin-bar level rejection | 178 | 26 (14.61%) | 71 | 81 | 0.0253 |
| Range bounce | 327 | 48 (14.68%) | 128 | 151 | 0.0414 |

The 2R target is on the index. Time exits, stop exits, actual option prices and costs produce different realized option payoffs. Minute OHLC cannot establish tick-by-tick execution; an index stop/target detected inside a minute is translated to the next option-minute open. Ambiguous stop/target bars count stop-first.

Timing clarification: raw price timestamps are minute opens; signal/index timestamps are minute closes. Option fills saved at a signal/exit timestamp use the next bar's open at that boundary. Detection can lag an intraminute threshold touch by up to a minute. The plan's reference to an extra holding minute is inaccurate: no extra full minute after the scheduled time cap is simulated. This clarification changes no execution code or results.

## Costs, loss exposure and account limits

| Setup | Mean after slippage, before fees | Mean fees | Worst base trade | Losses over ₹1,000 |
| --- | --- | --- | --- | --- |
| EMA 5/10 | −₹50.97 | ₹25.39 | −₹2,145.80 | 101 |
| RSI divergence | ₹4.35 | ₹24.09 | −₹1,266.29 | 10 |
| Bollinger squeeze | −₹72.59 | ₹23.20 | −₹1,669.87 | 19 |
| Pin-bar level rejection | −₹78.78 | ₹24.82 | −₹1,789.81 | 10 |
| Range bounce | −₹81.93 | ₹23.30 | −₹1,789.81 | 16 |

Base: 0.10% adverse slippage per side, zero brokerage, plus configured exchange/SEBI/GST/stamp/STT formulas. Stress: 0.30% per side and ₹20 brokerage per order. These are hypothetical historical cost scenarios, not verified broker bills or recorded bid/ask executions.

**These results are independent trade opportunities, not account returns.** Every opportunity is assessed against the same initial ₹20,000 entry-premium-plus-fees allowance; equity is not compounded. The account's first-trade/later-trade/daily loss buckets, drawdown pause and operational option-premium stop are not simulated. The article's 2% suggestion would be ₹500 at ₹25,000; a 15-point index stop does not enforce that rupee amount. The large losses above show the distinction.

## All 15 variants

| Setup | Candle minutes | Hold cap | Trades base/stress | Base win rate | Base mean P&L | Stress mean P&L |
| --- | --- | --- | --- | --- | --- | --- |
| EMA 5/10 | 1 | 5 | 890/890 | 41.69% | −₹85.57 | −₹175.54 |
| EMA 5/10 | 1 | 10 | 890/890 | 38.65% | −₹84.13 | −₹174.28 |
| EMA 5/10 | 1 | 15 | 891/891 | 37.93% | −₹76.36 | −₹166.49 |
| RSI divergence | 5 | 5 | 373/373 | 42.63% | −₹45.94 | −₹133.70 |
| RSI divergence | 5 | 10 | 368/368 | 40.49% | −₹43.06 | −₹130.92 |
| RSI divergence | 5 | 15 | 360/360 | 43.06% | −₹19.74 | −₹107.60 |
| Bollinger squeeze | 5 | 5 | 469/469 | 38.81% | −₹85.82 | −₹172.41 |
| Bollinger squeeze | 5 | 10 | 447/447 | 36.24% | −₹101.70 | −₹188.04 |
| Bollinger squeeze | 5 | 15 | 431/431 | 33.64% | −₹95.79 | −₹182.29 |
| Pin-bar level rejection | 5 | 5 | 181/181 | 39.23% | −₹82.52 | −₹171.61 |
| Pin-bar level rejection | 5 | 10 | 177/177 | 41.24% | −₹115.28 | −₹204.43 |
| Pin-bar level rejection | 5 | 15 | 170/170 | 40.59% | −₹103.60 | −₹192.91 |
| Range bounce | 5 | 5 | 331/331 | 43.81% | −₹86.12 | −₹172.75 |
| Range bounce | 5 | 10 | 328/328 | 39.02% | −₹118.40 | −₹205.04 |
| Range bounce | 5 | 15 | 317/317 | 41.32% | −₹105.23 | −₹191.98 |

## Period stability

After-cost mean option P&L per affordable trade; 2026 covers January–23 April only.

| Setup | 2025 Q1 | 2025 Q2 | 2025 Q3 | 2025 Q4 | 2026 partial |
| --- | --- | --- | --- | --- | --- |
| EMA 5/10 | −₹86.96 | −₹34.20 | −₹125.91 | −₹0.15 | −₹125.24 |
| RSI divergence | −₹137.48 | −₹159.15 | ₹113.33 | −₹31.44 | ₹91.48 |
| Bollinger squeeze | −₹116.65 | −₹128.43 | −₹184.94 | −₹2.91 | −₹62.35 |
| Pin-bar level rejection | −₹247.70 | ₹31.62 | −₹57.63 | −₹146.45 | −₹66.84 |
| Range bounce | −₹157.66 | −₹300.56 | −₹61.14 | −₹96.96 | ₹7.11 |

## Data coverage and exclusions

Screening retained 120,683 valid minute observations from 121,054, rejecting 371 invalid/out-of-session observations. The corrected run additionally excludes 374 observations on 21 October 2025, leaving **120,309 minutes across 322 observed dates**, and 24,020 complete five-minute candles. An observed date is not a guarantee of a complete exchange session. There is one isolated observation on 23 August 2025; it cannot produce a signal because the consecutive-bar gate fails, but it remains in the one-minute indicator history. The full historical exchange calendar was not independently reconciled.

The independent verifier exposed a floating-point-only EMA crossing in the initial run. Investigating that session also found regular-hours prices during Muhurat trading. [NSE circular CMTR70319](https://nsearchives.nseindia.com/content/circulars/CMTR70319.pdf) places that day's normal market at 13:45–14:45. The correction removes the whole special day before indicators and rounds EMA differences to eight decimals. Strategy parameters were unchanged; the initial results and original source snapshots remain preserved. The earlier IG study was not silently changed, so its coverage differs.

| Primary setup | Raw signals | Index attempts/completed | Excluded late/overlap/daily cap | Missing option evidence | Unresolved index | Unaffordable base/stress |
| --- | --- | --- | --- | --- | --- | --- |
| EMA 5/10 | 10448 | 963/962 | 600 / 383 / 8502 | 34 | 1 | 37/37 |
| RSI divergence | 410 | 376/375 | 25 / 0 / 9 | 5 | 1 | 10/10 |
| Bollinger squeeze | 627 | 451/451 | 35 / 79 / 62 | 7 | 0 | 13/13 |
| Pin-bar level rejection | 197 | 178/178 | 17 / 2 / 0 | 1 | 0 | 7/7 |
| Range bounce | 369 | 327/327 | 28 / 8 / 6 | 2 | 0 | 8/8 |

Contract choice uses prior-session NSE listing/lot evidence and the last completed five-minute option quote, first earliest eligible expiry (1–7 days), then nearest ITM strike; quote volume must be at least ten lots. The one-minute EMA setup can use a quote 0–4 minutes old. No cheaper contract replaces an unaffordable choice.

The three-entry daily cap and serial schedule apply to index opportunities before option eligibility. An unavailable or unaffordable option can consume an index slot and displace a later opportunity. This is not three executable option entries per day, and it does not test the guide's high trade-frequency suggestion.

The option validator requires valid positive-volume prices for every minute through exit. This makes results conditional on future path availability; exclusions need not be random. Missing values are not filled. Base/stress affordability is checked separately; compare their denominators rather than assuming identical samples.

## Reproduction and verification

**45 targeted tests passed**, including 11 Tradetron tests for signal rules, pivot confirmation, gap isolation, future-prefix invariance, numerical crossover equality and the special-session exclusion. Ruff passed for the four new Python files. An independent code reviewer found no frozen-rule or causal-timing defect in the initial signal implementation and identified the reporting limitations above; the subsequent numerical/session corrections have regression tests.

The separate verifier imports no application signal, risk, selection or cost helper. It reconstructed **216,389 signal rows**, **6,996 completed index outcomes**, checked **6,849 as-of contract rankings**, and **13,698 option fill/fee calculations** from raw data. Source/plan/input hashes matched. Unresolved/refused index attempts across correlated variants: 8. Unpriced selected options: 0. Protected sessions evaluated: 0.

Artifacts: `data/research/tradetron-scalping-2026-09-27-corrected/`. It contains frozen registration, input hashes, all signals, index/option ledgers, exclusions, period breakdowns, and `verification.json`. The superseded initial run is in `data/research/tradetron-scalping-2026-09-27/`, with `frozen-source-snapshot/`; it is not the reported result.

```sh
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/research_tradetron_scalping.py \
  --output data/research/tradetron-scalping-new-run
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/verify_tradetron_scalping.py \
  data/research/tradetron-scalping-new-run
```

Resource review was static: files and DuckDB connections use context managers; queries retain the existing 512MB/two-thread limits; data frames are bounded by the study and processed one family at a time. No persistent app state, broker connections or live database calls. No prolonged leak/load measurement was performed. PyArrow's environment CPU-cache permission warnings did not prevent successful verification. No strategy was enabled and no live settings or orders changed.
