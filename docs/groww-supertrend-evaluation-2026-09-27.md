# Groww Supertrend scalping evaluation — 27 September 2026

**All four tested adaptations lost money after modeled option execution costs.** The predeclared primary test, 1:2 index reward/risk with a ten-minute maximum hold, produced a **38.35% net option win rate across 532 affordable trades**, averaging **−₹36.70 per trade**, or **−₹114.19** under higher-cost assumptions. These results do not support live deployment of this adaptation.

## Source and what the test can establish

The [Groww article](https://groww.in/p/scalping-strategy) explains general scalping styles, costs, liquidity and execution. It does not define a reproducible entry algorithm for market making or large-volume stock trades. Those ideas were not assigned fabricated backtest results. Testing market making would require bid/ask, order-book and execution evidence beyond this dataset.

The user-supplied transcript of the [Groww video](https://www.youtube.com/watch?v=ip_vWNyLj5w) supplies the actual new hypothesis: Supertrend (10,3), a one-minute candle touching the line without a trend-colour change, then a break of that candle's high/low, stop at its opposite extreme, 1:2 or 1:3 target, and a maximum ten-minute hold. Downward signals buy ATM puts; upward signals buy ATM calls. The screenshot examples discussed in the transcript are not a statistically representative accuracy test.

The source describes entering as the level breaks **inside a minute**. Our aligned index and option data contain minute OHLC, without the exact simultaneous trigger-time option quote. This study tests a **close-confirmed adaptation**: only the immediately following candle may confirm by closing beyond the setup extreme, then execution occurs at the next minute's open. The confirmation candle must preserve trend and avoid the opposite setup extreme. This extra confirmation, one-bar setup expiry and delay can miss fast profitable moves; the results cannot establish the exact intraminute video's accuracy. These assumptions were frozen before results, not chosen afterward.

The [registered protocol](plans/2026-09-27-groww-supertrend.md) defines all calculations, timing and exclusions. Indicator bands follow the [published TradingView Supertrend recurrence](https://www.tradingview.com/support/solutions/43000634738-supertrend/), with Wilder ATR10, multiplier3 and an initial downward state. There is no additional EMA or candle-body filter.

## All four registered results

Research capital: **₹25,000**, with a 20% reserve and ₹20,000 maximum initial entry funding including buy fees. One observed historical option lot; 1-minute Nifty signals; historical period **1 January 2025–23 April 2026**. All figures below refer to options affordable at that initial capital, not compounded account returns.

| Index target | Maximum hold | Affordable option trades | Net win rate | Mean net per trade | Higher-cost mean | Base losses above ₹1,000 |
|---|---:|---:|---:|---:|---:|---:|
|1:2|5 min|542|40.77%|−₹44.40|−₹121.76|12|
|**1:2 — primary**|**10 min**|**532**|**38.35%**|**−₹36.70**|**−₹114.19**|**24**|
|1:3|5 min|541|39.74%|−₹58.16|−₹135.46|13|
|1:3|10 min|530|36.23%|−₹47.75|−₹125.13|25|

Base assumptions: 10bp adverse slippage per side, zero brokerage plus configured exchange, SEBI, GST, stamp and STT charges. Stress: 30bp per side and ₹20 per order plus the same configured charges. These are modeled costs, not historical Kotak bills.

For the primary result, the moving-five-active-day 95% interval for mean net P&L is **[−₹102.28, +₹35.20]** at base costs and **[−₹179.58, −₹42.04]** under stress. The base win-rate interval is **34.29%–42.89%**. All four stress-cost mean intervals are below zero in this sample. These bootstrap intervals use 2,000 draws with seed42 and do not establish future performance; the data have been used in earlier strategy research.

## Index targets are different from option returns

The primary index replay had 537 completed opportunities: 227 positive index outcomes (42.27%), with 96 target hits (17.88%), 235 stops and 206 time exits. Mean gross index result was +0.0479R. Four options were too expensive and one price path was unavailable, leaving the 532 trades in the main money table.

An index 2R target is **not** a promise of net option 2R. Observed option prices, changing premium sensitivity, delayed execution and costs determine the money result. In the primary test, options averaged **−₹18.70 after modeled slippage but before explicit fees**; fees then averaged another ₹17.99, yielding −₹36.70. Lower brokerage alone would not make this particular recorded sample profitable under the remaining assumptions.

The primary result varied across periods:

| Period | Trades | Mean net per trade |
|---|---:|---:|
|2025 Q1|110|+₹13.86|
|2025 Q2|87|−₹83.07|
|2025 Q3|103|−₹120.40|
|2025 Q4|90|−₹90.19|
|2026 through 23 April|142|+₹47.16|

## Risk and execution findings

The video places stops on the **index**, so this study did not silently replace them with option-premium stops. Consequently the user's ₹1,000 per-trade allowance is not enforced. The primary variant had 24 base-cost losses above ₹1,000, with a worst loss of ₹1,567.64; stress had 29 above ₹1,000 and a worst loss of ₹1,641.07. The 1:3 variants' worst modeled loss was ₹4,855.96 at base costs and ₹4,944.39 under stress.

The large 1:3 loss was checked against both source price paths: on 6 June 2025, a 24,700 put expiring 12 June entered at 10:02 with a modeled ₹177.10 fill, 75 units. The index stop was touched during the 10:06–10:07 minute, when Nifty rose from 24,706.80 to a 24,802.25 high. The option's open fell from ₹172.25 at 10:06 to ₹112.80 at 10:07; after modeled exit slippage, the sale was ₹112.65. The simulation only acted once that minute closed. This is evidence of execution-delay exposure in this model, **not proof that a tick-driven stop would incur the same loss**. It also explains why the theoretical index stop loss of 13 points cannot be treated as the realized cash risk.

The three-per-day cap applies to serial **index** entries, with missing/unaffordable options still using an index slot. Daily first/later-trade loss buckets, the ₹2,000 daily-loss pause, portfolio drawdown, capital compounding and an independent option-premium hard stop are not simulated. These results are a strategy opportunity study, not a validation of the live platform's cash-risk controls. The execution and exit model differs from the earlier Tradejini premium-stop study, so their profit rankings are not a controlled comparison.

## Coverage and validation

- 120,309 screened Nifty minutes over 322 observed dates, after excluding 374 Muhurat-session observations. The isolated 23 August 2025 observation remains in indicator history but cannot produce an entry after the gap-readiness gate; full exchange-calendar reconciliation remains a data limitation.
- 671 close-confirmed signals, each with an eligible observed option quote and prior listing. Selection uses expiry 0–7 days, nearest eligible strike, historical lot size, and a completed five-minute quote with volume at least ten lots. ATM is a nearest-strike proxy; delta and bid/ask liquidity are not verified.
- Scheduling yielded 546/537/545/535 index opportunities respectively. Every cell had four unaffordable option observations. The two ten-minute cells each had one missing/untradeable option path, excluded explicitly; five-minute cells had none. No missing outcome was counted as a zero loss or a win.
- **79 regression tests passed**, including seven new Groww tests. Independent review also matched Supertrend over 4,991 valid synthetic bars with 84 flips and checked index-to-option fill timestamps. Ruff checks passed.
- The independent verifier reconstructed **120,309 indicator/signal rows, 671 contract selections, 2,163 index outcomes and 4,326 option outcomes across correlated variants and cost scenarios**. All 296 option-source fingerprints matched. It rechecked option types, raw price paths, scheduling, fills, fees, counts, means and net win rates; aggregate reports match their per-cell files. Existing diagnostic helpers produce the bootstrap and period summaries.
- Outcome queries excluded the reserved **24 April–21 July** period. Whole archive files were hashed for provenance, including any reserved rows they contain, without evaluating those rows. Zero protected sessions were evaluated.
- All changes are offline research files. No live/sandbox activation, broker requests, orders, deployment or changes to prior registered strategies occurred. File and DuckDB resources were statically reviewed for context-managed cleanup; both scripts exited successfully. No long-lived cache, thread or worker was introduced.

## Reproduce

Artifacts are under `data/research/groww-supertrend-2026-09-27/`: registration and transcript fingerprint, signal table, selections, raw option paths, ledgers, results and `verification.json`.

```bash
LOG_FORMAT='%(levelname)s %(message)s' UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/research_groww_supertrend.py --output /tmp/groww-fresh-run
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/verify_groww_supertrend.py data/research/groww-supertrend-2026-09-27
```

The runner requires a new output directory and preserves earlier experiments. Sources: `services/research/groww_supertrend.py`, `scripts/research_groww_supertrend.py`, `scripts/verify_groww_supertrend.py`, `test/test_research_groww_supertrend.py`. No parameters were retuned after these results.
