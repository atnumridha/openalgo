# StockGro timeframe/session comparison — 27 September 2026

**Eight missing comparisons were run; the already-tested one-minute baseline was reused. All nine cells lost money after modeled costs.** Five-minute candles had the least negative primary mean, but no increase in win rate versus one-minute candles. This does not demonstrate a profitable timeframe or justify live activation.

The [StockGro article](https://www.stockgro.club/blogs/trading/best-time-frame-for-scalping/) is timeframe and session guidance, not a complete new trading algorithm. It was read in full on 27 September 2026; the page displays an update date of 17 June 2026. Its discussion cannot itself be assigned a strategy accuracy percentage.

This experiment compares the existing **EMA5/10** entry rule across **1-, 3- and 5-minute candles**, with the same **15-minute maximum hold, 15-point signal-close index stop and 2R index target**. It uses **NIFTY ITM long options**, a **₹25,000 initial-capital allowance** and **₹5,000 cash buffer**, over **1 January 2025–23 April 2026**. Only chart interval and entry window vary.

## Already tested versus newly tested

- The earlier [IG study](ig-scalping-evaluation-2026-09-27.md) compared three-/five-minute charts for several other indicator rules. It did not hold EMA5/10 constant across all three intervals.
- The corrected [Tradetron study](tradetron-scalping-evaluation-2026-09-27.md) already supplied EMA5/10 on one-minute candles with a 15-minute cap. That result is reused, not represented as another independent run.
- New: EMA5/10 on three-/five-minute candles, plus separate opening-/closing-entry windows for each of the three intervals. This is eight new cells and one reused baseline, not nine independent confirmations.

## Primary comparison: first three eligible index entries per day

| Chart interval | Affordable option trades | Win rate after base costs | Mean base P&L/trade | Mean stress P&L/trade | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 minute | 891 | 37.93% | −₹76.36 | −₹166.49 | Reused baseline |
| 3 minute | 916 | 35.37% | −₹75.90 | −₹164.39 | New test |
| 5 minute | 869 | 37.05% | −₹70.76 | −₹159.49 | New test |

Here “win rate” means positive option P&L after modeled fees/slippage. It does not mean correctly forecasting every candle or reaching the full 2R target. The primary `all` entry window is still capped at the first three serial index entries/day; it is not an evenly sampled all-hours strategy.

| Chart interval | Win-rate 95% interval | Mean base P&L 95% interval | Mean stress P&L 95% interval |
| --- | --- | --- | --- |
| 1 minute | 34.67% to 41.19% | −₹131.97 to −₹17.11 | −₹222.28 to −₹107.74 |
| 3 minute | 32.61% to 37.94% | −₹128.28 to −₹27.12 | −₹217.29 to −₹114.02 |
| 5 minute | 33.83% to 39.91% | −₹129.04 to −₹18.17 | −₹217.06 to −₹106.63 |

These are conditional moving-five-active-day block intervals (2,000 draws, seed42). Individual intervals are not tests of the difference between timeframes, and no pairwise superiority claim is made. All studies reuse exploratory data; the protected period from 24 April–21 July 2026 remains unused. Multiple cells are correlated and these intervals are not adjusted for selection across research studies.

## Opening and closing entry windows

Opening entries: 09:15≤time<10:15 IST. Closing entries: 14:30≤time<15:30 IST, but the complete 15-minute horizon must finish by 15:25, so the last eligible signal is 15:10. These are entry windows; an opening trade can exit after 10:15. Window filtering occurs before each cell's independent daily cap.

| Chart | Entry window | Trades base/stress | Base win rate | Mean base P&L | Mean stress P&L |
| --- | --- | --- | --- | --- | --- |
| 1m | all | 891/891 | 37.93% | −₹76.36 | −₹166.49 |
| 1m | opening | 738/738 | 38.08% | −₹77.87 | −₹168.25 |
| 1m | closing | 654/654 | 37.16% | −₹85.64 | −₹173.71 |
| 3m | all | 916/915 | 35.37% | −₹75.90 | −₹164.39 |
| 3m | opening | 276/276 | 32.97% | −₹157.07 | −₹244.49 |
| 3m | closing | 398/398 | 35.68% | −₹69.45 | −₹156.27 |
| 5m | all | 869/869 | 37.05% | −₹70.76 | −₹159.49 |
| 5m | opening | 146/146 | 31.51% | −₹144.59 | −₹231.74 |
| 5m | closing | 254/254 | 34.25% | −₹97.77 | −₹182.96 |

Restricting entries to either session did not produce a positive mean under either cost scenario. This is a result for the specified EMA setup, not proof that session timing never matters. The best-looking secondary cell must not replace the primary comparison after inspection.

## Targets, losses and the difference from account returns

| Chart | Complete index outcomes | Full 2R hits | Stop exits | Time exits | Worst base option trade | Base losses over ₹1,000 |
| --- | --- | --- | --- | --- | --- | --- |
| 1m | 962 | 265 (27.55%) | 527 | 170 | −₹2,145.80 | 101 |
| 3m | 963 | 196 (20.35%) | 494 | 273 | −₹3,348.84 | 71 |
| 5m | 910 | 165 (18.13%) | 445 | 300 | −₹2,817.42 | 62 |

Index targets do not guarantee a net 1:2 option payoff. Actual premiums, time exits, stop overshoot, minute-based detection and costs change the result. Stop-first ordering is used if both index barriers are touched in a minute. Option fills use the next minute-open boundary corresponding to the signal/index-exit close; no extra full minute is appended to the time cap.

Base costs: 0.10% adverse slippage per side, zero brokerage, plus configured exchange/SEBI/GST/stamp/STT. Stress: 0.30% per side and ₹20 brokerage per order plus those charges. These are modeled costs, not verified broker bills or historical bid/ask executions.

**This is not a simulation of the user's funded account.** Initial affordability is reapplied independently; equity is not compounded. First-trade/later-trade/daily loss budgets, portfolio drawdown pause and operational option-premium stops are not modeled. A 15-point index stop cannot guarantee a ₹1,000 option loss limit. No sums should be interpreted as portfolio returns.

## Coverage and interpretation limits

The study retains 120,309 screened minute observations on 322 observed dates, producing 40,068 complete three-minute and 24,020 complete five-minute candles. It uses the corrected prior sample: 374 observations on the 21 October 2025 Muhurat session are excluded. The isolated 23 August observation remains in one-minute history but cannot trigger entry. The full exchange-session calendar has not been independently reconciled; see the prior data caveats.

| Chart/window | Raw window signals | Index attempts/completed | Late/overlap/cap exclusions | Missing option evidence | Unresolved index | Unaffordable base/stress |
| --- | --- | --- | --- | --- | --- | --- |
| 1m/all | 10448 | 963/962 | 600 / 383 / 8502 | 34 | 1 | 37/37 |
| 1m/opening | 1353 | 804/803 | 0 / 239 / 310 | 31 | 1 | 34/34 |
| 1m/closing | 1752 | 686/686 | 573 / 408 / 85 | 12 | 0 | 20/20 |
| 3m/all | 3317 | 963/963 | 127 / 111 / 2116 | 18 | 0 | 29/30 |
| 3m/opening | 315 | 289/289 | 0 / 11 / 15 | 4 | 0 | 9/9 |
| 3m/closing | 595 | 411/411 | 127 / 42 / 15 | 5 | 0 | 8/8 |
| 5m/all | 1856 | 910/910 | 64 / 41 / 841 | 15 | 0 | 26/26 |
| 5m/opening | 155 | 149/149 | 0 / 1 / 5 | 1 | 0 | 2/2 |
| 5m/closing | 347 | 262/262 | 64 / 16 / 5 | 2 | 0 | 6/6 |

Contracts are selected using prior-session NSE lot/listing evidence and a completed five-minute option quote: earliest eligible expiry (1–7 days), then nearest ITM strike, minimum ten lots of quote volume. One-/three-minute signals may use quotes 0–4 minutes old. Entry premium plus entry fees must fit ₹20,000; no cheaper replacement is selected.

Larger chart intervals change EMA lookbacks in elapsed time even though periods stay 5/10. Three consecutive intervals are required after the session opens or a gap: earliest readiness is 09:19, 09:27 and 09:35 for one-, three- and five-minute charts. These differences change the eligible trades and opening-hour sample. This is not a controlled experiment isolating chart noise alone.

The daily cap applies to index opportunities before option eligibility; unavailable or unaffordable choices can displace later opportunities. The option validator requires valid positive-volume observations throughout the path, making the priced sample conditional on future availability. Missingness need not be random. Scenario affordability is recomputed separately. Intersecting session samples and reused dates do not create independent evidence.

The article's sub-two-minute holding discussion, suggested 1R/1.5R reward ratios, qualitative market-regime advice, VWAP, FX sessions, Bank Nifty and tick-level trading were not evaluated. Retaining the user's 15-minute cap and 2R target makes this a limited, explicit adaptation of its timeframe advice.

## Period stability of the primary comparisons

After-cost mean option P&L per affordable trade. The 2026 column ends on 23 April.

| Chart | 2025 Q1 | 2025 Q2 | 2025 Q3 | 2025 Q4 | 2026 partial |
| --- | --- | --- | --- | --- | --- |
| 1m | −₹86.96 | −₹34.20 | −₹125.91 | −₹0.15 | −₹125.24 |
| 3m | −₹96.55 | −₹22.53 | −₹113.16 | −₹80.03 | −₹63.92 |
| 5m | −₹25.18 | −₹140.35 | −₹79.91 | −₹33.63 | −₹73.00 |

## Reproduction and verification

The [frozen research specification](plans/2026-09-27-stockgro-timeframes.md) was saved before outcomes. **54 targeted tests passed**, including nine new tests covering one-minute equivalence, prefix invariance, interval aggregation, readiness, IST window boundaries and refusal to reuse changed option evidence. Ruff passed for the four new Python files.

A fresh code review found one baseline-reuse audit gap. It was addressed in the independent verifier: it now checks the old option-input manifest is bound to the original registration and rehashes all **339 baseline option/listing source files**. A synthetic regression test fails when source data changes. The runner's index/settings equality check and exact saved-signal equality also passed; seven reused artifact hashes match.

The independent verifier reconstructed **184,397 signal rows** and **4,473 completed index outcomes** for the new cells, checked **4,385 as-of contract rankings** and **8,770 raw option fill/fee calculations**. It imports separate verification utilities, not application signal/risk/selection/cost functions. All source, plan and input hashes matched. Unresolved/refused index attempts: 1; unpriced selected options: 0; protected outcomes evaluated: 0. The reused baseline's original verification remains separately identified.

Artifacts: `data/research/stockgro-timeframes-2026-09-27/`, including registration, reuse references, data audit, signals, every new index/option ledger, per-cell results and `verification.json`. No prior result or registered source file was modified.

```sh
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/research_stockgro_timeframes.py \
  --output data/research/stockgro-timeframes-new-run
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/verify_stockgro_timeframes.py \
  data/research/stockgro-timeframes-new-run
```

Resource review was static: context-managed local files/DuckDB; existing 512MB/two-thread query limits; one timeframe's option requests at a time; bounded study frames. No persistent workers, broker sockets or live DB access. No prolonged leak/load measurement. No live or sandbox settings or orders were changed.
