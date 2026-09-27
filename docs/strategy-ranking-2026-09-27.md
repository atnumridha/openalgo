# Groww algorithmic tests and ranking of all strategy research — 27 September 2026

**No strategy is proven profitable or ready for live release.** The new daily-regime-filtered EMA50/200 has the highest observed stressed average, but only 28 trades and its result depends on one large winner. EMA9/15 with Bank Nifty confirmation has more observations, but breaches the intended ₹1,000 trade-loss ceiling. For the next controlled sandbox evaluation, my preference is **the one-minute opening-box breakout with a 15-minute maximum hold**: it has direct option-premium stops and no observed ₹1,000 loss breach in either cost scenario. That choice prioritizes fit to the user's risk requirement; it does not change the numerical ranking or establish safety. The 15-minute box variant was exploratory, not its original 10-minute primary.

The box's stressed average is only **+₹10.04 per trade**, its uncertainty interval spans substantial losses, and portfolio/daily-budget enforcement still needs a dedicated replay of this exact candidate. It is a candidate for validation, not a reason to increase risk. No strategy was activated or changed in the trading application by this task.

## Scope and how to read the ranking

Executed **12 new frozen scalping cells**, plus **four separate equity inclusion trades across two rebalance events**. Audited 90 distinct scalping cells in total: 81 had affordable observed option trades, nine had none. A reused StockGro baseline was excluded from the count. Reconciled 84,462 saved option outcome records across base/stress scenarios; repeated records, shared dates and variants are not independent observations.

[Groww's article](https://groww.in/blog/algorithmic-trading-strategies) describes seven broad families. It does not supply seven complete trading systems. The specific adaptations, cost assumptions and ranking rule were [frozen before the new outcomes](plans/2026-09-27-groww-algorithmic-ranking.md).

The main table ranks each family's **best observed variant** by stressed mean net option P&L. Choosing the best variant is retrospective and can overfit. The complete artifact also preserves original primary variants and every losing/no-trade cell. Base and stress costs can admit different numbers of affordable trades; both counts are shown. Win rate means the proportion of affordable priced option trades with positive net P&L under base costs. It is not directional-prediction accuracy, target-hit probability or a forecast of future wins.

All ranked scalping cells use ₹25,000 initial capital and an ₹20,000 initial entry-funding ceiling. These are independent affordability studies, not ₹25,000 portfolio returns. Earlier studies use ITM options and index-based admission; newer studies use ATM options, and Tradejini uses actual option admission and premium stops. Lot sizes, exit schedules, calendar treatment and available samples differ. Thus the table is a descriptive research ranking, not a controlled head-to-head comparison. The isolated August 2025 observation and the older studies' special-session handling remain evidence limitations.

Base uses 10bp adverse slippage per side and zero brokerage; stress uses 30bp and ₹20 per order, plus modeled fees/taxes. These are scenario assumptions, not actual broker fills or certified historical fee schedules. Underlying 2R targets do not guarantee 2R net option payoffs. Capital is not reset this way in real trading.

## Ranked families

| Rank | Strategy / variant | Base / stress trades | Net wins | Base mean ₹ | Stress mean ₹ | Stress-positive periods / 5 |
|---:|---|---:|---:|---:|---:|---:|
| 1 | EMA 50/200 + daily regime filter — `timing_50_200-hold15` | 28 / 28 | 46.4% | +164.42 | +84.76 | 2 |
| 2 | EMA 9/15 + Bank Nifty confirmation — `ema915-r2-hold15` | 219 / 219 | 46.6% | +108.04 | +19.44 | 2 |
| 3 | Opening box breakout — `box-1m-hold15` | 173 / 173 | 41.0% | +83.12 | +10.04 | 3 |
| 4 | Stochastic pullback — `stochastic-5m-r2-hold15` | 429 / 428 | 45.7% | -14.52 | -104.05 | 1 |
| 5 | RSI divergence — `divergence-5m-r2-hold15` | 360 / 360 | 43.1% | -19.74 | -107.60 | 1 |
| 6 | MA 5/20/200 — `ma-3m-r2-hold5` | 870 / 870 | 43.8% | -23.50 | -112.30 | 0 |
| 7 | EMA 9/21 — `ema921-1m-hold10` | 952 / 952 | 40.2% | -32.69 | -112.93 | 0 |
| 8 | Parabolic SAR — `sar-5m-r2-hold5` | 909 / 909 | 43.7% | -23.95 | -113.38 | 0 |
| 9 | Supertrend pullback — `supertrend-r2-hold10` | 532 / 532 | 38.3% | -36.70 | -114.19 | 0 |
| 10 | Z-score mean reversion — `mean_z20-hold15` | 823 / 823 | 40.6% | -38.33 | -116.14 | 0 |
| 11 | Four-hour range breakout — `fourhour-r2-hold15` | 172 / 172 | 36.6% | -31.84 | -119.09 | 1 |
| 12 | EMA 50/200 crossover — `trend_50_200-hold15` | 112 / 112 | 42.0% | -48.16 | -125.84 | 1 |
| 13 | EMA 5 reversal — `ema5-r2-hold15` | 915 / 914 | 41.0% | -52.42 | -140.99 | 0 |
| 14 | MACD crossover — `macd-r2-hold10` | 60 / 60 | 46.7% | -58.64 | -146.53 | 1 |
| 15 | EMA 5/10 crossovers/time windows — `ema-3m-closing-r2-hold15` | 398 / 398 | 35.7% | -69.45 | -156.27 | 0 |
| 16 | Pin-bar rejection — `pinbar-5m-r2-hold5` | 181 / 181 | 39.2% | -82.52 | -171.61 | 0 |
| 17 | Bollinger squeeze — `squeeze-5m-r2-hold5` | 469 / 469 | 38.8% | -85.82 | -172.41 | 0 |
| 18 | Range bounce — `range-5m-r2-hold5` | 331 / 331 | 43.8% | -86.12 | -172.75 | 0 |

The other two families have no measurable option win rate: the strict IG RSI rules generated no entries, and the new 10%-from-daily-mean example generated no entries. Neither is a 0%-accuracy result.

## Why the top three still do not qualify

| Candidate | Stress mean 95% day-block interval | Positive stressed periods | Worst stressed trade | Trades losing more than ₹1,000, stress | Stress mean after removing its single largest winner |
|---|---:|---:|---:|---:|---:|
| EMA 50/200 + daily regime filter | ₹-123.54 to ₹463.14 | 2/5 | ₹-1424.48 | 3 | ₹-88.77 |
| EMA 9/15 + Bank Nifty confirmation | ₹-128.58 to ₹198.78 | 2/5 | ₹-2796.26 | 26 | ₹-3.68 |
| Opening box breakout | ₹-127.21 to ₹140.84 | 3/5 | ₹-898.79 | 0 | ₹1.77 |

Intervals resample the same development observations; they do not account fully for selecting among many strategies. Removing a winner is an arithmetic sensitivity check, not a new strategy replay. The new regime filter loses in Q1 2025, Q4 2025 and Jan–Apr 2026; one winning trade turns its aggregate positive. EMA9/15 has 219 observations but also depends on favorable outliers under stress. Box is less sensitive to its largest win, but its small stressed margin, two losing periods and broad interval still leave profitability unproven.

The ₹1,000 ceiling is planned risk, not a guaranteed realized cap. Gaps, slippage and delayed exits can exceed stops. Index-triggered exits in these studies do not enforce the user's monetary cap. None of these opportunity sums enforce the ₹1,000 first-trade bucket, separate ₹1,000 later-trade bucket, ₹2,000 daily loss pause and persistent portfolio drawdown rule together.

## New Groww scalping tests

Five-minute closed NIFTY signals, 2R index targets, 5/10/15-minute holds, actual one-minute option paths. Period: **1 Jan 2025–23 Apr 2026**. The **24 Apr–21 Jul 2026** reserved outcomes remain unused.

| Adaptation | Max hold | Priced affordable trades | Base net win rate | Base mean ₹ | Stress mean ₹ |
|---|---:|---:|---:|---:|---:|
| mean_z20 | 5m | 846 | 42.55% | -44.79 | -122.49 |
| mean_z20 | 10m | 834 | 41.49% | -59.84 | -137.57 |
| mean_z20 | 15m | 823 | 40.58% | -38.33 | -116.14 |
| mean_daily10 | 5m | 0 | N/A | N/A | N/A |
| mean_daily10 | 10m | 0 | N/A | N/A | N/A |
| mean_daily10 | 15m | 0 | N/A | N/A | N/A |
| trend_50_200 | 5m | 113 | 45.13% | -60.44 | -138.19 |
| trend_50_200 | 10m | 113 | 42.48% | -50.05 | -127.72 |
| trend_50_200 | 15m | 112 | 41.96% | -48.16 | -125.84 |
| timing_50_200 | 5m | 29 | 55.17% | +123.12 | +43.31 |
| timing_50_200 | 10m | 29 | 44.83% | +87.78 | +8.08 |
| timing_50_200 | 15m | 28 | 46.43% | +164.42 | +84.76 |

The z-score test buys a closed re-entry into a 20-bar ±2-standard-deviation band, with candle direction confirmation. The literal 10% daily-mean example uses only previously completed daily closes. Trend following crosses EMA50/200 on five-minute bars. The timing adaptation adds prior-day SMA200 direction and a low-realized-volatility condition; it is **not a test of VIX, macro-news timing or every possible Groww implementation**. Primary hold was 15 minutes for each family.

The first run failed input validation before signals/outcomes: 31 pre-cutoff Yahoo daily rows had missing closes. The corrected run excludes and records them without filling prices. Daily features use strictly earlier dates. The failed manifest is retained. No tuning followed the outcomes.

## Index-rebalancing family: separate event study

All Nifty50 additions in the official [February 2025 notice](https://www.niftyindices.com/Press_Release/ind_prs21022025.pdf) and [August 2025 notice](https://nsearchives.nseindia.com/web/pressrelease/2025-08/ind_prs22082025_20250822194818.pdf) were included. Buy next-session open after the public announcement, sell last close before inclusion. Yahoo daily prices were downloaded only for the bounded 2025 event windows and archived. Zomato history uses its current Yahoo ticker ETERNAL.NS.

| Stock | Entry → exit | Whole shares | Gross P&L | Net, illustrative 30bp round trip | Net, illustrative 60bp round trip |
|---|---|---:|---:|---:|---:|
| JIOFIN.NS | 2025-02-24 → 2025-03-27 | 43 | ₹-224.46 | ₹-253.92 | ₹-283.38 |
| ETERNAL.NS | 2025-02-24 → 2025-03-27 | 45 | ₹-616.50 | ₹-645.27 | ₹-674.04 |
| INDIGO.NS | 2025-08-25 → 2025-09-29 | 1 | ₹-442.50 | ₹-460.28 | ₹-478.07 |
| MAXHEALTH.NS | 2025-08-25 → 2025-09-29 | 8 | ₹-1024.00 | ₹-1052.22 | ₹-1080.45 |

Each two-stock campaign starts with ₹25,000, with up to ₹10,000 gross funding per name and uninvested cash retained. February's campaign loses ₹899.19 at 30bp / ₹957.43 at 60bp; August's loses ₹1,512.51 / ₹1,558.52. **0/4 profitable trades**, across only two correlated events. These are month-long holds, not scalping. Costs are sensitivity assumptions, not a Kotak equity fee quote; there is no portfolio stop/drawdown model or shorting of deleted names. This tiny sample cannot establish the general value of rebalance trading and is excluded from the scalping rank.

## ML and earlier portfolio studies

These remain separate because they use actual evolving risk state and mostly ₹10,000 capital. They are not comparable with independent ₹25,000 opportunity averages. Existing results were audited, not retrained and relabeled as new tests.

- [Original 2019 archival baseline](historical-test-2026-09-26.md): one training loss and four later losses; old monthly options, coarse execution. Not suitable for current scalping selection.
- [2026 five-minute UI baseline](historical-ui-retest-2026-09-26.md): lost in both development partitions; later minute-level diagnosis exposed resolution/ambiguity limitations. Preserve as an earlier stage, not an extra independent strategy.
- [Corrected baseline plus four filtered variants](filtered-strategy-retest-2026-09-26.md): the original control was positive on a small 2026 sample, all four filtered variants lost. No candidate qualified. The control's subsequent [four-quarter robustness study](strategy-robustness-2026-09-26.md) lost in every 2025 quarter (19 base trades; sum −₹5,935.63 across four separate accounts, not one account return).
- [Initial two technical ML models](technical-ml-training-2026-09-26.md): selected Ridge lost in both later periods. Corrected evidence is canonical; the older “verified” folder is explicitly superseded.
- [Twelve-configuration ML search](ml-walkforward-search-2026-09-26.md): 36 chronological fits, 288 correlated trading replays. Original consistency ranking below; all failed qualification. Each later period starts a fresh ₹10,000 account, so sums are across three accounts.

| Original ML rank | Configuration | Base trades | Positive periods / 3 | Base P&L sum | Stress P&L sum | Qualified |
|---:|---|---:|---:|---:|---:|---|
| 1 | compact-ridge10 | 23 | 2 | ₹+652.18 | ₹+269.60 | No |
| 2 | all-boosted | 20 | 1 | ₹-1790.24 | ₹-2653.68 | No |
| 3 | portable-boosted | 29 | 1 | ₹+2998.09 | ₹-464.94 | No |
| 4 | compact-ridge100 | 23 | 1 | ₹-1177.28 | ₹-2150.49 | No |
| 5 | portable-extra_trees | 5 | 0 | ₹-1403.45 | ₹-1692.50 | No |
| 6 | portable-ridge100 | 12 | 0 | ₹-3994.13 | ₹-3616.05 | No |
| 7 | all-ridge100 | 9 | 0 | ₹-3581.69 | ₹-2867.28 | No |
| 8 | portable-ridge10 | 7 | 0 | ₹-4465.97 | ₹-4126.22 | No |
| 9 | all-extra_trees | 8 | 0 | ₹-1625.37 | ₹-1988.89 | No |
| 10 | all-ridge10 | 9 | 0 | ₹-4829.74 | ₹-4385.62 | No |
| 11 | compact-extra_trees | 3 | 0 | ₹-1838.19 | ₹-1992.27 | No |
| 12 | compact-boosted | 16 | 0 | ₹-1890.03 | ₹-3777.62 | No |

[Prediction-focused ML follow-up](ml-prediction-improvement-2026-09-26.md): 24 fits and 48 validation variants; later prediction error improved 1.64%, worsened 0.07%, and was unchanged across the three folds. Failed the prediction screen; prediction errors are not option win rates or a new P&L ranking.

## Ideas that still cannot be honestly profit-tested with this archive

| Idea | Current outcome |
|---|---|
| Cross-exchange/statistical arbitrage | No synchronized executable bid/ask, size and fill/latency history for both legs. Only NIFTY option raw paths are available for this study. Minute last-price differences are not attainable arbitrage profit. |
| VWAP/TWAP | Execution schedules for splitting an order. Current entries are one whole option lot, so multiple legal child lots cannot be formed. No execution-quality claim or accuracy percentage; this is a feasibility audit. |
| Fabio order-flow setup | Historical depth/aggressor prints unavailable; previous feasibility audit remains unranked. |
| HFT/quantum concepts | No verified executable edge test; do not assign invented profitability or accuracy. |
| Bank Nifty option execution | Bank Nifty index confirmation was tested, but this ranking's traded option legs are NIFTY. It does not prove Bank Nifty option profitability. |

## Verification and reproducibility

- 83 focused regression tests passed, including 12 new signal/ranking tests. This is not a full-repository-green claim.
- Independent new verifier rebuilt **96,080 family/bar signal rows**, checked **1,261 contract selections**, **2,951 index outcomes**, **5,902 option scenario outcomes**, and **338 option-source hashes**. It uses separate signal, selection, exit and fee calculations from the production research functions.
- Rebalance verifier reconciled four trades/two campaigns from six archived source files and checked benchmark returns against the hashed daily source. No corporate actions occurred in these bounded downloads.
- Fresh read-only review found no blocking defects; its sample-count clarity finding was addressed by displaying both base and stress counts.
- Ranking reconciles counts, win rates and net means/sums directly from saved outcome rows, retains evidence hashes, and checks the older 25k EMA option audit duplicates the later EMA9/15 result.
- Source/calendar/risk limitations remain; repeated historical tests cannot substitute for genuinely new forward observations. No protected outcomes, live orders, activation, UI changes or deployment in this task.

Local commands, from the repository root:

```sh
uv run --no-sync python scripts/research_groww_algorithmic.py --output /tmp/groww-algorithmic-reproduction
uv run --no-sync python scripts/verify_groww_algorithmic.py data/research/groww-algorithmic-2026-09-27
uv run --no-sync python scripts/verify_groww_rebalance.py data/research/groww-rebalance-2026-09-27
uv run --no-sync python scripts/research_rank_all.py --output /tmp/strategy-ranking-reproduction
```

Each runner requires a new output directory and preserves existing experiments. Ranking reads existing saved outcomes; it does not query or reevaluate protected prices.

Full evidence: [all 90 cells, primary variants and duplicates](../data/research/strategy-ranking-2026-09-27-final/ranking.md), [machine-readable ranking](../data/research/strategy-ranking-2026-09-27-final/ranking.json), [CSV](../data/research/strategy-ranking-2026-09-27-final/ranking.csv), [new scalping results](../data/research/groww-algorithmic-2026-09-27/results.json), [new independent verification](../data/research/groww-algorithmic-2026-09-27/verification.json), [rebalance results](../data/research/groww-rebalance-2026-09-27/results.json). Large local research evidence remains ignored by Git; this report and scripts are the durable repository records.
