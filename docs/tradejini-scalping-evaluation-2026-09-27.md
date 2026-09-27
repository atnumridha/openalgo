# Tradejini Nifty-option scalping evaluation — 27 September 2026

The opening-range breakout deserves more research than EMA9/21 in this sample. All six EMA adaptations lost money after modeled costs. All six box adaptations made money at base costs, but five became negative under stress costs. The remaining cell averaged only ₹10.04 after stress costs, with a wide uncertainty interval that includes losses. **No setup is established as profitable or ready for live release.**

## What was tested

The [Tradejini article](https://www.tradejini.com/blogs/introduction-to-scalping-in-nifty-options), dated 11 June 2025, discusses VWAP pullbacks, EMA9/21 crossings and first-15-minute range breakouts on 1/3-minute charts. It offers premium-based stops and targets, unlike our earlier index-barrier studies. Its bought-put examples incorrectly put a stop above the purchase premium; all options here are long positions with stops below entry. VWAP needs futures volume, and volume confirmation is essential to the described box setup. These results therefore evaluate explicitly limited adaptations, not a complete replication.

Frozen [plan](plans/2026-09-27-tradejini-scalping.md): two families × two chart intervals × three maximum holds = **12 cells**. Four 10-minute cells were designated primary before returns were evaluated. Entry uses a completed signal, then the option's next-minute open; one nearest eligible ATM option lot, premium stop 10 points, target 20 points, no trailing/partial exits. This is gross 1:2; time exits and costs change realized reward/risk. Base costs use 10bp adverse slippage per side and zero brokerage plus configured charges. Stress uses 30bp and ₹20/order plus charges.

Capital is ₹25,000, with ₹20,000 maximum entry funding including buy fees and a ₹1,000 planned loss cap including modeled stop execution costs. Three admitted serial option entries per day maximum. This is **not** a compounded portfolio: the first-trade/later-trade loss buckets, ₹2,000 daily-loss pause and portfolio drawdown rules are not simulated. The sum of these opportunities must not be presented as the return on a continuously funded ₹25,000 account.

## Main comparison: maximum ten-minute hold

Win rate means positive **net option P&L after costs**, not prediction accuracy or target-hit rate. Counts are completed base-cost trades.

| Setup / chart | Trades | Net win rate | Mean net / trade | Stress mean / trade |
|---|---:|---:|---:|---:|
| EMA9/21 /1m |952|40.23%|−₹32.69|−₹112.93|
| EMA9/21 /3m |669|40.06%|−₹40.90|−₹117.57|
| Box /1m, price only |173|43.35%|+₹48.21|−₹22.77|
| Box /3m, price only |150|42.67%|+₹27.42|−₹50.70|

Stress EMA3m has 670 trades because altered entry fills alter the stop/target levels and subsequent scheduling. The four primary mean-net 95% intervals at base costs are respectively [−₹79.63,+₹17.09], [−₹88.77,+₹7.18], [−₹83.24,+₹168.34] and [−₹121.45,+₹141.30]. Each includes zero.

## Every predeclared cell

| Setup / chart | Max hold | Base trades | Base win rate | Base mean net | Stress trades | Stress mean net |
|---|---:|---:|---:|---:|---:|---:|
| EMA9/21 /1m |5min|952|45.48%|−₹30.71|952|−₹113.87|
| EMA9/21 /1m |10min|952|40.23%|−₹32.69|952|−₹112.93|
| EMA9/21 /1m |15min|950|38.00%|−₹55.01|951|−₹134.20|
| EMA9/21 /3m |5min|680|41.91%|−₹46.51|680|−₹125.75|
| EMA9/21 /3m |10min|669|40.06%|−₹40.90|670|−₹117.57|
| EMA9/21 /3m |15min|661|38.43%|−₹42.38|663|−₹116.52|
| Box /1m, price only |5min|173|46.24%|+₹40.73|173|−₹35.62|
| Box /1m, price only |10min|173|43.35%|+₹48.21|173|−₹22.77|
| Box /1m, price only |15min|173|41.04%|+₹83.12|173|+₹10.04|
| Box /3m, price only |5min|150|48.00%|+₹64.79|150|−₹9.18|
| Box /3m, price only |10min|150|42.67%|+₹27.42|150|−₹50.70|
| Box /3m, price only |15min|150|38.00%|+₹12.03|150|−₹53.89|

These correlated variants reuse the same history; they are not 12 independent confirmations. The 15-minute-hold, 1m-box cell is an exploratory follow-up candidate because it is the only cell still positive at stress costs. Its base mean 95% interval is [−₹53.33,+₹211.52], and stress interval [−₹127.21,+₹140.84]. Base win-rate 95% interval is 34.10–47.98%. Bootstrap intervals use 2,000 moving-five-active-day draws, seed 42, and do not adjust for selecting among 12 variants.

The candidate's performance is unstable across periods:

| Period | Trades | Base mean net | Stress mean net |
|---|---:|---:|---:|
|2025Q1|38|+₹329.50|+₹253.53|
|2025Q2|43|+₹118.04|+₹52.43|
|2025Q3|39|−₹26.84|−₹112.65|
|2025Q4|30|−₹177.07|−₹244.14|
|2026 through 23 April|23|+₹136.66|+₹68.13|

At base costs it reached the target 48 times, stopped 83 times, and timed out 42 times. Its 41.04% positive-net rate is not a 41.04% full-target rate: only 27.75% reached the 20-point target. A high nominal reward/risk ratio alone does not establish positive expectancy.

## Data, coverage and limits

- Period: **1 January 2025–23 April 2026**. 120,309 screened index minutes across 322 observed dates; 374 Muhurat-session rows excluded before indicators. The isolated 23 August 2025 observation remains in indicator history but cannot trigger an entry after the readiness gate. Exchange-calendar completeness has not been fully reconciled.
- Raw signal counts: EMA1m 3,023; EMA3m 855; box1m 175; box3m 152. Across these 4,205 requests, 4,198 contracts had an eligible observed quote and prior listing. Eligibility is based on a preceding NSE listing, 0–7 days to expiry and a completed five-minute quote with at least 10 lots of volume. Actual observed lots were 25/65/75. Eight selected contracts were more than 25 index points from spot (maximum 37.55): nearest eligible strike is an ATM proxy, not a verified delta 0.40–0.60 constraint.
- Box1m and 3m each rejected two unaffordable entries. Main EMA1m excluded 13 unaffordable, 4 nonpositive-stop and 7 unlisted/unquoted requests. Main EMA3m excluded 3 unaffordable and 8 nonpositive-stop requests. Scheduling removes further signals. No admitted entry had an unresolved price path in any cell/scenario. No completed modeled loss exceeded ₹1,000; this does not guarantee a real gap loss ceiling.
- Data do not include matching futures volume. The inspected local Zenodo futures archive covers 2017–2020 and does not overlap these options. **VWAP was not tested; box volume confirmation was omitted.** Spot prices proxy the illustrated futures signals. No delta, spread, news or order-book confirmation was supplied.
- Outcomes use observed option OHLC, not simulated premiums. Stop/target fills assume barrier execution with adverse slippage. Opening gaps through stops take the worse open; gaps above target receive only target. A bar touching both barriers takes the stop first. Every used bar must have valid OHLC and positive volume; even open-boundary fills are conditioned on that minute's eventual completeness. Tick fills, latency and market depth remain unverified.
- The article leaves candle strength and other discretionary choices unspecified. We froze a 50%-body definition, EMA warm-up, exact first-breakout window and gap handling before outcomes. Choosing alternatives now would be a new experiment, not validation of these results.
- This is repeatedly used development data. Protected 24 April–21 July outcomes were not evaluated. Costs are assumptions, not historical Kotak bills. No strategy was activated in live or sandbox, and no broker orders were placed.

## Reproduction and evidence

Artifacts: `data/research/tradejini-scalping-2026-09-27/` contains the registration, source/data fingerprints, signal tables, quote-based selections, raw option paths, per-cell ledgers and result summaries. The independent verifier imports no application signal, selection, risk or fee helpers.

Validation passed: **72 regression tests**, including 18 new tests; Ruff check and format; independent reconstruction of 320,754 signal rows, 4,198 contract selections, 11,910 admission/execution decisions and 11,670 completed outcomes across correlated cells and cost scenarios. All 339 option-source fingerprints matched. Independent checks cover signals, option types, selection rank, raw paths, entry scheduling, fills, fees, net P&L, counts, means and win rates. Bootstrap intervals and period summaries are produced by the existing diagnostics helpers; they are not separate independent replications. `verification.json` records zero protected sessions evaluated.

```bash
LOG_FORMAT='%(levelname)s %(message)s' UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/research_tradejini_scalping.py --output /tmp/tradejini-fresh-run
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/verify_tradejini_scalping.py data/research/tradejini-scalping-2026-09-27
```

Use a new output directory; the runner refuses to overwrite an existing experiment. Relevant source: `services/research/tradejini_scalping.py`, `scripts/research_tradejini_scalping.py`, `scripts/verify_tradejini_scalping.py`, and `test/test_research_tradejini_scalping.py`. New file/DuckDB resources are context-managed, queries use 512MB/two threads, and no background worker remains after the scripts exit.
