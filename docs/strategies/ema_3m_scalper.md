# Three-minute EMA9/20 selected-option scalper

This Python addition evaluates a long position in one selected option contract.
It uses OpenAlgo's indicators and, optionally, its historical market data. All
orders and fills in the output are local simulations. It cannot send broker
orders. Results do not establish future profitability.

The rules below were fixed before comparing performance on 1 October 2026.
That day's manual trades informed the idea, so that day is discovery data,
not an independent test. Older observations of the same chosen contract also
have selection bias: the contract was selected after observing today's trades.

## Rules

Input candles are one-minute OHLCV with timezone-aware **opening** timestamps.
Only closed minutes contribute to signals. Three-minute bars start at 09:15 IST;
each needs exactly three consecutive minutes. No interpolation fills gaps.
EMA9, EMA20 and Supertrend(10,3) run on completed three-minute bars. Unexpected
intraday gaps reset indicator warmup and pending pullback setups.

Two candidates are compared without searching parameter combinations:

1. `crossover`: previous EMA9 <= EMA20, current EMA9 > EMA20, and close above
   both averages.
2. `pullback`: during an existing EMA9 > EMA20 trend, previous close above its
   EMA9, current low touching EMA9, and current close >= EMA20 arm a setup.
   Within the next three completed candles, a bullish close above both EMA9
   and the setup high confirms entry. A setup can produce one signal.

Both require bullish Supertrend (OpenAlgo direction **-1**), with its stop below
the signal close. Execution uses the next minute's opening price, with adverse
slippage and tick rounding. Thus the 09:57–10:00 candle can signal an opening
fill at 10:00, using none of that minute's high, low or close to decide entry.

SL is the Supertrend value captured at the signal, rounded downward. Target
is the actual modeled entry plus **3 × (entry − SL)**, in whole ticks. Each
new entry gets new levels. The position's initial stop and target remain fixed;
later indicator values do not rewrite its original risk. The 1:3 ratio is price
geometry before charges; net reward/risk is lower.

Defaults are ₹15,000 paper capital, one metadata-defined lot, ₹500 maximum
planned all-in loss per trade, and ₹1,500 daily loss allowance. Premium plus
entry fees must be affordable. The admission calculation includes exit fees
and adverse stop slippage; an oversized Supertrend stop is rejected, never
squeezed into the budget. Only one position is allowed. After a net losing
exit, wait five minutes before another entry. Earlier losses reduce the daily
allowance; later wins do not expand it above ₹1,500.

Entries start at 09:30 and stop before 15:00. Flatten at 15:20. These are
strategy limits; [NSE's current equity derivatives session](https://www.nseindia.com/static/market-data/market-timings)
ends at 15:40. A stop gap exits at the worse opening price. An opening gap above
target receives no favorable gap improvement. If both SL and target touch
within a minute, SL wins and ambiguity is recorded. Missing exposure minutes
or an unfinished final position mark the replay incomplete and halt subsequent
admissions. They are not discarded to improve profit statistics. Actual gap
losses can exceed planned risk limits.

## Run historical replay

From the OpenAlgo repository, using its existing uv environment:

```sh
uv run --no-sync python scripts/ema_3m_scalper.py \
  --candles /absolute/path/option_1m.csv \
  --as-of '2026-10-01T11:47:42+05:30' \
  --lot-size 65 --tick-size 0.05 \
  --costs docs/strategies/ema_3m_paper_costs.example.json \
  --output /absolute/path/paper-report
```

Verify the lot and tick for the **specific contract and dates**. Do not reuse
today's lot size for other expiries or historical contract regimes. CSV requires
`timestamp,open,high,low,close,volume`. Set `--as-of` to the actual observation
cutoff; a forming candle is unavailable even if its row exists in the file.
Both candidates run by default; use `--variant pullback` or `crossover` to run one.

`--fetch-openalgo` can replace `--candles` for a read-only history request. Supply
`--symbol`, `--exchange NFO`, `--start-date` and `--end-date`. It reads
`OPENALGO_API_KEY` from the process environment and `OPENALGO_HOST` (default
`http://127.0.0.1:5001`). Only a loopback OpenAlgo host is accepted. It does not
read stored broker credentials or change Analyze Mode. This is a historical
paper replay, not a daemon claiming fills at already elapsed prices.

## Cost assumptions and interpretation

The example is an explicit research model, not a verified contract note. It
assumes ₹10 brokerage per fill and 10 basis points adverse slippage per side.
Exchange rate combines assumed NSE option transaction charges of 0.03503%
and IPFT of ₹50/crore (0.0005%). See the [broker charge sheet](https://www.nuvamawealth.com/old/important-links/exchange-charge-sheet)
and [Kotak terms](https://www.kotakneo.com/disclaimer/). Published sources can
differ; use the actual account's rates before relying on net results.

[NSE's levy table](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies)
provides sell-side option STT 0.15%, buy-side stamp duty 0.003%, SEBI turnover
fee 0.0001%, and GST 18% on taxable service charges. Rates in JSON are decimal
fractions, not percentage numbers. Daily contract-note rounding, exchange fee
tiers, broker plan differences and actual spread can change costs. A stress
model should increase brokerage to ₹20 and slippage to 30 bps, without changing
entry rules after observing results.

Inspect signal rejections as well as trades. At 65 units, ₹500 allows less than
₹7.69 between entry and SL after fees. Zero trades can be a valid result of
the risk limit; it is not evidence that the strategy wins or loses. A few
profitable fills in one contract do not prove an edge. Broader, complete data
and future paper observations are required before considering live execution.
