# Fabio Valentini order-flow model: accuracy is not measurable from these inputs

**Result: no defensible historical win rate can be assigned to this model from the supplied transcript and saved research data.** The completed audit finds two independent blockers: the essential order-flow observations are absent, and the excerpt does not specify a reproducible entry/exit rule set. This is an unavailable result, not evidence of a 0% win rate or proof that the model fails.

The audit covers the comparison period **1 January 2025–23 April 2026**. It produces no signals or trades and evaluates no outcomes from the protected **24 April–21 July 2026** period. No candle-only proxy was run: replacing actual aggressive trades and volume-at-price with candle colour or candle ranges would remove the central feature being tested.

## Accuracy and cost result

The requested comparison assumptions remain INR25,000 capital, a 20% cash buffer, one eligible ITM option lot, a 2R index target and a 15-minute maximum holding time. These assumptions are recorded in the audit manifest. They cannot fill in the missing signal information.

| Requested measurement | Result |
|---|---|
| Evaluable historical trades | 0; signals cannot be identified |
| Positive index outcomes / completed trades | N/A / 0; percentage undefined |
| Full index 2R targets / completed trades | N/A / 0; percentage undefined |
| Positive option outcomes after base costs | N/A; no selected trades to price |
| Positive option outcomes after stress costs | N/A; no selected trades to price |
| Mean or total option P&L, base / stress | N/A / N/A |
| Statistical confidence interval | N/A; no outcome sample |
| Qualification for live trading | Not established |

For comparability, the existing research uses 10 basis points of adverse slippage per side and zero brokerage in base conditions; stress uses 30 basis points per side and INR20 brokerage per order. Both include the configured exchange, SEBI, GST, stamp and STT formulas, applied hypothetically to historical prices. **Those costs were not applied here**, because there is no valid trade ledger. No zero-return observations were manufactured to populate the comparison table. An eventual index target hit would still be distinct from a positive option return after costs, and an index 2R target would not guarantee net option 2R.

## What the supplied text establishes, and what it omits

The entire attached `Pasted text.txt` was read. It contains 100 timestamped segments: 99 quoted segments and one summary placeholder. The union of the quoted time spans is **697 seconds (11 minutes 37 seconds)**, compared with a final labelled timestamp of **2:24:38**. This is approximately 8.0% timestamp coverage; it measures the text's labels, not verified coverage of the original video. No claim is made that the attachment faithfully transcribes the full video.

Examples of missing material include the 08:31–10:00 summary placeholder, the jump from 14:12 to 1:03:51, and the jump from 1:12:02 to 2:12:19. Some hyperlink timestamps disagree with the adjacent labels: the passage labelled 13:41 links to 15:49. Deictic instructions such as placing a stop “here” need the original chart and cannot be converted into a numeric price from text alone.

| Element described in the attachment | Evidence in the supplied timestamps | Missing reproducible definition |
|---|---|---|
| Use the profile to distinguish balance from imbalance | 03:42–04:29; 07:06–07:31 | Instrument/contract, profile anchor and reset, price-bin size, value-area algorithm and percentage, acceptance/rejection condition |
| Confirm one side's aggression and momentum | 08:04–08:31; 11:40–12:15 | Aggressor classification, measurement window, minimum size/count/imbalance and exact trigger |
| Filter aggressive orders around 20–30 | 1:03:51–1:04:18 | Units, whether individual prints or combined executions, platform aggregation, direction and threshold choice |
| Wait for follow-through/retracement instead of the first drive | 2:12:19–2:13:10 | Break definition, retest tolerance, timeout, confirming candle and executable entry time |
| Protect the trade behind aggression | 12:00–12:08; 1:11:35–1:12:02 | Numeric stop location, buffer, update policy and gap handling |
| Target another area; scale out as conditions change | Opening excerpt; 1:11:35–1:12:02 | Target selection, partial sizes, trailing policy, final exit and maximum hold |
| Risk some of that day's gains on directional days | 2:24:12–2:24:38 | Directional-day classifier, risk amount, sizing rule and daily reset accounting |

The attachment presents a discretionary model and says it adapts to context. It does not supply a complete fixed algorithm. Its 20–30% win-rate improvement claim lacks a dataset, sample size, baseline, definition of a win, and clarification of relative percent versus percentage points. The isolated example of risking USD160 to make USD500 is a gross payoff illustration, not a measured success probability. The tournament-return claim also cannot establish this particular setup's win rate. These claims remain unverified by this study.

The text mentions US-session futures trading. Transferring that model to NIFTY options introduces another hypothesis: the traded instrument, contract size, tick size, liquidity, session and option-price response differ. A full model replication would need the original market and rules; an Indian-market adaptation would need its own registered specification. A one-lot position also cannot reproduce partial exits in fractions of a tradable lot. A fixed 2R/15-minute comparison is an adaptation, not a demonstrated native rule of the excerpt.

## What was checked in the saved data

The audit reads the raw broker candle schemas and volume fields, the screened NIFTY five-minute schema, and the two raw option Parquet schemas. It queries date-filtered counts and volume availability only. It does not compute price changes, trading indicators, entries, stops, targets or returns.

| Audited input in 2025-01-01 through 2026-04-23 | Observations | Sessions | Volume evidence |
|---|---:|---:|---|
| Kotak NIFTY one-minute snapshots, 16 files | 121,054 raw candles | 323 | All 121,054 source-volume values are zero |
| Kotak Bank Nifty five-minute snapshots, 19 files including earlier warmup | 24,471 raw candles in the audit period | 322 | All 24,471 source-volume values are zero |
| Screened NIFTY five-minute Parquet | 24,150 candles | 323 | All 24,150 usable-volume values are null; source volume is zero |
| NIFTY option one-minute raw file, 2025 | 69,687,860 contract-minute rows | 249 | 32,871,706 positive-volume, 36,816,119 zero-volume, 35 negative-volume rows |
| NIFTY option one-minute raw file, 2026 through 23 April | 25,744,252 contract-minute rows | 75 | 11,933,492 positive-volume and 13,810,760 zero-volume rows |

These are availability counts, not accepted/executable candles or trade counts. Broker raw counts include invalid or out-of-session candles; they intentionally differ from prior screened-price reports. Option volume anomalies are retained in this audit rather than repaired. The option session counts are observed source coverage and are not a promise of complete exchange coverage or exact index-session alignment.

Both option files contain `date`, `timestamp`, `underlying`, `expiry`, `strike`, `option_type`, `exercise_style`, `open`, `high`, `low`, `close`, `volume`, `oi`, `settle_price`, `source` and `granularity`. The reported source is `upstox_expired`, the underlying is NIFTY, and the granularity is one minute. There are **no individual trade-size records, aggressor-side fields, bid/ask execution volumes at each price, or chronological book events**. Open interest does not provide those missing observations. The broker schemas are only timestamp, OHLC and a zero source-volume field.

The separate local `Nifty spot and futures data.zip` was checked at the archive-member level. Its members are annual 2017–2020 archives, outside this comparison period. Its prices were not evaluated. This is a bounded audit of the designated research inputs and that archive's member names, not a claim that no other vendor or uninspected local database could contain suitable data.

The field distinctions agree with primary documentation: [Upstox's candle schema](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/) describes OHLC, total volume and open interest; it does not turn aggregate candles into individual trades. [Sierra Chart's Numbers Bars documentation](https://www.sierrachart.com/index.php?page=doc/NumbersBars.php#NumbersBarsAccuracy) requires tick-level data for accurate bid/ask volume and volume-at-price, and its trade-volume filters operate on individual trade observations. These references explain data requirements; they do not verify the video's performance or establish which software the speaker used.

## Why an OHLC proxy cannot recover the missing signal

The audit also runs a small constructive check using two **synthetic tapes**, solely to demonstrate information loss. Both have open 100, high 101, low 99, close 100.5 and volume 100. Their four trade prices are identical; the traded sizes and sides differ.

| Synthetic tape | Sizes at prices 100, 101, 99, 100.5 | Price with most traded volume | Buy-minus-sell volume | Signed volume of individual trades of size at least 20 |
|---|---|---:|---:|---:|
| A | 10, 80, 5, 5 | 101 | +90 | +80 |
| B | 10, 5, 80, 5 | 99 | -90 | -80 |

Identical OHLCV can therefore imply opposite aggression and different profile locations. Assigning candle volume uniformly across its range, assigning buy/sell direction from candle colour, or calling an entire minute's volume a large individual order cannot identify which tape occurred. These are mathematical counterexamples, not market simulations or accuracy results. No synthetic volume or order flow was inserted into historical data.

## What would make a real test possible

1. Supply a complete, numerical specification or annotate the full original chart/video examples without selecting only winners. Freeze profile construction, imbalance and aggression thresholds, trade aggregation, entry, stop, target and exit logic before observing new outcomes.
2. Use licensed historical executions for the chosen actual futures/option contract with exchange timestamps, trade prices and quantities, and a reliable aggressor flag or synchronized quotes/order events from which classification can be documented. Per-price bid/ask aggregates can support some footprint calculations, but aggregate size alone cannot reproduce an individual-print size filter. If resting liquidity, absorption or queue behaviour is part of the rule, synchronized depth/order events are additionally needed.
3. For NIFTY adaptation, define how the selected futures contract's profile informs the spot/option signal, including rolls and basis. Keep lot sizes and quantity units explicit; the unexplained 20–30 filter cannot be transplanted mechanically between markets.
4. Register the common INR25,000/20%-buffer/one-ITM-lot/2R/15-minute protocol, cost assumptions, signal opportunity denominator, unavailable observations and conservative execution handling. Use the same signals for paired base/stress analysis and distinguish full target hits from positive exits.
5. Evaluate the fixed model on a separately authorized, unexamined period and then in forward sandbox mode. The existing protected period remains unconsumed by this audit. Repeatedly tuning on the familiar development period would not constitute an independent accuracy test.

[NSE's historical order/trade data layout](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Hist_Order_data_layout_1.13_0.pdf) documents a distinct event-level dataset, including trade time and trade records. That is an example of the required data category, not confirmation of present access, pricing, redistribution rights or a ready-made aggressor classifier. No data purchase, download, subscription or order was made.

## Reproduction and verification

Implementation: `scripts/research_fabio_orderflow.py`. Canonical evidence: `data/research/fabio-orderflow-2026-09-26-final/`.

- `registered-audit.json`: script/transcript/input SHA-256 hashes, dates and fixed comparison assumptions; written before statistical queries.
- `data-audit.json`: raw schemas, filtered counts, source-volume availability and old archive member names.
- `transcript-audit.json`: segment counts, labelled coverage and largest omitted spans.
- `synthetic-nonidentifiability.json`: both synthetic tapes and checked OHLCV/profile/aggression values.
- `results.json`: explicit unavailable accuracy, target and P&L fields, with zero evaluable trades and no proxy.
- `verification.json`: checks on the completed artifacts, date boundaries, hashes and synthetic proof.

From the `openalgo` directory, choose an unused output path:

```sh
UV_CACHE_DIR=/tmp/openalgo-uv-cache LOG_FORMAT='%(levelname)s %(message)s' \
  uv run --no-sync python scripts/research_fabio_orderflow.py \
  --output data/research/fabio-orderflow-new-audit
```

The script completed successfully and passed Ruff checks. Artifact verification confirms the reported counts and unavailable metrics. All row queries apply the development-period predicate; SHA-256 hashing reads whole-file bytes, including files that also contain later history, but no protected price outcomes or performance were inspected. Two initial incomplete output directories contain only registration manifests from a corrected SQL alias error; they are not result sets. The `-complete` directory is an intermediate successful audit; `-final` adds explicit negative-volume counts and underlying checks.

The runner uses context-managed file/archive/DuckDB handles, a 256 MB DuckDB memory ceiling and two query threads. Raw broker batches are released as processing advances; large option files stay in DuckDB and return only aggregates. Resource cleanup was checked statically. The runner imports no application, broker, database-service or trading modules and has no network or order path. `test/conftest.py` isolation was read; no application test suite or live database was invoked. No shared strategy code, risk settings or activation state changed.
