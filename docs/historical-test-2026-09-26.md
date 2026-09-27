# Historical strategy test — 26 September 2026

**Decision: the tested baseline does not demonstrate profitability and should not advance to live trading.** Run #1 completed through the authenticated Research UI and was independently reproduced with identical results. No rule tuning was performed after seeing the results.

## What was tested

- Candidate: **Trend and breakout**, using only closed NIFTY five-minute bars; 20-bar lookback, 10% option stop, 20% target, next-bar entry, seed 42.
- Dataset #1: **NIFTY 2019 Jan-May | 5-min monthly options | 85 sessions | archival screen**, from [Zenodo record 10899828](https://zenodo.org/records/10899828), CC0. It contains 74,860 bars, monthly options and historical lot size 75. It is an old archival sample, not current weekly-option evidence.
- Development used **25 sessions, 1 January–4 February 2019**. The first 17 sessions (through 23 January) were training; the following eight were exploratory out-of-sample. Each replay starts separately with ₹10,000, so their ending equities are not one continuous account history.
- Risk: ₹10,000 capital; 20% cash buffer; ₹1,000 first-trade planned-loss allowance; another ₹1,000 shared by later trades; ₹2,000 daily allowance; persistent 20% peak-equity drawdown control. Only whole lots and one long-option position at a time.
- Cost scenario: current configured Kotak API/NSE assumptions applied hypothetically to the 2019 price series. **These are not claimed to be actual 2019 fees.** The run's dated window applies to this simulation only. Brokerage ₹0/order; exchange plus IPFT 0.03553%; SEBI 0.0001%; GST 18% on applicable fees; buy stamp 0.003%; sell STT 0.15%; adverse slippage 10 basis points per side. References: [Kotak API guide](https://www.kotakneo.com/investing-guide/trading-account/kotak-neo-trade-api-guide/) and [charge calculator](https://www.kotakneo.com/calculator/brokerage-calculator/). Live-profile fees were not saved or replaced.

## Results after modeled costs

| Evaluation | Sessions | Trades | Net P&L | Ending equity | Maximum marked drawdown | Win rate |
|---|---:|---:|---:|---:|---:|---:|
| Training | 17 | 1 | **−₹795.53** | ₹9,204.47 | 15.36% | 0% |
| Out-of-sample | 8 | 4 | **−₹1,646.77** | ₹8,353.23 | 19.99% | 0% |
| Engine stress resimulation | Same 8 | 24 | +₹5,185.46 | ₹15,185.46 | 16.41% | 50% |

All position outcomes were complete. The baseline training and out-of-sample profit factors were zero. The exploratory 200-session-block bootstrap of OOS P&L had 5th/95th percentiles of **−₹3,270.32 / −₹23.22**. With only eight OOS sessions and four trades, this is a small-sample diagnostic, not a confidence claim about future returns.

### Why the stress result is not a pass

The engine reruns the entire strategy with slippage increased from 10 to 30 basis points per side and brokerage multiplied by 1.5 (zero remains zero). It can therefore change stops, exit times, later entry opportunities, affordable quantities and the equity path. It does not simply subtract more fees from the same trades.

The first divergence occurs on **24 January 2019 at 13:25** in `NIFTY31JAN1910800PE`. The candle low is ₹74.55. The baseline stop is ₹74.549475, while the stressed entry moves the stop to ₹74.698425. The stressed position stops at 13:25; the baseline position remains open until 14:10. Subsequent trades diverge. This shows sensitivity to a small price-threshold difference; candle screening does not establish exchange-valid tick rounding, executable spreads or fills.

An additional friction-only diagnostic held the **same four baseline OOS trades, timestamps and quantities fixed** and increased only modeled execution friction. Their P&L worsened from **−₹1,646.77 to −₹1,707.39**. This diagnostic is not a separate strategy backtest. The positive resimulation must not be substituted for the failed baseline or treated as robust profitability evidence.

## Main limitations and next decision

- There were **112 unaffordable-whole-lot rejections** across training and OOS. With the cash buffer, initial deployable premium was at most ₹8,000; many 75-unit monthly-option lots could not fit. Additional opportunities were refused by loss/drawdown budgets or missing quotes.
- The dataset contains a limited monthly-contract strike selection. Quotes, bid/ask spread, market depth and actual fills are unavailable; expiry-day low-premium fills and quantities need particular caution when interpreting candle results.
- **VWAP pullback could not run**: every underlying bar lacks observed volume. The validator explicitly refuses invented index volume.
- The new 2020–2026 NSE archive is daily data. It cannot replace matching intraday prices in this five-minute test.
- **All 60 final holdout sessions remain unconsumed.** The baseline failed development screening, so this version was not frozen, sent to the final holdout, enrolled for forward qualification, or enabled for live trading.

The practical next step is a broader, recent, validated intraday option dataset and a clearly specified strategy/capital fit. This result does not justify optimizing on the reserved holdout or enabling real-money trading.

## Reproducibility and evidence

- Stored UI result: **Research → Results → Run #1**.
- Dataset hash: `ecb7a7eb1490d30aa30eedb96ee22f9611cd0dbcbabbd0b191732675512246e1`.
- Configuration hash: `f2e098d907949efd69850876b5d6267f5911889bb5adb64a5b3d37618881b553`.
- Implementation hash: `8b10d0c5feec7cbe307a33a4bef3cf9c9b1db889cf33b4f579bbd5d2b444f607`.
- Full report and diagnostics: `data/research/results/2026-09-26-run-1/run-1.json`.
- Trade exports in the same directory: `training-trades.csv`, `out-of-sample-trades.csv`, `stress-resimulation-trades.csv`.

No product code, trading rules, live authorization, or broker orders were changed to obtain this result.
