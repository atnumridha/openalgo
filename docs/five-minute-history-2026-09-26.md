# Five-minute NIFTY history downloaded on 26 September 2026

The snapshot is saved under `openalgo/data/research/five-minute-2026-09-26/`.

| Dataset | Screened coverage | Sessions | Five-minute bars |
|---|---|---:|---:|
| NIFTY index, direct from Kotak Neo | 27 Sep 2021–25 Sep 2026 | 1,235 | 92,313 |
| NIFTY options, 2024 public archive | 1 Oct–31 Dec 2024 | 61 | 2,902,606 |
| NIFTY options, 2025 public archive | 1 Jan–31 Dec 2025 | 249 | 13,885,907 |
| NIFTY options, 2026 public archive | 1 Jan–21 Jul 2026 | 135 | 8,006,900 |

The options total is **24,795,413 bars over 445 observed sessions**. This is the source's observed contract coverage, not a claim of every listed strike or expiry. Recent expired options after 21 July 2026 are absent from these files. 443 of 445 option sessions have index observations; 24,673,759 option bars have an exactly matching screened index timestamp.

## Files to use

- `NIFTY-spot-5m.csv`: index OHLC, ready for inspection or trend calculations.
- `NIFTY-spot-5m.parquet`: the same index data in compact form.
- `public-options/five-minute/`: 22 monthly option Parquet files, each with expiry, strike, call/put, OHLC, volume and OI; accompanying CSVs show daily coverage.
- `NIFTY-spot-5m-2021-2026.zip`: index data, original responses, quality reports and download/conversion helpers.
- `NIFTY-options-5m-2024-2026.zip`: converted options, source metadata, quality reports and conversion helpers. Original one-minute Parquet files remain separately in `public-options/raw/`.
- `verification.json`, `spot-validation.json`, `public-options/validation.json` and `checksums.json`: reproducible evidence and file hashes.

Every candle has `bar_start` and `bar_close` in IST. Signals must wait until `bar_close`. These are five-minute OHLC bars, not individual market ticks.

## Quality checks and limits

**Kotak index:** all 61 requested date batches completed, producing 94,181 raw rows. Screening kept 92,313 rows and separated 9 invalid-OHLC rows and 1,859 rows outside 09:15–15:30. No price was repaired. There are 1,188 sessions with all 75 regular bars and 47 partial sessions, with 312 absent bars within those observed sessions. Special sessions outside regular hours remain in raw files. Index volume is unavailable: usable volume is blank, and provider zeroes remain separately as `source_volume`. This supports price/trend research, but not index-volume VWAP.

**Options:** downloaded 124,458,249 original one-minute rows. A five-minute bar is retained only if all five distinct minutes exist and pass price, timestamp, expiry and volume checks. 172,025 incomplete, duplicated or invalid groups were omitted without filling gaps. 8,468,929 retained bars report zero volume; those are not evidence that an order could execute. Prices, OI and volume are preserved; five-minute volume is summed, and OI uses the final observed minute.

**Verification:** all 64 original files passed checksum checks; all converted files passed key uniqueness and OHLC/duration checks. Independently recalculating 44 sample bars from the original minutes matched OHLC, volume and final OI. For 21 July 2026, all 156 sampled source contracts matched NSE daily records, and all intraday ranges stayed inside NSE daily ranges. For 129 contracts, intraday volume equalled NSE traded contracts multiplied by lot size; source volume should not be treated as lot counts. This is a one-date comparison, not full-series exchange reconciliation.

**Source differences:** 3,122 index bars overlapped the earlier Yahoo download. Median close difference was about 0.05 index points; maximum close difference was 7.60 points and maximum open difference 88.55 points. Sources were not merged or silently corrected. The detailed comparison is in `spot-yahoo-comparison.json`.

## Sources and Research import status

Index prices came read-only from the existing authenticated [Kotak Neo historical API](https://github.com/Kotak-Neo/Kotak-Neo/blob/main/docs/market-data-apis/historical-data.md). It supports active instruments; expired contracts are excluded. No credentials are stored in this snapshot.

The options archive came from [rissin/nse-options-intraday](https://huggingface.co/datasets/rissin/nse-options-intraday). Its card attributes the minutes to Upstox; source files were pinned to a revision and matched the published SHA-256 hashes. The card labels its license `other` and defers redistribution rights to the providers. Those rights are not verified here. No third-party repository code was executed.

**Saved for local research; not yet imported into the Research selector.** These bulk archives exceed the current 20 MB/100,000-row import limits. A bounded bundle needs point-in-time lot sizes, a fixed contract-selection rule, coverage checks and source-rights review. Importing or downloading data does not prove profitability or enable live trading. No trading settings were changed.

## Reproduce

From the `openalgo` directory, use its existing virtual environment:

```sh
.venv/bin/python data/research/five-minute-2026-09-26/download_kotak.py
.venv/bin/python data/research/five-minute-2026-09-26/download_public_options.py
.venv/bin/python data/research/five-minute-2026-09-26/prepare_spot.py
.venv/bin/python data/research/five-minute-2026-09-26/prepare_options.py
.venv/bin/python data/research/five-minute-2026-09-26/verify_download.py
```

The download helpers target this fixed snapshot and reuse saved files; they are not daily refresh jobs. The options converter handles one month at a time with a 768 MB DuckDB memory limit, a 2 GB spill limit and context-managed connections. HTTP/file reads are streamed or bounded and broker database sessions are released. Resource cleanup was reviewed statically; no server code or background collector was installed.
