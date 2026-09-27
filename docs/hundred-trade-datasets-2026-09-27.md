# Five-strategy research dataset — 27 September 2026

Prepared at least 100 distinct, observed-price historical trades for each unchanged research strategy. These are research-eligible observations, not executed broker trades or live-release qualifications.

| Strategy | Unique usable trades | First trade | Last trade |
|---|---:|---|---|
| EMA 9/15 + Bank Nifty | 655 | 2021-06-08 | 2026-07-01 |
| EMA 50/200 + daily regime | 118 | 2017-01-24 | 2026-01-28 |
| MACD + EMA 200 | 181 | 2021-06-10 | 2026-06-30 |
| Opening-box breakout | 632 | 2021-06-01 | 2026-07-01 |
| EMA 5 reversal | 2,763 | 2021-06-10 | 2026-07-02 |

The modern source covers 2021–2026. The rare EMA 50/200 strategy additionally uses a separately labelled 2017–2020 monthly-options sample; those older observations are not the same market regime or contract structure as today's weekly options. Comparisons should show source and year strata, not treat the entire pool as one recent test. This is not a last-three-months dataset.

Fixed assumptions: ₹25,000 initial capital, one historical lot, ₹20,000 premium-plus-entry-fee ceiling, maximum 15-minute hold. Index-based exits use 2R; the opening box uses a 10-point premium stop and 20-point target. All opportunities in each fixed source interval were considered; no profitable-trade selection, duplication, synthetic prices or parameter optimization was used to reach the count. Both base and stress scenarios must have a complete observed fill path and pass initial affordability.

Each strategy folder contains `trades.json` (signal time, direction, contract, expiry, dated lot size, source/exposure labels, and both cost-scenario outcomes) and `option-paths.parquet` (observed minute OHLC/volume indexed by trade ID and minute OPEN). The shared `*-clean-1m/5m.parquet` index data use candle CLOSE timestamps. The older Zenodo files also use minute CLOSE labels, corroborated with an independent index source. Signals must wait for the close and execute on a subsequent bar.

The daily file includes pre-period warmup. Use strictly prior daily observations for regime features. `option-paths.parquet` retains the observed horizon; only the required fill path has been certified continuous and positive-volume. Longer/changed exit rules require fresh completeness checks. Missing history has never been filled. The supplied trade pool is conditional on data quality and affordability; use candidate/exclusion metadata when evaluating missing-data bias.

The existing frozen comparison engines enforce at most three entries a day and no overlap within each strategy. They do not replay the installed portfolio governor, shared ₹2,000 daily allowance, first/later-trade loss buckets, drawdown pauses or every protective premium stop. Counts therefore describe the frozen research rules, not guaranteed eligible live orders.

Base uses 10 bps adverse slippage per side and ₹0 brokerage; stress uses 30 bps and ₹20 per order. Both apply the previously used hypothetical numerical fee assumptions (exchange 0.0003553, SEBI 0.000001, GST 0.18, buy stamp 0.00003, sell STT 0.0015). These are comparison assumptions, not verified historical charges for every year. Do not interpret scenario totals as a continuously funded account return.

Screening checks OHLC, timestamps, duplicates, complete five-minute selection quotes, positive-volume execution minutes, prior-session official NSE contract listings, point-in-time lot sizes and initial affordability. Every accepted selected path was also checked against its same-day NSE high/low range. That envelope check is weaker than independently verifying every intraday candle or fill. `quality-rejections.json` preserves failures. The index source comparison records material differences from Kotak on some bars; prices were not silently averaged or repaired.

`readiness.json` contains counts by year, source and prior-study exposure. This pool is not an untouched holdout. Overlapping earlier research dates remain labelled, and formerly reserved dates evaluated during preparation are now exposed. Split chronologically with embargoes before future model fitting and preserve a new forward sample. A larger count does not establish profitability.

Sources and usage:

- [TradeMarkk index/options archive](https://huggingface.co/datasets/thetrademarkk/india-index-options-1m), pinned revision `0f4800e43e6f96cec0794369d78eb4d3c4211ef5`. Its card specifies educational use and CC BY-NC 4.0; this bundle remains for offline research and carries the original card.
- [Aparna Bhat's 2017–2020 dataset](https://zenodo.org/records/10899828), DOI `10.5281/zenodo.10899828`, published CC0. Original ZIP checksums and metadata are recorded.
- Official NSE daily records verify listing identity, available lot metadata and daily price envelopes. Legacy lot sizes are supplemented from the saved NSE circulars FAOP32134, FAOP47854 and FAOP61415.
- [Independent NIFTY minute data](https://github.com/sandeepkapri/Nifty50-Minute-Data) corroborates the older timestamp convention; 369,749 overlapping rows aligned best after subtracting one minute from Zenodo's close labels (median close difference zero; 99.23% within one point). This is corroboration rather than proof of every source observation.

`checksums.json` authenticates the delivered files. The larger original archives and preparation helpers remain one directory above this bundle. This package is a research input bundle; it has not been imported into the application's 20 MB Research upload flow and does not activate sandbox or live trading.

Local bundle: `data/research/hundred-trades-2026-09-27/ready/`. Preparation rejected 0 candidate paths during final NSE reference checks. The focused execution suite passed 71 tests.
