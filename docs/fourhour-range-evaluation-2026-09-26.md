# Four-hour range historical evaluation

The frozen **NIFTY afternoon adaptation did not show a profitable edge** under the requested INR25,000, one-ITM-lot assumptions. Its primary 15-minute variant had **36.63% winning option outcomes after base costs**, with a mean loss of **INR31.84** per affordable opportunity. The mean loss increased to **INR119.09** under stress. All three predeclared holding limits lost money after modeled costs. No parameters were changed to seek profits.

These are exploratory observations from **1 January 2025–23 April 2026**. No protected dates from 24 April–21 July 2026 were evaluated. These dates were already available to earlier research, so they are not fresh out-of-sample confirmation.

## What was actually tested

The entire supplied transcript for [video O5eC5lY7ZXY](https://www.youtube.com/watch?v=O5eC5lY7ZXY) was read, including the stop exceptions and market examples. The transcript describes the first completed four-hour candle on a New York day, followed by a five-minute close outside and then back inside its range. It reports selected Bitcoin examples with 5/7 wins, EURUSD 5/6 and gold 6/10. Those are source claims, not verified results of this study.

The historical Indian cash-index session in the saved data runs 09:15–15:30 IST. Its short session does not reproduce the video's New York day or overnight range. This study explicitly uses **09:15–13:15 IST as the range**, then five-minute triggers after 13:15. No Bitcoin, EURUSD or XAU history was evaluated, and the transcript does not identify enough exchange/date/bar-anchoring detail to reproduce its shown examples exactly. Current exchange hours should not be inferred from this historical sampling convention; [NSE publishes current market timings](https://www.nseindia.com/static/market-data/market-timings).

The frozen implementation:

- Requires all 240 observed opening one-minute candles before the range becomes available. A missing opening minute excludes that day's range. It never interpolates or uses a partly formed range.
- Requires a five-minute **close strictly outside**, then a later close strictly inside both boundaries. Wicks and equality do not trigger. A high-side rejection buys a put; a low-side rejection buys a call.
- Sets the index stop at the full breakout excursion extreme, including the re-entry candle, and enters at the next minute open. A fresh breakout is needed for another signal; state resets daily. An incomplete trigger bucket discards the pending excursion.
- Uses a **2R index target**, 15-minute maximum hold as the primary, and predeclared 5/10-minute sensitivity. Maximum three serial entries/day, no overlap, and the full planned horizon must end by 15:25. These caps are comparison adaptations, not transcript rules.
- Does not apply a Bank Nifty filter or an indicator. It excludes the transcript's discretionary smaller stop at nearby resistance/order blocks: no objective threshold or selection rule was supplied. References to "range high/low" in examples are resolved to the explicit breakout-extreme rule stated in the main checklist.

## Accuracy and payoff are different measurements

| Maximum hold | Completed index trades | Positive signed index outcome | Full index 2R target | Time exits | Stop exits |
|---|---:|---:|---:|---:|---:|
| 5 minutes | 187 | 82/187 = 43.85% | 4/187 = 2.14% | 160 | 23 |
| 10 minutes | 182 | 77/182 = 42.31% | 11/182 = 6.04% | 130 | 41 |
| **15 minutes, primary** | **175** | **70/175 = 40.00%** | **15/175 = 8.57%** | **112** | **48** |

The primary index positive-rate 95% five-active-day moving-block interval is **32.00%–46.43%**. Index outcomes are direction-adjusted price differences before trading costs; the cash index is a signal source, not a purchased instrument. Net after-cost accuracy is measured using the actual options below. A positive timed exit is not a full 2R hit. Primary mean index R was -0.0494, with -79.55 aggregate signed index points. No primary outcomes were unresolved or ambiguous.

## Actual options with INR25,000 initial capital

One lot of the nearest observed ITM NIFTY option is selected using a completed option five-minute quote at the signal and prior-session NSE listing evidence. Expiry must be 1–7 calendar days away and the observed quote volume at least ten lots. Call/put direction follows the index signal; both are purchased options. The selected premium plus entry charges must fit **INR20,000**, preserving a 20% cash buffer. There is no search for a cheaper replacement after rejection.

Base costs apply 10bp adverse slippage per side and zero brokerage, plus exchange, SEBI, GST, stamp and STT charges. Stress applies 30bp per side and INR20 brokerage per order with the same fee formulas. Slipped option prices round adversely to INR0.05 ticks. These are configured fee assumptions applied hypothetically to historical prices, not verified historical bills. Entry uses the next minute open; exit uses the next minute open after the index exit is observable. A zero-volume or missing required minute would exclude the option observation.

| Hold | Affordable options | Net win rate, base / stress | Mean net outcome, base / stress | Sum of independent outcomes, base / stress |
|---|---:|---:|---:|---:|
| 5 minutes | 183 | 41.53% / 31.69% | -INR82.04 / -INR169.55 | -INR15,013.95 / -INR31,027.16 |
| 10 minutes | 178 | 39.33% / 33.71% | -INR50.55 / -INR137.88 | -INR8,998.53 / -INR24,541.84 |
| **15 minutes, primary** | **172** | **36.63% / 34.30%** | **-INR31.84 / -INR119.09** | **-INR5,476.85 / -INR20,484.12** |

**These sums are not returns on a funded INR25,000 account.** Each is an independent one-lot opportunity checked against initial-capital affordability. There is no compounding, shared-capital replay, daily loss bucket or portfolio drawdown admission. An actual account would accept a different sequence. The index 2R target does not establish an option net 1:2 reward/risk ratio.

Primary base wins were **63/172**, with a block-bootstrap 95% interval of **30.05%–42.53%**; stress wins were **59/172**, interval **27.75%–40.24%**. Mean outcome intervals were **-INR178.63 to +INR100.69** base and **-INR261.29 to +INR12.85** stress. The intervals do not establish a reliable profitable edge; they also do not prove that every possible interpretation fails. They use 2,000 samples of five consecutive active trading-day blocks, seed 42, conditional on the observed coverage and affordability. The duration variants are correlated, not independent replications.

The largest single primary loss was **INR2,065.58 base / INR2,180.97 stress**, on 13 March 2026. **12 base / 17 stress** observations lost more than INR1,000. The stop is an index level; it does not enforce a rupee option loss cap. Larger holding limits were not selected as a new primary after seeing results.

## Primary results by period

| Period | Affordable observations | Base net sum | Stress net sum |
|---|---:|---:|---:|
| 2025 Q1 | 39 | +INR5,813.68 | +INR2,380.32 |
| 2025 Q2 | 27 | +INR743.48 | -INR1,767.52 |
| 2025 Q3 | 38 | -INR2,631.70 | -INR5,676.85 |
| 2025 Q4 | 31 | -INR5,237.26 | -INR7,764.69 |
| 2026 through 23 April | 37 | -INR4,165.05 | -INR7,655.38 |

## Coverage and exclusions

The source contains 121,054 raw NIFTY minute rows. Screening rejects 371 invalid/out-of-session rows, leaving **120,683 valid minutes across 323 observed sessions**. Exactly **270 sessions** have every required first-four-hour minute; **53 sessions** are excluded, about 16.4% of observed sessions. Completeness is a data-availability screen, not a prediction filter. Results may not generalize to the missing sessions.

The 270 complete ranges generate **208 signals across 117 sessions**; 153 complete sessions have no signal. No incomplete post-range five-minute buckets occurred on those retained sessions. The primary has **175 trades across 110 sessions**, excluding 23 late signals, six overlapping signals and four beyond the daily cap. Every attempted primary index exit resolves.

Of the 175 primary index trades, **174 have eligible observed/listed ITM option evidence** and one does not. **Two priced lots exceed the capital allowance**, leaving 172 affordable observations under both cost scenarios across 107 active days. No selected option observation was excluded for missing/zero-volume minutes. The 5/10-minute variants each have one unavailable option and three unaffordable priced lots; all exclusions are retained in the saved ledgers.

## Evidence and reproduction

The plan, source, transcript and price-input hashes were written before outcomes. All three variants, including negative outcomes, are retained under `data/research/fourhour-range-2026-09-26/`. The option input manifest additionally fingerprints the actual option minute archives and prior-session listings.

Verification passed **21 targeted tests**: six new range-detector tests and 15 existing execution/selection/cost tests. The independent verifier reconstructed **544 index outcomes** from raw minute candles, checked all **208 signal ranges and excursion stops**, and matched **1,082 base/stress option fill-and-fee calculations** over **541 selected option observations**. It confirmed prior listings, quote-as-of timing, ITM direction, initial affordability, source/plan hash agreement and zero evaluated protected sessions. These counts span all three durations, with correlated/repeated contracts. `verification.json` includes the option win-rate intervals. PyArrow emitted CPU-cache-detection permission warnings in the sandbox; verification exited successfully. Broader app regression testing is owned by the parent integration task.

Source files: `services/research/fourhour_range.py`, `scripts/research_fourhour_range.py`, and `test/test_research_fourhour_range.py`. Frozen plan: `docs/plans/2026-09-26-fourhour-range-evaluation.md`. Shared signal/cost/execution helpers and live application files were not edited.

From the `openalgo` directory, reproduce with an unused output path:

```sh
UV_CACHE_DIR=/tmp/openalgo-uv-cache LOG_FORMAT='%(levelname)s %(message)s' \
  uv run --no-sync python scripts/research_fourhour_range.py \
  --output data/research/fourhour-range-new-run
```

The independent verifier for this saved run is:

```sh
UV_CACHE_DIR=/tmp/openalgo-uv-cache LOG_FORMAT='%(levelname)s %(message)s' \
  uv run --no-sync python data/research/fourhour-range-2026-09-26/verify.py
```

This evidence does not support promoting this particular NIFTY adaptation over the previously tested EMA9/15 candidate. It does not validate or refute all discretionary versions on Bitcoin, EURUSD or gold. No strategy was activated and no orders were placed.
